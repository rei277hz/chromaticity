"""Buck2 NativeLink executors, configured by the root Buck configuration."""

load("@prelude//cfg/exec_platform:marker.bzl", "get_exec_platform_marker")

def remote_enabled():
    value = read_root_config("remote_execution", "enabled", "false").lower()
    if value not in ["true", "false"]:
        fail("remote_execution.enabled must be true or false")
    return value == "true"

def platform_properties():
    image = read_root_config("remote_execution", "worker_image", "unconfigured")
    if remote_enabled() and not image.startswith("sha256:"):
        fail("NativeLink needs remote_execution.worker_image set to the built Docker image ID; run remote_execution/re up")
    return {
        "OSFamily": "linux",
        "ISA": "x86-64",
        "worker-image": image,
    }

def test_profile():
    return "remote" if remote_enabled() else None

def test_profiles():
    if not remote_enabled():
        return {}
    return {"remote": {
        "capabilities": platform_properties(),
        "use_case": "perceptual-grade",
        "local_enabled": False,
        "remote_cache_enabled": True,
    }}

def _platform_impl(ctx):
    constraints = {}
    for configuration in ctx.attrs.constraints:
        constraints.update(configuration[ConfigurationInfo].constraints)
    configuration = ConfigurationInfo(constraints = constraints, values = {})
    label = ctx.label.raw_target()
    platform = ExecutionPlatformInfo(
        label = label,
        configuration = configuration,
        executor_config = CommandExecutorConfig(
            local_enabled = False,
            remote_enabled = True,
            remote_cache_enabled = True,
            remote_execution_properties = ctx.attrs.properties,
            remote_execution_use_case = "perceptual-grade",
            remote_output_paths = "output_paths",
            allow_cache_uploads = False,
        ),
    )
    return [
        DefaultInfo(),
        platform,
        PlatformInfo(label = str(label), configuration = configuration),
    ]

nativelink_platform = rule(
    impl = _platform_impl,
    attrs = {
        "constraints": attrs.list(attrs.dep(providers = [ConfigurationInfo])),
        "properties": attrs.dict(attrs.string(), attrs.string()),
    },
)

def _platforms_impl(ctx):
    return [
        DefaultInfo(),
        ExecutionPlatformRegistrationInfo(
            platforms = [platform[ExecutionPlatformInfo] for platform in ctx.attrs.platforms],
            fallback = "error",
            exec_marker_constraint = get_exec_platform_marker(),
        ),
    ]

nativelink_platforms = rule(
    impl = _platforms_impl,
    attrs = {"platforms": attrs.list(attrs.dep(providers = [ExecutionPlatformInfo]))},
)
