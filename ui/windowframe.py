"""统一窗口外框：平滑圆角、主题标题栏、系统拖动/缩放及快速输入回退。

同时保留 DWM 配色入口，供采用原生边框的窗口使用。
"""
from __future__ import annotations

import ctypes
from functools import lru_cache
import sys
import weakref

from PySide6.QtCore import QEvent, QObject, QPoint, QRectF, QSize, Qt
from PySide6.QtGui import QGuiApplication, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QApplication, QHBoxLayout, QLabel, QToolButton, QWidget
from shiboken6 import isValid

from . import design as d

DWMWA_USE_IMMERSIVE_DARK_MODE = 20
DWMWA_BORDER_COLOR = 34
DWMWA_CAPTION_COLOR = 35
DWMWA_TEXT_COLOR = 36
DWMWA_COLOR_DEFAULT = 0xFFFFFFFF
DWMWA_COLOR_NONE = 0xFFFFFFFE


def colorref(color):
    return color.red() | (color.green() << 8) | (color.blue() << 16)


@lru_cache(maxsize=1)
def _set_attribute():
    from ctypes import wintypes
    function = ctypes.WinDLL('dwmapi').DwmSetWindowAttribute
    function.argtypes = [wintypes.HWND, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD]
    function.restype = ctypes.c_long
    return function


def apply(widget):
    """仅更新已有 HWND 的装饰；不创建或重建窗口。不支持的属性由系统拒绝。"""
    if (sys.platform != 'win32' or QGuiApplication.platformName() != 'windows'
            or widget.windowFlags() & Qt.WindowType.FramelessWindowHint
            or not widget.testAttribute(Qt.WidgetAttribute.WA_WState_Created)):
        return {}
    try:
        function = _set_attribute()
        handle = int(widget.winId())
        values = {
            DWMWA_USE_IMMERSIVE_DARK_MODE: int(d.CURRENT_THEME == 'dark'),
            DWMWA_CAPTION_COLOR: colorref(d.INK_900),
            DWMWA_TEXT_COLOR: colorref(d.TEXT_HI),
            DWMWA_BORDER_COLOR: DWMWA_COLOR_NONE if d.is_glass() else DWMWA_COLOR_DEFAULT,
        }
        result = {}
        for attribute, value in values.items():
            data = ctypes.c_uint32(value)
            result[attribute] = int(function(handle, attribute, ctypes.byref(data), ctypes.sizeof(data)))
        return result
    except (AttributeError, OSError):
        return {}


def radius(widget):
    return 0.0 if widget.isMaximized() or widget.isFullScreen() else d.R_WINDOW


def _physical_drag_active():
    """排队的快速/远程输入可能已松开物理按键，此时原生拖动会立即退出。"""
    if sys.platform != 'win32':
        return True
    try:
        return bool(ctypes.windll.user32.GetAsyncKeyState(1) & 0x8000)
    except (AttributeError, OSError):
        return False


def resize_edges(widget, point):
    """只将最外侧 6px 留给缩放；内容与按钮保持完整点击区。"""
    if widget.isMaximized() or widget.isFullScreen() or not widget.rect().contains(point):
        return Qt.Edge(0)
    edges = Qt.Edge(0)
    if point.x() < 6:
        edges |= Qt.Edge.LeftEdge
    elif point.x() >= widget.width()-6:
        edges |= Qt.Edge.RightEdge
    if point.y() < 6:
        edges |= Qt.Edge.TopEdge
    elif point.y() >= widget.height()-6:
        edges |= Qt.Edge.BottomEdge
    return edges


class RoundedFrame(QObject):
    """平滑透明圆角配合 Qt 原生系统缩放，无窗口 mask、轮询或句柄重建。"""
    def __init__(self, window):
        super().__init__(window)
        self.window = window
        self._cursor_owner = None
        self._cursor = None
        self._cursor_explicit = False
        self._resize_anchor = None
        self._resize_geometry = None
        self._resize_edges = Qt.Edge(0)
        self._native_resize_started = False
        QApplication.instance().installEventFilter(self)

    def _restore_cursor(self):
        widget = self._cursor_owner() if self._cursor_owner is not None else None
        if widget is not None and isValid(widget):
            if self._cursor_explicit:
                widget.setCursor(self._cursor)
            else:
                widget.unsetCursor()
        self._cursor_owner = None

    def eventFilter(self, obj, event):  # noqa: N802
        kind = event.type()
        if kind not in (QEvent.Type.MouseMove, QEvent.Type.MouseButtonPress,
                        QEvent.Type.MouseButtonRelease, QEvent.Type.Leave,
                        QEvent.Type.Hide, QEvent.Type.WindowStateChange):
            return False
        if not isinstance(obj, QWidget) or obj.window() is not self.window:
            return False
        if kind in (QEvent.Type.Leave, QEvent.Type.Hide, QEvent.Type.WindowStateChange):
            self._restore_cursor()
            if kind != QEvent.Type.Leave:
                self._resize_anchor = None
            return False
        if kind == QEvent.Type.MouseButtonRelease:
            self._resize_anchor = None
            return False
        point = self.window.mapFromGlobal(event.globalPosition().toPoint())
        edges = resize_edges(self.window, point)
        if kind == QEvent.Type.MouseButtonPress and event.button() == Qt.MouseButton.LeftButton and edges:
            self._resize_anchor = event.globalPosition().toPoint()
            self._resize_geometry = self.window.geometry()
            self._resize_edges = edges
            self._native_resize_started = False
            event.accept()
            return True
        if kind == QEvent.Type.MouseMove:
            # 原生拖动未接管时（例如某些远程输入环境），用同一锚点完成连续缩放。
            if self._resize_anchor is not None:
                if not event.buttons() & Qt.MouseButton.LeftButton:
                    self._resize_anchor = None
                else:
                    delta = event.globalPosition().toPoint()-self._resize_anchor
                    geometry = self._resize_geometry
                    left, right, top, bottom = geometry.left(), geometry.right(), geometry.top(), geometry.bottom()
                    if self._resize_edges & Qt.Edge.LeftEdge:
                        left = max(right-self.window.maximumWidth()+1, min(left+delta.x(), right-self.window.minimumWidth()+1))
                    if self._resize_edges & Qt.Edge.RightEdge:
                        right = min(left+self.window.maximumWidth()-1, max(right+delta.x(), left+self.window.minimumWidth()-1))
                    if self._resize_edges & Qt.Edge.TopEdge:
                        top = max(bottom-self.window.maximumHeight()+1, min(top+delta.y(), bottom-self.window.minimumHeight()+1))
                    if self._resize_edges & Qt.Edge.BottomEdge:
                        bottom = min(top+self.window.maximumHeight()-1, max(bottom+delta.y(), top+self.window.minimumHeight()-1))
                    self.window.setGeometry(left, top, right-left+1, bottom-top+1)
                    if not self._native_resize_started and _physical_drag_active():
                        handle = self.window.windowHandle()
                        self._native_resize_started = bool(handle and handle.startSystemResize(self._resize_edges))
                    event.accept()
                    return True
            owner = self._cursor_owner() if self._cursor_owner is not None else None
            if owner is not obj or not edges:
                self._restore_cursor()
            if edges:
                if self._cursor_owner is None:
                    self._cursor_owner = weakref.ref(obj)
                    self._cursor = obj.cursor()
                    self._cursor_explicit = obj.testAttribute(Qt.WidgetAttribute.WA_SetCursor)
                vertical = bool(edges & (Qt.Edge.TopEdge | Qt.Edge.BottomEdge))
                horizontal = bool(edges & (Qt.Edge.LeftEdge | Qt.Edge.RightEdge))
                if vertical and horizontal:
                    matching = edges in (Qt.Edge.TopEdge | Qt.Edge.LeftEdge, Qt.Edge.BottomEdge | Qt.Edge.RightEdge)
                    cursor = Qt.CursorShape.SizeFDiagCursor if matching else Qt.CursorShape.SizeBDiagCursor
                else:
                    cursor = Qt.CursorShape.SizeVerCursor if vertical else Qt.CursorShape.SizeHorCursor
                obj.setCursor(cursor)
        return False


class _CloseButton(QToolButton):
    def __init__(self, window):
        super().__init__(window)
        self.setFixedSize(44, 32)
        self.setToolTip('关闭设置')
        self.setAccessibleName('关闭设置窗口')
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)  # 与系统标题栏一致，Tab 留给设置项；Alt+F4 可关闭。
        self.setMouseTracking(True)
        self.clicked.connect(window.close)

    def paintEvent(self, event):  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        root = self.window()
        point = self.mapTo(root, QPoint(0, 0))
        outer = QRectF(root.rect()).translated(-point.x(), -point.y())
        hovered = self.underMouse() or self.isDown()
        if hovered:
            shape = QPainterPath()
            shape.addRect(QRectF(self.rect()))
            p.fillPath(shape.intersected(d.rounded_path(outer, radius(root))), d.ERROR)
        p.setPen(QPen(Qt.GlobalColor.white if hovered else d.TEXT_2, 1.3))
        center = self.rect().center()
        p.drawLine(center.x()-4, center.y()-4, center.x()+4, center.y()+4)
        p.drawLine(center.x()+4, center.y()-4, center.x()-4, center.y()+4)
        if self.hasFocus():
            p.setClipPath(d.rounded_path(outer, radius(root)))
            p.setPen(QPen(d.SIGNAL, 1.2))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRoundedRect(QRectF(self.rect()).adjusted(3,3,-3,-3), 7, 7)
        p.end()


class TitleBar(QWidget):
    def __init__(self, window):
        super().__init__(window)
        self._window = window
        self._drag_offset = None
        self._native_move_started = False
        self.setFixedHeight(36)
        self.setMouseTracking(True)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(18, 0, 8, 0)
        layout.setSpacing(8)
        self.icon = QLabel()
        self.icon.setFixedSize(18, 18)
        self.caption = QLabel(window.windowTitle())
        self.caption.setObjectName('windowCaption')
        for label in (self.icon, self.caption):
            label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        layout.addWidget(self.icon)
        layout.addWidget(self.caption)
        layout.addStretch(1)
        self.close_button = _CloseButton(window)
        layout.addWidget(self.close_button)
        window.windowTitleChanged.connect(self.caption.setText)
        window.windowIconChanged.connect(self._set_icon)
        self._set_icon(window.windowIcon())

    def _set_icon(self, icon):
        ratio = self.devicePixelRatioF()
        pixmap = icon.pixmap(QSize(18, 18), ratio)
        self.icon.setPixmap(pixmap)

    def mousePressEvent(self, event):  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_offset = event.globalPosition().toPoint()-self._window.pos()
            self._native_move_started = False
            event.accept()

    def mouseMoveEvent(self, event):  # noqa: N802
        if (self._drag_offset is not None and event.buttons() & Qt.MouseButton.LeftButton
                and not self._window.isMaximized()):
            self._window.move(event.globalPosition().toPoint()-self._drag_offset)
            if not self._native_move_started and _physical_drag_active():
                handle = self._window.windowHandle()
                self._native_move_started = bool(handle and handle.startSystemMove())

    def mouseReleaseEvent(self, event):  # noqa: N802
        self._drag_offset = None

    def mouseDoubleClickEvent(self, event):  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            if self._window.isMaximized():
                self._window.showNormal()
            else:
                self._window.showMaximized()
            event.accept()
