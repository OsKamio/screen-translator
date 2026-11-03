# -*- coding: utf-8 -*-
"""实时翻译窗口：桌面上的半透明取景框，自动翻译框内文字。

交互：
- 拖动窗口内部任意位置移动；拖边缘/四角缩放
- 顶部小条：≡ 拖动提示、状态文字、⟳ 立即刷新、✕ 隐藏窗口
- 右键菜单：暂停/继续、立即刷新、设置、隐藏、退出

关键：窗口会被设置成“不被屏幕捕获 API 截到”（WDA_EXCLUDEFROMCAPTURE），
否则它自己的译文会被再次识别，形成自我循环。
"""
from __future__ import annotations

import ctypes
import logging

from PySide6.QtCore import QPoint, QPointF, QRect, QRectF, Qt, Signal
from PySide6.QtGui import (
    QColor, QCursor, QFontMetrics, QGuiApplication, QLinearGradient, QPainter,
    QPainterPath, QPen,
)
from PySide6.QtWidgets import QMenu, QWidget

from . import design as d
from . import theme
from .motion import Driver

log = logging.getLogger(__name__)

WDA_NONE = 0x00000000
WDA_EXCLUDEFROMCAPTURE = 0x00000011

EDGE_LEFT, EDGE_RIGHT, EDGE_TOP, EDGE_BOTTOM = 1, 2, 4, 8


def set_capture_excluded(widget: QWidget, enabled: bool = True) -> bool:
    """让窗口内容不被屏幕捕获（Windows 10 2004+）。返回是否设置成功。

    ``enabled=False`` 用于**撤销**排除（WDA_NONE）—— 远程桌面 / 投屏 / 共享屏幕
    本质上都是屏幕捕获，被排除的窗口在那些画面里**完全不出现**，
    用户会以为"窗口没了/点按钮没反应"（2026-09-21 用户反馈）。
    排除与否由 ``live.capture_excluded`` 配置决定。
    """
    try:
        hwnd = int(widget.winId())
        fn = ctypes.windll.user32.SetWindowDisplayAffinity
        fn.argtypes = [ctypes.c_void_p, ctypes.c_uint]
        fn.restype = ctypes.c_bool
        affinity = WDA_EXCLUDEFROMCAPTURE if enabled else WDA_NONE
        return bool(fn(ctypes.c_void_p(hwnd), ctypes.c_uint(affinity)))
    except Exception as exc:  # noqa: BLE001
        log.warning("设置抓屏排除失败：%s", exc)
        return False


class LiveWindow(QWidget):
    """实时翻译取景框窗口。"""

    source_frame_toggled = Signal(bool)
    source_select_requested = Signal()
    overlay_mode_requested = Signal()
    capture_mode_changed = Signal()
    closed = Signal()              # 隐藏窗口
    quit_requested = Signal()
    settings_requested = Signal()
    refresh_requested = Signal()   # 立即刷新
    pause_toggled = Signal(bool)
    geometry_changed = Signal(QRect)
    font_size_changed = Signal(int)   # 顶部管理栏调整字号

    MIN_W, MIN_H = 260, 110
    BAR_H = 40
    RESIZE_MARGIN = 8
    KEEP_VISIBLE = 60

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent, Qt.WindowType.FramelessWindowHint
                         | Qt.WindowType.WindowStaysOnTopHint
                         | Qt.WindowType.Tool)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setMinimumSize(self.MIN_W, self.MIN_H)
        self.setMouseTracking(True)
        self.setWindowTitle("实时翻译")

        self._font_size = 22
        self._show_original = False
        self._show_stats = False
        self._show_source_frame = True
        self._bg_opacity = 55
        self._paused = False
        self._excluded: bool | None = None
        self._want_excluded = True     # 是否要求"不被截屏捕获"（配置 live.capture_excluded）
        self._suppress = False         # 抓屏避让中：内容置空（见 suppress_content）

        self._translated = ""
        self._original = ""
        self._status = ""
        self._error = ""
        self._hint = "把窗口拖到需要翻译的区域上方"
        self._busy = False

        self._action = None            # ("move"/"resize"/"btn", 数据)
        self._press_global = QPoint()
        self._start_geom = QRect()
        self._hover_btn: str | None = None
        self._appeared = False
        self._motion = Driver(self)
        self._hover_levels = {}
        self._arrival_t = 0.0
        self._refresh_angle = 0.0
        self._scroll = 0               # 译文滚动偏移（滚轮查看上下文）
        self._max_scroll = 0
        self._extent_key = None
        self._extent_total = 0

        self.resize(560, 170)

    # ------------------------------------------------------------------ 配置
    def apply_config(self, cfg) -> None:
        self._font_size = int(cfg.get("live.font_size", 22) or 22)
        self._show_original = bool(cfg.get("live.show_original", False))
        self._show_stats = bool(cfg.get("live.show_stats", False))
        self._show_source_frame = bool(cfg.get("live.show_source_frame", True))
        self._bg_opacity = int(cfg.get("live.bg_opacity", 55) or 0)
        want_excluded = bool(cfg.get("live.capture_excluded", True))
        if want_excluded != self._want_excluded:
            self._want_excluded = want_excluded
            self._apply_capture_exclusion()   # 改设置后立刻生效（窗口可能已显示）

        if bool(cfg.get("live.remember_geometry", True)):
            geom = cfg.get("live.geometry", None)
            if isinstance(geom, (list, tuple)) and len(geom) == 4:
                rect = QRect(int(geom[0]), int(geom[1]), int(geom[2]), int(geom[3]))
                self.setGeometry(self._clamp_to_screen(rect))
        self.update()

    def apply_click_through(self, enabled: bool) -> None:
        """点击穿透（开启后鼠标操作会落到下层窗口，只能用悬浮球菜单关闭）。

        注意：只在状态真正变化时才调用 setWindowFlag —— 它会销毁并重建原生窗口，
        每次调用都会让窗口闪一下（曾导致实时窗口看起来“出不来”）。
        """
        enabled = bool(enabled)
        current = bool(self.windowFlags() & Qt.WindowType.WindowTransparentForInput)
        if current == enabled:
            return
        was_visible = self.isVisible()
        self._excluded = None  # 窗口标志改变后，原生窗口的抓屏排除需重新设置
        self.setWindowFlag(Qt.WindowType.WindowTransparentForInput, enabled)
        if was_visible:
            self.show()
            self._apply_capture_exclusion()

    # ------------------------------------------------------------------ 状态
    def set_result(self, translated: str, original: str,
                   status: str = "", busy: bool = False) -> None:
        changed = translated != self._translated
        if changed and translated and not busy:
            self._motion.pulse("arrival", lambda v: self._set_motion("_arrival_t", v), up=120, down=430)
        self._translated = translated
        self._original = original
        self._status = status
        self._busy = busy
        self._error = ""
        self._hint = "" if (translated or busy) else "未识别到文字，等待画面变化…"
        if changed:
            # 新内容：还在顶部就继续从头看；用户正在翻上下文则保持位置
            total, visible = self._content_extent()
            if self._scroll == 0:
                pass
            else:
                self._scroll = min(self._scroll, self._max_scroll)
        self.update()

    def set_error(self, message: str) -> None:
        """错误态：语义色显示原因，且不再混入“未识别到文字”提示。"""
        self._error = message.strip()
        self._status = ""
        self._busy = False
        self.update()

    def set_busy(self, busy: bool) -> None:
        self._busy = busy
        self.update()

    def set_status(self, text: str) -> None:
        self._error = ""          # 新状态覆盖旧的错误提示
        self._status = text
        self.update(QRect(0, 0, self.width(), self.BAR_H+3))

    def set_paused(self, paused: bool) -> None:
        self._paused = paused
        self._status = "已暂停" if paused else ""
        self.update(QRect(0, 0, self.width(), self.BAR_H+3))

    def is_paused(self) -> bool:
        return self._paused

    def capture_excluded(self) -> bool | None:
        """窗口是否已成功设置“不被截屏”（None = 还没尝试）。"""
        return self._excluded

    def window_geometry_for_capture(self) -> QRect:
        return self.geometry()

    # ------------------------------------------------------------------ 事件
    def showEvent(self, event):  # noqa: N802
        super().showEvent(event)
        self._apply_capture_exclusion()
        # 实时取景窗口始终保持透明度和位置稳定；只动画工具栏绘制。

    def closeEvent(self, event):  # noqa: N802
        self.closed.emit()  # Alt+F4 / 系统关闭同样停止后台，不只隐藏 QWidget。
        super().closeEvent(event)

    def leaveEvent(self, event):  # noqa: N802
        if self._hover_btn is not None:
            self._set_hover_button(None)
            self.setToolTip("")
            self.update(QRect(0, 0, self.width(), self.BAR_H+3))
        super().leaveEvent(event)

    def _set_motion(self, attr, value):
        setattr(self, attr, float(value))
        self.update(QRect(0, 0, self.width(), self.BAR_H+3))

    def _set_hover_button(self, button):
        self._hover_btn = button
        for name in self._bar_buttons():
            current = self._hover_levels.get(name, 0.0)
            def setter(value, name=name):
                self._hover_levels[name] = float(value)
                self.update(self._bar_buttons()[name])
            self._motion.to("hover:"+name, current, float(name == button), setter, 150)

    def hideEvent(self, event):  # noqa: N802
        self._hover_btn = None
        self._hover_levels.clear()
        self._arrival_t = self._refresh_angle = 0.0
        super().hideEvent(event)

    def _apply_capture_exclusion(self) -> None:
        if not self.isVisible():
            return
        if not self._want_excluded:
            # 用户要求对截图/录屏/投屏可见：撤销排除，
            # 并把 _excluded 置 False → 引擎改用抓屏避让（否则会截到自己）
            if self._excluded is not False:
                set_capture_excluded(self, False)
                log.info("实时窗口抓屏排除：已关闭（窗口会出现在截图/录屏/投屏里）")
            self._excluded = False
            self.capture_mode_changed.emit()
            return
        if self._excluded is True:
            # 已经是排除状态就别再调 SetWindowDisplayAffinity 了：
            # 每次 show 都重设会触发窗口重新合成，是"闪"的一部分来源
            return
        ok = set_capture_excluded(self, True)
        if ok != self._excluded:
            log.info("实时窗口抓屏排除：%s", "已启用" if ok else "不可用（将用隐藏避让）")
        self._excluded = ok
        self.capture_mode_changed.emit()

    def suppress_content(self, on: bool) -> None:
        """抓屏避让：把窗口**内容**整体置空，但窗口本身不 hide。

        抓屏只需拍到窗口下面的真实画面，用户也不必看到窗口整体消失再重建。
        调用后请立刻 ``repaint()``，让这一帧真正落地（否则抓屏可能抓到旧内容）。
        """
        on = bool(on)
        if on == self._suppress:
            return
        self._suppress = on
        self.update()

    # ---- 按钮 / 边缘判定 ----
    def _bar_buttons(self) -> dict[str, QRect]:
        """顶部管理栏右侧的按钮（从右往左：关闭、刷新、放大字号、缩小字号、黄框开关）。"""
        h = self.BAR_H
        right = self.width()
        return {
            "close": QRect(right - h, 0, h, h),
            "refresh": QRect(right - 2 * h, 0, h, h),
            "font_inc": QRect(right - 3 * h, 0, h, h),
            "font_dec": QRect(right - 4 * h, 0, h, h),
            "source_frame": QRect(right - 5 * h, 0, h, h),
        }

    def _update_source_frame_tooltip(self) -> None:
        tips = {"source_frame": "隐藏取景黄框（继续翻译）" if self._show_source_frame else "显示取景黄框",
                "font_dec": "减小译文字号", "font_inc": "增大译文字号",
                "refresh": "立即重新识别", "close": "隐藏实时翻译窗口"}
        self.setToolTip(tips.get(self._hover_btn, ""))

    def _button_at(self, pos: QPoint) -> str | None:
        for name, rect in self._bar_buttons().items():
            if rect.contains(pos):
                return name
        return None

    def _hit_edge(self, pos: QPoint) -> int:
        m = self.RESIZE_MARGIN
        w, h = self.width(), self.height()
        edge = 0
        if pos.x() <= m:
            edge |= EDGE_LEFT
        elif pos.x() >= w - m:
            edge |= EDGE_RIGHT
        if pos.y() <= m:
            edge |= EDGE_TOP
        elif pos.y() >= h - m:
            edge |= EDGE_BOTTOM
        return edge

    @staticmethod
    def _cursor_for_edge(edge: int) -> Qt.CursorShape:
        if edge in (EDGE_LEFT, EDGE_RIGHT):
            return Qt.CursorShape.SizeHorCursor
        if edge in (EDGE_TOP, EDGE_BOTTOM):
            return Qt.CursorShape.SizeVerCursor
        if edge in (EDGE_LEFT | EDGE_TOP, EDGE_RIGHT | EDGE_BOTTOM):
            return Qt.CursorShape.SizeFDiagCursor
        if edge in (EDGE_RIGHT | EDGE_TOP, EDGE_LEFT | EDGE_BOTTOM):
            return Qt.CursorShape.SizeBDiagCursor
        return Qt.CursorShape.ArrowCursor

    def mousePressEvent(self, event):  # noqa: N802
        if event.button() != Qt.MouseButton.LeftButton:
            super().mousePressEvent(event)
            return
        pos = event.position().toPoint()
        self._press_global = event.globalPosition().toPoint()
        self._start_geom = QRect(self.geometry())

        btns = self._bar_buttons()
        if btns["close"].contains(pos):
            self._action = ("btn", "close")
        elif btns["refresh"].contains(pos):
            self._action = ("btn", "refresh")
        elif btns["font_inc"].contains(pos):
            self._action = ("btn", "font_inc")
        elif btns["font_dec"].contains(pos):
            self._action = ("btn", "font_dec")
        elif btns["source_frame"].contains(pos):
            self._action = ("btn", "source_frame")
        else:
            edge = self._hit_edge(pos)
            self._action = ("resize", edge) if edge else ("move", 0)

    def wheelEvent(self, event):  # noqa: N802
        """滚轮查看上下文（内容超出可视区时）。"""
        delta = event.angleDelta().y()
        if not delta:
            super().wheelEvent(event)
            return
        # 按整行步进，避免滚动后停在半行上
        line_h = QFontMetrics(d.font(self._font_size, d.W_MED)).lineSpacing()
        step = max(20, line_h)
        notches = max(1, abs(delta) // 120)
        self._scroll_by(-step * notches if delta > 0 else step * notches)
        event.accept()

    def _scroll_by(self, dy: int) -> None:
        self._content_extent()                 # 刷新 _max_scroll
        line_h = max(1, QFontMetrics(d.font(self._font_size, d.W_MED)).lineSpacing())
        # 吸附到行网格：滚动后总是停在整行上，不出现半行残影
        snapped = int(round((self._scroll + dy) / float(line_h))) * line_h
        new = max(0, min(self._max_scroll, snapped))
        if new != self._scroll:
            self._scroll = new
            self.update()

    def _adjust_font(self, delta: int) -> None:
        new = max(12, min(40, self._font_size + delta))
        if new == self._font_size:
            return
        self._font_size = new
        self._scroll = 0
        self.update()
        self.font_size_changed.emit(new)

    def mouseMoveEvent(self, event):  # noqa: N802
        pos = event.position().toPoint()
        if self._action is None:
            edge = self._hit_edge(pos)
            self.setCursor(QCursor(self._cursor_for_edge(edge)))
            # 跟踪工具条按钮 hover（用于极淡的 hover 底）
            hover = None if edge else self._button_at(pos)
            if hover != self._hover_btn:
                self._set_hover_button(hover)
                self._update_source_frame_tooltip()
                self.update(QRect(0, 0, self.width(), self.BAR_H+3))
            super().mouseMoveEvent(event)
            return

        if not (event.buttons() & Qt.MouseButton.LeftButton):
            super().mouseMoveEvent(event)
            return

        delta = event.globalPosition().toPoint() - self._press_global
        kind, data = self._action
        if kind == "move":
            self.setGeometry(self._clamp_to_screen(self._start_geom.translated(delta),
                                                   keep_visible=True))
        elif kind == "resize":
            self.setGeometry(self._resized(self._start_geom, data, delta))
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):  # noqa: N802
        if self._action is not None and event.button() == Qt.MouseButton.LeftButton:
            kind, data = self._action
            self._action = None
            if kind == "btn":
                if self._button_at(event.position().toPoint()) != data:
                    self.update()
                    return
                if data == "close":
                    self.hide()
                    self.closed.emit()
                elif data == "refresh":
                    self._refresh_angle = 0.0
                    self._motion.to("refresh", 0.0, 360.0,
                                    lambda v: self._set_motion("_refresh_angle", v), 420)
                    self.refresh_requested.emit()
                elif data == "font_inc":
                    self._adjust_font(2)
                elif data == "font_dec":
                    self._adjust_font(-2)
                elif data == "source_frame":
                    self._show_source_frame = not self._show_source_frame
                    self._update_source_frame_tooltip()
                    self.update()
                    self.source_frame_toggled.emit(self._show_source_frame)
                return
            if self.geometry() != self._start_geom:
                self.geometry_changed.emit(self.geometry())
        super().mouseReleaseEvent(event)

    def contextMenuEvent(self, event):  # noqa: N802
        menu = QMenu(self)
        d.style_menu(menu)
        act_pause = menu.addAction("继续翻译" if self._paused else "暂停翻译")
        act_refresh = menu.addAction("立即刷新")
        act_source = menu.addAction("重新选择取景区域（译文分开显示）")
        act_overlay = menu.addAction("恢复覆盖翻译（尝试直接抓取下层窗口）")
        menu.addSeparator()
        act_settings = menu.addAction("设置…")
        act_hide = menu.addAction("隐藏实时窗口")
        menu.addSeparator()
        act_quit = menu.addAction("退出程序")
        act_pause.triggered.connect(lambda _c=False: self.pause_toggled.emit(not self._paused))
        act_refresh.triggered.connect(lambda _c=False: self.refresh_requested.emit())
        act_source.triggered.connect(lambda _c=False: self.source_select_requested.emit())
        act_overlay.triggered.connect(lambda _c=False: self.overlay_mode_requested.emit())
        act_settings.triggered.connect(lambda _c=False: self.settings_requested.emit())
        act_hide.triggered.connect(lambda _c=False: (self.hide(), self.closed.emit()))
        act_quit.triggered.connect(lambda _c=False: self.quit_requested.emit())
        menu.exec(event.globalPosition().toPoint())

    # ------------------------------------------------------------------ 几何
    def _resized(self, start: QRect, edge: int, delta: QPoint) -> QRect:
        g = QRect(start)
        if edge & EDGE_LEFT:
            g.setLeft(min(g.left() + delta.x(), g.right() - self.MIN_W))
        if edge & EDGE_RIGHT:
            g.setRight(max(g.right() + delta.x(), g.left() + self.MIN_W))
        if edge & EDGE_TOP:
            g.setTop(min(g.top() + delta.y(), g.bottom() - self.MIN_H))
        if edge & EDGE_BOTTOM:
            g.setBottom(max(g.bottom() + delta.y(), g.top() + self.MIN_H))
        return self._clamp_to_screen(g)

    def _clamp_to_screen(self, rect: QRect, keep_visible: bool = False) -> QRect:
        """限制在屏幕可用区域内；keep_visible 时只要求留一部分可见。"""
        vg = QGuiApplication.primaryScreen().availableGeometry()
        g = QRect(rect)
        if keep_visible:
            k = self.KEEP_VISIBLE
            if g.width() >= vg.width():
                g.moveLeft(vg.left())
            else:
                g.moveLeft(max(vg.left() + k - g.width(), min(g.left(), vg.right() - k)))
            if g.height() >= vg.height():
                g.moveTop(vg.top())
            else:
                g.moveTop(max(vg.top() + k - g.height(), min(g.top(), vg.bottom() - k)))
            return g
        # 缩放时保证整窗在屏内
        if g.width() > vg.width():
            g.setWidth(vg.width())
        if g.height() > vg.height():
            g.setHeight(vg.height())
        if g.left() < vg.left():
            g.moveLeft(vg.left())
        if g.top() < vg.top():
            g.moveTop(vg.top())
        if g.right() > vg.right():
            g.moveRight(vg.right())
        if g.bottom() > vg.bottom():
            g.moveBottom(vg.bottom())
        return g

    # ------------------------------------------------------------------ 绘制
    def _bg_card(self, p: QPainter) -> QRectF:
        """双层半透明卡片（背景不透明度可配），返回内芯矩形。"""
        rect = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        ratio = max(0, min(100, self._bg_opacity)) / 100.0
        shell = QColor(d.INK_800)
        shell.setAlpha(int(255 * ratio))
        core = QColor(d.INK_700)
        core.setAlpha(int(255 * ratio))
        inner = d.paint_card(p, rect, radius=d.R_WINDOW, shell=shell, core=core,
                             pad=1.5, shadow=True, highlight=ratio > 0.15)
        if ratio > 0.15:
            d.paint_grain(p, inner, d.R_LG - 1.5, opacity=0.3)
        return inner

    def _paint_bar_button(self, p: QPainter, rect: QRect, icon: str,
                          *, tone: str) -> None:
        hover_t = self._hover_levels.get(icon, 0.0)
        hovered = hover_t > 0.01
        if hovered:
            p.setPen(Qt.PenStyle.NoPen)
            bg = QColor(d.INK_500)
            bg.setAlpha(round(170*hover_t))
            p.setBrush(bg)
            p.drawRoundedRect(QRectF(rect).adjusted(3, 3, -3, -3), 14, 14)
        if hovered:
            if icon in ("font_inc", "font_dec"):
                color = d.TEXT_HI
            elif tone == "danger":
                color = d.ERROR
            else:
                color = d.TEXT_HI
        else:
            color = d.TEXT_2          # 常态也要看得清（这几个都是可用功能）
        if hovered:
            color = d.mix(d.TEXT_2, color, hover_t)
        if icon == "source_frame":
            color = d.SOURCE_FRAME if self._show_source_frame else d.TEXT_3
            if self._show_source_frame:
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(QColor(204, 161, 67, 24))
                p.drawRoundedRect(QRectF(rect).adjusted(3, 3, -3, -3), d.R_XS, d.R_XS)
            icon_rect = QRectF(rect).adjusted(6, 6, -6, -6)
            d.paint_icon(p, icon_rect, "source_frame", color)
            if not self._show_source_frame:
                p.setPen(QPen(color, 1.25))
                p.drawLine(icon_rect.topLeft(), icon_rect.bottomRight())
            return
        if icon in ("font_inc", "font_dec"):
            # 字号按钮：“A” + 自绘的 +/− 符号。
            # 不用字体里的 "+"/"−"：它们的字宽、线粗、垂直位置都不同，
            # 放在一起会显得一个粗一个细、一个高一个低（像没对齐）。
            font = d.font(d.F_CAPTION, d.W_SEMI, tight=True)
            p.setFont(font)
            fm = p.fontMetrics()
            a_w = float(fm.horizontalAdvance("A"))
            sign = 7.0                     # 符号尺寸（两个按钮共用）
            gap = 2.5
            total = a_w + gap + sign
            x = rect.center().x() - total / 2.0
            baseline = rect.center().y() + (fm.ascent() - fm.descent()) / 2.0

            p.setPen(color)
            p.drawText(QPointF(x, baseline + 0.5), "A")

            pen = QPen(color, 1.7)
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            p.setPen(pen)
            sx = x + a_w + gap + sign / 2.0
            sy = rect.center().y() + 1.0   # 与 A 的视觉中心对齐
            p.drawLine(QPointF(sx - sign / 2.0, sy), QPointF(sx + sign / 2.0, sy))
            if icon == "font_inc":
                p.drawLine(QPointF(sx, sy - sign / 2.0), QPointF(sx, sy + sign / 2.0))
            return
        p.save()
        p.translate(QPointF(rect.center()))
        p.scale(1 + 0.06*hover_t, 1 + 0.06*hover_t)
        if icon == "refresh":
            p.rotate(self._refresh_angle)
        p.translate(-QPointF(rect.center()))
        d.paint_icon(p, d.icon_rect(rect, 16), icon, color, width=1.25)
        p.restore()

    # ---- 内容尺寸与滚动 ----
    def _text_body(self, inner: QRectF | None = None) -> QRect:
        """译文可视区矩形。"""
        if inner is None:
            inner = QRectF(self.rect()).adjusted(1.5, 1.5, -1.5, -1.5)
        top = int(inner.top() + self.BAR_H + 2*d.S2)
        bottom = int(inner.bottom() - d.S3)
        if self._show_original and self._original:
            bottom -= min(48, max(22, self._font_size))
        return QRect(int(inner.left() + d.S5), top,
                     max(0, int(inner.width()) - 2 * d.S5), max(0, bottom - top))

    def _content_extent(self, inner: QRectF | None = None) -> tuple[int, int]:
        """返回 (内容总高, 可视高) 并刷新 _max_scroll。"""
        body = self._text_body(inner)
        visible = max(1, body.height())
        text = self._translated or ""
        if not text:
            self._max_scroll = 0
            return 0, visible
        key = (text, self._font_size, body.width(), self.devicePixelRatioF())
        if key != self._extent_key:
            fm = QFontMetrics(d.font(self._font_size, d.W_MED))
            rect = fm.boundingRect(QRect(0, 0, max(16, body.width() - 8), 100000),
                                  int(Qt.TextFlag.TextWordWrap), text)
            self._extent_key, self._extent_total = key, max(1, rect.height())
        total = self._extent_total
        self._max_scroll = max(0, total - visible)
        self._scroll = max(0, min(self._max_scroll, self._scroll))
        return total, visible

    def _paint_scrollbar(self, p: QPainter, body: QRect,
                         total: int, visible: int) -> None:
        """内容超出时在右侧显示滚动指示（要有存在感，否则用户不知道能滚）。"""
        if self._max_scroll <= 0 or total <= 0:
            return
        frac = min(1.0, visible / float(total))
        handle_h = max(24.0, body.height() * frac)
        travel = max(1.0, body.height() - handle_h)
        y = body.top() + (self._scroll / float(self._max_scroll)) * travel
        p.setPen(Qt.PenStyle.NoPen)
        bar = QColor(d.TEXT_3)
        bar.setAlpha(235)
        p.setBrush(bar)
        p.drawRoundedRect(QRectF(body.right() - 3.0, y, 4.0, handle_h), 2.0, 2.0)

    def paintEvent(self, _event):  # noqa: N802
        if self._suppress:
            # 抓屏避让：整体置空（全透明）——抓屏就能拍到底下真正要翻译的内容。
            # 刻意**不用 hide()/show()**：那会重建/重新合成窗口，实测窗口消失
            # 平均 68ms、最长 249ms（4~15 帧），用户看到的就是"一闪一闪"。
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()
        inner = self._bg_card(p)

        # ---- 顶部工具条：一条发丝分隔线 + 细线图标（不再用实心色块）----
        bar_y = inner.top() + self.BAR_H
        p.setPen(QPen(QColor(d.LINE), 1.0))
        p.drawLine(QPointF(inner.left() + 1, bar_y), QPointF(inner.right() - 1, bar_y))

        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(d.ERROR if self._error else d.TEXT_3 if self._paused else d.SIGNAL)
        p.drawEllipse(QPointF(inner.left()+15, inner.top()+self.BAR_H/2), 3.0, 3.0)

        text_rect = QRect(int(inner.left() + 28), int(inner.top()),
                          max(0, int(inner.width()) - 28 - len(self._bar_buttons()) * self.BAR_H),
                          self.BAR_H)
        p.setFont(d.font(d.F_CAPTION, d.W_MED, wide=True))
        if self._error:
            p.setPen(d.ERROR)
            bar_text = f"翻译失败：{self._error.splitlines()[0][:60]}"
        elif self._status:
            p.setPen(d.TEXT_2)
            bar_text = self._status
        else:
            # 空闲时不重复中间那句引导语，保持顶部干净
            p.setPen(d.TEXT_3)
            bar_text = "实时翻译"
        bar_text = p.fontMetrics().elidedText(bar_text, Qt.TextElideMode.ElideRight, text_rect.width())
        p.drawText(text_rect, Qt.AlignVCenter | Qt.AlignLeft, bar_text)

        btns = self._bar_buttons()
        dock = QRectF(btns["source_frame"].united(btns["close"])).adjusted(1, 3, -3, -3)
        dock_color = QColor(d.INK_600)
        dock_color.setAlpha(round(150*max(0, min(100, self._bg_opacity))/100))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(dock_color)
        p.drawRoundedRect(dock, dock.height()/2, dock.height()/2)
        self._paint_bar_button(p, btns["source_frame"], "source_frame", tone="muted")
        self._paint_bar_button(p, btns["font_dec"], "font_dec", tone="muted")
        self._paint_bar_button(p, btns["font_inc"], "font_inc", tone="muted")
        self._paint_bar_button(p, btns["refresh"], "refresh", tone="muted")
        self._paint_bar_button(p, btns["close"], "close", tone="danger")

        # 新译文仅在工具栏分隔线上提示，不淡出或移动正文。
        if self._arrival_t > 0.001:
            accent = QColor(d.SIGNAL)
            accent.setAlpha(round(150*self._arrival_t))
            p.setPen(QPen(accent, 1.5))
            p.drawLine(QPointF(inner.left()+12, bar_y), QPointF(inner.left()+68, bar_y))

        # ---- 译文（主层级，内容超出时可滚动查看）----
        body = self._text_body(inner)
        if _event.rect().bottom() < body.top():
            p.end()
            return  # 工具栏反馈不反复排版长译文。
        total, visible = self._content_extent(inner)
        text = self._translated or ""

        if text:
            flags = (Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop
                     | Qt.TextFlag.TextWordWrap)
            p.save()
            p.setClipRect(body)
            avail_w = body.width() - 8
            draw_rect = QRect(body.left(), body.top() - self._scroll,
                              max(16, avail_w), max(total, body.height()))
            p.setFont(d.font(self._font_size, d.W_MED))
            # 深色描边保证任意背景上可读（不用纯黑，避免脏）
            if self._bg_opacity < 25:
                shadow = QColor("#FFFFFF" if d.CURRENT_THEME == "light" else "#152018")
                p.setPen(shadow)
                for dx, dy in ((-1, 0), (1, 0), (0, -1), (0, 1)):
                    p.drawText(draw_rect.translated(dx, dy), flags, text)
            p.setPen(d.TEXT_HI)
            p.drawText(draw_rect, flags, text)
            p.restore()
            self._paint_scrollbar(p, body, total, visible)
        elif not self._busy:
            p.setFont(d.font(d.F_BODY, d.W_REG))
            p.setPen(d.TEXT_3)
            msg = "等待画面变化…" if self._error else (self._hint or "等待画面变化…")
            p.drawText(body, Qt.AlignmentFlag.AlignCenter
                       | Qt.TextFlag.TextWordWrap, msg)

        # ---- 原文（次级）----
        if self._show_original and self._original:
            org_h = min(48, max(22, self._font_size))
            org_rect = QRect(int(inner.left() + d.S3),
                             int(inner.bottom() - org_h - d.S3),
                             max(0, int(inner.width()) - 2 * d.S3), org_h)
            p.setFont(d.font(max(10.0, self._font_size - 9), d.W_REG))
            p.setPen(d.TEXT_2)
            p.drawText(org_rect,
                       Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop
                       | Qt.TextFlag.TextWordWrap, self._original)

        p.end()
