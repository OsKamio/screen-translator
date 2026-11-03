# -*- coding: utf-8 -*-
"""
屏幕区域抓取。

界面层(Qt)使用 *逻辑坐标*，Windows 屏幕采集(这里用 mss)使用 *物理像素坐标*，
两者通过屏幕 DPI 缩放系数(devicePixelRatio)换算：

    物理偏移 = 逻辑偏移 × dpr

本模块的捕获接口只接收纯数据（逻辑屏幕矩形 + dpr），不访问 Qt 对象，
因此可以安全地在后台线程调用。调用方只需在主线程准备好：

    spec = CaptureSpec(screen.geometry(), screen.devicePixelRatio())
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

import mss
import numpy as np
from PySide6.QtCore import QRect

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class CaptureSpec:
    """一次抓屏所需的纯数据描述。"""

    screen_geom: QRect   # 目标屏幕的逻辑矩形(geometry)
    dpr: float           # 目标屏幕的缩放系数


def _monitors() -> list[dict]:
    with mss.mss() as sct:
        return sct.monitors  # [0] 虚拟桌面整体，[1:] 各屏幕


def match_monitor(spec: CaptureSpec, monitors=None) -> dict | None:
    """把 (逻辑尺寸, dpr) 与 mss monitor 配对（按物理像素尺寸）。"""
    want_w = round(spec.screen_geom.width() * spec.dpr)
    want_h = round(spec.screen_geom.height() * spec.dpr)
    candidates = [
        mon for mon in (monitors if monitors is not None else _monitors())[1:]
        if abs(mon["width"] - want_w) <= 2 and abs(mon["height"] - want_h) <= 2
    ]
    if not candidates:
        log.warning("找不到尺寸匹配的 monitor: logical=%dx%d dpr=%.2f",
                    spec.screen_geom.width(), spec.screen_geom.height(), spec.dpr)
        return None
    return candidates[0]


def _clamp(v: int, lo: int, hi: int) -> int:
    return max(lo, min(v, hi))


def capture(spec: CaptureSpec, logical_rect: QRect) -> np.ndarray | None:
    """
    抓取逻辑坐标矩形内的屏幕内容，返回 BGR ndarray (H, W, 3)。

    注：返回 OpenCV 习惯的 BGR 通道顺序（与 mss 输出一致），
    便于直接交给 RapidOCR 等 cv2 系 OCR 使用。
    矩形自动钳制到目标屏幕内；交集为空时返回 None。
    """
    geom = spec.screen_geom
    inter = logical_rect.intersected(geom)
    if inter.isEmpty():
        return None

    region = None
    try:
        with mss.mss() as sct:
            mon = match_monitor(spec, sct.monitors)
            if mon is None:
                return None
            dpr = spec.dpr
            px = mon["left"] + round((inter.x() - geom.x()) * dpr)
            py = mon["top"] + round((inter.y() - geom.y()) * dpr)
            pw = min(mon["width"], max(1, round(inter.width() * dpr)))
            ph = min(mon["height"], max(1, round(inter.height() * dpr)))
            px = _clamp(px, mon["left"], mon["left"] + mon["width"] - pw)
            py = _clamp(py, mon["top"], mon["top"] + mon["height"] - ph)
            region = {"left": px, "top": py, "width": pw, "height": ph}
            shot = np.asarray(sct.grab(region))  # BGRA
    except Exception:  # noqa: BLE001
        log.exception("mss 抓屏失败: %s", region)
        return None

    return shot[:, :, :3].copy()  # BGRA -> BGR
