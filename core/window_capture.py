# -*- coding: utf-8 -*-
"""直接读取下层应用窗口，不清空译文，也不影响录屏/投屏。"""
from __future__ import annotations
import json
import logging
from pathlib import Path
import struct
import subprocess
import sys
import numpy as np
from .screen import match_monitor

log = logging.getLogger(__name__)


def capture_window(spec, rect, ignore_handles=()) -> np.ndarray | None:
    if sys.platform != "win32":
        return None
    monitor = match_monitor(spec)
    if monitor is None or not spec.screen_geom.contains(rect):
        return None
    dpr = spec.dpr
    request = {
        "rect": [monitor["left"] + round((rect.x()-spec.screen_geom.x())*dpr),
                 monitor["top"] + round((rect.y()-spec.screen_geom.y())*dpr),
                 max(1, round(rect.width()*dpr)), max(1, round(rect.height()*dpr))],
        "ignore": list(ignore_handles),
    }
    try:
        # GUI 冻结程序没有 Python 命令行；独立控制台 helper 保留二进制管道。
        command = ([str(Path(sys.executable).with_name("ScreenTranslatorCapture.exe"))]
                   if getattr(sys, "frozen", False) else
                   [sys.executable, str(Path(__file__).with_name("window_capture_worker.py"))])
        result = subprocess.run(
            command,
            input=json.dumps(request).encode("utf-8"), stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL, timeout=2.5,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        if result.returncode or len(result.stdout) < 8:
            return None
        width, height = struct.unpack("<II", result.stdout[:8])
        if [width, height] != request["rect"][2:] or len(result.stdout) != 8+width*height*4:
            return None
        image = np.frombuffer(result.stdout, dtype=np.uint8, offset=8).reshape(height, width, 4)[:, :, :3].copy()
        # 部分 GPU/受保护窗口返回成功，但只有空黑帧；转用独立取景。
        if not image.any():
            return None
        return image
    except (OSError, subprocess.TimeoutExpired, ValueError):
        log.info("下层窗口无法直接抓取，改用独立取景", exc_info=True)
        return None
