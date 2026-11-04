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
    lut_helper = importlib.import_module(extension.__package__ + ".lut_helper")

    report = {
        "schema": 2,
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
        "jobs": {},
        "sample_by_signature": {},
        "ready_at": {},
        "request_at": {},
        "build_context": None,
        "gpu_probe_started_at": None,
        "gpu_probe_seconds": None,
        "gpu_probe_recorded": False,
        "baseline_started": time.perf_counter(),
    }

    def phase_record(sample, phase_name):
        return sample.setdefault(phase_name, {
            "jobs_started": 0,
            "dispatch_batches": 0,
            "dispatch_submission_seconds": 0.0,
            "worker_between_batches_seconds": 0.0,
            "texture_allocation_seconds": 0.0,
            "readback_seconds": 0.0,
            "worker_setup_seconds": 0.0,
            "worker_calculation_seconds": 0.0,
            "request_to_helper_submit_seconds": None,
            "helper_submit_to_result_seconds": None,
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
                    "request_signatures", "reported_phases", "received_qualities",
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
    original_create_job = backend.create_job

    def timed_create_job(self, settings, working_space, progressive):
        sample = state["active_sample"]
        signature = nodes._stack_signature(settings, working_space)
        print(
            f"PG_STACK_LUT helper request started progressive={bool(progressive)}",
            flush=True,
        )
        started = time.perf_counter()
        job = original_create_job(settings, working_space, progressive)
        creation_seconds = time.perf_counter() - started
        print(
            f"PG_STACK_LUT helper request queued progressive={bool(progressive)} "
            f"seconds={creation_seconds:.6f}",
            flush=True,
        )
        record = {
            "signature": signature,
            "progressive": bool(progressive),
            "created_at": started,
            "submitted_at": None,
            "reported_phases": set(),
            "received_qualities": set(),
            "sample": sample,
        }
        state["jobs"][id(job)] = record
        if sample is None:
            report["initialization"].setdefault("jobs", []).append({
                "signature": signature,
                "progressive": bool(progressive),
            })
        else:
            sample.setdefault("jobs", []).append({
                "signature": signature,
                "progressive": bool(progressive),
            })
            sample["started_signatures"].add(signature)
            sample["signature"] = signature
            state["sample_by_signature"][signature] = sample
            setup_phase = "preview" if progressive else "full"
            phase_record(sample, setup_phase)["jobs_started"] += 1
        return job

    backend.create_job = MethodType(timed_create_job, backend)

    original_ensure_runtime = backend._ensure_runtime

    def timed_ensure_runtime(self):
        if self.runtime is None and state["gpu_probe_started_at"] is None:
            state["gpu_probe_started_at"] = time.perf_counter()
        return original_ensure_runtime()

    backend._ensure_runtime = MethodType(timed_ensure_runtime, backend)

    original_advance = lut_helper.HelperStackJob.advance

    def record_worker_metrics(job, prepared, quality, received_at):
        diagnostics = prepared.diagnostics or {}
        sample = job["sample"] or state["sample_by_signature"].get(job["signature"])
        if sample is None:
            return
        if diagnostics.get("worker_program_reused") is not None:
            sample["gpu_program_reused"] = bool(diagnostics["worker_program_reused"])
        worker_started = diagnostics.get("worker_started_at")
        worker_finished = diagnostics.get("worker_calculated_at")
        if worker_started is not None and worker_finished is not None:
            phase_record(sample, quality)["worker_calculation_seconds"] = max(
                0.0, worker_finished - worker_started
            )
        setup = diagnostics.get("worker_setup_seconds")
        if setup is not None and not job.get("setup_recorded"):
            phase_record(sample, "preview" if job["progressive"] else "full")[
                "worker_setup_seconds"
            ] += setup
            job["setup_recorded"] = True
        phase_values = diagnostics.get("phases", {})
        for phase_name, values in phase_values.items():
            if phase_name in job["reported_phases"]:
                continue
            metrics = phase_record(sample, phase_name)
            for name in (
                "dispatch_batches", "dispatch_submission_seconds",
                "inter_step_wait_seconds", "texture_allocation_seconds",
                "readback_seconds",
            ):
                if name in values:
                    target = (
                        "worker_between_batches_seconds"
                        if name == "inter_step_wait_seconds" else name
                    )
                    metrics[target] += values[name]
            job["reported_phases"].add(phase_name)
        metrics = phase_record(sample, quality)
        if job["submitted_at"] is not None:
            metrics["helper_submit_to_result_seconds"] = max(
                0.0, received_at - job["submitted_at"]
            )

    def timed_advance(self):
        job = state["jobs"].get(id(self))
        had_group = self.group is not None
        receipt = original_advance(self)
        received_at = time.perf_counter()
        if job is not None and not had_group and self.group is not None:
            job["submitted_at"] = received_at
            requested_at = state["request_at"].get(
                (job["signature"], job["progressive"])
            )
            if requested_at is not None and job["sample"] is not None:
                phase = "preview" if job["progressive"] else "full"
                phase_record(job["sample"], phase)[
                    "request_to_helper_submit_seconds"
                ] = max(0.0, received_at - requested_at)
            print("PG_STACK_LUT helper job submitted", flush=True)
        if (job is not None and state["gpu_probe_started_at"] is not None
                and not state["gpu_probe_recorded"] and self.group is not None):
            state["gpu_probe_seconds"] = max(
                0.0, received_at - state["gpu_probe_started_at"]
            )
            state["gpu_probe_recorded"] = True
            record_initial("gpu_probe_seconds", state["gpu_probe_seconds"])
        if receipt is not None:
            quality, prepared = receipt
            signature = nodes._stack_signature(prepared.settings, prepared.space)
            state["ready_at"][(signature, quality)] = received_at
            job = state["jobs"].get(id(self)) or next(
                (candidate for candidate in state["jobs"].values()
                 if candidate["signature"] == signature), None
            )
            if job is not None:
                sample = job["sample"] or state["sample_by_signature"].get(signature)
                if sample is not None:
                    job["sample"] = sample
                    record_worker_metrics(job, prepared, quality, received_at)
                    job["received_qualities"].add(quality)
            print(f"PG_STACK_LUT {quality} helper result received", flush=True)
        return receipt

    lut_helper.HelperStackJob.advance = timed_advance

    original_request = runtime.request

    def timed_request(self, source, signature, settings, working_space, *, lane="linear",
                      progressive=None):
        sample = state["active_sample"]
        if lane == "lut" and sample is not None:
            progressive = (self._lanes[lane].progressive
                           if progressive is None else bool(progressive))
            state["request_at"][(signature, progressive)] = time.perf_counter()
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
                phase_record(sample, quality)["result_to_install_seconds"] = max(
                    0.0, started - ready_at
                )
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
            for field in (
                "jobs_started", "dispatch_batches", "dispatch_submission_seconds",
                "worker_between_batches_seconds", "texture_allocation_seconds",
                "readback_seconds", "worker_setup_seconds",
                "worker_calculation_seconds", "request_to_helper_submit_seconds",
                "helper_submit_to_result_seconds", "result_to_install_seconds",
                "kernel_build_seconds", "kernel_swap_seconds", "install_seconds",
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
    report["initialization"]["scenario_setup_seconds"] = (
        time.perf_counter() - state["baseline_started"]
    )
    save_report()
    first_interval = begin_drag()
    bpy.app.timers.register(run_drag_tick, first_interval=first_interval)


if __name__ == "__main__":
    main()
