"""视频参考改版回归：顶部导航完整点击区域、键盘、缩放与状态保留。"""
import os
import sys
from unittest.mock import patch
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from PySide6.QtCore import Qt
from PySide6.QtGui import QFontMetrics
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
import main as M
from core.config import Config
from ui import design as d, motion
from ui.settings import SettingsWindow

app = QApplication([])
M.setup_application(app)
cfg = Config(os.path.join(os.path.dirname(__file__), '_tmp_cfg', 'video-style.json'))
window = SettingsWindow(cfg)
window.show()
navigation = window._navigation
setter = next(s for path, _g, s in window._binds if path == 'translate.timeout')
setter(29)
with patch.object(motion, 'system_allows_motion', lambda: True):
    motion.configure(True)
    for width, height in [(760, 540), (900, 640), (1100, 820)]:
        window.resize(width, height)
        app.processEvents()
        fm = QFontMetrics(d.font(d.F_BODY))
        for index in range(5):
            rect = navigation.visualItemRect(navigation.item(index))
            assert rect.width() >= fm.horizontalAdvance(navigation.item(index).text())+20
            assert navigation.viewport().rect().contains(rect.center())
            QTest.mouseClick(navigation.viewport(), Qt.LeftButton, pos=rect.center())
            assert window._tabs.currentIndex() == navigation.currentRow() == index
        QTest.qWait(400)
        assert not window._page_transition.isVisible()
        assert not navigation.driver.active
        assert window._collect()['translate']['timeout'] == 29
    navigation.setCurrentRow(2)
    navigation.setFocus()
    QTest.keyClick(navigation, Qt.Key_Right)
    assert window._tabs.currentIndex() == 3
    QTest.keyClick(navigation, Qt.Key_Left)
    assert window._tabs.currentIndex() == 2
    motion.configure(False)
    assert not navigation.driver.active
    assert not window._page_transition.isVisible()
window.hide()
print('VIDEO_DESIGN_PASS (full hit areas, labels, keyboard, 3 sizes, reduced motion, unsaved state)')
