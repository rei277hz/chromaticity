"""Small nonblocking JSON frames for the private Blender helper socket."""

import json
import socket
import struct


MAX_FRAME = 4 * 1024 * 1024


def frame(value):
    data = json.dumps(value, separators=(",", ":"), allow_nan=False).encode("utf8")
    if len(data) > MAX_FRAME:
        raise ValueError("Helper control frame exceeds the size limit")
    return struct.pack("!I", len(data)) + data


def receive(sock):
    def read(size):
        data = bytearray()
        while len(data) < size:
            chunk = sock.recv(size - len(data))
            if not chunk:
                raise EOFError("Helper control socket closed")
            data.extend(chunk)
        return bytes(data)

    length = struct.unpack("!I", read(4))[0]
    if length > MAX_FRAME:
        raise ValueError("Helper control frame exceeds the size limit")
    return json.loads(read(length))


class Channel:
    def __init__(self, sock):
        self.socket = sock
        sock.setblocking(False)
        self.incoming = bytearray()
        self.outgoing = bytearray()

    def send(self, value):
        encoded = frame(value)
        if len(self.outgoing) + len(encoded) > 2 * MAX_FRAME:
            raise BufferError("Helper control queue is full")
        self.outgoing.extend(encoded)

    def pump(self):
        if self.outgoing:
            try:
                count = self.socket.send(self.outgoing[:65536])
                del self.outgoing[:count]
            except BlockingIOError:
                pass
        try:
            data = self.socket.recv(65536)
            if not data:
                raise EOFError("Helper control socket closed")
            self.incoming.extend(data)
        except BlockingIOError:
            pass

        messages = []
        while len(self.incoming) >= 4:
            length = struct.unpack("!I", self.incoming[:4])[0]
            if length > MAX_FRAME:
                raise ValueError("Helper control frame exceeds the size limit")
            if len(self.incoming) < 4 + length:
                break
            messages.append(json.loads(self.incoming[4:4 + length]))
            del self.incoming[:4 + length]
        return messages

    def close(self):
        self.socket.close()
