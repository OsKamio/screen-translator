# -*- coding: utf-8 -*-
"""旧主题入口（兼容层）：统一转发到 ui/design.py 的设计系统。

新代码请直接 `from . import design` 并只用 design 的 token 与绘制工具；
这里保留旧名字，避免未迁移的模块视觉脱节。
"""
from __future__ import annotations

from PySide6.QtCore import QRect

from . import design as d

# ---- 颜色（旧名 → 新 token）----
BG = d.INK_900
PANEL = d.INK_700
PANEL_2 = d.INK_600
BORDER = d.LINE
TEXT = d.TEXT_HI
TEXT_DIM = d.TEXT_2
ACCENT = d.ACCENT
ACCENT_DARK = d.ACCENT_DEEP
SELECT = d.SELECT_LINE
ERROR = d.ERROR
OK = d.OK

OVERLAY_DIM = d.OVERLAY_DIM
SELECT_FILL = d.SELECT_FILL


def app_font(size: float, weight: int = d.W_REG, italic: bool = False):
    """兼容旧调用：转发到设计系统字体（Bahnschrift + Noto Sans SC）。"""
    return d.font(size, int(weight), italic=italic)


def rounded_rect_path(rect, radius: float):
    return d.rounded_path(rect, radius)


def fit_rect_in_screen(rect: QRect, screen_geom: QRect, margin: int = d.S3) -> QRect:
    return d.fit_in(rect, screen_geom, margin)
