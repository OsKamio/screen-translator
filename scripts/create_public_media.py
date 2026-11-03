"""用实际 Qt 界面生成公开展示素材；仅使用默认空白配置、示例文字和预设译文。

需要已安装的 FFmpeg。视频按固定 60fps 时间线导出，不作为真实运行速度测试。
"""
from __future__ import annotations
import argparse
import math
import shutil
import subprocess
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from PySide6.QtCore import QAbstractAnimation, QElapsedTimer, QEventLoop, QPoint, QRect, QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QFont, QImage, QPainter, QPen, QPixmap, QRegion
from PySide6.QtWidgets import QApplication, QWidget
from shiboken6 import isValid
from core.config import Config
from ui import design as d, glass, motion
from ui.settings import SettingsWindow
from ui.resultwin import ResultWindow
from ui.livewin import LiveWindow
from ui.floatball import FloatBall
from ui.sourceframe import SourceFrame
import main as M

W, H, FPS, DURATION = 1920, 1080, 60, 40
TIME = 0.0


class ExportClock:
    def start(self): self.started = TIME
    def nsecsElapsed(self): return int((TIME-self.started)*1_000_000_000)


class DemoSource(QWidget):
    def __init__(self):
        super().__init__()
        self.resize(720, 140)
        self.text = 'Please open the settings window and click Save.'
    def paintEvent(self, event):
        painter = QPainter(self); painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen); painter.setBrush(QColor('#FFFFFF'))
        painter.drawRoundedRect(QRectF(self.rect()).adjusted(.5,.5,-.5,-.5), 12, 12)
        painter.setFont(d.font(24, d.W_MED)); painter.setPen(QColor('#253242'))
        painter.drawText(self.rect().adjusted(24,18,-24,-18), Qt.TextFlag.TextWordWrap|Qt.AlignmentFlag.AlignVCenter, self.text)
        painter.end()


def wait_materials(app):
    app.processEvents()
    timer = QElapsedTimer(); timer.start()
    while glass._pending and timer.elapsed() < 4000:
        loop = QEventLoop(); QTimer.singleShot(10, loop.quit); loop.exec()
    if glass._pending:
        raise RuntimeError('Glass material generation did not complete')


def draw_widget(painter, widget, box, opacity=1):
    if isinstance(widget, SourceFrame):
        ratio = widget.devicePixelRatioF()
        pixmap = QPixmap(round(widget.width()*ratio), round(widget.height()*ratio))
        pixmap.setDevicePixelRatio(ratio); pixmap.fill(Qt.GlobalColor.transparent)
        border = QPainter(pixmap)
        widget.render(border, QPoint(), QRegion(), QWidget.RenderFlag.DrawChildren|QWidget.RenderFlag.IgnoreMask)
        border.end()
    else:
        pixmap = widget.grab()
    width, height = pixmap.width(), pixmap.height()
    ratio = min(box.width()/width, box.height()/height)
    target = QRectF(box.center().x()-width*ratio/2, box.center().y()-height*ratio/2, width*ratio, height*ratio)
    painter.save(); painter.setOpacity(opacity)
    painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
    painter.drawPixmap(target, pixmap, QRectF(pixmap.rect())); painter.restore()


def text(painter, x, y, value, size, color='#1A2837', weight=500, width=650, height=80):
    painter.setFont(d.font(size, weight)); painter.setPen(QColor(color))
    painter.drawText(QRectF(x,y,width,height), Qt.AlignmentFlag.AlignLeft|Qt.AlignmentFlag.AlignTop|Qt.TextFlag.TextWordWrap, value)


def main():
    global TIME
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, default=Path(__file__).resolve().parent.parent/'docs'/'media')
    parser.add_argument('--ffmpeg', default=shutil.which('ffmpeg'))
    parser.add_argument('--review-dir', type=Path)
    parser.add_argument('--stills-only', action='store_true')
    args = parser.parse_args(); args.out.mkdir(parents=True, exist_ok=True)
    if args.review_dir: args.review_dir.mkdir(parents=True, exist_ok=True)
    app = QApplication([]); M.setup_application(app); motion.configure(False)
    cfg = Config(str(Path(__file__).resolve().parent/'_tmp_cfg'/'public-media.json'))
    cfg.set('live.capture_excluded', False)
    cfg.set('live.bg_opacity', 95)
    settings = SettingsWindow(cfg); settings.resize(900,640)
    result = ResultWindow(); result.apply_config(cfg)
    live = LiveWindow(); live.apply_config(cfg); live.resize(720,190)
    ball = FloatBall(); ball.set_ball_size(84)
    source = DemoSource(); frame = SourceFrame(); frame.set_source(QRect(0,0,720,140))
    frame.clearMask()  # 离屏合成只需要实际边框绘制，不需要原生鼠标穿透区域。
    widgets = [settings, result, live, ball, source, frame]
    for widget in widgets:
        widget.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
        widget.show()
    result.show_result('Please open the settings window and click Save.', '请打开设置窗口，然后点击保存。', 'en')
    result.place_near(QRect(0,0,460,120), app.primaryScreen().availableGeometry())
    result.adjustSize()
    live.set_result('请打开设置窗口，然后点击保存。', source.text, status='示例字幕')
    setter = next(setter for path, getter, setter in settings._binds if path == 'ui.theme')

    def theme(mode, scheme=None):
        d.set_theme(mode, scheme); setter(mode); settings.refresh_theme(); result.refresh_theme()
        for widget in (live,ball): widget.update()
        settings.grab(); live.grab(); result.grab(); wait_materials(app)

    theme('light'); settings._navigation.setCurrentRow(0); app.processEvents()
    settings.grab().save(str(args.out/'settings.png'))
    result.grab().save(str(args.out/'result-card.png')); live.grab().save(str(args.out/'live-caption.png'))
    if args.stills_only:
        for widget in widgets: widget.hide()
        return 0
    if not args.ffmpeg:
        raise RuntimeError('FFmpeg is required; provide --ffmpeg <path>')
    # 仅导出进程使用虚拟时钟；实际应用代码及真实刷新率不改变。
    motion.QElapsedTimer = ExportClock
    motion.system_allows_motion = lambda: True
    motion.configure(True)
    group_starts = {}
    def advance():
        for driver in tuple(motion._drivers):
            for animation, _finalizers in tuple(driver.active.values()):
                if not isValid(animation): continue
                if isinstance(animation, motion._FrameAnimation): animation._step()
                elif isinstance(animation, QAbstractAnimation):
                    key = id(animation)
                    group_starts.setdefault(key, TIME)
                    animation.setCurrentTime(round((TIME-group_starts[key])*1000))
        app.processEvents()

    shown_frame = [True]
    def caption(original, translated):
        source.text = original; source.update(); live.set_result(translated, original, status='示例字幕已更新')
    def toggle_frame(on):
        shown_frame[0] = on; live._show_source_frame = on; live.update()
    events = [
        (4, lambda: ball._animate_hover(1.0)),
        (7, lambda: result._btn_copy_trans.feedback('已复制')),
        (10, lambda: result._btn_copy_trans._restore_feedback()),
        (13, lambda: settings._navigation.setCurrentRow(2)),
        (15, lambda: caption('Read subtitles without selecting the same area again.', '阅读字幕时，不用反复框选。')),
        (18, lambda: caption('The translation updates when the text changes.', '实时译文会随内容变化更新。')),
        (20, lambda: toggle_frame(False)), (21.3, lambda: toggle_frame(True)),
        (23, lambda: settings._navigation.setCurrentRow(0)),
        (24.6, lambda: settings._navigation.setCurrentRow(2)),
        (28, lambda: settings._navigation.setCurrentRow(1)),
        (32, lambda: settings._navigation.setCurrentRow(2)),
        (36, lambda: settings._navigation.setCurrentRow(0)),
    ]
    encoding = subprocess.Popen([str(args.ffmpeg),'-hide_banner','-loglevel','error','-y',
        '-f','rawvideo','-pixel_format','rgba','-video_size',f'{W}x{H}','-framerate',str(FPS),'-i','-',
        '-an','-c:v','libx264','-preset','veryfast','-crf','20','-pix_fmt','yuv420p','-movflags','+faststart',
        str(args.out/'demo.mp4')],stdin=subprocess.PIPE,stdout=subprocess.DEVNULL,stderr=subprocess.PIPE)
    actions = iter(events); pending = next(actions, None)
    logo = QImage(str(Path(__file__).resolve().parent.parent/'assets'/'screen-translator.png'))
    checkpoints = {0, 4*FPS, 8*FPS, 12*FPS, 16*FPS, 20*FPS, 24*FPS, 28*FPS, 32*FPS, 36*FPS, 39*FPS}
    try:
        for number in range(DURATION*FPS):
            TIME = number/FPS
            while pending is not None and TIME >= pending[0]:
                pending[1](); pending = next(actions, None)
            advance()
            image = QImage(W,H,QImage.Format.Format_RGBA8888); image.fill(QColor('#EEF1F5'))
            p = QPainter(image); p.setRenderHint(QPainter.RenderHint.Antialiasing)
            p.drawImage(QRectF(88,52,42,42), logo)
            text(p,146,56,'ScreenTranslator',28,weight=650,width=600)
            text(p,1470,63,'WINDOWS · LOCAL OCR',16,'#60768E',width=365)
            if TIME < 4:
                heading, sub, points = '让屏幕上的文字\n更容易读懂。', '框选翻译与实时字幕，放在桌面随手可用。', ['本机 OCR 识别','由你选择翻译服务','框选翻译与连续字幕']
                draw_widget(p,settings,QRectF(760,160,1080,800))
            elif TIME < 13:
                heading, sub, points = '框选一次，\n专注阅读。', '译文优先展示，原文保留在下方。\n复制或重新框选，都在卡片里完成。', ['点击悬浮入口，拖出选区','查看原文与译文','一键复制，继续阅读']
                draw_widget(p,result,QRectF(820,270,950,550))
            elif TIME < 23:
                heading, sub, points = '字幕变化，\n译文跟着更新。', '固定取景区域，连续阅读；黄框可以随时开关。', ['文字变化后自动更新','支持暂停、刷新与调字号','可设置录屏显示译文']
                box = QRectF(820,260,980,190); draw_widget(p,source,box)
                if shown_frame[0]: draw_widget(p,frame,box.adjusted(-6,-6,6,6))
                text(p,823,222,'取景区域 · 示例原文',17,'#697C91',width=960)
                draw_widget(p,live,QRectF(815,510,990,290))
                text(p,823,810,'实时译文窗口',17,'#697C91',width=960)
            else:
                heading, sub, points = ('选好服务，\n连续阅读。', '集中管理翻译服务、接口顺序与实时窗口。', ['选择目标语言与翻译服务','调整接口优先级与失败回退','设置实时字幕与取景区域']) if TIME < 36 else ('随手翻译，\n阅读更连贯。', 'ScreenTranslator · 屏幕翻译', ['Windows 桌面工具','本地识别 · 自选翻译接口','查看仓库说明即可开始'])
                draw_widget(p,settings,QRectF(760,160,1080,800))
            for index,line in enumerate(heading.split('\n')): text(p,88,230+index*74,line,52,weight=650,width=650,height=80)
            text(p,90,430,sub,22,'#60748C',width=590,height=140)
            for index,line in enumerate(points):
                y=602+index*58; p.setPen(Qt.PenStyle.NoPen); p.setBrush(QColor('#3C79AE'));p.drawEllipse(QRectF(92,y+9,7,7))
                text(p,118,y,line,21,'#405A75',width=550,height=45)
            draw_widget(p,ball,QRectF(88,820,78,78))
            text(p,186,842,'右键入口，快速打开设置',17,'#698198',width=490)
            text(p,88,1010,'github.com/OsKamio/screen-translator',17,'#56708A',width=950,height=30)
            text(p,1260,1010,'原生界面演示 · 示例文字 / 预设译文',15,'#75889B',width=580,height=30)
            p.setPen(Qt.PenStyle.NoPen);p.setBrush(QColor('#D1DBE6'));p.drawRoundedRect(QRectF(88,1055,1744,3),1.5,1.5)
            p.setBrush(QColor('#3C79AE'));p.drawRoundedRect(QRectF(88,1055,1744*TIME/DURATION,3),1.5,1.5)
            p.end()
            encoding.stdin.write(bytes(image.constBits()))
            if number == 90: image.save(str(args.out/'demo-poster.png'))
            if args.review_dir and number in checkpoints: image.save(str(args.review_dir/f'{number/FPS:04.1f}s.png'))
            if number % (FPS*5) == 0: print(f'MEDIA_RENDER {number//FPS}/{DURATION}s',flush=True)
        encoding.stdin.close(); code=encoding.wait(timeout=60)
        if code: raise RuntimeError(encoding.stderr.read().decode('utf-8',errors='replace'))
    finally:
        for widget in widgets: widget.hide()
        glass.clear_cache()
        if encoding.poll() is None: encoding.terminate()
    subprocess.run([str(args.ffmpeg),'-hide_banner','-loglevel','error','-y','-ss','24','-t','11','-i',str(args.out/'demo.mp4'),
        '-filter_complex','crop=1120:820:750:150,fps=18,scale=900:-2:flags=lanczos,split[a][b];[a]palettegen=max_colors=128[p];[b][p]paletteuse=dither=sierra2_4a',
        '-loop','0',str(args.out/'demo.gif')],check=True)
    print('PUBLIC_MEDIA_DONE (40s, 1920x1080, 60fps; native widgets with sample content)',flush=True)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
