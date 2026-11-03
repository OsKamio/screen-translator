# -*- coding: utf-8 -*-
"""真机无闪烁回归：真实下层截图、投屏可见、失败分离、重新框选。无网络。"""
from __future__ import annotations
import os
import sys
import time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from PySide6.QtCore import QRect, Qt
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import QApplication, QWidget
from PySide6.QtTest import QTest
import main as M
import core.live as L
from core.config import Config
from core.screen import CaptureSpec, capture

for stream in (sys.stdout, sys.stderr):
    stream.reconfigure(encoding="utf-8", errors="replace")

class Content(QWidget):
    def __init__(self):
        super().__init__(None, Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setGeometry(160, 190, 680, 150)
        self.color = QColor(255, 255, 255)
    def paintEvent(self, event):
        p = QPainter(self)
        p.fillRect(self.rect(), self.color)
        p.end()


def pump(app, ms):
    deadline = time.monotonic()+ms/1000
    while time.monotonic() < deadline:
        app.processEvents()
        time.sleep(.005)


def main():
    app = QApplication([])
    M.setup_application(app)
    cfg = Config(os.path.join(os.path.dirname(__file__), "_tmp_cfg", "no_flicker.json"))
    theme = next((arg.split('=', 1)[1] for arg in sys.argv if arg.startswith('--theme=')), 'system')
    cfg.set('ui.theme', theme)
    cfg.set("live.enabled", False)
    cfg.set("live.capture_excluded", False)
    cfg.set("live.geometry", [160, 190, 680, 150])
    cfg.set("live.interval_ms", 300)
    cfg.set("live.remember_geometry", False)
    content = Content()
    content.show()
    decoration = QWidget(None, Qt.Tool | Qt.FramelessWindowHint |
                         Qt.WindowStaysOnTopHint | Qt.WindowTransparentForInput)
    decoration.setAttribute(Qt.WA_TranslucentBackground)
    decoration.setGeometry(content.geometry().adjusted(-12, -12, 12, 12))
    decoration.show()  # 不在 ignore_handles 中，必须自动跳过这类透明装饰层。
    pump(app, 100)
    seen = []
    def fake_ocr(image, **kwargs):
        seen.append(float(image.mean()))
        return "White original" if image.mean()>245 else "Updated original"
    L.ocr.recognize_as_text = fake_ocr
    L.core_translate.translate = lambda text, cfg: ("原文译文："+text, "en")
    ctrl = M.Controller(cfg)
    ctrl.show_live_window()
    original = QRect(content.geometry())
    ctrl._live.setGeometry(original)
    suppressed = []
    original_suppress = ctrl._live.suppress_content
    def spy_suppress(on):
        if on: suppressed.append(time.monotonic())
        original_suppress(on)
    ctrl._live.suppress_content = spy_suppress
    try:
        pump(app, 2000)
        assert seen and seen[0]>245, seen
        assert not cfg.get("live.separate_capture"), "native capture should preserve overlay"
        assert ctrl._live.geometry() == original
        assert ctrl._live.capture_excluded() is False
        assert ctrl._live.isVisible() and not ctrl._live._suppress
        assert "White original" in ctrl._live._translated
        print("native overlay: actual lower-window image, translated window stays visible")
        # 普通桌面捕获仍可看到译文背板：没有偷偷打开全局抓屏排除。
        spec = CaptureSpec(app.primaryScreen().geometry(), app.primaryScreen().devicePixelRatio())
        desktop = capture(spec, original)
        assert desktop is not None and desktop.mean()<240, desktop.mean()
        print("recording visibility: ordinary screen capture includes overlay")
        content.color = QColor(190, 190, 190)
        content.update()
        ctrl._engine.force_refresh()
        pump(app, 1700)
        assert any(180<value<205 for value in seen), seen
        assert "Updated original" in ctrl._live._translated
        print("changed covered content: fresh original captured and translated")
        # 不支持 / 黑帧 / 超时等返回 None，测试自动分离走真实 Controller 接线。
        real_native = M.capture_window
        M.capture_window = lambda *args: None
        ctrl._engine.force_refresh()
        pump(app, 1600)
        assert cfg.get("live.separate_capture")
        assert ctrl._engine._capture_provider is None
        assert ctrl._engine._pre_capture is None
        assert ctrl._engine._rect == original
        assert not ctrl._live.geometry().intersects(original)
        assert ctrl._source_frame.isVisible()
        assert ctrl._live.isVisible()
        assert not ctrl._source_frame.mask().contains(ctrl._source_frame.rect().center())
        print("fallback: source stays fixed, panel moves outside, no clearing hooks")
        # 工具栏黄框开关：只改外观，线程和取景保持不变；更新区域也不强制重新显示。
        thread = ctrl._engine._thread
        source_geom = cfg.get("live.source_geometry")[:]
        point = ctrl._live._bar_buttons()["source_frame"].center()
        QTest.mouseMove(ctrl._live, point)
        QTest.mouseClick(ctrl._live, Qt.LeftButton, pos=point)
        assert not cfg.get("live.show_source_frame")
        assert not ctrl._source_frame.isVisible()
        assert ctrl._engine._thread is thread and ctrl._engine._rect == original
        assert cfg.get("live.source_geometry") == source_geom
        assert ctrl._live._show_source_frame is False
        ctrl._push_live_spec()
        assert not ctrl._source_frame.isVisible()
        cfg.save()
        assert Config(cfg.path).load().get("live.show_source_frame") is False
        QTest.mouseClick(ctrl._live, Qt.LeftButton, pos=point)
        assert cfg.get("live.show_source_frame") and ctrl._source_frame.isVisible()
        assert ctrl._engine._thread is thread and ctrl._engine._rect == original
        print("yellow-frame toolbar toggle: no translation restart; preference persists")

        # 移动译文不移动取景区域；拖回原文位置会自动避让。
        ctrl._live.setGeometry(original)
        ctrl._on_live_geometry_changed(original)
        assert ctrl._engine._rect == original
        assert not ctrl._live.geometry().intersects(original)
        # Esc 取消重新框选，应恢复当前模式。
        ctrl.select_live_source()
        assert ctrl.overlay.isVisible() and not ctrl._live.isVisible()
        ctrl._on_capture_cancelled()
        pump(app, 250)
        assert ctrl._live.isVisible() and ctrl._engine._rect == original
        # 新选区通过已有遮罩信号进入独立取景，不触发手动翻译任务。
        selected = QRect(original.x()+20, original.y()+20, 300, 120)
        ctrl.select_live_source()
        ctrl._on_region_selected(selected)
        pump(app, 250)
        assert ctrl._engine._rect == selected
        assert not ctrl._running_task
        print("selection: cancel, reselect, and source/panel geometry remain correct")
        # 复原覆盖时回到取景位置，再尝试 native。
        M.capture_window = real_native
        ctrl.restore_live_overlay()
        pump(app, 1500)
        assert not cfg.get("live.separate_capture")
        assert ctrl._live.geometry() == selected
        assert not ctrl._source_frame.isVisible()
        # 迟到的失败回调不能在用户隐藏窗口后切换模式。
        generation = ctrl._capture_generation
        ctrl.hide_live_window()
        ctrl._fallback_live_source(selected, generation)
        assert not cfg.get("live.separate_capture")
        assert not ctrl._live.isVisible()
        assert not suppressed, suppressed
        print("LIVE_NO_FLICKER_PASS (zero content-clear calls)")
        from ui import glass
        print(f"theme={theme}, glass_effect_active={glass.active()}")
        return 0
    finally:
        ctrl.hide_live_window()
        ctrl._geometry_timer.stop()
        content.close()
        decoration.close()
        ctrl.ball.hide()
        ctrl.overlay.hide()

if __name__ == "__main__":
    sys.exit(main())
