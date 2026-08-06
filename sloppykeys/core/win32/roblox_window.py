"""Locating, measuring and repositioning the Roblox game window."""

from __future__ import annotations

import ctypes
import os
from ctypes import wintypes

from .bindings import (
    IMAGE_PATH_BUFFER_SIZE,
    PROCESS_QUERY_LIMITED_INFORMATION,
    SW_RESTORE,
    SWP_NOACTIVATE,
    SWP_NOOWNERZORDER,
    SWP_NOZORDER,
    WINDOW_CLASS_BUFFER_SIZE,
    WNDENUMPROC,
    kernel32,
    user32,
)

ROBLOX_PROCESS_NAMES = {"robloxplayerbeta.exe", "robloxplayerlauncher.exe"}
ROBLOX_WINDOW_CLASS = "windowsclient"


def get_process_exe_name(pid: int) -> str:
    handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not handle:
        return ""

    try:
        buffer_size = wintypes.DWORD(IMAGE_PATH_BUFFER_SIZE)
        buffer = ctypes.create_unicode_buffer(buffer_size.value)
        if not kernel32.QueryFullProcessImageNameW(handle, 0, buffer, ctypes.byref(buffer_size)):
            return ""
        return os.path.basename(buffer.value)
    finally:
        kernel32.CloseHandle(handle)


def window_rect(hwnd: int) -> tuple[int, int, int, int] | None:
    rect = wintypes.RECT()
    if not user32.GetWindowRect(hwnd, ctypes.byref(rect)):
        return None
    return (rect.left, rect.top, rect.right, rect.bottom)


def window_class_name(hwnd: int) -> str:
    buffer = ctypes.create_unicode_buffer(WINDOW_CLASS_BUFFER_SIZE)
    if user32.GetClassNameW(hwnd, buffer, WINDOW_CLASS_BUFFER_SIZE) <= 0:
        return ""
    return buffer.value


def window_frame_offsets(hwnd: int) -> tuple[int, int, int, int]:
    """Border thickness (left, top, right, bottom) between window and client area."""
    outer = wintypes.RECT()
    client = wintypes.RECT()
    client_origin = wintypes.POINT(0, 0)

    if not user32.GetWindowRect(hwnd, ctypes.byref(outer)):
        return (0, 0, 0, 0)
    if not user32.GetClientRect(hwnd, ctypes.byref(client)):
        return (0, 0, 0, 0)
    if not user32.ClientToScreen(hwnd, ctypes.byref(client_origin)):
        return (0, 0, 0, 0)

    client_width = client.right - client.left
    client_height = client.bottom - client.top

    return (
        max(0, client_origin.x - outer.left),
        max(0, client_origin.y - outer.top),
        max(0, outer.right - (client_origin.x + client_width)),
        max(0, outer.bottom - (client_origin.y + client_height)),
    )


def client_to_screen(hwnd: int, client_x: int, client_y: int) -> tuple[int, int] | None:
    point = wintypes.POINT(int(client_x), int(client_y))
    if not user32.ClientToScreen(hwnd, ctypes.byref(point)):
        return None
    return (int(point.x), int(point.y))


def client_size(hwnd: int) -> tuple[int, int] | None:
    rect = wintypes.RECT()
    if not user32.GetClientRect(hwnd, ctypes.byref(rect)):
        return None
    return (rect.right - rect.left, rect.bottom - rect.top)


def find_roblox_window() -> int | None:
    """Pick the real game window, preferring the player over launcher/utility windows."""
    found_hwnd: int | None = None
    best_score = (-1, -1, -1)

    def callback(hwnd: int, _lparam: int) -> bool:
        nonlocal found_hwnd, best_score

        if not user32.IsWindowVisible(hwnd):
            return True

        pid = wintypes.DWORD(0)
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if pid.value == 0:
            return True

        exe_name = get_process_exe_name(pid.value).lower()
        if exe_name not in ROBLOX_PROCESS_NAMES:
            return True

        if window_class_name(hwnd).lower() != ROBLOX_WINDOW_CLASS:
            return True

        if user32.IsIconic(hwnd):
            return True

        rect = window_rect(hwnd)
        area = 0 if rect is None else max(0, rect[2] - rect[0]) * max(0, rect[3] - rect[1])

        score = (1 if exe_name == "robloxplayerbeta.exe" else 0, 1, int(area))
        if score > best_score:
            best_score = score
            found_hwnd = hwnd

        return True

    user32.EnumWindows(WNDENUMPROC(callback), 0)
    return found_hwnd


def position_window_to_client_rect(
    hwnd: int,
    target_x: int,
    target_y: int,
    target_w: int,
    target_h: int,
) -> bool:
    """Move/resize so the window's *client area* lands exactly on the target rect."""
    left, top, right, bottom = window_frame_offsets(hwnd)

    return bool(
        user32.SetWindowPos(
            hwnd,
            0,
            target_x - left,
            target_y - top,
            target_w + left + right,
            target_h + top + bottom,
            SWP_NOZORDER | SWP_NOACTIVATE | SWP_NOOWNERZORDER,
        )
    )


def activate_window(hwnd: int) -> bool:
    if not user32.IsWindow(hwnd):
        return False
    if user32.IsIconic(hwnd):
        user32.ShowWindow(hwnd, SW_RESTORE)
    return bool(user32.SetForegroundWindow(hwnd))


def is_window(hwnd: int | None) -> bool:
    return hwnd is not None and bool(user32.IsWindow(hwnd))


def is_minimized(hwnd: int) -> bool:
    return bool(user32.IsIconic(hwnd))
