# -*- coding: utf-8 -*-
"""主题回归：系统跟随、手动覆盖、界面状态与原生窗口稳定性。"""
from __future__ import annotations
import os
import sys
from unittest.mock import patch
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import numpy as np
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QApplication
import main as M
from core.config import Config
from core.live import LiveEngine
from ui import design as d
from ui.widgets import HintLabel

app = QApplication([])
M.setup_application(app)
cfg = Config(os.path.join(os.path.dirname(__file__), "_tmp_cfg", "theme.json"))
ctrl = M.Controller(cfg)
ctrl.open_settings()
settings = ctrl._settings
settings._tabs.setCurrentIndex(3)
# 保存前正在编辑的控件不应被系统主题切换重置。
setter = next(setter for path, getter, setter in settings._binds if path == "translate.timeout")
setter(31)
with patch.object(LiveEngine, "start", lambda self: None):
    ctrl.show_live_window()
ctrl._after_live_shown()
ctrl._live.set_result("这是用于查看滚动位置的翻译内容。\n"*20, "Source")
ctrl._live._scroll_by(60)
scroll = ctrl._live._scroll
handle = int(ctrl._live.winId())
ctrl._engine._last_sig = np.ones((36, 64))
signature = ctrl._engine._last_sig
source = ctrl._engine._rect
ctrl.result.show_result("Original text", "这是翻译结果", "en")
for scheme, expected in [(Qt.ColorScheme.Dark, "dark"), (Qt.ColorScheme.Light, "light")]:
    ctrl._on_system_scheme_changed(scheme)
    assert d.CURRENT_THEME == expected
    assert d.INK_900.name() in settings.styleSheet()
    assert d.TEXT_HI.name() in ctrl.result._trans_view.styleSheet()
    assert settings._tabs.currentIndex() == settings._navigation.currentRow() == 3
    assert settings._collect()["translate"]["timeout"] == 31
    assert int(ctrl._live.winId()) == handle and ctrl._live.isVisible()
    assert ctrl._live._scroll == scroll
    assert ctrl._engine._last_sig is signature and ctrl._engine._rect == source
    for label in settings.findChildren(HintLabel):
        assert label._color == getattr(d, label._color_token)
    assert ctrl.result._translated == "这是翻译结果"
# 手动主题覆盖系统事件。
cfg.set("ui.theme", "light")
ctrl.apply_ui_config()
ctrl._on_system_scheme_changed(Qt.ColorScheme.Dark)
assert d.CURRENT_THEME == "light"
cfg.set("ui.theme", "dark")
ctrl.apply_ui_config()
ctrl._on_system_scheme_changed(Qt.ColorScheme.Light)
assert d.CURRENT_THEME == "dark"
cfg.save()
assert Config(cfg.path).load().get("ui.theme") == "dark"
# 保存 UI 的新选择进入 Controller 时，应立即更新所有已有界面。
data = cfg.copy_data()
data["ui"]["theme"] = "light"
ctrl._on_settings_saved(data)
assert d.CURRENT_THEME == "light"
ctrl.result.show_error("接口暂时不可用")
ctrl._refresh_theme(Qt.ColorScheme.Dark)
assert d.ERROR.name() in ctrl.result._trans_view.styleSheet()
assert d.hexs(QColor(10, 20, 30, 18)) == "rgba(10,20,30,18)"
assert d.hexs(QColor(10, 20, 30), .5) == "rgba(10,20,30,128)"
ctrl.hide_live_window()
settings.hide()
ctrl.ball.hide()
ctrl._geometry_timer.stop()
print("THEME_PASS (system/light/dark; state retained; no native window rebuild)")
