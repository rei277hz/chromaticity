"""Passive X11 sampling of actual Blender-window pixels for Shader timing."""

import ctypes
import json
from math import isfinite
from pathlib import Path
import time


class _XVisualInfo(ctypes.Structure):
    _fields_ = [
        ("visual", ctypes.c_void_p), ("visualid", ctypes.c_ulong),
        ("screen", ctypes.c_int), ("depth", ctypes.c_int),
        ("class_id", ctypes.c_int), ("red_mask", ctypes.c_ulong),
        ("green_mask", ctypes.c_ulong), ("blue_mask", ctypes.c_ulong),
        ("colormap_size", ctypes.c_int), ("bits_per_rgb", ctypes.c_int),
    ]


def _channel(value, mask):
    if not mask:
        return 0
    shift = (mask & -mask).bit_length() - 1
    maximum = mask >> shift
    return round(((value & mask) >> shift) * 255 / maximum)


def _pixel_average(xlib, image, x, y, red_mask, green_mask, blue_mask):
    samples = []
    for row in range(y - 2, y + 3):
        for column in range(x - 2, x + 3):
            value = xlib.XGetPixel(image, column, row)
            samples.append((_channel(value, red_mask), _channel(value, green_mask),
                            _channel(value, blue_mask)))
    return [round(sum(pixel[index] for pixel in samples) / len(samples))
            for index in range(3)]


def validate_capture_request(request, width, height):
    """Return validated integer centers whose 5x5 ROIs fit the root window."""
    if not isinstance(request, dict):
        raise ValueError("Capture request must be an object")
    points = request.get("points")
    if not isinstance(points, (list, tuple)) or len(points) != 4:
        raise ValueError("Capture request must contain four swatch points")
    validated = []
    for point in points:
        if (not isinstance(point, (list, tuple)) or len(point) != 2
                or any(type(value) is not int for value in point)):
            raise ValueError("Capture points must be integer X11 coordinates")
        x, y = point
        if x < 2 or y < 2 or x + 3 > width or y + 3 > height:
            raise ValueError("Capture point 5x5 region is outside the X11 root window")
        validated.append((x, y))
    return tuple(validated)


def _load_x11(libraries):
    # Buck's Python interpreter has its own loader search paths. Load each
    # pinned dependency globally before its consumer, without relying on a
    # host X11 installation or changing process-global environment variables.
    names = ("libmd.so.0", "libbsd.so.0", "libXau.so.6", "libXdmcp.so.6",
             "libxcb.so.1", "libX11.so.6")
    loaded = []
    for name in names:
        try:
            loaded.append(ctypes.CDLL(str(libraries / name), mode=ctypes.RTLD_GLOBAL))
        except OSError as error:
            raise RuntimeError(f"Could not load bundled X11 dependency {name}: {error}") from error
    return loaded


def capture_loop(fixture, display, request_path, trace_path, stop_path, interval_ms=5.):
    """Poll request JSON and append timestamped four-point X11 observations."""
    if not isfinite(interval_ms) or interval_ms <= 0:
        raise ValueError("Capture interval must be finite and positive")
    libraries = Path(fixture) / "usr/lib/x86_64-linux-gnu"
    loaded_libraries = _load_x11(libraries)
    xlib = loaded_libraries[-1]
    xlib.XOpenDisplay.argtypes = [ctypes.c_char_p]
    xlib.XOpenDisplay.restype = ctypes.c_void_p
    xlib.XCloseDisplay.argtypes = [ctypes.c_void_p]
    xlib.XDefaultScreen.argtypes = [ctypes.c_void_p]
    xlib.XDefaultScreen.restype = ctypes.c_int
    xlib.XRootWindow.argtypes = [ctypes.c_void_p, ctypes.c_int]
    xlib.XRootWindow.restype = ctypes.c_ulong
    xlib.XDefaultDepth.argtypes = [ctypes.c_void_p, ctypes.c_int]
    xlib.XDefaultDepth.restype = ctypes.c_int
    xlib.XDisplayWidth.argtypes = [ctypes.c_void_p, ctypes.c_int]
    xlib.XDisplayWidth.restype = ctypes.c_int
    xlib.XDisplayHeight.argtypes = [ctypes.c_void_p, ctypes.c_int]
    xlib.XDisplayHeight.restype = ctypes.c_int
    xlib.XMatchVisualInfo.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_int,
                                      ctypes.c_int, ctypes.POINTER(_XVisualInfo)]
    xlib.XMatchVisualInfo.restype = ctypes.c_int
    xlib.XGetImage.argtypes = [ctypes.c_void_p, ctypes.c_ulong, ctypes.c_int,
                               ctypes.c_int, ctypes.c_uint, ctypes.c_uint,
                               ctypes.c_ulong, ctypes.c_int]
    xlib.XGetImage.restype = ctypes.c_void_p
    xlib.XGetPixel.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_int]
    xlib.XGetPixel.restype = ctypes.c_ulong
    xlib.XDestroyImage.argtypes = [ctypes.c_void_p]
    xlib.XSync.argtypes = [ctypes.c_void_p, ctypes.c_int]

    connection = xlib.XOpenDisplay(display.encode("ascii"))
    if not connection:
        raise RuntimeError(f"Could not open X11 display {display}")
    screen = xlib.XDefaultScreen(connection)
    visual = _XVisualInfo()
    depth = xlib.XDefaultDepth(connection, screen)
    if not xlib.XMatchVisualInfo(connection, screen, depth, 4, ctypes.byref(visual)):
        xlib.XCloseDisplay(connection)
        raise RuntimeError("X11 display has no TrueColor visual")
    root = xlib.XRootWindow(connection, screen)
    width = xlib.XDisplayWidth(connection, screen)
    height = xlib.XDisplayHeight(connection, screen)
    request_path, trace_path, stop_path = map(Path, (request_path, trace_path, stop_path))
    previous_request = None
    previous_end = None
    request_mtime = None
    try:
        with trace_path.open("a", encoding="utf8", buffering=1) as trace:
            while not stop_path.exists():
                try:
                    current_mtime = request_path.stat().st_mtime_ns
                    if current_mtime != request_mtime:
                        request = json.loads(request_path.read_text(encoding="utf8"))
                        request_mtime = current_mtime
                        previous_request = request
                    else:
                        request = previous_request
                except (FileNotFoundError, json.JSONDecodeError):
                    request = None
                if request and request.get("enabled"):
                    points = validate_capture_request(request, width, height)
                    started = time.perf_counter_ns()
                    xlib.XSync(connection, 0)
                    left = min(point[0] for point in points) - 2
                    top = min(point[1] for point in points) - 2
                    right = max(point[0] for point in points) + 3
                    bottom = max(point[1] for point in points) + 3
                    image = xlib.XGetImage(connection, root, left, top,
                                           right - left, bottom - top, 0xFFFFFFFF, 2)
                    if not image:
                        raise RuntimeError("XGetImage failed while sampling Shader viewport")
                    try:
                        colors = [_pixel_average(
                            xlib, image, point[0] - left, point[1] - top,
                            visual.red_mask, visual.green_mask, visual.blue_mask,
                        ) for point in points]
                    finally:
                        xlib.XDestroyImage(image)
                    xlib.XSync(connection, 0)
                    finished = time.perf_counter_ns()
                    trace.write(json.dumps({
                        "start_ns": started, "end_ns": finished,
                        "previous_end_ns": previous_end,
                        "request_id": request.get("request_id"),
                        "observed": colors,
                    }, separators=(",", ":")) + "\n")
                    previous_end = finished
                time.sleep(interval_ms / 1000.)
    finally:
        xlib.XCloseDisplay(connection)


__all__ = ("capture_loop", "validate_capture_request")
