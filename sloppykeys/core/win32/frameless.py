"""Frameless-window helpers: drop the native caption, and drop DWM's own border.

Qt's `FramelessWindowHint` removes the caption but *not* the 1px border the Desktop
Window Manager paints around every top-level window on Windows 11.
"""

from __future__ import annotations

import ctypes
from ctypes import wintypes

from .bindings import SW_MINIMIZE, SWP_FRAMECHANGED, SWP_NOMOVE, SWP_NOSIZE, SWP_NOZORDER, user32

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
