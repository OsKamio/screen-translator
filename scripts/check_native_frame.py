"""检查真实窗口圆角、标题栏和主题，可导出完整窗口及透明边缘预览。"""
import argparse
import json
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import numpy as np
from PySide6.QtCore import QElapsedTimer, QEventLoop, QTimer, Qt
from PySide6.QtWidgets import QApplication
from core.config import Config
from ui import design as d, glass, motion, windowframe
from ui.settings import SettingsWindow
import main as M

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--out', type=Path)
args = parser.parse_args()
app = QApplication([]); M.setup_application(app); motion.configure(False)
if app.platformName() != 'windows':
    print('NATIVE_FRAME_SKIP (requires Windows desktop)')
    sys.exit(0)

def pump(ms=100):
    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec()


cfg = Config(str(Path(__file__).resolve().parent/'_tmp_cfg'/'native-frame.json'))
win = SettingsWindow(cfg); win.resize(900, 640)
work = app.primaryScreen().availableGeometry()
win.move(work.center()-win.rect().center())
win.show(); win.raise_(); win.activateWindow(); pump()
handle = int(win.winId())
flags = win.windowFlags()
rows = []
try:
    for mode, scheme in [('glass', Qt.ColorScheme.Dark), ('glass', Qt.ColorScheme.Light),
                         ('dark', None), ('light', None)]:
        cfg.set('ui.theme', mode)
        win.refresh_from_config()
        d.set_theme(mode, scheme); win.refresh_theme()
        pump()
        clock = QElapsedTimer(); clock.start()
        while glass._pending and clock.elapsed() < 4000:
            pump(20)
        assert not glass._pending
        assert int(win.winId()) == handle and win.windowFlags() == flags
        assert flags & Qt.WindowType.FramelessWindowHint
        assert win.testAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        assert win.mask().isEmpty(), '透明圆角应保留抗锯齿，不使用有锯齿的区域 mask'
        image = win.grab().toImage()
        assert all(image.pixelColor(x,y).alpha() == 0 for x,y in
                   [(0,0),(image.width()-1,0),(0,image.height()-1),(image.width()-1,image.height()-1)])
        extent = round(d.R_WINDOW*win.devicePixelRatioF())
        partial = {image.pixelColor(x,y).alpha() for x in range(extent) for y in range(extent)}
        assert len([alpha for alpha in partial if 0 < alpha < 255]) >= 8
        assert windowframe.resize_edges(win, win.rect().center()) == Qt.Edge(0)
        assert windowframe.resize_edges(win, win.rect().bottomRight()) == (Qt.Edge.RightEdge | Qt.Edge.BottomEdge)
        if mode == 'glass':
            scene = glass._scene(win.width(), d.CURRENT_THEME == 'dark')[0].astype(np.float32)
            # 各位置的变化只有小幅中性亮度起伏，没有独立橙/紫/青条纹。
            channel_range = np.ptp(scene, axis=(0, 1))
            assert channel_range.max() <= 10, channel_range
            columns = scene.mean(axis=0)
            assert np.abs(np.diff(columns, axis=0)).max() <= 1.1
        frame = win.frameGeometry()
        shot = win.screen().grabWindow(0, frame.x(), frame.y(), frame.width(), frame.height())
        assert not shot.isNull()
        if args.out:
            args.out.mkdir(parents=True, exist_ok=True)
            shot.save(str(args.out/(d.theme_key()+'-with-frame.png')))
            image.save(str(args.out/(d.theme_key()+'-transparent.png')))
        ratio = shot.devicePixelRatioF()
        pixel = shot.toImage().pixelColor(round(frame.width()*.55*ratio), round(18*ratio))
        actual = (pixel.red(), pixel.green(), pixel.blue())
        expected = (d.INK_900.red(), d.INK_900.green(), d.INK_900.blue())
        assert max(abs(a-b) for a,b in zip(actual, expected)) <= 3, (d.theme_key(), actual, expected)
        rows.append({'theme': d.theme_key(), 'native_handle_preserved': True,
                     'corner_radius':d.R_WINDOW, 'smooth_alpha_levels':len(partial), 'caption_verified':True})
    win.resize(940, 680); pump()
    assert win.size().width() == 940 and int(win.winId()) == handle
    win.showMaximized(); pump()
    assert windowframe.radius(win) == 0
    assert windowframe.resize_edges(win, win.rect().bottomRight()) == Qt.Edge(0)
    assert win.grab().toImage().pixelColor(0,0).alpha() == 255
    win.showNormal(); pump()
    assert windowframe.radius(win) == d.R_WINDOW
    assert win.grab().toImage().pixelColor(0,0).alpha() == 0
    win.close(); pump(20)
    win.show(); pump()
    assert win.isVisible() and win.windowFlags() == flags
finally:
    win.hide()
    glass.clear_cache()
print(json.dumps(rows, ensure_ascii=False))
print('NATIVE_FRAME_PASS (smooth 28px corners, themed titlebar, stable handle, resize, maximize/restore, reopen)')
