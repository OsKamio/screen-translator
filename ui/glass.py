"""原生液态玻璃：参考用户提供的 SDF / Snell 位移场，材质与文字分开绘制。

折射只采样应用自己绘制的背景。没有桌面截图、浏览器或后台刷新循环。
"""
from __future__ import annotations

from collections import OrderedDict
from functools import lru_cache
import math
import sys
import weakref
import logging

import cv2
import numpy as np
from PySide6.QtCore import QObject, QPoint, QPointF, QRectF, QRunnable, QThreadPool, Qt, Signal, Slot
from PySide6.QtGui import QBrush, QColor, QImage, QLinearGradient, QPainter, QPen, QPixmap, QRadialGradient
from PySide6.QtWidgets import QApplication, QWidget
from shiboken6 import isValid

_reduced = False
_epoch = 0
_surfaces = OrderedDict()
_surface_bytes = 0
_build_count = 0
_renderer = None
_pending = {}
_unbuilt = set()
_deferred = weakref.WeakSet()
MAX_PENDING = 24
MAX_CACHE_BYTES = 32*1024*1024
# 材质本来就是柔焦；按面积限制采样，文字和轮廓仍按屏幕 DPI 绘制。
MAX_SURFACE_PIXELS = 110_000
TILE_HEIGHT = 760
BODY_OPTICS = (14.0, 48.0, 4.0)
NAV_OPTICS = (12.0, 32.0, 2.0)  # Hero 导航的低强度折射，减轻细小文字附近的视觉噪声。


def refresh_preferences():
    global _reduced
    previous = _reduced
    _reduced = False
    if sys.platform == 'win32':
        try:
            import winreg
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                    r'Software\Microsoft\Windows\CurrentVersion\Themes\Personalize') as key:
                _reduced = winreg.QueryValueEx(key, 'EnableTransparency')[0] == 0
        except (OSError, ValueError):
            pass
    if previous != _reduced:
        clear_cache()
    return previous != _reduced


def active():
    from . import design as d
    return d.is_glass() and not _reduced


def clear_cache():
    global _epoch, _surface_bytes
    _epoch += 1
    _surfaces.clear()
    _surface_bytes = 0
    _scene.cache_clear()
    _displacement.cache_clear()
    _pending.clear()
    _unbuilt.clear()
    _deferred.clear()
    if _renderer is not None:
        _renderer.pool.clear()


def _rgb_image(array):
    array = np.ascontiguousarray(array, dtype=np.uint8)
    return QImage(array.data, array.shape[1], array.shape[0], array.strides[0],
                  QImage.Format.Format_RGB888).copy()


@lru_cache(maxsize=3)
def _scene(width, dark):
    """低对比的中性背景，只有宽幅柔光；不绘制色条或装饰图形。"""
    ratio = min(1.25, 1400/max(1, width))
    w, h = max(1, round(width*ratio)), round(TILE_HEIGHT*ratio)
    image = QImage(w, h, QImage.Format.Format_RGBA8888)
    image.fill(QColor('#1D2733' if dark else '#E9EEF3'))
    p = QPainter(image)
    p.scale(ratio, ratio)
    p.setPen(Qt.PenStyle.NoPen)
    for offset in (-TILE_HEIGHT, 0, TILE_HEIGHT):
        center = QPointF(width*.32, TILE_HEIGHT*.46+offset)
        gradient = QRadialGradient(center, max(220, min(650, width*.82)))
        gradient.setColorAt(0, QColor(255, 255, 255, 7 if dark else 28))
        gradient.setColorAt(1, QColor(255, 255, 255, 0))
        p.setBrush(gradient)
        p.drawRect(QRectF(0, 0, width, TILE_HEIGHT))
    # 与系统标题栏接壤的上沿保持同一底色，避免出现另一条横向色带。
    base = QColor('#1D2733' if dark else '#E9EEF3')
    top = QLinearGradient(0, 0, 0, 96)
    top.setColorAt(0, base)
    top.setColorAt(.33, base)
    base.setAlpha(0)
    top.setColorAt(1, base)
    p.fillRect(QRectF(0, 0, width, 96), top)
    p.end()
    array = np.frombuffer(image.constBits(), dtype=np.uint8).reshape(h, image.bytesPerLine())[:, :w*4].reshape(h, w, 4)[:, :, :3].copy()
    array = cv2.GaussianBlur(array, (0, 0), 7*ratio, borderType=cv2.BORDER_REFLECT_101)
    pixmap = QPixmap.fromImage(_rgb_image(array))
    pixmap.setDevicePixelRatio(ratio)
    return array, pixmap, ratio


def paint_background(painter, widget, *, radius=None):
    from . import design as d
    if radius is not None:
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        brush = QBrush(d.INK_900)
        if active():
            width, ox, oy = _background_context(widget)
            _array, pixmap, _ratio = _scene(width, d.CURRENT_THEME == 'dark')
            brush = QBrush(pixmap)
            painter.setBrushOrigin(QPointF(-ox, -oy))
        painter.fillPath(d.rounded_path(QRectF(widget.rect()), radius), brush)
        painter.restore()
        return
    painter.fillRect(widget.rect(), d.INK_900)
    if active():
        width, ox, oy = _background_context(widget)
        _array, pixmap, _ratio = _scene(width, d.CURRENT_THEME == 'dark')
        painter.drawTiledPixmap(QRectF(widget.rect()), pixmap, QPointF(ox, oy))


class GlassCanvas(QWidget):
    _glass_canvas = True

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground)

    def paintEvent(self, event):  # noqa: N802
        if active():
            p = QPainter(self)
            paint_background(p, self)
            p.end()
        else:
            super().paintEvent(event)


def _background_context(host):
    if getattr(host, '_glass_canvas', False) and host.parentWidget() is not None:
        root = host.window()
        # 锚定滚动视口，避免初始页面与头尾背景断开，也避免滚动时逐帧生成材质。
        point = host.parentWidget().mapTo(root, QPoint(0, 0))
        return max(1, root.width()), point.x(), point.y()
    return max(1, host.width()), 0, 0


def _context(widget, rect):
    host = widget
    while host.parentWidget() is not None and not getattr(host, '_glass_canvas', False):
        host = host.parentWidget()
    point = widget.mapTo(host, QPoint(0, 0))
    width, ox, oy = _background_context(host)
    return width, round(ox+point.x()+rect.x()), round(oy+point.y()+rect.y())


@lru_cache(maxsize=3)
def _displacement(width, height, radius, bevel):
    """圆角盒距离场 → 高度积分 → Snell 折射方向；不处理控件文字。"""
    y, x = np.mgrid[:height, :width].astype(np.float32)
    px, py = x-width/2+.5, y-height/2+.5

    qx, qy = np.abs(px)-width/2+radius, np.abs(py)-height/2+radius
    ax, ay = np.maximum(qx, 0), np.maximum(qy, 0)
    length = np.hypot(ax, ay)
    dist = length+np.minimum(np.maximum(qx, qy), 0)-radius
    # SDF 的解析法线替代四次额外距离场与有限差分，首次切页也保持轻量。
    normal_length = np.maximum(length, 1e-6)
    gx = np.sign(px)*np.where(length>1e-6, ax/normal_length, qx>=qy)
    gy = np.sign(py)*np.where(length>1e-6, ay/normal_length, qy>qx)
    n = max(1, math.ceil(bevel))
    depth = np.arange(n+1, dtype=np.float32)/n
    u = 1-np.clip(depth, 0, 1)
    denom = np.maximum(1-u**4, 0)**.75
    slope = np.divide(u**3, denom, out=np.zeros_like(u), where=denom>=1e-6)
    theta = np.arctan(np.minimum(slope, 8))
    bend = np.sin(theta-np.arcsin(np.sin(theta)/1.5))
    bend[denom<1e-6] = 0
    # 高度积分的导数就是 bend；内部平面与外部均无位移。
    slope_field = np.interp(np.clip(-dist, 0, n), np.arange(n+1), bend).astype(np.float32)
    slope_field[(dist>0) | (dist < -n)] = 0
    dx, dy = np.clip(-gx*slope_field*1.35, -1, 1), np.clip(-gy*slope_field*1.35, -1, 1)
    dot = (gx*(-.55)+gy*(-.85))/math.hypot(.55, .85)
    specular = (np.maximum(dot, 0)+np.maximum(-dot, 0)*.35)*np.clip(1+dist/max(1, bevel), 0, 1)
    alpha = np.clip(.5-dist, 0, 1)
    return x, y, dx, dy, specular, alpha


def _material(width, height, ratio, radius, scene, scene_ratio, ox, oy, dark, primary, optics):
    global _build_count
    w, h = max(2, round(width*ratio)), max(2, round(height*ratio))
    r = min(radius*ratio, w/2, h/2)
    depth, strength, aberration = optics
    bevel = min(depth*ratio, r, min(w, h)/2)
    x, y, dx, dy, specular, alpha = _displacement(w, h, round(r, 2), round(bevel, 2))
    result = np.empty((h, w, 3), dtype=np.uint8)
    # SVG scale 是 map 中间灰两侧各一半的位移；各通道保留轻微色散。
    for channel, displacement in enumerate((strength+aberration, strength, max(0, strength-aberration))):
        mx = ((ox+x/ratio)+dx*displacement*.5)*scene_ratio
        my = ((oy+y/ratio)+dy*displacement*.5)*scene_ratio
        mx = np.clip(mx, 0, scene.shape[1]-1).astype(np.float32)
        my = np.mod(my, scene.shape[0]).astype(np.float32)
        result[:, :, channel] = cv2.remap(scene[:, :, channel], mx, my, cv2.INTER_LINEAR,
                                          borderMode=cv2.BORDER_REFLECT_101)
    result = cv2.GaussianBlur(result, (0, 0), max(.1, .4*ratio)).astype(np.float32)
    # 原组件 tint=.12；深色用较低白色 tint，保持文字对比。
    tint = .06 if dark else .12
    result = result*(1-tint)+255*tint
    if primary:
        ink = np.array([51, 112, 164] if dark else [30, 82, 133], dtype=np.float32)
        result = result*.20+ink*.80
    gleam = np.clip(specular*(.10 if primary else (.18 if dark else .22)), 0, .5)[:, :, None]
    result = result*(1-gleam)+255*gleam
    rgba = np.empty((h, w, 4), dtype=np.uint8)
    rgba[:, :, :3] = np.clip(result, 0, 255)
    rgba[:, :, 3] = np.round(alpha*255)
    image = QImage(rgba.data, w, h, rgba.strides[0], QImage.Format.Format_RGBA8888).copy()
    image.setDevicePixelRatio(ratio)
    _build_count += 1
    return image


def _store_surface(key, pixmap):
    global _surface_bytes
    old = _surfaces.pop(key, None)
    if old is not None:
        _surface_bytes -= old.width()*old.height()*4
    size = pixmap.width()*pixmap.height()*4
    while _surfaces and _surface_bytes+size > MAX_CACHE_BYTES:
        _key, old = _surfaces.popitem(last=False)
        _surface_bytes -= old.width()*old.height()*4
        _unbuilt.discard(_key)
    _surfaces[key] = pixmap
    _surface_bytes += size


class _MaterialJob(QRunnable):
    def __init__(self, renderer, key, args):
        super().__init__()
        self.renderer, self.key, self.args = renderer, key, args

    def run(self):
        try:
            result = _material(*self.args)
        except Exception as exc:
            logging.getLogger(__name__).warning('玻璃材质回退：%s', type(exc).__name__)
            result = None
        try:
            self.renderer.completed.emit(self.key, result)
        except RuntimeError:  # 应用关闭后不触碰已销毁的 Qt 接收者。
            pass


class _MaterialRenderer(QObject):
    completed = Signal(object, object)

    def __init__(self):
        super().__init__(QApplication.instance())
        self.pool = QThreadPool(self)
        self.pool.setMaxThreadCount(1)
        self.completed.connect(self._ready)

    @Slot(object, object)
    def _ready(self, key, result):
        watchers = _pending.pop(key, ())
        if key[0] != _epoch:
            return
        if result is not None and key in _surfaces:
            _store_surface(key, QPixmap.fromImage(result))
        for reference in watchers:
            widget = reference()
            if widget is not None and isValid(widget) and widget.isVisible():
                widget.update()
        # 连续缩放时队列满额的表面，在容量释放后可重新请求，不永久停留在底色。
        deferred = tuple(_deferred)
        _deferred.clear()
        for widget in deferred:
            if isValid(widget) and widget.isVisible():
                widget.update()


def _placeholder(width, height, ratio, radius, scene, ox, oy, dark, primary):
    """即时绘制无位移的同源底色；后台只补充折射，保持首次点击响应。"""
    from . import design as d
    pixmap = QPixmap(max(2, round(width*ratio)), max(2, round(height*ratio)))
    pixmap.setDevicePixelRatio(ratio)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    rect = QRectF(0, 0, width, height)
    painter.setClipPath(d.rounded_path(rect, radius))
    painter.drawTiledPixmap(rect, scene, QPointF(ox, oy))
    painter.fillRect(rect, QColor(255,255,255,15 if dark else 31))
    if primary:
        painter.fillRect(rect, QColor(51,112,164,204) if dark else QColor(30,82,133,204))
    painter.end()
    return pixmap


def surface(widget, rect, radius, *, primary=False, sample_rect=None, optics=BODY_OPTICS):
    global _renderer
    from . import design as d
    width, height = max(2, round(rect.width())), max(2, round(rect.height()))
    ratio = min(2.0, widget.devicePixelRatioF(), math.sqrt(MAX_SURFACE_PIXELS/(width*height)),
                2048/max(width, height))
    host_width, ox, oy = _context(widget, sample_rect or rect)
    key = (_epoch, width, height, ratio, round(radius, 2), host_width, ox, oy,
           d.CURRENT_THEME, bool(primary), optics)
    pixmap = _surfaces.get(key)
    if key in _unbuilt and len(_pending) < MAX_PENDING:
        _unbuilt.discard(key)
        pixmap = None
    elif key in _unbuilt:
        _deferred.add(widget)
    if pixmap is None:
        dark = d.CURRENT_THEME == 'dark'
        scene, backdrop, scene_ratio = _scene(host_width, dark)
        args = (width, height, ratio, radius, scene, scene_ratio, ox, oy, dark, primary, optics)
        if width*height*ratio*ratio <= 24_000:
            pixmap = QPixmap.fromImage(_material(*args))
        else:
            pixmap = _placeholder(width, height, ratio, radius, backdrop, ox, oy, dark, primary)
            if len(_pending) < MAX_PENDING:
                if _renderer is None:
                    _renderer = _MaterialRenderer()
                _pending[key] = [weakref.ref(widget)]
                _renderer.pool.start(_MaterialJob(_renderer, key, args))
            else:
                _unbuilt.add(key)
                _deferred.add(widget)
        _store_surface(key, pixmap)
    else:
        _surfaces.move_to_end(key)
        watchers = _pending.get(key)
        if watchers is not None and not any(reference() is widget for reference in watchers):
            watchers.append(weakref.ref(widget))
    return pixmap


def paint_surface(painter, widget, rect, radius, *, primary=False, opacity=1.0, pixmap=None, optics=BODY_OPTICS):
    pixmap = pixmap if pixmap is not None else surface(widget, rect, radius, primary=primary, optics=optics)
    painter.save()
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
    painter.setOpacity(painter.opacity()*max(0, min(1, opacity)))
    painter.drawPixmap(rect, pixmap, QRectF(0, 0, pixmap.width(), pixmap.height()))
    light = QLinearGradient(rect.topLeft(), rect.bottomRight())
    light.setColorAt(0, QColor(255, 255, 255, 132))
    light.setColorAt(.40, QColor(255, 255, 255, 32))
    light.setColorAt(.80, QColor(203, 221, 240, 72))
    light.setColorAt(1, QColor(255, 255, 255, 116))
    painter.setPen(QPen(light, 1.0))
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.drawRoundedRect(rect.adjusted(.6, .6, -.6, -.6), radius, radius)
    painter.restore()


def paint_on(painter, rect, radius, *, primary=False, opacity=1.0):
    if not active() or not isinstance(painter.device(), QWidget):
        return False
    paint_surface(painter, painter.device(), rect, radius, primary=primary, opacity=opacity)
    return True
