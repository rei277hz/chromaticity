"""Run the Stack timing scenario inside the installed Blender extension."""

import importlib
import json
from pathlib import Path
import sys
import time
import traceback
from types import MethodType
from uuid import uuid4


def main():
    import addon_utils
    import bpy
    import gpu

    config_path = Path(sys.argv[sys.argv.index("--") + 1])
    config = json.loads(config_path.read_text(encoding="utf8"))
    report_path = Path(config["report"])
    tree_id = "ShaderNodeTree" if config["node_tree"] == "shader" else "CompositorNodeTree"

    bpy.context.preferences.system.gpu_backend = "OPENGL"
    gpu.init()
    gpu_info = {
        "backend": gpu.platform.backend_type_get(),
        "renderer": gpu.platform.renderer_get(),
        "vendor": gpu.platform.vendor_get(),
        "version": gpu.platform.version_get(),
        "compute_shaders": gpu.capabilities.compute_shader_support_get(),
    }
    if not gpu_info["compute_shaders"]:
        raise RuntimeError("Stack LUT timing requires compute shader support")
    if "llvmpipe" not in gpu_info["renderer"].lower():
        raise RuntimeError("Expected the pinned Mesa llvmpipe software renderer")

    repository = Path(config["repository"])
    bpy.context.preferences.extensions.repos.new(
        name="Perceptual Grade Stack timing",
        module="pg_stack_lut_timing",
        custom_directory=str(repository),
    )
    extension = importlib.import_module("bl_ext.pg_stack_lut_timing.perceptual_grade")
    errors = []
    enabled = addon_utils.enable(extension.__name__, default_set=False,
                                 handle_error=errors.append)
    if enabled is not extension or errors:
        raise RuntimeError("Could not enable the packaged extension: " + repr(errors))
    nodes = importlib.import_module(extension.__package__ + ".nodes")
    lut_gpu = importlib.import_module(extension.__package__ + ".lut_gpu")

    report = {
        "schema": 1,
        "completed": False,
        "blender": bpy.app.version_string,
        "blender_build": bpy.app.build_hash.decode("ascii", errors="replace"),
        "gpu": gpu_info,
        "node_tree": config["node_tree"],
        "grade_count": config["grade_count"],
        "profile": {
            "samples": config["samples"],
            "updates_per_drag": config["updates"],
            "update_interval_ms": config["interval_ms"],
            "preview_hold_timeout_seconds": config["preview_timeout"],
        },
        "initialization": {},
        "drags": [],
    }
    state = {
        "active_sample": None,
        "job_creation": None,
        "jobs": {},
        "sample_by_signature": {},
        "ready_at": {},
        "request_at": {},
        "build_context": None,
        "baseline_started": time.perf_counter(),
    }

    def phase_record(sample, phase_name):
        return sample.setdefault(phase_name, {
            "jobs_started": 0,
            "dispatch_batches": 0,
            "dispatch_submission_seconds": 0.0,
            "inter_step_wait_seconds": 0.0,
            "texture_allocation_seconds": 0.0,
            "readback_seconds": 0.0,
            "result_to_install_seconds": None,
            "kernel_build_seconds": 0.0,
            "kernel_swap_seconds": 0.0,
            "installed": False,
        })

    def record_initial(name, value):
        if value is not None:
            report["initialization"][name] = value

    def json_ready(value):
        if isinstance(value, dict):
            return {
                key: json_ready(item)
                for key, item in value.items()
                if key not in {
                    "sample", "gesture_token", "started_signatures",
                    "_phase_start_at", "_request_to_phase_start",
                }
            }
        if isinstance(value, (tuple, list)):
            return [json_ready(item) for item in value]
        if isinstance(value, set):
            return sorted(json_ready(item) for item in value)
        return value

    def save_report():
        report_path.write_text(
            json.dumps(json_ready(report), indent=2, allow_nan=False) + "\n",
            encoding="utf8",
        )

    runtime = nodes._preparation_runtime
    backend = runtime._lanes["lut"].host_owner

    original_ensure_shader = backend._ensure_shader

    def timed_ensure_shader(self):
        if self._shader is not None:
            return original_ensure_shader()
        print("PG_STACK_LUT shader initialization started", flush=True)
        started = time.perf_counter()
        result = original_ensure_shader()
        record_initial("shader_initialization_seconds", time.perf_counter() - started)
        print("PG_STACK_LUT shader initialization finished", flush=True)
        return result

    backend._ensure_shader = MethodType(timed_ensure_shader, backend)

    original_create_job = backend.create_job

    def timed_create_job(self, settings, working_space, progressive):
        sample = state["active_sample"]
        signature = nodes._stack_signature(settings, working_space)
        shader_cold = self._shader is None
        creation = {
            "sample": sample,
            "signature": signature,
            "progressive": bool(progressive),
            "texture_seconds": {"preview": 0.0, "full": 0.0},
        }
        state["job_creation"] = creation
        print(
            f"PG_STACK_LUT job creation started progressive={bool(progressive)}",
            flush=True,
        )
        started = time.perf_counter()
        try:
            baker = original_create_job(settings, working_space, progressive)
        finally:
            state["job_creation"] = None
        setup_seconds = time.perf_counter() - started
        print(
            f"PG_STACK_LUT job creation finished progressive={bool(progressive)} "
            f"seconds={setup_seconds:.6f}",
            flush=True,
        )
        job = {
            "signature": signature,
            "progressive": bool(progressive),
            "setup_seconds": setup_seconds,
            "texture_seconds": creation["texture_seconds"],
            "last_advance_finished_at": None,
            "phases": {
                "preview": {"dispatch_batches": 0, "dispatch_submission_seconds": 0.0,
                            "readback_seconds": 0.0},
                "full": {"dispatch_batches": 0, "dispatch_submission_seconds": 0.0,
                         "readback_seconds": 0.0},
            },
            "sample": sample,
        }
        state["jobs"][id(baker)] = job
        if sample is None:
            report["initialization"].setdefault("jobs", []).append(job)
        else:
            sample.setdefault("jobs", []).append(job)
            sample["started_signatures"].add(signature)
            sample["signature"] = signature
            sample["shader_was_cold"] = sample.get("shader_was_cold", False) or shader_cold
            state["sample_by_signature"][signature] = sample
            setup_phase = "preview" if progressive else "full"
            metrics = phase_record(sample, setup_phase)
            metrics["jobs_started"] += 1
            metrics["setup_seconds"] = metrics.get("setup_seconds", 0.0) + setup_seconds
        return baker

    backend.create_job = MethodType(timed_create_job, backend)

    original_create_phase = lut_gpu.StackLUTBaker._create_phase

    def timed_create_phase(self):
        started = time.perf_counter()
        result = original_create_phase(self)
        elapsed = time.perf_counter() - started
        phase_name = "preview" if self.size == 33 else "full"
        job = state["jobs"].get(id(self))
        creation = state["job_creation"]
        if job is not None:
            job["texture_seconds"][phase_name] += elapsed
            sample = job["sample"]
        elif creation is not None:
            creation["texture_seconds"][phase_name] += elapsed
            sample = creation["sample"]
        else:
            sample = state["active_sample"]
        if sample is not None:
            record = phase_record(sample, phase_name)
            record["texture_allocation_seconds"] += elapsed
        return result

    lut_gpu.StackLUTBaker._create_phase = timed_create_phase

    original_readback = lut_gpu.StackLUTBaker._readback

    def timed_readback(self):
        phase_name = "preview" if self.size == 33 else "full"
        started = time.perf_counter()
        result = original_readback(self)
        elapsed = time.perf_counter() - started
        job = state["jobs"].get(id(self))
        sample = job["sample"] if job is not None else state["active_sample"]
        if sample is not None:
            phase_record(sample, phase_name)["readback_seconds"] += elapsed
        if job is not None:
            job["phases"][phase_name]["readback_seconds"] += elapsed
        return result

    lut_gpu.StackLUTBaker._readback = timed_readback

    original_advance = lut_gpu.StackLUTBaker.advance

    def timed_advance(self):
        size = self.size
        waiting_for_readback = self._readback_pending
        job = state["jobs"].get(id(self))
        sample = job["sample"] if job is not None else state["active_sample"]
        phase_name = "preview" if size == 33 else "full"
        step_started = time.perf_counter()
        if job is not None and sample is not None:
            previous_step = job["last_advance_finished_at"]
            if previous_step is not None:
                phase_record(sample, phase_name)["inter_step_wait_seconds"] += max(
                    0.0, step_started - previous_step
                )
        if not waiting_for_readback and sample is not None:
            starts = sample.setdefault("_phase_start_at", {}).setdefault(phase_name, {})
            request_signature = job["signature"] if job is not None else self.signature
            if request_signature not in starts:
                phase_started_at = time.perf_counter()
                request_progressive = job["progressive"] if job is not None else True
                requested_at = state["request_at"].get(
                    (request_signature, request_progressive)
                )
                if requested_at is not None:
                    sample.setdefault("_request_to_phase_start", {}).setdefault(
                        phase_name, {}
                    )[request_signature] = max(
                        0.0, phase_started_at - requested_at
                    )
                starts[request_signature] = phase_started_at
        cursor = self.cursor
        if not waiting_for_readback:
            print(f"PG_STACK_LUT dispatch started size={size} cursor={cursor}", flush=True)
        started = time.perf_counter()
        receipt = original_advance(self)
        elapsed = time.perf_counter() - started
        if job is not None:
            job["last_advance_finished_at"] = time.perf_counter()
        if not waiting_for_readback:
            print(
                f"PG_STACK_LUT dispatch finished size={size} cursor={cursor} "
                f"seconds={elapsed:.6f}",
                flush=True,
            )
        if not waiting_for_readback and sample is not None:
            record = phase_record(sample, phase_name)
            record["dispatch_batches"] += 1
            record["dispatch_submission_seconds"] += elapsed
            if job is not None:
                job["phases"][phase_name]["dispatch_batches"] += 1
                job["phases"][phase_name]["dispatch_submission_seconds"] += elapsed
        if receipt is not None:
            quality, prepared = receipt
            signature = nodes._stack_signature(prepared.settings, prepared.space)
            ready_at = time.perf_counter()
            state["ready_at"][(signature, quality)] = ready_at
            sample = state["sample_by_signature"].get(signature, sample)
            if sample is not None:
                phase_record(sample, quality)["result_ready_at"] = ready_at
            print(f"PG_STACK_LUT {quality} result ready", flush=True)
        return receipt

    lut_gpu.StackLUTBaker.advance = timed_advance

    original_request = runtime.request

    def timed_request(self, source, signature, settings, working_space, *, lane="linear",
                      progressive=None):
        sample = state["active_sample"]
        if lane == "lut" and sample is not None:
            state["request_at"][(signature, bool(progressive))] = time.perf_counter()
            sample["lut_requests"] += 1
            sample["request_signatures"].append(signature)
            sample["latest_signature"] = signature
            if not progressive:
                sample["final_signature"] = signature
        return original_request(source, signature, settings, working_space,
                                lane=lane, progressive=progressive)

    runtime.request = MethodType(timed_request, runtime)

    original_stack_kernel = nodes._stack_kernel

    def timed_stack_kernel(tree_type, prepared, signature, quality):
        started = time.perf_counter()
        result = original_stack_kernel(tree_type, prepared, signature, quality)
        elapsed = time.perf_counter() - started
        context = state["build_context"]
        sample = context["sample"] if context is not None else state["sample_by_signature"].get(signature)
        if sample is not None:
            phase_record(sample, quality)["kernel_build_seconds"] += elapsed
        else:
            record_initial("unattributed_kernel_build_seconds", elapsed)
        return result

    nodes._stack_kernel = timed_stack_kernel

    original_replace = nodes._replace_node_kernel

    def timed_replace(node, kernel):
        context = state["build_context"]
        started = time.perf_counter()
        result = original_replace(node, kernel)
        elapsed = time.perf_counter() - started
        if context is not None:
            phase_record(context["sample"], context["quality"])["kernel_swap_seconds"] += elapsed
        return result

    nodes._replace_node_kernel = timed_replace

    original_build_install = nodes._build_and_install

    def timed_build_install(signature, authorized_records, prepared, quality="full"):
        sample = state["sample_by_signature"].get(signature)
        started = time.perf_counter()
        ready_at = state["ready_at"].get((signature, quality))
        if sample is not None:
            context = {"sample": sample, "quality": quality}
            state["build_context"] = context
            if ready_at is not None:
                phase_record(sample, quality)["result_to_install_seconds"] = max(0.0, started - ready_at)
        else:
            state["build_context"] = None
        try:
            result = original_build_install(signature, authorized_records, prepared, quality)
        finally:
            elapsed = time.perf_counter() - started
            state["build_context"] = None
        installed_at = time.perf_counter()
        if sample is not None and not result:
            phase_record(sample, quality)["installed"] = True
            phase_record(sample, quality)["install_seconds"] = elapsed
            if quality == "preview" and signature == sample.get("latest_signature"):
                sample["preview_installed"] = True
                last_update = sample.get("last_update_at")
                if last_update is not None:
                    sample["preview_seconds_after_last_update"] = installed_at - last_update
                sample["preview_installed_at"] = installed_at
            if quality == "full" and signature == sample.get("final_signature"):
                sample["full_installed"] = True
                sample["full_installed_at"] = installed_at
            print(f"PG_STACK_LUT {quality} kernel installed", flush=True)
        elif sample is None:
            record_initial("unattributed_install_seconds", elapsed)
        return result

    nodes._build_and_install = timed_build_install

    window = bpy.context.window
    if window is None:
        raise RuntimeError("The native Blender window is unavailable")
    area = next((item for item in window.screen.areas if item.type == "NODE_EDITOR"), None)
    if area is None:
        area = next(item for item in window.screen.areas if item.type != "CONSOLE")
        area.type = "NODE_EDITOR"
    area.ui_type = tree_id
    tree = bpy.data.node_groups.new("Stack LUT timing", tree_id)
    tree.use_fake_user = True
    area.spaces.active.node_tree = tree
    node = nodes.create_stack_node(tree)
    tree.nodes.active = node
    node.location = (0, 0)
    for _index in range(config["grade_count"]):
        entry = node.pg_stack_entries.add()
        entry.key = uuid4().hex
        entry.grade = nodes._make_grade()
    node.pg_active_index = 0
    tree.nodes.active = node

    bpy.context.preferences.edit.use_global_undo = True
    window_key = window.as_pointer()
    deadline = time.perf_counter() + config["timeout"]
    current_sample_index = 0

    def is_current(quality, signature):
        return nodes._kernel_is_current(
            node.node_tree, tree_id, signature, quality, stack=True
        )

    def fail(error):
        report["error"] = str(error)
        report["traceback"] = traceback.format_exc()
        save_report()
        print(report["traceback"], file=sys.stderr, flush=True)
        bpy.ops.wm.quit_blender()
        return None

    def flatten_sample(sample):
        sample["distinct_lut_requests"] = len(set(sample["request_signatures"]))
        sample["requests_without_started_job"] = len(
            set(sample["request_signatures"]) - sample["started_signatures"]
        )
        sample["started_job_count"] = len(sample.get("jobs", ()))
        sample.pop("request_signatures", None)
        sample.pop("started_signatures", None)
        for phase_name in ("preview", "full"):
            metric = sample.get(phase_name, {})
            signature = sample.get(
                "final_signature" if phase_name == "full" else "latest_signature"
            )
            request_starts = sample.get("_request_to_phase_start", {}).get(
                phase_name, {}
            )
            sample[f"{phase_name}_request_to_phase_start_seconds"] = (
                request_starts.get(signature) if signature is not None else None
            )
            for field in (
                "jobs_started", "dispatch_batches", "dispatch_submission_seconds",
                "inter_step_wait_seconds",
                "texture_allocation_seconds", "readback_seconds", "result_to_install_seconds",
                "kernel_build_seconds", "kernel_swap_seconds", "setup_seconds", "install_seconds",
            ):
                sample[f"{phase_name}_{field}"] = metric.get(field)
        if sample.get("release_at") is not None and sample.get("full_installed_at") is not None:
            sample["release_to_full_seconds"] = sample["full_installed_at"] - sample["release_at"]
        if sample.get("release_at") is not None and sample.get("gesture_started_at") is not None:
            sample["gesture_seconds"] = sample["release_at"] - sample["gesture_started_at"]

    def finish():
        nonlocal current_sample_index
        report["completed"] = True
        report["duration_seconds"] = time.perf_counter() - state["baseline_started"]
        for sample in report["drags"]:
            flatten_sample(sample)
            sample.pop("jobs", None)
            sample.pop("gesture_token", None)
            for phase_name in ("preview", "full"):
                sample.pop(phase_name, None)
            for key in ("gesture_started_at", "last_update_at", "release_at",
                        "preview_installed_at", "full_installed_at"):
                sample.pop(key, None)
        save_report()
        addon_utils.disable(extension.__name__, default_set=False)
        bpy.ops.wm.quit_blender()
        return None

    def run_drag_tick():
        nonlocal current_sample_index
        try:
            if time.perf_counter() > deadline:
                raise TimeoutError("Stack LUT timing session exceeded its deadline")
            if current_sample_index >= config["samples"]:
                return finish()

            sample = report["drags"][-1]
            if sample["updates"] < config["updates"]:
                apply_update(sample)
                return config["interval_ms"] / 1000.0

            if (not sample["preview_installed"]
                    and time.perf_counter() - sample["last_update_at"] < config["preview_timeout"]):
                return 0.02

            if sample.get("release_at") is None:
                nodes._end_gesture(window_key, sample["gesture_token"])
                sample["release_at"] = time.perf_counter()
                sample["final_signature"] = nodes._settings_signature_for(node)
                if sample["final_signature"] is None:
                    raise RuntimeError("Could not compute the final Stack signature")
                sample["latest_signature"] = sample["final_signature"]
                return 0.02

            if not is_current("full", sample["final_signature"]):
                return 0.02

            sample["full_installed"] = True
            current_sample_index += 1
            state["active_sample"] = None
            if current_sample_index >= config["samples"]:
                return finish()
            return begin_drag()
        except BaseException as error:
            return fail(error)

    def begin_drag():
        sample = {
            "index": current_sample_index,
            "updates": 0,
            "lut_requests": 0,
            "request_signatures": [],
            "started_signatures": set(),
            "jobs": [],
            "preview_installed": False,
            "full_installed": False,
            "gesture_started_at": time.perf_counter(),
        }
        report["drags"].append(sample)
        state["active_sample"] = sample
        sample["gesture_token"] = nodes._begin_gesture(window_key, node)
        apply_update(sample)
        return config["interval_ms"] / 1000.0

    def apply_update(sample):
        next_index = sample["updates"]
        fraction = (next_index + 1) / config["updates"]
        exposure = -0.75 + 1.5 * fraction + 0.2 * current_sample_index
        node.pg_stack_entries[node.pg_active_index].grade.pg_linear.exposure = exposure
        sample["updates"] += 1
        sample["last_update_at"] = time.perf_counter()

    report_path.parent.mkdir(parents=True, exist_ok=True)
    report["initialization"]["setup_seconds"] = time.perf_counter() - state["baseline_started"]
    save_report()
    first_interval = begin_drag()
    bpy.app.timers.register(run_drag_tick, first_interval=first_interval)


if __name__ == "__main__":
    main()
