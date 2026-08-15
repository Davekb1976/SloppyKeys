"""Frameless-window helpers: drop the native caption, and drop DWM's own border.

Qt's `FramelessWindowHint` removes the caption but *not* the 1px border the Desktop
Window Manager paints around every top-level window on Windows 11.
"""

from __future__ import annotations

import ctypes
from ctypes import wintypes

from .bindings import (
    HTCAPTION,
    HWND_NOTOPMOST,
    HWND_TOPMOST,
    RGN_DIFF,
    SW_MINIMIZE,
    SWP_FRAMECHANGED,
    SWP_NOACTIVATE,
    SWP_NOMOVE,
    SWP_NOSIZE,
    SWP_NOZORDER,
    WM_NCLBUTTONDOWN,
    gdi32,
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


def set_cutout_mask(
    hwnd: int,
    width: int,
    height: int,
    hole: tuple[int, int, int, int] | None,
) -> bool:
    """Shape the window to `width`x`height` minus `hole` (x, y, w, h), or clear it.

    Region coordinates are relative to the window's upper-left. The window is
    frameless, so its window rect equals its client rect (measured: identical
    origin and size) and CSS pixels map straight through at 100% scaling — the
    hole rect can be handed over exactly as the DOM reports it.

    Pixels inside the hole leave the window entirely: whatever sits behind
    renders there and takes the clicks. Passing None restores a solid window.
    """
    if hole is None:
        return user32.SetWindowRgn(hwnd, None, True) != 0

    x, y, w, h = (int(v) for v in hole)
    if w <= 0 or h <= 0:
        return user32.SetWindowRgn(hwnd, None, True) != 0

    outer = gdi32.CreateRectRgn(0, 0, int(width), int(height))
    inner = gdi32.CreateRectRgn(x, y, x + w, y + h)
    if not outer or not inner:
        # Nothing was handed to the window, so both handles are still ours.
        gdi32.DeleteObject(outer)
        gdi32.DeleteObject(inner)
        return False

    gdi32.CombineRgn(outer, outer, inner, RGN_DIFF)
    gdi32.DeleteObject(inner)

    # SetWindowRgn takes ownership of `outer` on success — deleting it here
    # would leave the window pointing at a freed region.
    if user32.SetWindowRgn(hwnd, outer, True) == 0:
        gdi32.DeleteObject(outer)
        return False
    return True


def begin_caption_drag(hwnd: int) -> None:
    """Hand the window to the OS move loop as if the caption had been grabbed.

    The mouse button is already physically down when this is called from the
    titlebar's mousedown, so DefWindowProc's modal loop tracks the cursor and
    ends on the real button release. Dragging then costs zero round trips per
    frame, which is the difference between smooth and stuttering.
    """
    user32.ReleaseCapture()
    user32.SendMessageW(hwnd, WM_NCLBUTTONDOWN, HTCAPTION, 0)
