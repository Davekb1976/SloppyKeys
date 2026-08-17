"""Frameless-window helpers: drop the native caption, and drop DWM's own border.

Qt's `FramelessWindowHint` removes the caption but *not* the 1px border the Desktop
Window Manager paints around every top-level window on Windows 11.
"""

from __future__ import annotations

import ctypes
from ctypes import wintypes

from .bindings import (
    HWND_NOTOPMOST,
    HWND_TOPMOST,
    SPI_GETWORKAREA,
    SW_MINIMIZE,
    SWP_FRAMECHANGED,
    SWP_NOACTIVATE,
    SWP_NOMOVE,
    SWP_NOSIZE,
    SWP_NOZORDER,
    user32,
)

GWL_STYLE = -16

# DwmSetWindowAttribute: suppress the window border entirely.
# DWMWA_BORDER_COLOR = 34, DWMWA_COLOR_NONE = 0xFFFFFFFE — Windows 11 build 22000+.
# https://learn.microsoft.com/en-us/windows/win32/api/dwmapi/ne-dwmapi-dwmwindowattribute
DWMWA_BORDER_COLOR = 34
DWMWA_COLOR_NONE = 0xFFFFFFFE

_dwmapi = ctypes.WinDLL("dwmapi")
_dwmapi.DwmSetWindowAttribute.argtypes = [
    wintypes.HWND,
    wintypes.DWORD,
    ctypes.c_void_p,
    wintypes.DWORD,
]
_dwmapi.DwmSetWindowAttribute.restype = ctypes.c_long  # HRESULT


def suppress_dwm_border(hwnd: int) -> bool:
    """Stop DWM painting its border around a frameless window. True if it took.

    Our window is frameless and masked (rounded corners minus the Roblox hole), but DWM
    still draws its 1px border at the window's *full, unmasked* rect — so it reads as a
    pale outline that doesn't follow the visible content, and because DWM repaints it on
    activation changes it comes and goes. Suppressing it is the documented way to have a
    rounded borderless window.

    Returns False rather than raising on an older Windows that doesn't know the attribute:
    a stray border is cosmetic, and nothing else depends on this.
    """
    value = wintypes.DWORD(DWMWA_COLOR_NONE)
    result = _dwmapi.DwmSetWindowAttribute(
        wintypes.HWND(hwnd),
        wintypes.DWORD(DWMWA_BORDER_COLOR),
        ctypes.byref(value),
        ctypes.sizeof(value),
    )
    return result == 0  # S_OK

WS_CAPTION = 0x00C00000
WS_THICKFRAME = 0x00040000
WS_MINIMIZEBOX = 0x00020000
WS_MAXIMIZEBOX = 0x00010000
WS_SYSMENU = 0x00080000


GA_ROOT = 2


def root_hwnd(child_hwnd: int) -> int:
    """The top-level window for a Tk child handle.

    Tk's winfo_id() returns the client child; the caption lives on its root
    ancestor, which is what style changes must target.
    """
    result = user32.GetAncestor(child_hwnd, GA_ROOT)
    return int(result) if result else child_hwnd


def make_frameless(hwnd: int) -> bool:
    """Drop the caption and resize border; keep minimize and the system menu."""
    style = user32.GetWindowLongW(hwnd, GWL_STYLE)
    if style == 0:
        return False

    new_style = style & ~WS_CAPTION & ~WS_THICKFRAME & ~WS_MAXIMIZEBOX
    new_style |= WS_MINIMIZEBOX | WS_SYSMENU

    user32.SetWindowLongW(hwnd, GWL_STYLE, new_style)
    return bool(
        user32.SetWindowPos(
            hwnd,
            0,
            0,
            0,
            0,
            0,
            SWP_NOMOVE | SWP_NOSIZE | SWP_NOZORDER | SWP_FRAMECHANGED,
        )
    )


def minimize(hwnd: int) -> None:
    user32.ShowWindow(hwnd, SW_MINIMIZE)


def find_window_by_title(title: str) -> int | None:
    """Top-level window with this exact caption, or None."""
    hwnd = user32.FindWindowW(None, title)
    return int(hwnd) if hwnd else None


def set_topmost(hwnd: int, on: bool) -> bool:
    """Pin the window above the normal z-order band, or release it."""
    return bool(
        user32.SetWindowPos(
            hwnd,
            HWND_TOPMOST if on else HWND_NOTOPMOST,
            0,
            0,
            0,
            0,
            SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE,
        )
    )


def set_window_below(hwnd: int, above_hwnd: int) -> bool:
    """Put `hwnd` directly beneath `above_hwnd` in the z-order, leaving it shown.

    `set_topmost(hwnd, False)` is not enough to get a window out of the way:
    HWND_NOTOPMOST drops it to the *top* of the non-topmost band, which is still
    above ours, so it keeps painting over the page. This is how the game gets
    covered without SW_HIDE — which would also drop its taskbar button.
    """
    return bool(
        user32.SetWindowPos(
            hwnd,
            above_hwnd,
            0,
            0,
            0,
            0,
            SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE,
        )
    )


def work_area() -> tuple[int, int, int, int]:
    """The primary screen minus the taskbar, as (left, top, width, height)."""
    rect = wintypes.RECT()
    if not user32.SystemParametersInfoW(SPI_GETWORKAREA, 0, ctypes.byref(rect), 0):
        return (0, 0, user32.GetSystemMetrics(0), user32.GetSystemMetrics(1))
    return (rect.left, rect.top, rect.right - rect.left, rect.bottom - rect.top)


def fit_and_centre(hwnd: int, width: int, height: int) -> tuple[int, int]:
    """Size the window to exactly width x height, clamped to the work area.

    The window is frameless, so its window rect is its client rect (measured:
    identical origin and size) and the size asked for here is the space the page
    actually gets. Returns the size applied, which is what the caller should
    treat as the layout's real height once a short screen has clamped it.

    Centred on the *primary* work area: a shorter secondary screen would clip a
    window this tall.
    """
    area_x, area_y, area_w, area_h = work_area()
    w = min(int(width), area_w)
    h = min(int(height), area_h)
    x = area_x + (area_w - w) // 2
    y = area_y + (area_h - h) // 2
    user32.SetWindowPos(hwnd, 0, x, y, w, h, SWP_NOZORDER | SWP_NOACTIVATE)
    return (w, h)


def move_to(hwnd: int, x: int, y: int) -> bool:
    """Move without resizing, activating, or leaving the topmost band."""
    return bool(
        user32.SetWindowPos(
            hwnd, 0, int(x), int(y), 0, 0, SWP_NOSIZE | SWP_NOZORDER | SWP_NOACTIVATE
        )
    )
