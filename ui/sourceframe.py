# -*- coding: utf-8 -*-
"""独立取景区域：边框在捕获矩形外，永远不会被 OCR 抓到。"""
from PySide6.QtCore import Qt, QRect
from PySide6.QtGui import QPainter, QPen, QRegion
from PySide6.QtWidgets import QWidget
from . import design as d


class SourceFrame(QWidget):
    MARGIN = 4
    def __init__(self):
        super().__init__(None, Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint
                         | Qt.Tool | Qt.WindowTransparentForInput)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setWindowTitle("实时翻译取景区域")

    def set_source(self, rect):
        m = self.MARGIN
        self.setGeometry(rect.adjusted(-m, -m, m, m))
        # 原文区域完全挖空，连透明层也不覆盖输入。
        self.setMask(QRegion(self.rect()) - QRegion(QRect(m, m, rect.width(), rect.height())))
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setPen(QPen(d.SOURCE_FRAME, 2))
        p.setBrush(Qt.NoBrush)
        p.drawRect(self.rect().adjusted(1, 1, -2, -2))
        p.end()
