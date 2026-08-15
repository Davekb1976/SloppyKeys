"""Raw ctypes bindings and Win32 constants.

Signatures are declared once here so callers get argument checking instead of
silently passing the wrong pointer type.
"""

from __future__ import annotations

import ctypes
from ctypes import wintypes

# # Process / window access
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
IMAGE_PATH_BUFFER_SIZE = 1024
WINDOW_CLASS_BUFFER_SIZE = 256

# # SetWindowPos flags
SWP_NOSIZE = 0x0001
SWP_NOMOVE = 0x0002
SWP_NOZORDER = 0x0004
SWP_NOACTIVATE = 0x0010
SWP_FRAMECHANGED = 0x0020
SWP_NOOWNERZORDER = 0x0200

# # SetWindowPos z-order targets
HWND_TOPMOST = -1
HWND_NOTOPMOST = -2

# # Region combine modes (CombineRgn)
RGN_DIFF = 4



# # ShowWindow commands
SW_MINIMIZE = 6
SW_RESTORE = 9

# # Virtual key codes
VK_LBUTTON = 0x01
VK_RBUTTON = 0x02
VK_SHIFT = 0x10
VK_CONTROL = 0x11
VK_MENU = 0x12  # Alt
VK_F1 = 0x70
VK_F3 = 0x72

KEY_DOWN_MASK = 0x8000

user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32
gdi32 = ctypes.windll.gdi32

WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)


def _set_sig(func, restype, *argtypes) -> None:
    func.argtypes = list(argtypes)
    func.restype = restype


_set_sig(user32.EnumWindows, wintypes.BOOL, WNDENUMPROC, wintypes.LPARAM)
_set_sig(
    user32.GetWindowThreadProcessId,
    wintypes.DWORD,
    wintypes.HWND,
    ctypes.POINTER(wintypes.DWORD),
)
_set_sig(user32.IsWindowVisible, wintypes.BOOL, wintypes.HWND)
_set_sig(user32.IsWindow, wintypes.BOOL, wintypes.HWND)
_set_sig(user32.IsIconic, wintypes.BOOL, wintypes.HWND)
_set_sig(user32.GetClassNameW, ctypes.c_int, wintypes.HWND, wintypes.LPWSTR, ctypes.c_int)
_set_sig(user32.GetWindowRect, wintypes.BOOL, wintypes.HWND, ctypes.POINTER(wintypes.RECT))
_set_sig(user32.GetClientRect, wintypes.BOOL, wintypes.HWND, ctypes.POINTER(wintypes.RECT))
_set_sig(user32.ClientToScreen, wintypes.BOOL, wintypes.HWND, ctypes.POINTER(wintypes.POINT))
# GetCursorPos takes LPPOINT; declaring it as such avoids the LP_POINT TypeError
# that byref(POINT) triggered under the previous c_void_p signature.
_set_sig(user32.GetCursorPos, wintypes.BOOL, ctypes.POINTER(wintypes.POINT))
_set_sig(user32.GetAsyncKeyState, wintypes.SHORT, wintypes.INT)
_set_sig(user32.ShowWindow, wintypes.BOOL, wintypes.HWND, ctypes.c_int)
_set_sig(user32.SetForegroundWindow, wintypes.BOOL, wintypes.HWND)
_set_sig(user32.GetWindowLongW, ctypes.c_long, wintypes.HWND, ctypes.c_int)
_set_sig(user32.SetWindowLongW, ctypes.c_long, wintypes.HWND, ctypes.c_int, ctypes.c_long)
_set_sig(user32.GetAncestor, wintypes.HWND, wintypes.HWND, ctypes.c_uint)
_set_sig(
    user32.SetWindowPos,
    wintypes.BOOL,
    wintypes.HWND,
    wintypes.HWND,
    ctypes.c_int,
    ctypes.c_int,
    ctypes.c_int,
    ctypes.c_int,
    ctypes.c_uint,
)

_set_sig(user32.FindWindowW, wintypes.HWND, wintypes.LPCWSTR, wintypes.LPCWSTR)
_set_sig(user32.SetWindowRgn, ctypes.c_int, wintypes.HWND, wintypes.HRGN, wintypes.BOOL)

_set_sig(
    gdi32.CreateRectRgn, wintypes.HRGN, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int
)
_set_sig(
    gdi32.CombineRgn, ctypes.c_int, wintypes.HRGN, wintypes.HRGN, wintypes.HRGN, ctypes.c_int
)
_set_sig(gdi32.DeleteObject, wintypes.BOOL, wintypes.HGDIOBJ)

_set_sig(kernel32.OpenProcess, wintypes.HANDLE, wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
_set_sig(
    kernel32.QueryFullProcessImageNameW,
    wintypes.BOOL,
    wintypes.HANDLE,
    wintypes.DWORD,
    wintypes.LPWSTR,
    ctypes.POINTER(wintypes.DWORD),
)
_set_sig(kernel32.CloseHandle, wintypes.BOOL, wintypes.HANDLE)


def is_key_down(virtual_key: int) -> bool:
    return bool(user32.GetAsyncKeyState(virtual_key) & KEY_DOWN_MASK)


def get_cursor_pos() -> tuple[int, int] | None:
    point = wintypes.POINT()
    if not user32.GetCursorPos(ctypes.byref(point)):
        return None
    return (int(point.x), int(point.y))
