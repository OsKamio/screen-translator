"""参考视频中的胶囊分段控件；保留 QListWidget 的键盘及无障碍语义。"""
from __future__ import annotations

import math

from PySide6.QtCore import QSize, QRectF, Qt
from PySide6.QtGui import QPainter, QPen, QPixmap
from PySide6.QtWidgets import QListWidget, QListView

from . import design as d
from .motion import Driver
from . import glass


class CapsuleNavigation(QListWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName('navigation')
        self.setFlow(QListView.Flow.LeftToRight)
        self.setWrapping(False)
        self.setUniformItemSizes(True)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setFixedHeight(54)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._selection_x = 0.0
        self._selection_w = 0.0
        self._stretch = 0.0
        self._ready = False
        self._layer_key = None
        self._base_layer = self._inverse_layer = None
        self._glass_thumb_rect = QRectF()
        self.driver = Driver(self)
        self.currentRowChanged.connect(self.sync)

    def resizeEvent(self, event):  # noqa: N802
        super().resizeEvent(event)
        width = max(1, self.viewport().width()//max(1, self.count()))
        self.setGridSize(QSize(width, self.viewport().height()))
        for index in range(self.count()):
            self.item(index).setSizeHint(self.gridSize())
        self.doItemsLayout()
        self.driver.finish_all()
        self._ready = False
        self.sync()

    def sync(self, _row=None):
        item = self.currentItem()
        if item is None:
            return
        cell = QRectF(self.visualItemRect(item)).adjusted(4, 5, -4, -5)
        if cell.isEmpty():
            return
        if not self._ready:
            self._selection_x, self._selection_w = cell.x(), cell.width()
            self._ready = True
        if abs(self._selection_x-cell.x()) < .01 and abs(self._selection_w-cell.width()) < .01:
            self.viewport().update()
            return
        start_x, start_w, start_stretch = self._selection_x, self._selection_w, self._stretch

        def frame(progress):
            self._selection_x = start_x+(cell.x()-start_x)*progress
            self._selection_w = start_w+(cell.width()-start_w)*progress
            self._stretch = start_stretch*(1-progress)+math.sin(math.pi*progress)
            self.viewport().update()

        self.driver.frames('selection', frame, 280)
        self.viewport().update()

    def _prepare_layers(self):
        viewport = self.viewport()
        ratio = viewport.devicePixelRatioF()
        texts = tuple(self.item(i).text() for i in range(self.count()))
        key = (viewport.width(), viewport.height(), ratio, d.theme_key(), glass.active(),
               self.currentRow(), texts)
        if key == self._layer_key:
            return
        layers = []
        # 字体排版与反色文字只在标签/主题/尺寸改变时生成一次。
        for inverse in (False, True):
            layer = QPixmap(round(viewport.width()*ratio), round(viewport.height()*ratio))
            layer.setDevicePixelRatio(ratio)
            layer.fill(Qt.GlobalColor.transparent)
            painter = QPainter(layer)
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            if not inverse and not glass.active():
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(d.INK_500)
                painter.drawRoundedRect(QRectF(viewport.rect()), 27, 27)
            painter.setPen(d.ON_ACTION if inverse else d.TEXT_2)
            for index, text in enumerate(texts):
                cell = QRectF(self.visualItemRect(self.item(index)))
                painter.setFont(d.font(d.F_BODY, d.W_SEMI if index == self.currentRow() else d.W_MED))
                text = painter.fontMetrics().elidedText(text, Qt.TextElideMode.ElideRight,
                                                        max(1, int(cell.width()-20)))
                painter.drawText(cell, Qt.AlignmentFlag.AlignCenter, text)
            painter.end()
            layers.append(layer)
        self._base_layer, self._inverse_layer = layers
        if glass.active():
            cell = QRectF(self.visualItemRect(self.currentItem())).adjusted(4, 5, -4, -5)
            self._glass_thumb_rect = cell
        else:
            self._glass_thumb_rect = QRectF()
        self._layer_key = key

    def paintEvent(self, event):  # noqa: N802
        self._prepare_layers()
        p = QPainter(self.viewport())
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(Qt.PenStyle.NoPen)
        if glass.active():
            glass.paint_surface(p, self, QRectF(self.viewport().rect()), 27, optics=glass.NAV_OPTICS)
        p.drawPixmap(0, 0, self._base_layer)
        selected = QRectF(self._selection_x-4*self._stretch, 5,
                          self._selection_w+8*self._stretch,
                          max(1, self.viewport().height()-10))
        if glass.active():
            cell = self._glass_thumb_rect
            thumb = glass.surface(self, cell, cell.height()/2, primary=True, optics=glass.NAV_OPTICS)
            glass.paint_surface(p, self, selected, selected.height()/2,
                                primary=True, pixmap=thumb)
        else:
            p.setBrush(d.ACTION)
            p.drawRoundedRect(selected, selected.height()/2, selected.height()/2)
        p.save()
        p.setClipPath(d.rounded_path(selected, selected.height()/2))
        p.drawPixmap(0, 0, self._inverse_layer)
        p.restore()
        if self.hasFocus():
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.setPen(QPen(d.SIGNAL, 1.5))
            p.drawRoundedRect(selected.adjusted(2, 2, -2, -2), 19, 19)
        p.end()
