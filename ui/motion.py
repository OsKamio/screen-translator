"""GSAP skills 的桌面实现：中断覆盖、绘制变换、错峰时间线和减少动态。

使用 Qt 原生动画；不引入 JavaScript / WebView，也不动画抓屏窗口的几何。
"""
from __future__ import annotations

import ctypes
import sys
import weakref

from PySide6.QtCore import (
    QEasingCurve, QEvent, QObject, QParallelAnimationGroup,
    QPauseAnimation, QPoint, QPointF, QRectF, QSequentialAnimationGroup, Qt, QTimer, QVariantAnimation,
    QElapsedTimer, Signal,
)
from PySide6.QtGui import QPainter
from PySide6.QtWidgets import (
    QApplication, QGraphicsEffect, QPushButton, QStyle, QStyleOptionButton,
    QStylePainter, QWidget,
)

from . import design as d
from . import glass

_enabled = True
_requested = True
_watcher = None
_drivers = weakref.WeakSet()


class _PreferenceWatcher(QObject):
    def eventFilter(self, obj, event):  # noqa: N802
        if event.type() == QEvent.Type.ApplicationStateChange:
            configure(_requested)
        return False


def system_allows_motion() -> bool:
    """跟随 Windows 的“动画效果”辅助功能开关。读取失败时保持可用。"""
    if sys.platform != "win32":
        return True
    try:
        value = ctypes.c_int(1)
        ok = ctypes.windll.user32.SystemParametersInfoW(0x1042, 0, ctypes.byref(value), 0)
        return bool(value.value) if ok else True
    except (AttributeError, OSError):
        return True


def enabled() -> bool:
    return _enabled


def configure(allow: bool = True) -> None:
    global _enabled, _requested, _watcher
    _requested = bool(allow)
    _enabled = _requested and system_allows_motion()
    if not _enabled:
        for driver in tuple(_drivers):
            driver.finish_all()
    app = QApplication.instance()
    if app is not None:
        glass_changed = d.is_glass() and glass.refresh_preferences()
        if _watcher is None:
            _watcher = _PreferenceWatcher(app)
            app.installEventFilter(_watcher)
        for widget in app.allWidgets():
            if glass_changed:
                refresh = getattr(widget, 'refresh_theme', None)
                if refresh is not None:
                    refresh()
                widget.update()
            sync = getattr(widget, "_sync_motion", None)
            if sync is not None:
                sync()


def curve(kind: str = "out") -> QEasingCurve:
    # power3.out 的 Qt 对应形式为 OutQuart；轻微 back 回弹只用于按钮。
    c = QEasingCurve(QEasingCurve.Type.OutBack if kind == "back" else
                     QEasingCurve.Type.Linear if kind == "linear" else
                     QEasingCurve.Type.OutCubic if kind == "cubic" else
                     QEasingCurve.Type.InOutSine if kind == "sine" else
                     QEasingCurve.Type.OutQuart)
    if kind == "back":
        c.setOvershoot(1.1)
    return c


class _FrameAnimation(QObject):
    """单个精确定时器按真实时间推进；高刷屏不受统一动画时钟的 16ms 限制。"""

    finished = Signal()

    def __init__(self, widget, setter, duration, ease, parent):
        super().__init__(parent)
        self._widget, self._setter = widget, setter
        self._duration = max(1, duration)
        self._curve = curve(ease)
        self._clock = QElapsedTimer()
        self._timer = QTimer(self)
        self._timer.setTimerType(Qt.TimerType.PreciseTimer)
        self._timer.timeout.connect(self._step)

    def start(self):
        screen = self._widget.screen()
        rate = screen.refreshRate() if screen is not None else 60.0
        rate = min(240.0, max(60.0, rate))
        self._clock.start()
        self._setter(0.0)
        self._timer.start(max(4, int(1000/rate)))

    def stop(self):
        self._timer.stop()

    def _step(self):
        progress = min(1.0, self._clock.nsecsElapsed()/(self._duration*1_000_000))
        self._setter(self._curve.valueForProgress(progress))
        if progress >= 1.0:
            self.stop()
            self.finished.emit()


class Driver(QObject):
    """按属性键覆盖旧 tween，隐藏时归位，完成后立即回收。"""

    def __init__(self, widget: QWidget):
        super().__init__(widget)
        self.widget = widget
        self.active = {}
        widget.installEventFilter(self)
        _drivers.add(self)
        # Python 回调无 QObject 接收者上下文，析构时也能清理引用。
        self.destroyed.connect(lambda: self._disposed())

    def _disposed(self):
        self.active.clear()
        _drivers.discard(self)

    def eventFilter(self, obj, event):  # noqa: N802
        if obj is self.widget and event.type() == QEvent.Type.Hide:
            self.finish_all()
        return False

    def cancel(self, key: str, *, finish: bool = False) -> None:
        entry = self.active.pop(key, None)
        if entry is not None:
            animation, finalizers = entry
            animation.stop()
            if finish:
                for setter, value in finalizers:
                    setter(value)
            animation.deleteLater()

    def finish_all(self) -> None:
        for key in tuple(self.active):
            self.cancel(key, finish=True)

    def _run(self, key, animation, finalizers) -> None:
        self.active[key] = (animation, finalizers)

        def done():
            if self.active.get(key, (None,))[0] is animation:
                self.active.pop(key)
            animation.deleteLater()

        animation.finished.connect(done)
        animation.start()

    def to(self, key, start, end, setter, duration=180, ease="out") -> None:
        self.cancel(key)
        if not enabled() or not self.widget.isVisible() or abs(start-end) < 0.001:
            setter(end)
            return
        anim = _FrameAnimation(self.widget,
            lambda progress: setter(start+(end-start)*progress), duration, ease, self)
        self._run(key, anim, [(setter, end)])

    def timeline(self, key, tracks) -> None:
        """tracks: (setter, start, end, duration_ms, position_ms, ease)。"""
        self.cancel(key)
        if not enabled() or not self.widget.isVisible():
            for setter, _start, end, _duration, _position, _ease in tracks:
                setter(end)
            return
        master = QParallelAnimationGroup(self)
        finalizers = []
        for setter, start, end, duration, position, ease in tracks:
            # 每条独立属性只在时间线创建时设置一次起点，避免入场闪跳。
            setter(start)
            seq = QSequentialAnimationGroup(master)
            if position:
                seq.addAnimation(QPauseAnimation(position, seq))
            anim = QVariantAnimation(seq)
            anim.setStartValue(float(start))
            anim.setEndValue(float(end))
            anim.setDuration(duration)
            anim.setEasingCurve(curve(ease))
            anim.valueChanged.connect(setter)
            seq.addAnimation(anim)
            master.addAnimation(seq)
            finalizers.append((setter, end))
        self._run(key, master, finalizers)

    def frames(self, key, setter, duration=280, ease='cubic') -> None:
        """把联动属性放在一个帧回调里更新，单次请求重绘，隐藏时照常归位。"""
        self.cancel(key)
        if not enabled() or not self.widget.isVisible():
            setter(1.0)
            return
        anim = _FrameAnimation(self.widget, setter, duration, ease, self)
        self._run(key, anim, [(setter, 1.0)])

    def pulse(self, key, setter, peak=1.0, up=110, down=320) -> None:
        self.cancel(key)
        if not enabled() or not self.widget.isVisible():
            setter(0.0)
            return
        setter(0.0)
        seq = QSequentialAnimationGroup(self)
        for start, end, duration in ((0.0, peak, up), (peak, 0.0, down)):
            anim = QVariantAnimation(seq)
            anim.setStartValue(start)
            anim.setEndValue(end)
            anim.setDuration(duration)
            anim.setEasingCurve(curve())
            anim.valueChanged.connect(setter)
            seq.addAnimation(anim)
        self._run(key, seq, [(setter, 0.0)])


class RevealEffect(QGraphicsEffect):
    """只变换绘制结果，不改变控件布局、窗口坐标或文档滚动位置。"""

    def __init__(self, widget):
        super().__init__(widget)
        self.progress = 1.0
        widget.setGraphicsEffect(self)

    def set_progress(self, value):
        self.progress = float(value)
        self.update()

    def draw(self, painter):
        if self.progress >= 0.999:
            self.drawSource(painter)
            return
        painter.save()
        offset = QPoint()
        source = self.sourcePixmap(Qt.CoordinateSystem.LogicalCoordinates, offset,
                                   QGraphicsEffect.PixmapPadMode.NoPad)
        painter.setOpacity(0.55 + 0.45 * self.progress)
        painter.translate(0, 5 * (1-self.progress))
        painter.drawPixmap(offset, source)
        painter.restore()


class PageTransition(QWidget):
    """250ms 的旧页淡出、新页轻移；快照一次，支持快速连续切页。"""

    def __init__(self, parent):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        # 这一层每帧都铺满不透明底色，不应再让 Qt 重绘背后的整页表单。
        self.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent)
        self.driver = Driver(self)
        self.old = None
        self.new = None
        self.progress = 1.0
        parent.installEventFilter(self)
        self.hide()

    def eventFilter(self, obj, event):  # noqa: N802
        if event.type() in (QEvent.Type.Resize, QEvent.Type.Hide):
            self.finish()
        return False

    def finish(self):
        self.driver.finish_all()
        self.hide()
        self.old = self.new = None

    def _sync_motion(self):
        if not enabled():
            self.finish()

    def play(self, previous, current):
        if not enabled() or not self.parentWidget().isVisible():
            self.finish()
            return
        # 中断时使用当前合成帧，避免突然跳回上一页。
        old = self.grab() if self.isVisible() else None
        new = current.grab()
        self.driver.cancel("page")
        self.setGeometry(current.geometry())
        self.old, self.new = old, new
        self.progress = 0.0
        self.show()
        self.raise_()
        self.driver.frames("page", self._set_progress, 240)

    def _set_progress(self, value):
        self.progress = float(value)
        self.update()
        if self.progress >= 0.999:
            self.hide()
            self.old = self.new = None

    def paintEvent(self, event):  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        p.fillRect(self.rect(), d.INK_900)
        if self.new is not None:
            p.setOpacity(0.75 + 0.25*self.progress)
            p.drawPixmap(QPointF(0, 7*(1-self.progress)), self.new)
        if self.old is not None:
            p.setOpacity(1-self.progress)
            p.drawPixmap(0, 0, self.old)
        p.end()


class NavigationMarker(QWidget):
    def __init__(self, navigation):
        super().__init__(navigation.viewport())
        self.navigation = navigation
        self.y = 0.0
        self.driver = Driver(self)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        navigation.viewport().installEventFilter(self)
        navigation.currentRowChanged.connect(self.sync)

    def eventFilter(self, obj, event):  # noqa: N802
        if event.type() in (QEvent.Type.Resize, QEvent.Type.Show):
            self.setGeometry(self.parentWidget().rect())
            self.sync()
        return False

    def sync(self, _row=None):
        item = self.navigation.currentItem()
        if item is None:
            return
        target = self.navigation.visualItemRect(item).center().y() - 12
        self.driver.to("position", self.y, target, self._set_y, 260)
        self.raise_()

    def _set_y(self, value):
        self.y = float(value)
        self.update()

    def paintEvent(self, event):  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(d.ACCENT)
        p.drawRoundedRect(QRectF(7, self.y, 3, 24), 1.5, 1.5)
        p.end()


class MotionButton(QPushButton):
    """保留原生键盘/焦点/点击语义，在绘制中加入轻微缩放反馈。"""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.driver = Driver(self)
        self._scale = 1.0
        self._feedback_timer = QTimer(self)
        self._feedback_timer.setSingleShot(True)
        self._feedback_timer.timeout.connect(self._restore_text)
        self._normal_text = None
        self.pressed.connect(lambda: self._animate_scale(0.97))
        self.released.connect(lambda: self._animate_scale(1.0, "back"))

    def _animate_scale(self, target, ease="out"):
        self.driver.to("scale", self._scale, target, self._set_scale, 180, ease)

    def _set_scale(self, value):
        self._scale = float(value)
        self.update()

    def enterEvent(self, event):  # noqa: N802
        if self.isEnabled():
            self._animate_scale(1.012, "back")
        super().enterEvent(event)

    def leaveEvent(self, event):  # noqa: N802
        self._animate_scale(1.0)
        super().leaveEvent(event)

    def feedback(self, text):
        if self._normal_text is None:
            self._normal_text = self.text()
        self.setText(text)
        self._feedback_timer.start(1300)
        self._animate_scale(1.025, "back")

    def _restore_text(self):
        if self._normal_text is not None:
            self.setText(self._normal_text)
            self._normal_text = None
        self._animate_scale(1.0)

    def hideEvent(self, event):  # noqa: N802
        self._feedback_timer.stop()
        self._restore_text()
        self._scale = 1.0
        super().hideEvent(event)

    def paintEvent(self, event):  # noqa: N802
        p = QStylePainter(self)
        p.translate(self.width()/2, self.height()/2)
        p.scale(self._scale, self._scale)
        p.translate(-self.width()/2, -self.height()/2)
        option = QStyleOptionButton()
        self.initStyleOption(option)
        if glass.active():
            primary = self.objectName() == 'primary'
            rect = QRectF(self.rect()).adjusted(1, 1, -1, -1)
            glass.paint_surface(p, self, rect, rect.height()/2, primary=primary)
            p.setFont(self.font())
            p.setPen(d.TEXT_3 if not self.isEnabled() else d.ON_ACTION if primary else d.TEXT_HI)
            p.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, self.text())
            if self.hasFocus():
                from PySide6.QtGui import QPen
                p.setBrush(Qt.BrushStyle.NoBrush)
                p.setPen(QPen(d.SIGNAL, 1.5))
                p.drawRoundedRect(rect.adjusted(3,3,-3,-3), max(1,rect.height()/2-3), max(1,rect.height()/2-3))
        else:
            p.drawControl(QStyle.ControlElement.CE_PushButton, option)
        p.end()
