"""动效回归：连续中断、归位、隐藏/销毁、减少动态与稳定实时抓屏。无网络。"""
from __future__ import annotations
import os
import sys
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from PySide6.QtCore import QCoreApplication, QEvent, QPoint, QRect, Qt
from PySide6.QtGui import QGuiApplication
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QWidget
import main as M
from core.config import Config
from core.live import LiveEngine
from ui import motion
from ui.widgets import TextButton

app = QApplication([])
M.setup_application(app)
cfg = Config(os.path.join(os.path.dirname(__file__), '_tmp_cfg', 'motion.json'))
assert cfg.get('ui.animations') is True
cfg.set('live.enabled', False)
cfg.set('live.capture_excluded', False)

with patch.object(motion, 'system_allows_motion', lambda: False):
    motion.configure(True)
    assert not motion.enabled()

with patch.object(motion, 'system_allows_motion', lambda: True):
    ctrl = M.Controller(cfg)
    ctrl.ball.show()
    ctrl.open_settings()
    settings = ctrl._settings
    QTest.qWait(400)
    assert not settings._page_transition.isVisible()
    timeout_set = next(s for p, _g, s in settings._binds if p == 'translate.timeout')
    timeout_set(33)
    # 动画期间反复切换，不能重建页面或丢掉编辑值。
    for index in [3, 1, 2, 0, 4, 1, 3, 2, 0, 3]:
        settings._navigation.setCurrentRow(index)
        QTest.qWait(24)
        assert len(settings._page_transition.driver.active) <= 1
    QTest.qWait(400)
    assert settings._tabs.currentIndex() == 3
    assert settings._collect()['translate']['timeout'] == 33
    assert not settings._page_transition.isVisible()
    assert settings._page_transition.old is settings._page_transition.new is None

    button = TextButton('Test', parent=settings)
    button.setGeometry(10, 10, 100, 35)
    button.show()
    fired = []
    button.clicked.connect(lambda: fired.append(1))
    QTest.mousePress(button, Qt.LeftButton)
    QTest.qWait(50)
    assert button._press_t > 0
    QTest.mouseRelease(button, Qt.LeftButton)
    QTest.qWait(350)
    assert len(fired) == 1 and abs(button._press_t) < .001
    for _ in range(12):
        button._animate_to('_hover_t', 1, 300)
        button._animate_to('_hover_t', 0, 120)
    assert len(button._motion.active) <= 1
    QTest.qWait(180)
    assert abs(button._hover_t) < .001 and not button._motion.active
    button.hide()

    # 原生按钮的键盘操作仍正常；成功提示定时恢复。
    settings._save_button.setFocus()
    QTest.keyClick(settings._save_button, Qt.Key_Space)
    assert settings._save_button.text() == '保存成功'
    QTest.qWait(1450)
    assert settings._save_button.text() == '保存更改'
    cfg_disk = Config(cfg.path)
    cfg_disk.load()
    assert cfg_disk.get('ui.animations') is True

    # 结果入场采用绘制变换，不再动画实际位置。
    result = ctrl.result
    result.show_result('source', 'Translation for motion regression', 'en')
    result.place_near(QRect(250, 250, 300, 80), QGuiApplication.primaryScreen().availableGeometry())
    geometry = QRect(result.geometry())
    result.show()
    QTest.qWait(80)
    assert result.geometry() == geometry
    assert any(0 < effect.progress < 1 for effect, _ in result._reveal_effects)
    first = result.grab().toImage()
    QTest.qWait(400)
    assert all(effect.progress == 1 for effect, _ in result._reveal_effects)
    assert not result._motion.active
    assert first != result.grab().toImage()
    with patch.object(result, '_copy') as copied:
        QTest.mouseClick(result._btn_copy_trans, Qt.LeftButton)
        copied.assert_called_once_with(result._translated)
        assert result._btn_copy_trans._text == '已复制'
    result.hide()
    assert result._btn_copy_trans._text == '复制译文'
    for _ in range(4):
        result.show()
        QTest.qWait(25)
        result.hide()
        assert not result._motion.active
        assert all(effect.progress == 1 for effect, _ in result._reveal_effects)

    with patch.object(LiveEngine, 'start', lambda self: None):
        ctrl.show_live_window()
    live = ctrl._live
    QTest.qWait(90)
    live.set_result('Long translation\n'*20, 'source')
    live._scroll_by(40)
    QTest.qWait(650)
    hwnd, capture_rect, scroll = int(live.winId()), QRect(live.window_geometry_for_capture()), live._scroll
    body = live._text_body()
    def body_image():
        img = live.grab().toImage()
        scale = img.devicePixelRatio()
        physical = QRect(round(body.x()*scale), round(body.y()*scale),
                         round(body.width()*scale), round(body.height()*scale))
        return img.copy(physical)
    body_before = body_image()
    refresh = live._bar_buttons()['refresh'].center()
    requested = []
    live.refresh_requested.connect(lambda: requested.append(1))
    QTest.mouseMove(live, refresh)
    QTest.mouseClick(live, Qt.LeftButton, pos=refresh)
    QTest.qWait(100)
    assert 0 < live._refresh_angle < 360
    assert body_image() == body_before
    assert live._scroll == scroll and live.window_geometry_for_capture() == capture_rect
    assert int(live.winId()) == hwnd and live.windowOpacity() == 1 and live.isVisible()
    assert requested == [1]
    QTest.qWait(450)
    live.hide()
    assert not live._motion.active

    ctrl.ball.set_busy(True, 'Busy')
    assert ctrl.ball._spinner.isActive()
    ctrl.ball.hide()
    assert not ctrl.ball._spinner.isActive()
    ctrl.ball.show()
    assert ctrl.ball._spinner.isActive()
    motion.configure(False)
    assert not ctrl.ball._spinner.isActive()
    result.show()
    assert all(effect.progress == 1 for effect, _ in result._reveal_effects)
    settings._tabs.setCurrentIndex(2)
    assert not settings._page_transition.isVisible()
    assert all(not d.active for d in tuple(motion._drivers))
    assert settings._collect()['ui']['animations'] is True  # 系统设置不改用户偏好
    motion.configure(True)
    # 正在动画的 QWidget 被销毁后，重新配置不可访问已销毁的动画。
    transient = QWidget()
    transient.show()
    driver = motion.Driver(transient)
    driver.to('test', 0, 1, lambda v: None, 1000)
    transient.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
    motion.configure(False)
    assert not driver.active
    ctrl.hide_live_window()
    ctrl.ball.set_busy(False)
    settings.hide()
    result.hide()
    ctrl.ball.hide()

print('MOTION_PASS (interrupt/cleanup/reduced motion/copy/save/stable live geometry and pixels)')
