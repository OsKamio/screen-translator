# -*- coding: utf-8 -*-
"""悬浮球：常驻桌面的可拖动小圆球，点击进入框选模式。"""
from __future__ import annotations

from PySide6.QtCore import (
    QPoint, QPointF, QRect, QRectF, Qt, QTimer, Signal,
)
from PySide6.QtGui import (
    QColor, QCursor, QGuiApplication, QPainter, QPainterPath, QPen, QRadialGradient,
    QLinearGradient, QAction,
)
from PySide6.QtWidgets import QMenu, QWidget

from . import design as d
from . import theme
from . import motion
from . import glass


class FloatBall(QWidget):
    """无边框置顶的圆形悬浮按钮。

    状态：
      idle   —— 常驻可用，点击发射 clicked
      busy   —— 正在识别/翻译（显示旋转进度，忽略点击）
    """

    clicked = Signal()
    exit_requested = Signal()
    settings_requested = Signal()
    live_toggle_requested = Signal()

    SIZE = 58  # 默认直径（可在设置中调整）

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent, Qt.WindowType.FramelessWindowHint
                         | Qt.WindowType.WindowStaysOnTopHint
                         | Qt.WindowType.Tool)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self._size = self.SIZE
        self.setFixedSize(self._size, self._size)
        self.setMouseTracking(True)
        self.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.setToolTip("点击：框选要翻译的区域\n右键：更多操作")

        self._state = "idle"
        self._hover = False
        self._busy_text = ""
        self._menu_open = False
        self._live_visible = False
        self._angle = 0.0
        self._drag_offset: QPoint | None = None
        self._pressed_at: QPoint | None = None
        self._moved = False

        self._spinner = QTimer(self)
        self._spinner.setInterval(40)
        self._spinner.timeout.connect(self._on_tick)

        # hover 动画（平滑插值，避免生硬跳变）
        self._hover_t = 0.0
        self._motion = motion.Driver(self)
        self._press_t = 0.0
        self._settle_t = 0.0
        self._shape_t = 0.0

    # ------------------------------------------------------------------ API
    def set_busy(self, busy: bool, text: str = "") -> None:
        was_busy = self.is_busy()
        self._state = "busy" if busy else "idle"
        self._busy_text = text
        self._sync_motion()
        self._motion.to("shape", self._shape_t, 1.0 if busy else 0.0,
                        lambda v: self._set_motion("_shape_t", v), 290, "back")
        if was_busy and not busy:
            self._motion.pulse("settle", lambda v: self._set_motion("_settle_t", v), up=100, down=300)
        self.setToolTip(text or "点击：框选要翻译的区域\n右键：更多操作")
        self.update()

    def _sync_motion(self) -> None:
        if self.is_busy() and self.isVisible() and motion.enabled():
            self._spinner.start()
        else:
            self._spinner.stop()

    def showEvent(self, event):  # noqa: N802
        super().showEvent(event)
        self._sync_motion()

    def hideEvent(self, event):  # noqa: N802
        self._spinner.stop()
        self._hover_t = self._press_t = self._settle_t = 0.0
        super().hideEvent(event)

    def _set_motion(self, attr, value):
        setattr(self, attr, float(value))
        self.update()

    def is_busy(self) -> bool:
        return self._state == "busy"

    # ------------------------------------------------------------------ 事件
    def _on_tick(self) -> None:
        self._angle = (self._angle + 9.0) % 360.0
        self.update()

    def enterEvent(self, event):  # noqa: N802
        self._hover = True
        self._animate_hover(1.0)
        super().enterEvent(event)

    def leaveEvent(self, event):  # noqa: N802
        self._hover = False
        self._animate_hover(0.0)
        super().leaveEvent(event)

    def _animate_hover(self, target: float) -> None:
        """平滑过渡 hover 状态（缓动插值）。"""
        self._motion.to("hover", self._hover_t, target,
                        self._on_hover_value, 250, "back")

    def _on_hover_value(self, value) -> None:
        self._hover_t = float(value)
        self.update()

    def mousePressEvent(self, event):  # noqa: N802
        if event.button() == Qt.MouseButton.RightButton and not self.is_busy():
            # 右键按下直接弹菜单（对无边框 Tool 窗口最可靠）
            self._show_menu(event.globalPosition().toPoint())
            event.accept()
            return
        if event.button() == Qt.MouseButton.LeftButton and not self.is_busy():
            self._pressed_at = event.globalPosition().toPoint()
            self._drag_offset = self._pressed_at - self.frameGeometry().topLeft()
            self._moved = False
            self._motion.to("press", self._press_t, 1.0,
                            lambda v: self._set_motion("_press_t", v), 100)
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):  # noqa: N802
        if self._drag_offset is not None and event.buttons() & Qt.MouseButton.LeftButton:
            target = event.globalPosition().toPoint() - self._drag_offset
            self._move_clamped(target)
            self._moved = True
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton and self._pressed_at is not None:
            was_moved = self._moved
            start = self._pressed_at
            self._pressed_at = None
            self._drag_offset = None
            self._motion.to("press", self._press_t, 0.0,
                            lambda v: self._set_motion("_press_t", v), 260, "back")
            if not was_moved and not self.is_busy():
                dist = (event.globalPosition().toPoint() - start).manhattanLength()
                if dist <= 8:
                    self.clicked.emit()
        super().mouseReleaseEvent(event)

    def contextMenuEvent(self, event):  # noqa: N802
        # 兜底入口：触控板两指点按、键盘菜单键等
        if not self.is_busy():
            self._show_menu(event.globalPosition().toPoint())
            event.accept()

    def _show_menu(self, pos: QPoint) -> None:
        """弹出右键菜单（exec 为模态，防止重入）。"""
        if self._menu_open or self.is_busy():
            return
        self._menu_open = True
        try:
            menu = self._build_menu()
            menu.exec(pos)
        finally:
            self._menu_open = False

    def _build_menu(self) -> QMenu:
        menu = QMenu(self)
        self._style_menu(menu)
        act_recap = QAction("框选翻译", menu)
        act_live = QAction("隐藏实时翻译窗口" if self._live_visible
                           else "实时翻译窗口", menu)
        act_settings = QAction("设置…", menu)
        act_quit = QAction("退出", menu)
        # triggered(bool) 带参信号 → 用 lambda 忽略参数再转发
        act_recap.triggered.connect(lambda _c=False: self.clicked.emit())
        act_live.triggered.connect(lambda _c=False: self.live_toggle_requested.emit())
        act_settings.triggered.connect(lambda _c=False: self.settings_requested.emit())
        act_quit.triggered.connect(lambda _c=False: self.exit_requested.emit())
        menu.addAction(act_recap)
        menu.addAction(act_live)
        menu.addSeparator()
        menu.addAction(act_settings)
        menu.addSeparator()
        menu.addAction(act_quit)
        return menu

    def set_live_visible(self, visible: bool) -> None:
        """记录实时窗口是否显示（决定右键菜单文案）。"""
        self._live_visible = bool(visible)

    @staticmethod
    def _style_menu(menu: QMenu) -> None:
        """深色圆角菜单（转发到设计系统，保持与其它窗口一致）。"""
        d.style_menu(menu)

    # ------------------------------------------------------------------ 配置
    def apply_config(self, cfg) -> None:
        """按配置调整尺寸与不透明度。"""
        size = int(cfg.get("ui.ball_size", self.SIZE) or self.SIZE)
        opacity = int(cfg.get("ui.ball_opacity", 100) or 100)
        self.set_ball_size(size)
        self.setWindowOpacity(max(0.2, min(1.0, opacity / 100.0)))

    def set_ball_size(self, size: int) -> None:
        self._size = int(size)
        self.setFixedSize(self._size, self._size)
        self.update()

    def _move_clamped(self, target: QPoint) -> None:
        """限制在主屏虚拟桌面范围内，避免拖出导致无法框选。"""
        vgeo = QGuiApplication.primaryScreen().availableVirtualGeometry()
        x = max(vgeo.left() + 4, min(target.x(), vgeo.right() - self.width() - 4))
        y = max(vgeo.top() + 4, min(target.y(), vgeo.bottom() - self.height() - 4))
        self.move(x, y)

    # ------------------------------------------------------------------ 绘制
    def paintEvent(self, _event):  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        center = QPointF(self.width() / 2.0, self.height() / 2.0)
        scale = 1.0 - 0.06*self._press_t + 0.035*self._settle_t
        p.translate(center)
        p.scale(scale, scale)
        p.translate(-center)
        r = self._size / 2.0 - 2.5
        if not self.is_busy():
            r += 1.2 * self._hover_t                     # 平滑放大
        if self.is_busy():
            self._paint_busy(p, center, r)
        else:
            self._paint_idle(p, center, r)
        p.end()

    def _paint_ball_base(self, p: QPainter, center: QPointF, r: float,
                         warm: float) -> None:
        """柔和单层悬浮按钮，圆角方形避免厚重玻璃装饰。"""
        rect = QRectF(center.x() - r, center.y() - r, 2 * r, 2 * r)
        radius = r*(0.70 + 0.22*self._shape_t + 0.08*min(1.0, warm))
        if glass.active():
            # 外轮廓变形只缩放已有材质，不能在每个高刷帧重建位移场。
            texture = glass.surface(self, QRectF(0,0,self.width(),self.height()), self.width()*.35, primary=True)
            p.save()
            p.setClipPath(d.rounded_path(rect, radius))
            glass.paint_surface(p, self, rect, radius, primary=True, pixmap=texture)
            p.restore()
        else:
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(d.mix(d.ACTION, d.ACTION_HI, min(1.0, warm)))
            p.drawRoundedRect(rect, radius, radius)

    def _paint_idle(self, p: QPainter, center: QPointF, r: float) -> None:
        self._paint_ball_base(p, center, r, self._hover_t)
        p.setFont(d.font(max(10.0, self._size * 0.44), d.W_SEMI, tight=True))
        p.setPen(d.ON_ACTION)
        p.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "译")
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(d.SIGNAL)
        p.drawEllipse(QPointF(self.width()*0.77, self.height()*0.24),
                      self._size*.055, self._size*.055)

    def _paint_busy(self, p: QPainter, center: QPointF, r: float) -> None:
        self._paint_ball_base(p, center, r, 0.0)
        # 细弧：笔画细、留白多，比粗进度环更克制
        pen = QPen(d.SIGNAL, 1.8)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        p.setPen(pen)
        p.setBrush(Qt.BrushStyle.NoBrush)
        rr = r - 5.0
        arc = QRectF(center.x() - rr, center.y() - rr, 2 * rr, 2 * rr)
        p.drawArc(arc, int(self._angle * 16), int(230 * 16))

        p.setFont(d.font(max(8.0, self._size * 0.16), d.W_MED, wide=True))
        p.setPen(d.ON_ACTION)
        p.drawText(self.rect().adjusted(0, 1, 0, 0),
                   Qt.AlignmentFlag.AlignCenter, self._busy_text or "…")
