"""实际保存路径、系统关闭和按钮取消回归；独立配置，不联网。"""
import os, sys
from unittest.mock import patch
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from PySide6.QtCore import QPoint, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from core.config import Config
from core.live import LiveEngine, LiveResult
import main as M

app = QApplication([])
M.setup_application(app)
cfg = Config(os.path.join(os.path.dirname(__file__), '_tmp_cfg', 'interaction.json'))
cfg.set('translate.enabled.mymemory', True)
ctrl = M.Controller(cfg)
ctrl.open_settings()
settings = ctrl._settings
set_mode = next(s for p, _g, s in settings._binds if p == 'live.enabled')
with patch.object(LiveEngine, 'start', lambda self: None):
    set_mode(True)
    settings._on_save()  # Config 先更新再发 saved，覆盖真实的共享对象场景
    assert ctrl._live is not None and ctrl._live.isVisible()
    set_mode(False)
    settings._on_save()
    assert not ctrl._live.isVisible()
    ctrl.show_live_window()
    live = ctrl._live
    refresh = []
    live.refresh_requested.connect(lambda: refresh.append(1))
    QTest.mousePress(live, Qt.LeftButton, pos=live._bar_buttons()['refresh'].center())
    QTest.mouseRelease(live, Qt.LeftButton, pos=QPoint(25, live.height()-25))
    assert not refresh
    generation = ctrl._engine._generation
    result = LiveResult(translated='Old', original='Old', generation=generation)
    ctrl._engine.reset_cache()
    ctrl._on_live_result(result)
    assert live._translated != 'Old'
    live.close()
    assert ctrl._engine._stop.is_set() and not live.isVisible()
ctrl.ball.hide()
settings.hide()
print('LIVE_INTERACTION_PASS (shared config/save, release outside cancels, stale result, system close)')
