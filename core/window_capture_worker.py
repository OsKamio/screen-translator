# -*- coding: utf-8 -*-
"""隔离 PrintWindow 的同步调用：父进程可超时终止，避免目标应用挂起引擎。"""
from __future__ import annotations
import ctypes as c
from ctypes import wintypes as w
import json
import struct
import sys


def render(request: dict) -> bytes:
    u = c.WinDLL("user32", use_last_error=True)
    g = c.WinDLL("gdi32", use_last_error=True)
    def bind(lib, name, args, result):
        fn = getattr(lib, name)
        fn.argtypes, fn.restype = args, result
        return fn
    try:
        bind(u, "SetProcessDpiAwarenessContext", [c.c_void_p], w.BOOL)(c.c_void_p(-4))
    except AttributeError:
        pass
    visible = bind(u, "IsWindowVisible", [w.HWND], w.BOOL)
    iconic = bind(u, "IsIconic", [w.HWND], w.BOOL)
    get_style = bind(u, "GetWindowLongW", [w.HWND, c.c_int], w.LONG)
    get_rect = bind(u, "GetWindowRect", [w.HWND, c.POINTER(w.RECT)], w.BOOL)
    get_class = bind(u, "GetClassNameW", [w.HWND, w.LPWSTR, c.c_int], c.c_int)
    enum_type = c.WINFUNCTYPE(w.BOOL, w.HWND, w.LPARAM)
    enum = bind(u, "EnumWindows", [enum_type, w.LPARAM], w.BOOL)
    dwm = c.WinDLL("dwmapi")
    attribute = bind(dwm, "DwmGetWindowAttribute", [w.HWND, w.DWORD, c.c_void_p, w.DWORD], w.LONG)
    x, y, width, height = request["rect"]
    ignored = set(request["ignore"])
    selected = []
    @enum_type
    def visit(hwnd, _param):
        if int(hwnd) in ignored or not visible(hwnd) or iconic(hwnd):
            return True
        if get_style(hwnd, -20) & 0x20:  # WS_EX_TRANSPARENT：鼠标/取景等穿透装饰层
            return True
        cloaked = w.DWORD()
        if attribute(hwnd, 14, c.byref(cloaked), c.sizeof(cloaked)) == 0 and cloaked.value:
            return True
        r = w.RECT()
        if not get_rect(hwnd, c.byref(r)):
            return True
        if r.right <= x or r.bottom <= y or r.left >= x+width or r.top >= y+height:
            return True
        name = c.create_unicode_buffer(256)
        get_class(hwnd, name, 256)
        if name.value in {"Progman", "WorkerW", "Shell_TrayWnd"}:
            return False  # 桌面及任务栏不能当作可独立绘制的内容窗口
        if r.left <= x and r.top <= y and r.right >= x+width and r.bottom >= y+height:
            selected.append((hwnd, r))
        return False  # 首个相交窗口未覆盖整块区域：不要误截更下层的应用
    enum(visit, 0)
    if not selected:
        return b""
    hwnd, r = selected[0]
    ww, hh = r.right-r.left, r.bottom-r.top
    if ww <= 0 or hh <= 0 or ww*hh > 32_000_000:
        return b""
    class BI(c.Structure):
        _fields_ = [("size", w.DWORD), ("width", w.LONG), ("height", w.LONG),
                    ("planes", w.WORD), ("bits", w.WORD), ("compression", w.DWORD),
                    ("image", w.DWORD), ("x", w.LONG), ("y", w.LONG),
                    ("used", w.DWORD), ("important", w.DWORD), ("colors", w.DWORD*3)]
    get_dc = bind(u, "GetDC", [w.HWND], w.HDC)
    release = bind(u, "ReleaseDC", [w.HWND, w.HDC], c.c_int)
    create_dc = bind(g, "CreateCompatibleDC", [w.HDC], w.HDC)
    create_dib = bind(g, "CreateDIBSection", [w.HDC, c.c_void_p, w.UINT, c.POINTER(c.c_void_p), w.HANDLE, w.DWORD], w.HBITMAP)
    select = bind(g, "SelectObject", [w.HDC, w.HGDIOBJ], w.HGDIOBJ)
    delete = bind(g, "DeleteObject", [w.HGDIOBJ], w.BOOL)
    delete_dc = bind(g, "DeleteDC", [w.HDC], w.BOOL)
    print_window = bind(u, "PrintWindow", [w.HWND, w.HDC, w.UINT], w.BOOL)
    flush = bind(g, "GdiFlush", [], w.BOOL)
    dc = get_dc(None)
    mem = create_dc(dc)
    info = BI()
    info.size, info.width, info.height = 40, ww, -hh
    info.planes, info.bits = 1, 32
    bits = c.c_void_p()
    bitmap = create_dib(dc, c.byref(info), 0, c.byref(bits), None, 0)
    if not dc or not mem or not bitmap or not bits.value:
        if bitmap: delete(bitmap)
        if mem: delete_dc(mem)
        if dc: release(None, dc)
        return b""
    old = select(mem, bitmap)
    try:
        if not print_window(hwnd, mem, 2):  # PW_RENDERFULLCONTENT
            return b""
        flush()
        offset = ((y-r.top)*ww + x-r.left)*4
        rows = [c.string_at(bits.value+offset+row*ww*4, width*4) for row in range(height)]
        return struct.pack("<II", width, height) + b"".join(rows)
    finally:
        select(mem, old)
        delete(bitmap)
        delete_dc(mem)
        release(None, dc)

if __name__ == "__main__":
    try:
        sys.stdout.buffer.write(render(json.load(sys.stdin)))
    except Exception:
        sys.exit(1)
