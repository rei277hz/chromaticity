"""Generic helper loop; extension operations are injected by module name."""

from concurrent.futures import CancelledError
from importlib import import_module
import os
import queue
import socket
import threading
import traceback

from .payloads import PayloadStore
from .transport import frame, receive
from .host import configure_helper


PROTOCOL = 1


class WorkerContext:
    def __init__(self, config, job, cancelled, send, payloads):
        self.role = config["role"]
        self.generation = config["generation"]
        self.session = config["session"]
        self.job = job
        self._cancelled = cancelled
        self._send = send
        self._payloads = payloads

    def checkpoint(self):
        if self._cancelled.is_set():
            raise CancelledError("Helper computation was cancelled")

    def preview(self, value):
        self.checkpoint()
        prefix = f"{self.role}-{self.generation}-{self.job['id']}"
        encoded, files = self._payloads.encode(value, prefix=prefix)
        try:
            self._send(dict(kind="preview", job=self.job["id"], value=encoded, files=files))
        except BaseException:
            self._payloads.release(files)
            raise
        self._payloads.transfer(files)


def run(config, namespace):
    metadata = configure_helper(config.get("host_settings", {}))
    operation_module = import_module(namespace + "." + config["worker_module"])
    factory = getattr(operation_module, "create", None)
    if not callable(factory):
        raise TypeError("Worker module must expose create()")
    worker = factory()
    sock = socket.create_connection(tuple(config["address"]), timeout=30)
    sock.settimeout(None)
    send_lock = threading.Lock()

    def send(message):
        message.update(session=config["session"], generation=config["generation"])
        with send_lock:
            sock.sendall(frame(message))

    send(dict(kind="hello", protocol=PROTOCOL, token=config["token"], **metadata))
    commands = queue.Queue()
    cancelled = threading.Event()
    stopping = threading.Event()
    active = [None]
    cancelled_jobs = set()
    state_lock = threading.Lock()

    def read_controls():
        try:
            while True:
                message = receive(sock)
                if (message.get("session") != config["session"]
                        or message.get("generation") != config["generation"]):
                    raise ValueError("Helper control identity mismatch")
                if message["kind"] == "cancel":
                    identity = message["job"]
                    with state_lock:
                        cancelled_jobs.add(identity)
                        if identity == active[0]:
                            cancelled.set()
                elif message["kind"] == "shutdown":
                    stopping.set()
                    cancelled.set()
                    commands.put(None)
                    return
                elif message["kind"] == "run":
                    commands.put(message)
                else:
                    raise ValueError("Unknown helper control message")
        except BaseException:
            # If the owner disappears, do not leave a private Blender process behind.
            os._exit(70)

    reader = threading.Thread(target=read_controls, name="Grade helper control", daemon=True)
    reader.start()
    payloads = PayloadStore(config["directory"])
    try:
        while not stopping.is_set():
            message = commands.get()
            if message is None:
                break
            identity = message["job"]
            with state_lock:
                active[0] = identity
                cancelled.clear()
                if identity in cancelled_jobs or stopping.is_set():
                    cancelled.set()
            context = WorkerContext(config, message, cancelled, send, payloads)
            prefix = f"{config['role']}-{config['generation']}-{identity}"
            try:
                inputs = payloads.decode(message["inputs"], copy=True)
                context.checkpoint()
                result = worker.dispatch(message["operation"], inputs, context)
                context.checkpoint()
                encoded, files = payloads.encode(result, prefix=prefix)
                try:
                    context.checkpoint()
                    send(dict(kind="complete", job=identity, value=encoded, files=files))
                except BaseException:
                    payloads.release(files)
                    raise
                payloads.transfer(files)
            except CancelledError:
                send(dict(kind="cancelled", job=identity))
            except Exception as error:
                send(dict(kind="failed", job=identity,
                          error=f"{type(error).__name__}: {error}",
                          traceback=traceback.format_exc()))
            finally:
                with state_lock:
                    cancelled_jobs.discard(identity)
                    active[0] = None
        close = getattr(worker, "close", None)
        if callable(close):
            close()
    finally:
        stopping.set()
        reader.join(timeout=2)
        payloads.close()
        sock.close()
