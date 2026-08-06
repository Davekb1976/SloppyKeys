"""Monitor mode queries: which display a window is on, and how fast it refreshes.

Refresh rate is not cosmetic here. Roblox acts on the last mouse-move it has *processed*,
and it processes them per rendered frame, so every input timing in `macro/input_scripts.py`
is really a frame count wearing milliseconds. A settle tuned on a 165Hz panel covers 2.75x
fewer frames at 60Hz, and the click then lands on a stale cursor position — the same macro
misplacing clicks on one monitor and not another, at identical resolution and scaling.

Typed ctypes like the rest of `core/win32`: argtypes declared so a wrong pointer type fails
loudly rather than returning nonsense.
"""

from __future__ import annotations

import ctypes
from ctypes import wintypes

user32 = ctypes.WinDLL("user32", use_last_error=True)
shcore = ctypes.WinDLL("shcore", use_last_error=True)
shcore.GetDpiForMonitor.argtypes = [
    ctypes.c_void_p,
    ctypes.c_int,
    ctypes.POINTER(ctypes.c_uint),
    ctypes.POINTER(ctypes.c_uint),
]
shcore.GetDpiForMonitor.restype = ctypes.c_long

MONITOR_DEFAULTTONEAREST = 2
ENUM_CURRENT_SETTINGS = -1

# What a monitor reports when it doesn't know its own rate (virtual displays, RDP).
UNKNOWN_FREQUENCIES = (0, 1)
DEFAULT_REFRESH_HZ = 60


class MONITORINFOEXW(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.DWORD),
        ("rcMonitor", wintypes.RECT),
        ("rcWork", wintypes.RECT),
        ("dwFlags", wintypes.DWORD),
        ("szDevice", wintypes.WCHAR * 32),
    ]


class DEVMODEW(ctypes.Structure):
    """Only the fields up to dmDisplayFrequency matter here, but the layout must be
    complete or `dmSize` is wrong and EnumDisplaySettingsW fills nothing."""

    _fields_ = [
        ("dmDeviceName", wintypes.WCHAR * 32),
        ("dmSpecVersion", wintypes.WORD),
        ("dmDriverVersion", wintypes.WORD),
        ("dmSize", wintypes.WORD),
        ("dmDriverExtra", wintypes.WORD),
        ("dmFields", wintypes.DWORD),
        ("dmPositionX", ctypes.c_long),
        ("dmPositionY", ctypes.c_long),
        ("dmDisplayOrientation", wintypes.DWORD),
        ("dmDisplayFixedOutput", wintypes.DWORD),
        ("dmColor", ctypes.c_short),
        ("dmDuplex", ctypes.c_short),
        ("dmYResolution", ctypes.c_short),
        ("dmTTOption", ctypes.c_short),
        ("dmCollate", ctypes.c_short),
        ("dmFormName", wintypes.WCHAR * 32),
        ("dmLogPixels", wintypes.WORD),
        ("dmBitsPerPel", wintypes.DWORD),
        ("dmPelsWidth", wintypes.DWORD),
        ("dmPelsHeight", wintypes.DWORD),
        ("dmDisplayFlags", wintypes.DWORD),
        ("dmDisplayFrequency", wintypes.DWORD),
        ("dmICMMethod", wintypes.DWORD),
        ("dmICMIntent", wintypes.DWORD),
        ("dmMediaType", wintypes.DWORD),
        ("dmDitherType", wintypes.DWORD),
        ("dmReserved1", wintypes.DWORD),
        ("dmReserved2", wintypes.DWORD),
        ("dmPanningWidth", wintypes.DWORD),
        ("dmPanningHeight", wintypes.DWORD),
    ]


user32.MonitorFromWindow.argtypes = [wintypes.HWND, wintypes.DWORD]
user32.MonitorFromWindow.restype = ctypes.c_void_p
user32.GetMonitorInfoW.argtypes = [ctypes.c_void_p, ctypes.POINTER(MONITORINFOEXW)]
user32.GetMonitorInfoW.restype = wintypes.BOOL
user32.EnumDisplaySettingsW.argtypes = [
    wintypes.LPCWSTR,
    wintypes.DWORD,
    ctypes.POINTER(DEVMODEW),
]
user32.EnumDisplaySettingsW.restype = wintypes.BOOL


def device_name_for_window(hwnd: int) -> str:
    """The `\\\\.\\DISPLAYn` the window mostly sits on, or "" if it can't be resolved."""
    monitor = user32.MonitorFromWindow(hwnd, MONITOR_DEFAULTTONEAREST)
    if not monitor:
        return ""
    info = MONITORINFOEXW()
    info.cbSize = ctypes.sizeof(MONITORINFOEXW)
    if not user32.GetMonitorInfoW(monitor, ctypes.byref(info)):
        return ""
    return str(info.szDevice)


def scale_percent_for_window(hwnd: int | None) -> int:
    """Windows display scaling of the monitor this window is on, as a percentage.

    100 means 96 DPI. **Anything else breaks this macro**, and it does so silently.

    Roblox is per-monitor DPI aware, so on a scaled monitor it lays its UI out larger in
    physical pixels — and it has a long-standing quality regression there, so the result is
    both bigger *and* blurry (Roblox devforum: "Roblox Loses Visual Quality above 100%
    Display Scaling", "Roblox Client Renders at a Low Resolution"). Everything this project
    stores is calibrated at 100%: the 1152x756 client, every coordinate in `content/`, every
    template's pixel size. At 125% a button is 1.25x larger, so a template cropped at 100%
    scores as if it were the wrong image (measured: best match at **0.80x = 1/1.25**) and a
    stored coordinate lands on the wrong element.

    `GetDpiForMonitor` is used rather than `GetDpiForWindow` on purpose: it reports the
    monitor's real DPI regardless of *this* process's awareness, whereas `GetDpiForWindow`
    answers 96 for a DPI-unaware caller and would hide exactly the case worth warning about.
    """
    if hwnd is None:
        return 100
    monitor = user32.MonitorFromWindow(hwnd, MONITOR_DEFAULTTONEAREST)
    if not monitor:
        return 100
    x_dpi, y_dpi = ctypes.c_uint(), ctypes.c_uint()
    try:
        # MDT_EFFECTIVE_DPI = 0
        if shcore.GetDpiForMonitor(monitor, 0, ctypes.byref(x_dpi), ctypes.byref(y_dpi)) != 0:
            return 100
    except (OSError, AttributeError):
        return 100
    if not x_dpi.value:
        return 100
    return round(x_dpi.value / 96 * 100)


def refresh_hz_for_window(hwnd: int | None) -> int:
    """Refresh rate of the monitor this window is on, in Hz.

    Falls back to `DEFAULT_REFRESH_HZ` rather than raising: a wrong-but-sane frame time is
    far better than a failed macro step, and 60 is the conservative direction (it asks for
    *more* settle time, never less).
    """
    if hwnd is None:
        return DEFAULT_REFRESH_HZ
    device = device_name_for_window(hwnd)
    if not device:
        return DEFAULT_REFRESH_HZ
    mode = DEVMODEW()
    mode.dmSize = ctypes.sizeof(DEVMODEW)
    if not user32.EnumDisplaySettingsW(device, ENUM_CURRENT_SETTINGS, ctypes.byref(mode)):
        return DEFAULT_REFRESH_HZ
    frequency = int(mode.dmDisplayFrequency)
    if frequency in UNKNOWN_FREQUENCIES:
        return DEFAULT_REFRESH_HZ
    return frequency
