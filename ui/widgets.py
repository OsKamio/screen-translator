# -*- coding: utf-8 -*-
"""可复用控件：细线图标按钮、eyebrow 标签、卡片容器。

统一保证：hover / pressed 有平滑反馈、笔画粗细一致、颜色只来自设计系统。
"""
from __future__ import annotations

import math

from PySide6.QtCore import QPointF, QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import (
    QColor, QCursor, QFontMetrics, QPainter, QPen, QTextBlockFormat,
    QTextCharFormat, QTextCursor, QTextDocument,
)
from PySide6.QtWidgets import (
    QLabel, QSizePolicy, QVBoxLayout, QWidget,
)

from . import design as d
from .motion import Driver
from . import glass


class _HoverMixin:
    """给自绘控件提供 hover / press 的平滑插值。"""

    def _init_hover(self, base: float = 0.0) -> None:
        self._hover_t = base
        self._press_t = 0.0
        self._motion = Driver(self)

    def _animate_to(self, attr: str, target: float, duration: int = d.DUR_FAST) -> None:
        self._motion.to(attr, getattr(self, attr), target,
                        lambda value: self._set_anim_value(attr, value), duration,
                        "back" if attr == "_press_t" and target == 0 else "out")

    def _set_anim_value(self, attr: str, value) -> None:
        setattr(self, attr, float(value))
        self.update()


class IconButton(QWidget, _HoverMixin):
    """极细线图标按钮（自绘，不用系统按钮外观）。"""

    clicked = Signal()

    def __init__(self, icon: str, *, size: int = 26, icon_size: int = 14,
                 tone: str = "muted", parent: QWidget | None = None):
        super().__init__(parent)
        self._init_hover()
        self._icon = icon
        self._icon_size = icon_size
        self._tone = tone
        self._pressed = False
        self.setFixedSize(size, size)
        self.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.setAttribute(Qt.WidgetAttribute.WA_Hover, True)

    def set_tone(self, tone: str) -> None:
        self._tone = tone
        self.update()

    def _icon_color(self) -> QColor:
        if self._tone == "danger":
            base, hi = d.TEXT_2, d.ERROR
        elif self._tone == "accent":
            base, hi = d.ACCENT, d.ACCENT_HI
        else:
            base, hi = d.TEXT_3, d.TEXT_HI
        return d.mix(base, hi, self._hover_t)

    def enterEvent(self, event):  # noqa: N802
        self._animate_to("_hover_t", 1.0)
        super().enterEvent(event)

    def leaveEvent(self, event):  # noqa: N802
        self._pressed = False
        self._animate_to("_hover_t", 0.0)
        super().leaveEvent(event)

    def mousePressEvent(self, event):  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            self._pressed = True
            self._animate_to("_press_t", 1.0, 100)
            self.update()

    def mouseReleaseEvent(self, event):  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton and self._pressed:
            self._pressed = False
            self._animate_to("_press_t", 0.0, 220)
            self.update()
            if self.rect().contains(event.position().toPoint()):
                self.clicked.emit()

    def paintEvent(self, _event):  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(self.rect())
        p.translate(rect.center())
        scale = 1.0 + 0.035*self._hover_t - 0.075*self._press_t
        p.scale(scale, scale)
        p.translate(-rect.center())

        # hover 时的极淡底色（不是生硬跳变）
        if self._hover_t > 0.01:
            bg = QColor(d.INK_500)
            bg.setAlpha(int(150 * self._hover_t))
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(bg)
            p.drawRoundedRect(rect.adjusted(1.0, 1.0, -1.0, -1.0), d.R_SM, d.R_SM)

        d.paint_icon(p, d.icon_rect(self.rect(), self._icon_size),
                     self._icon, self._icon_color(),
                     width=1.35 if self._pressed else 1.25)
        p.end()


class IconMark(QWidget):
    """仅显示一个细线图标（拖动把手等装饰用途，不接收鼠标）。"""

    def __init__(self, icon: str, *, size: int = 14, tone: str = "muted",
                 parent: QWidget | None = None):
        super().__init__(parent)
        self._icon = icon
        self._size = size
        self._tone = tone
        self.setFixedSize(size + 6, size + 6)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)

    def paintEvent(self, _event):  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        color = d.TEXT_3 if self._tone == "muted" else d.TEXT_2
        d.paint_icon(p, d.icon_rect(self.rect(), self._size), self._icon,
                     color, width=1.25)
        p.end()


class SettingsCard(QWidget):
    """设置分组卡片：外层壳 + 内芯 + eyebrow 标题 + 琥珀锚点短线。

    自绘而非 QGroupBox，才能做出与其它窗口一致的层次与发丝边。
    """

    # 标题区留白与表单字段约束全部取自 design 的"设置窗口排版节奏"：
    # 标题与首行内容之间必须留够 —— 中文标题（F_CAPTION）字形几乎填满字高，
    # 只差 1px 时视觉上就是"两行字糊在一起"（用户截图，2026-09-20）。
    LABEL_W = 104
    FIELD_MAX_W = 360

    def __init__(self, title: str, parent: QWidget | None = None):
        super().__init__(parent)
        self._title = title
        outer = QVBoxLayout(self)
        outer.setContentsMargins(d.SET_CARD_PAD_X, self.content_top(),
                                 d.SET_CARD_PAD_X, d.SET_CARD_PAD_BOTTOM)
        outer.setSpacing(0)
        self._outer = outer

    # ---------------------------------------------------------- 标题几何
    @staticmethod
    def title_height() -> float:
        """标题行高 —— 布局留白与 paintEvent 绘制共用同一个值，不可能对不上。"""
        return float(QFontMetrics(d.font(d.F_H1, d.W_SEMI)).height())

    @classmethod
    def content_top(cls) -> int:
        """内容区第一行距离卡片顶部的距离（标题上边距 + 标题高 + 间隙）。"""
        return int(d.SET_CARD_PAD_TOP + cls.title_height() + d.SET_TITLE_GAP)

    def body(self) -> QVBoxLayout:
        """返回用于放内容的垂直布局。"""
        return self._outer

    def paintEvent(self, _event):  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        inner = d.paint_card(p, rect, radius=d.R_LG, shell=d.INK_800,
                             core=d.INK_700, pad=1.5, shadow=True)
        d.paint_grain(p, inner, d.R_LG - 1.5, opacity=0.22)

        p.setFont(d.font(d.F_H1, d.W_SEMI))
        title_h = self.title_height()
        top = inner.top() + d.SET_CARD_PAD_TOP
        pad_x = d.SET_CARD_PAD_X
        p.setPen(d.TEXT_HI)
        p.drawText(QRectF(inner.left() + pad_x, top,
                          max(0.0, inner.width() - pad_x * 2), title_h),
                   Qt.AlignLeft | Qt.AlignVCenter, self._title)
        p.end()


class HintLabel(QWidget):
    """多行说明文字：自绘，行距与高度都受控（替代 QLabel 当说明文字用）。

    为什么不用 QLabel —— 三个坑，都在本机真实字体下复现过：
    * QSS **不支持** ``line-height``，QLabel 根本没有调行距的手段；
    * Microsoft YaHei UI 12px 时 ``fm.lineSpacing == fm.height == 15``、``leading == 0``，
      相邻行之间零空隙 → 中文上下笔画黏连，看着就是"字相互遮挡"；
    * 布局给的高度按 QLabel 的 heightForWidth 算，会小于真实所需（「关于」页曾少 7px），
      末行被直接裁掉。

    这里改用 QTextDocument：显式 ``QTextBlockFormat.setLineHeight`` 设行距，
    高度一律取自同一份文档的布局结果，行距与高度不可能再对不上。
    支持富文本（``<b>`` / ``<br>``，与原来的 QLabel 用法保持一致）。
    """

    _HUGE = 1_000_000        # 测"不换行自然宽度"用的宽度
    # QTextBlockFormat::LineHeightTypes —— FixedHeight = 2（不是 4，4 是 LineDistanceHeight，
    # 含义是"在字体行高之上再加这么多像素"，会把行距撑爆）
    _FIXED_HEIGHT = 2

    def __init__(self, text: str = "", *, size: float = d.F_SMALL,
                 color: QColor | None = None, line_height: float | None = None,
                 parent: QWidget | None = None):
        super().__init__(parent)
        self._size = size
        self._color_token = next((name for name in ("TEXT_3", "TEXT_2", "TEXT", "OK", "ERROR")
                                  if color is not None and color is getattr(d, name)), "TEXT_3")
        self._color = QColor(color) if color is not None else QColor(d.TEXT_3)
        self._text = ""

        self.setFont(d.font(size))
        # 行距 = max(设计 token, 字体自身行距 + 1px)：
        # 只加呼吸、绝不压缩字体 —— 若取比字体行距还小的值，带 descender 的英文/下划线
        # 仍会贴到下一行（本机字体 F_SMALL 的自然行距是 19px，比 token 18 还大）。
        want = float(line_height) if line_height else (
            d.LH_SMALL if size <= d.F_SMALL else d.LH_BODY)
        self._lh = max(want, float(QFontMetrics(self.font()).lineSpacing()) + 1.0)

        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Minimum)
        self._doc = QTextDocument(self)
        self._doc.setDocumentMargin(0)
        self._doc.setDefaultFont(self.font())
        self.setText(text)

    # ------------------------------------------------------------ 内容
    def setText(self, text: str) -> None:  # noqa: N802
        self._text = text or ""
        doc = self._doc
        doc.setDefaultFont(self.font())
        if _is_rich(self._text):
            doc.setHtml(self._text)
        else:
            doc.setPlainText(self._text)
        self._style_doc()
        if self.width() > 0:
            self._sync_min_height(self.width())
        self.updateGeometry()
        self.update()

    def text(self) -> str:
        return self._text

    def line_height(self) -> float:
        """当前行距（px）—— 自检脚本用它判断行距是否真的生效。"""
        return self._lh

    def set_color(self, color: QColor) -> None:
        """设定文字色（自绘不走 QSS，用这个替代 ``setStyleSheet("color: …")``）。"""
        self._color_token = next((name for name in ("TEXT_3", "TEXT_2", "TEXT", "OK", "ERROR")
                                  if color is getattr(d, name)), self._color_token)
        self._color = QColor(color)
        self._style_doc()
        self.update()

    def refresh_theme(self) -> None:
        self._color = QColor(getattr(d, self._color_token))
        self._style_doc()
        self.update()

    def _style_doc(self) -> None:
        """统一行距 + 文字色；``mergeCharFormat`` 只改颜色，保留 ``<b>`` 等格式。"""
        doc = self._doc
        cur = QTextCursor(doc)
        cur.select(QTextCursor.SelectionType.Document)
        cf = QTextCharFormat()
        cf.setForeground(self._color)
        cur.mergeCharFormat(cf)

        block = doc.begin()
        while block.isValid():
            fmt = block.blockFormat()
            fmt.setLineHeight(self._lh, self._FIXED_HEIGHT)
            QTextCursor(block).setBlockFormat(fmt)
            block = block.next()

    # ------------------------------------------------------------ 尺寸
    def hasHeightForWidth(self) -> bool:  # noqa: N802
        return True

    def _doc_height(self, width: int) -> int:
        self._doc.setTextWidth(float(max(1, width)))
        # 至少一行高：空文本的 label 也占住一行，内容出现/清空时布局不跳
        return int(math.ceil(max(self._lh, self._doc.size().height())))

    def _natural_width(self) -> int:
        # textWidth = -1 表示不换行；此时 idealWidth() 才是真实的单行宽度
        # （size().width() 会直接回显 textWidth，用 _HUGE 量出来就是 _HUGE）
        self._doc.setTextWidth(-1)
        return int(math.ceil(self._doc.idealWidth()))

    def heightForWidth(self, width: int) -> int:  # noqa: N802
        return self._doc_height(width)

    def sizeHint(self):  # noqa: N802
        natural = self._natural_width()
        cap = self.maximumWidth()
        width = natural if cap >= self._HUGE else min(natural, cap)
        return QSize(max(1, width), self._doc_height(width))

    def minimumSizeHint(self):  # noqa: N802
        w = self.width()
        if w > 0:
            return QSize(120, self._doc_height(w))
        return QSize(120, int(self._lh))

    def _sync_min_height(self, width: int) -> None:
        """显式设高度下限。

        必须用 ``setMinimumHeight``（= ``minimumSize()``），**不能**只靠
        ``minimumSizeHint()``：布局压缩时取的是 item 的 ``minimumSize()``，
        minimumSizeHint 只是 sizeHint 的下限，压不住。本机实测容器会把
        hint 压到 53px（正好一行），多行文字就叠在一起。
        """
        need = self._doc_height(width)
        if self.minimumHeight() != need:
            self.setMinimumHeight(need)

    def resizeEvent(self, event):  # noqa: N802
        super().resizeEvent(event)
        # 宽度变了 → 需要的高度变了 → 一并修正高度下限，父布局会重新分配
        if event.oldSize().width() != event.size().width():
            self._sync_min_height(event.size().width())
            self.updateGeometry()

    # ------------------------------------------------------------ 绘制
    def paintEvent(self, _event):  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        self._doc.setTextWidth(float(max(1, self.width())))
        self._doc.drawContents(p, QRectF(0, 0, self.width(), self.height()))
        p.end()


def _is_rich(text: str) -> bool:
    """判断是否含 HTML 标签（``<b>`` / ``<br>`` 这类说明文案会用到）。"""
    try:
        return bool(Qt.mightBeRichText(text))
    except AttributeError:  # 个别绑定版本没有该静态方法
        return ("<" in text and ">" in text)


class TextButton(QWidget, _HoverMixin):
    """自绘文字按钮：hover / pressed 颜色平滑插值（替代系统按钮外观）。"""

    clicked = Signal()

    PAD_X = 15
    PAD_Y = 8

    def __init__(self, text: str, *, variant: str = "ghost",
                 parent: QWidget | None = None):
        super().__init__(parent)
        self._init_hover()
        self._text = text
        self._variant = variant
        self._pressed = False
        self._enabled = True
        self._feedback_t = 0.0
        self._feedback_text = None
        self._feedback_timer = QTimer(self)
        self._feedback_timer.setSingleShot(True)
        self._feedback_timer.timeout.connect(self._restore_feedback)
        self.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.setAttribute(Qt.WidgetAttribute.WA_Hover, True)
        self.setFont(d.font(d.F_BODY, d.W_MED))

    def feedback(self, text="已复制") -> None:
        if self._feedback_text is None:
            self._feedback_text = self._text
            self.setMinimumWidth(self.sizeHint().width())
        self.set_text(text)
        self._feedback_timer.start(1200)
        self._motion.pulse("feedback", lambda v: self._set_anim_value("_feedback_t", v))

    def _restore_feedback(self) -> None:
        if self._feedback_text is not None:
            self.set_text(self._feedback_text)
            self._feedback_text = None

    def hideEvent(self, event):  # noqa: N802
        self._feedback_timer.stop()
        self._restore_feedback()
        self._press_t = self._hover_t = self._feedback_t = 0.0
        super().hideEvent(event)

    # ---- 变体配色 ----
    def _colors(self) -> tuple[QColor, QColor, QColor]:
        """(常态底色, hover 底色, 文字色)"""
        if self._variant == "primary":
            return d.ACTION, d.ACTION_HI, d.ON_ACTION
        if self._variant == "quiet":
            return QColor(0, 0, 0, 0), d.INK_500, d.TEXT_2
        return (d.INK_600, d.INK_500, d.TEXT)

    def set_enabled(self, enabled: bool) -> None:
        self._enabled = bool(enabled)
        self.setCursor(QCursor(Qt.CursorShape.PointingHandCursor if enabled
                               else Qt.CursorShape.ArrowCursor))
        self.update()

    def set_text(self, text: str) -> None:
        self._text = text
        self.updateGeometry()
        self.update()

    def sizeHint(self):  # noqa: N802
        fm = self.fontMetrics()
        from PySide6.QtCore import QSize
        return QSize(fm.horizontalAdvance(self._text) + self.PAD_X * 2,
                     fm.height() + self.PAD_Y * 2)

    def minimumSizeHint(self):  # noqa: N802
        return self.sizeHint()

    # ---- 交互 ----
    def enterEvent(self, event):  # noqa: N802
        if self._enabled:
            self._animate_to("_hover_t", 1.0)
        super().enterEvent(event)

    def leaveEvent(self, event):  # noqa: N802
        self._pressed = False
        self._animate_to("_hover_t", 0.0)
        super().leaveEvent(event)

    def mousePressEvent(self, event):  # noqa: N802
        if self._enabled and event.button() == Qt.MouseButton.LeftButton:
            self._pressed = True
            self._animate_to("_press_t", 1.0, d.DUR_FAST)
            self.update()

    def mouseReleaseEvent(self, event):  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton and self._pressed:
            self._pressed = False
            self._animate_to("_press_t", 0.0, d.DUR_BASE)
            if self._enabled and self.rect().contains(event.position().toPoint()):
                self.clicked.emit()

    def paintEvent(self, _event):  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        p.translate(rect.center())
        scale = 1.0 + 0.008*self._hover_t - 0.035*self._press_t + 0.018*self._feedback_t
        p.scale(scale, scale)
        p.translate(-rect.center())
        base, hover, fg = self._colors()

        if not self._enabled:
            bg = QColor(d.INK_600)
            bg.setAlpha(90)
            fg = d.TEXT_3
        else:
            # pressed 时向更深处插值，营造“按下”的物理感
            bg = d.mix(base, hover, min(1.0, self._hover_t))
            if self._variant == "primary" and self._press_t > 0:
                bg = d.mix(bg, d.ACTION, self._press_t * 0.8)

        if glass.active():
            glass.paint_surface(p, self, rect, rect.height()/2, primary=self._variant == 'primary',
                                opacity=1.0 if self._enabled else .55)
        elif bg.alpha() > 0:
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(bg)
            p.drawRoundedRect(rect, rect.height()/2, rect.height()/2)

        if self._variant == "ghost" and not glass.active():
            border = QColor(d.LINE)
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.setPen(QPen(border, 1.0))
            p.drawRoundedRect(rect, rect.height()/2, rect.height()/2)

        p.setFont(self.font())
        p.setPen(fg)
        p.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, self._text)
        p.end()


class PillLabel(QLabel):
    """eyebrow 风格的小标签：极小字号 + 宽字距 + 可选状态点。"""

    def __init__(self, text: str = "", *, tone: str = "neutral", dot: bool = False,
                 parent: QWidget | None = None):
        super().__init__(text, parent)
        self._tone = tone
        self._dot = dot
        self.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)
        self.setFont(d.font(d.F_MICRO, d.W_SEMI, wide=True))
        self._restyle()

    def set_tone(self, tone: str, *, dot: bool = False) -> None:
        self._tone = tone
        self._dot = dot
        self._restyle()

    def _restyle(self) -> None:
        color = {
            "neutral": d.TEXT_2,
            "ok": d.OK,
            "error": d.ERROR,
            "accent": d.TEXT_HI,
            "info": d.INFO,
        }.get(self._tone, d.TEXT_2)
        bg = QColor(d.INK_600)
        border = QColor(d.LINE)
        pad_left = 18 if self._dot else 10
        self.setStyleSheet(
            f"QLabel {{ color: {color.name()};"
            f" background: rgba({bg.red()},{bg.green()},{bg.blue()},{bg.alpha()});"
            f" border: 1px solid rgba({border.red()},{border.green()},{border.blue()},"
            f"{border.alpha()});"
            f" border-radius: 12px;"
            f" padding: 5px 12px 5px {pad_left}px; }}"
        )

    def paintEvent(self, event):  # noqa: N802
        super().paintEvent(event)
        if not self._dot:
            return
        color = {
            "neutral": d.TEXT_3, "ok": d.OK, "error": d.ERROR,
            "accent": d.SIGNAL, "info": d.INFO,
        }.get(self._tone, d.TEXT_3)
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(color)
        p.drawEllipse(QRectF(8.0, self.height() / 2 - 2.0, 4.0, 4.0))
        p.end()


def token_qss() -> str:
    """通用 QSS：给仍使用标准控件的区域统一深色外观。"""
    return f"""
    QLineEdit, QPlainTextEdit, QSpinBox, QDoubleSpinBox, QComboBox {{
        background: {d.hexs(d.INK_600)};
        border: 1px solid {d.hexs(d.LINE)};
        border-radius: {int(d.R_SM)}px;
        padding: 6px 9px;
        color: {d.hexs(d.TEXT)};
        selection-background-color: {d.hexs(d.ACCENT, 0.35)};
        selection-color: {d.hexs(d.TEXT_HI)};
    }}
    QLineEdit:hover, QSpinBox:hover, QDoubleSpinBox:hover, QComboBox:hover,
    QPlainTextEdit:hover {{ border: 1px solid {d.hexs(d.LINE_STRONG)}; }}
    QLineEdit:focus, QPlainTextEdit:focus, QSpinBox:focus,
    QDoubleSpinBox:focus, QComboBox:focus {{
        border: 1px solid {d.hexs(d.ACCENT, 0.75)};
    }}
    """
