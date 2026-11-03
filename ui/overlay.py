# -*- coding: utf-8 -*-
"""全屏框选遮罩：覆盖主屏，按住左键拖出矩形选择区域。

视觉（相对早期版本的精修）：
- 选区“挖空”遮罩层，框内保持原始亮度（专业截图工具的做法）；
- 细线轮廓 + L 形角标，而不是粗边框加实心方块；
- 从选区边缘延伸的极淡十字准线，便于对齐；
- 尺寸气泡用等宽数字 + 玻璃底；顶部提示条用发丝边玻璃条。
"""
from __future__ import annotations

from PySide6.QtCore import QPoint, QPointF, QRect, QRectF, Qt, Signal
from PySide6.QtGui import (
    QColor, QCursor, QGuiApplication, QPainter, QPainterPath, QPen,
)
from PySide6.QtWidgets import QWidget

from . import design as d
from . import theme


class CaptureOverlay(QWidget):
    """半透明全屏遮罩。松开左键时发射 region_selected（全局逻辑坐标）。"""

    region_selected = Signal(QRect)
    cancelled = Signal()

    MIN_SIZE = 6  # 小于该尺寸视为误触，不发选区

    def __init__(self):
        screen = QGuiApplication.primaryScreen()
        geom = screen.geometry()
        super().__init__(None, Qt.WindowType.FramelessWindowHint
                         | Qt.WindowType.WindowStaysOnTopHint
                         | Qt.WindowType.Tool)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setGeometry(geom)
        self.setMouseTracking(True)
        self.setCursor(QCursor(Qt.CursorShape.CrossCursor))
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

        self._begin: QPoint | None = None
        self._cur: QPoint | None = None
        self._active = False

    # ------------------------------------------------------------------ 公开
    def begin_capture(self) -> None:
        """显示并抢占键盘，准备框选。"""
        self._begin = None
        self._cur = None
        self._active = False
        self.show()
        self.raise_()
        self.activateWindow()
        self.setFocus(Qt.FocusReason.ActiveWindowFocusReason)
        self.grabKeyboard()  # 确保 Esc 一定能收到
        self.update()

    # ------------------------------------------------------------------ 事件
    def mousePressEvent(self, event):  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            self._begin = event.position().toPoint()
            self._cur = self._begin
            self._active = True
            self.update()

    def mouseMoveEvent(self, event):  # noqa: N802
        if self._active:
            self._cur = event.position().toPoint()
            self.update()

    def mouseReleaseEvent(self, event):  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton and self._active:
            self._active = False
            self._cur = event.position().toPoint()
            sel = self._selection()
            self.releaseKeyboard()
            if sel is not None:
                # 转换为全局逻辑坐标
                sel.translate(self.geometry().topLeft())
                self.region_selected.emit(sel)
            else:
                self.cancelled.emit()

    def keyPressEvent(self, event):  # noqa: N802
        if event.key() == Qt.Key.Key_Escape:
            self.releaseKeyboard()
            self._active = False
            self.cancelled.emit()
        else:
            super().keyPressEvent(event)

    def _selection(self) -> QRect | None:
        if self._begin is None or self._cur is None:
            return None
        r = QRect(self._begin, self._cur).normalized()
        if r.width() < self.MIN_SIZE or r.height() < self.MIN_SIZE:
            return None
        return r

    # ------------------------------------------------------------------ 绘制
    def _paint_hint_bar(self, p: QPainter) -> None:
        """顶部玻璃提示条：主文案 + 次级说明。"""
        title = "拖出要翻译的区域"
        sub = "Esc 取消　·　松开鼠标开始识别"

        p.setFont(d.font(d.F_BODY, d.W_MED))
        fm1 = p.fontMetrics()
        p.setFont(d.font(d.F_CAPTION, d.W_REG, wide=True))
        fm2 = p.fontMetrics()

        w = max(fm1.horizontalAdvance(title), fm2.horizontalAdvance(sub)) + 2 * d.S6
        h = fm1.height() + fm2.height() + d.S3 + d.S2
        bar = QRectF((self.width() - w) / 2.0, d.S7, w, h)

        # 玻璃底 + 发丝边
        shell = QColor(d.INK_800)
        shell.setAlpha(232)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(shell)
        p.drawRoundedRect(bar, d.R_MD, d.R_MD)
        d.paint_hairline(p, bar, d.R_MD, d.LINE_STRONG)

        p.setFont(d.font(d.F_BODY, d.W_MED))
        p.setPen(d.TEXT_HI)
        p.drawText(QRectF(bar.left(), bar.top() + d.S2, bar.width(), fm1.height()),
                   Qt.AlignmentFlag.AlignCenter, title)
        p.setFont(d.font(d.F_CAPTION, d.W_REG, wide=True))
        p.setPen(d.TEXT_3)
        p.drawText(QRectF(bar.left(), bar.top() + d.S2 + fm1.height() + 2,
                          bar.width(), fm2.height()),
                   Qt.AlignmentFlag.AlignCenter, sub)

    def _paint_crosshair(self, p: QPainter, sel: QRect) -> None:
        """从选区边缘延伸的极淡准线（对齐用）。"""
        pen = QPen(QColor(255, 255, 255, 22), 1.0)
        p.setPen(pen)
        p.drawLine(QPointF(sel.left(), 0), QPointF(sel.left(), sel.top()))
        p.drawLine(QPointF(sel.right(), 0), QPointF(sel.right(), sel.top()))
        p.drawLine(QPointF(sel.left(), sel.bottom()), QPointF(sel.left(), self.height()))
        p.drawLine(QPointF(sel.right(), sel.bottom()),
                   QPointF(sel.right(), self.height()))
        p.drawLine(QPointF(0, sel.top()), QPointF(sel.left(), sel.top()))
        p.drawLine(QPointF(sel.right(), sel.top()), QPointF(self.width(), sel.top()))
        p.drawLine(QPointF(0, sel.bottom()), QPointF(sel.left(), sel.bottom()))
        p.drawLine(QPointF(sel.right(), sel.bottom()),
                   QPointF(self.width(), sel.bottom()))

    def _paint_corners(self, p: QPainter, sel: QRect) -> None:
        """L 形角标：比粗边框 + 方块更克制、更专业。"""
        pen = QPen(d.ACCENT_HI, 2.0)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        p.setPen(pen)
        p.setBrush(Qt.BrushStyle.NoBrush)
        arm = min(20.0, max(10.0, min(sel.width(), sel.height()) * 0.22))
        x0, y0, x1, y1 = sel.left(), sel.top(), sel.right(), sel.bottom()
        # 左上
        p.drawLine(QPointF(x0, y0), QPointF(x0 + arm, y0))
        p.drawLine(QPointF(x0, y0), QPointF(x0, y0 + arm))
        # 右上
        p.drawLine(QPointF(x1, y0), QPointF(x1 - arm, y0))
        p.drawLine(QPointF(x1, y0), QPointF(x1, y0 + arm))
        # 左下
        p.drawLine(QPointF(x0, y1), QPointF(x0 + arm, y1))
        p.drawLine(QPointF(x0, y1), QPointF(x0, y1 - arm))
        # 右下
        p.drawLine(QPointF(x1, y1), QPointF(x1 - arm, y1))
        p.drawLine(QPointF(x1, y1), QPointF(x1, y1 - arm))

    def _paint_size_badge(self, p: QPainter, sel: QRect) -> None:
        """等宽数字的尺寸气泡（避免数字宽度跳动）。"""
        text = f"{sel.width()} × {sel.height()}"
        p.setFont(d.mono_font(d.F_SMALL, d.W_MED))
        fm = p.fontMetrics()
        bw = fm.horizontalAdvance(text) + d.S4
        bh = fm.height() + d.S2
        tx = sel.left()
        ty = sel.bottom() + d.S2
        if ty + bh > self.height():
            ty = sel.top() - bh - d.S2
        if tx + bw > self.width():
            tx = self.width() - bw - d.S2
        if tx < d.S2:
            tx = d.S2
        badge = QRectF(tx, ty, bw, bh)
        bg = QColor(d.INK_800)
        bg.setAlpha(236)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(bg)
        p.drawRoundedRect(badge, d.R_XS, d.R_XS)
        d.paint_hairline(p, badge, d.R_XS, d.LINE_STRONG)
        p.setPen(d.ACCENT_HI)
        p.drawText(badge, Qt.AlignmentFlag.AlignCenter, text)

    def paintEvent(self, _event):  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)

        sel = QRect()
        if self._begin is not None and self._cur is not None:
            sel = QRect(self._begin, self._cur).normalized()

        # 1) 遮罩：把选区“挖空”，框内保持原始亮度
        full = QPainterPath()
        full.addRect(QRectF(self.rect()))
        if not sel.isEmpty():
            cut = QPainterPath()
            cut.addRect(QRectF(sel))
            p.fillPath(full.subtracted(cut), d.OVERLAY_DIM)
            self._paint_crosshair(p, sel)
            p.setPen(QPen(QColor(d.ACCENT_HI.red(), d.ACCENT_HI.green(),
                                 d.ACCENT_HI.blue(), 180), 1.5))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRect(QRectF(sel).adjusted(0.75, 0.75, -0.75, -0.75))
            self._paint_corners(p, sel)
            self._paint_size_badge(p, sel)
        else:
            p.fillPath(full, d.OVERLAY_DIM)

        # 2) 顶部提示
        self._paint_hint_bar(p)
        p.end()
