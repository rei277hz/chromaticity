# HDR picker Blender adapter

`color_tools.hdr_color_picker_blender` owns the picker GPU renderer, viewport
interaction, sidebar, active OCIO view and Grease Pencil brush integration.
The product owns these implementations, its entrypoint, manifest and packaging.
Numerical transforms live in `hdr-color-picker-core`.

Each registration constructs an explicit `Session` and `blender_runtime.App`.
Its lifecycle Store runs on a private shared-framework ActorSystem; physical
execution helpers remain lazy. `services.py` configures those services, and
`jobs/` supplies picker-specific dispatch.
The Session's controller owns its arena and releases preview resources when
hidden or disabled. UI registrations, timers, handlers and GPU display state
belong to that same Session. Cleanup retains exact original handles across
reload and retries failed cleanup before allowing a fresh registration.
The installed package has its own private dependency namespace and never
imports or discovers another extension.

[Product tests](tests/) exercise the
installed package in native Blender 5.2.2, including compute/OCIO parity, real
viewport pixels, brush values, cancellation, scene undo and independent peer
shutdown. [Display limits](DISPLAY.md)
remain explicit; physical HDR and macOS/Metal are not established by Linux tests.
