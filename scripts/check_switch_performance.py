"""切换性能回归：高刷调度、过渡层隔离、文字缓存及隐藏后的计时器清理。"""
import os
import sys
from types import SimpleNamespace
from unittest.mock import patch
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QWidget
from core.config import Config
from ui import design as d, motion
from ui.settings import SettingsWindow
from ui.widgets import SettingsCard
import main as M

app = QApplication([])
M.setup_application(app)
with patch.object(motion, 'system_allows_motion', lambda: True):
    motion.configure(True)
    widget = QWidget()
    widget.show()
    driver = motion.Driver(widget)
    samples = []
    with patch.object(widget, 'screen', return_value=SimpleNamespace(refreshRate=lambda: 180.0)):
        driver.frames('high-refresh', samples.append, 160)
    animation = driver.active['high-refresh'][0]
    assert animation._timer.interval() <= 6
    assert animation._timer.timerType() == Qt.TimerType.PreciseTimer
    QTest.qWait(70)
    assert 0 < samples[-1] < 1
    widget.hide()
    assert samples[-1] == 1 and not driver.active and not animation._timer.isActive()
    count = len(samples)
    QTest.qWait(30)
    assert len(samples) == count

    cfg = Config(os.path.join(os.path.dirname(__file__), '_tmp_cfg', 'switch-performance.json'))
    window = SettingsWindow(cfg)
    window.show()
    QTest.qWait(300)
    navigation = window._navigation
    navigation.viewport().repaint()
    key = navigation._base_layer.cacheKey()
    for _ in range(4):
        navigation.viewport().repaint()
    assert navigation._base_layer.cacheKey() == key
    d.set_theme('dark')
    window.refresh_theme()
    navigation.viewport().repaint()
    assert navigation._base_layer.cacheKey() != key

    paints = []
    original = SettingsCard.paintEvent
    def paint(card, event):
        paints.append(card)
        original(card, event)
    with patch.object(SettingsCard, 'paintEvent', paint):
        window._tabs.setCurrentIndex(3)
        QTest.qWait(40)
        transition = window._page_transition
        assert transition.isVisible()
        assert transition.testAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent)
        paints.clear()
        for _ in range(5):
            transition.repaint()
        assert not paints, '过渡层重绘不应重新绘制背后的设置卡片'
    QTest.qWait(320)
    assert not transition.isVisible() and not transition.driver.active
    window._tabs.setCurrentIndex(2)
    motion.configure(False)
    assert not navigation.driver.active and not transition.driver.active
    window.hide()
print('SWITCH_PERFORMANCE_PASS (180Hz, precise clock, text cache, opaque layer, timer cleanup)')
