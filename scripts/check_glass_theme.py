"""液态玻璃：主题持久化、异步材质、系统偏好、缓存与实时窗口稳定性。"""
import os
import sys
from pathlib import Path
from unittest.mock import patch
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from PySide6.QtCore import QElapsedTimer, QEventLoop, QRectF, QTimer, Qt
from PySide6.QtWidgets import QApplication, QWidget
from core.config import Config
from core.live import LiveEngine
from ui import design as d, glass, motion
import main as M


def events(ms=20):
    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec()


def drain():
    clock = QElapsedTimer(); clock.start()
    while glass._pending and clock.elapsed() < 5000:
        events()
    assert not glass._pending, '玻璃后台任务必须有界完成'


app = QApplication([])
M.setup_application(app)
motion.configure(False)
with patch.object(glass, 'refresh_preferences', lambda: False):
    glass._reduced = False
    cfg = Config(str(Path(__file__).resolve().parent/'_tmp_cfg'/'glass-theme.json'))
    cfg.set('ui.theme', 'glass')
    cfg.save()
    assert Config(cfg.path).load().get('ui.theme') == 'glass'
    ctrl = M.Controller(cfg)
    ctrl.open_settings()
    win = ctrl._settings
    win._tabs.setCurrentIndex(3)
    setter = next(setter for path, getter, setter in win._binds if path == 'translate.timeout')
    setter(31)
    assert any(path == 'ui.theme' and getter() == 'glass' for path, getter, setter in win._binds)
    with patch.object(LiveEngine, 'start', lambda self: None):
        ctrl.show_live_window()
    ctrl._after_live_shown()
    live = ctrl._live
    live.set_result('用于验证液态玻璃正文稳定性。\n'*20, 'Source')
    live._scroll_by(40)
    handle, geometry, scroll = int(live.winId()), live.geometry(), live._scroll
    ctrl.result.show_result('Original', '清晰的译文', 'en')
    palettes = []
    for scheme, key in [(Qt.ColorScheme.Light, 'glass-light'), (Qt.ColorScheme.Dark, 'glass-dark')]:
        ctrl._on_system_scheme_changed(scheme)
        assert d.theme_key() == key and glass.active()
        win.grab(); live.grab(); ctrl.result.grab()
        drain()
        palettes.append(d.TEXT_HI.name())
        assert int(live.winId()) == handle and live.geometry() == geometry and live.isVisible()
        assert live._scroll == scroll
        assert win._collect()['translate']['timeout'] == 31
        assert win._tabs.currentIndex() == win._navigation.currentRow() == 3
    assert palettes[0] != palettes[1]
    area = win._tabs.widget(3)
    page = area.widget()
    context = glass._context(page, QRectF(page.rect()))
    assert context[0] == win.width()
    area.verticalScrollBar().setValue(25)
    assert glass._context(page, QRectF(page.rect())) == context
    area.verticalScrollBar().setValue(0)

    # 大材质返回即时底色，后台完成后替换缓存，不阻塞首次点击。
    glass.clear_cache()
    rect = QRectF(0, 0, 700, 200)
    first = glass.surface(win, rect, 20)
    assert glass._pending
    key = first.cacheKey()
    drain()
    ready = glass.surface(win, rect, 20)
    assert ready.cacheKey() != key and not ready.isNull()
    # 连续调整尺寸压满队列后，表面仍可在空闲时完成，不留下永久底色。
    probe = QWidget(); probe.resize(900, 400); probe.show()
    with patch.object(glass, 'MAX_PENDING', 1):
        glass.surface(probe, QRectF(0, 0, 600, 200), 20)
        waiting = glass.surface(probe, QRectF(1, 0, 620, 200), 20)
        assert glass._unbuilt and len(glass._pending) <= 1
        drain()
        glass.surface(probe, QRectF(1, 0, 620, 200), 20)
        drain()
        assert glass.surface(probe, QRectF(1, 0, 620, 200), 20).cacheKey() != waiting.cacheKey()
    probe.hide()

    # 暖缓存下，动画仅移动/缩放原有材质；文本、DPI 与点击语义沿用原生控件。
    nav = win._navigation
    nav.viewport().repaint(); drain(); nav.viewport().repaint(); drain()
    builds = glass._build_count
    for stretch in (0, .3, 1, .7, 0):
        nav._stretch = stretch
        nav.viewport().repaint()
    assert glass._build_count == builds
    live.grab(); drain()
    before = live.grab().toImage()
    for _ in range(3):
        live.repaint()
    assert live.grab().toImage() == before
    assert int(live.winId()) == handle and live.geometry() == geometry

    # 系统关闭透明效果时保留主题选择，使用不透明高对比表面。
    glass._reduced = True
    glass.clear_cache()
    win.refresh_theme()
    win.grab(); live.grab()
    assert d.is_glass() and not glass.active() and not glass._pending
    assert 'background: transparent; }\nQLineEdit' not in win.styleSheet()
    glass._reduced = False
    ctrl._refresh_theme(Qt.ColorScheme.Light)

    # 同为浅色的玻璃/普通模式不能复用错误的 palette 或导航缓存。
    nav.viewport().repaint(); glass_key = nav._base_layer.cacheKey()
    cfg.set('ui.theme', 'light'); ctrl.apply_ui_config()
    nav.viewport().repaint()
    assert d.theme_key() == 'light' and nav._base_layer.cacheKey() != glass_key
    assert not glass.active()
    cfg.set('ui.theme', 'glass'); ctrl.apply_ui_config()
    ctrl._on_system_scheme_changed(Qt.ColorScheme.Dark)
    assert d.theme_key() == 'glass-dark'
    drain()

    # LRU 不随控件数量无限增长；位移场单独有小容量上限。
    glass.clear_cache()
    with patch.object(glass, 'MAX_CACHE_BYTES', 80_000):
        for x in range(12):
            glass.surface(win, QRectF(x, 0, 80, 25), 12)
        assert glass._surface_bytes <= glass.MAX_CACHE_BYTES
    assert glass._displacement.cache_info().maxsize == 3
    glass.clear_cache()
    ctrl.hide_live_window()
    ctrl.result.hide(); win.hide(); ctrl.ball.hide()
    ctrl._geometry_timer.stop()
print('GLASS_THEME_PASS (light/dark, saved selection, async textures, bounded cache, reduced transparency, stable live HWND)')
