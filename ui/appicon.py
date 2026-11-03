# -*- coding: utf-8 -*-
"""应用图标加载（供窗口显式设置标题栏图标）。"""
from __future__ import annotations

import os

from PySide6.QtGui import QIcon

ICON_RELATIVE = os.path.join("assets", "screen-translator.ico")


def icon_path() -> str:
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(root, ICON_RELATIVE)


def window_icon() -> QIcon | None:
    """返回应用图标；文件不存在时返回 None。"""
    path = icon_path()
    if not os.path.exists(path):
        return None
    icon = QIcon(path)
    return None if icon.isNull() else icon
