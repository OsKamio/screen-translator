# -*- coding: utf-8 -*-
"""结果面板：展示识别出的原文与译文，支持复制与再次框选。

视觉：浅色 / 深色平面卡片、鼠尾草绿强调，内容绘制变换与错峰入场。
排版：eyebrow 小标签 → 译文（主层级）→ 原文（次级）；行距放宽，左侧对齐。
"""
from __future__ import annotations

from PySide6.QtCore import (
    QPoint, QRect, QRectF, Qt, Signal,
)
from PySide6.QtGui import (
    QColor, QGuiApplication, QPainter, QPen, QTextBlockFormat, QTextCursor,
)
from PySide6.QtWidgets import (
    QHBoxLayout, QLabel, QSizePolicy, QTextBrowser, QVBoxLayout, QWidget,
)

from . import design as d
from .motion import Driver, RevealEffect
from .widgets import IconButton, IconMark, PillLabel, TextButton
from core import translate as core_translate

def browser_qss() -> str:
    return f"""
QTextBrowser {{
    background: transparent;
    border: none;
    selection-background-color: {d.hexs(d.ACCENT, 0.34)};
    selection-color: {d.hexs(d.TEXT_HI)};
}}
QTextBrowser QScrollBar:vertical {{
    background: transparent; width: 7px; margin: 2px 0;
}}
QTextBrowser QScrollBar::handle:vertical {{
    background: {d.hexs(d.INK_400)};
    border-radius: 3px; min-height: 28px;
}}
QTextBrowser QScrollBar::handle:vertical:hover {{
    background: {d.hexs(d.TEXT_3)};
}}
QTextBrowser QScrollBar::add-line:vertical,
QTextBrowser QScrollBar::sub-line:vertical {{ height: 0; }}
"""


class ResultWindow(QWidget):
    """无边框置顶卡片：原文 / 译文 / 操作按钮。"""

    closed = Signal()
    recapture_requested = Signal()

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent, Qt.WindowType.FramelessWindowHint
                         | Qt.WindowType.WindowStaysOnTopHint
                         | Qt.WindowType.Tool)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)

        self._original = ""
        self._translated = ""
        self._drag_offset: QPoint | None = None
        self._dragging = False
        self._font_size = 17
        self._show_original = True
        self._max_ratio = 0.85
        self._appeared = False

        root = QVBoxLayout(self)
        # 留白按设计系统加倍
        root.setContentsMargins(d.S6, d.S5, d.S6, d.S5)
        root.setSpacing(d.S3)
        self._layout = root

        # ---- 头部：拖动提示 + 状态标签 + 关闭 ----
        header = QHBoxLayout()
        header.setSpacing(d.S2)
        self._grip = IconMark("grip", size=18, tone="normal")
        header.addWidget(self._grip)
        self._pill = PillLabel("识别中", tone="neutral", dot=True)
        header.addWidget(self._pill)
        header.addStretch(1)
        self._close_btn = IconButton("close", size=26, icon_size=13, tone="muted")
        self._close_btn.setToolTip("关闭结果")
        self._close_btn.clicked.connect(self._on_close)
        header.addWidget(self._close_btn)
        root.addLayout(header)

        # ---- 原文（次级层级）----
        self._orig_caption = QLabel("原文")
        self._orig_caption.setFont(d.font(d.F_MICRO, d.W_SEMI, wide=True))
        self._orig_caption.setStyleSheet(f"QLabel {{ color: {d.hexs(d.TEXT_2)}; }}")


        self._orig_view = QTextBrowser()
        self._orig_view.setReadOnly(True)
        self._orig_view.setOpenLinks(False)
        self._orig_view.viewport().setAutoFillBackground(False)
        self._orig_view.document().setDocumentMargin(0)   # 去掉默认边距，高度才准确


        # ---- 译文（主层级）----
        self._trans_caption = QLabel("译文")
        self._trans_caption.setFont(d.font(d.F_MICRO, d.W_SEMI, wide=True))
        self._trans_caption.setStyleSheet(f"QLabel {{ color: {d.hexs(d.TEXT_2)}; }}")
        root.addWidget(self._trans_caption)

        self._trans_view = QTextBrowser()
        self._trans_view.setReadOnly(True)
        self._trans_view.setOpenLinks(False)
        self._trans_view.viewport().setAutoFillBackground(False)
        self._trans_view.document().setDocumentMargin(0)
        root.addWidget(self._trans_view)
        root.addWidget(self._orig_caption)
        root.addWidget(self._orig_view)

        # ---- 底部操作 ----
        footer = QHBoxLayout()
        footer.setSpacing(d.S2)
        self._btn_copy_trans = TextButton("复制译文", variant="primary")
        self._btn_copy_orig = TextButton("复制原文", variant="ghost")
        self._btn_again = TextButton("重新框选", variant="quiet")
        self._btn_copy_trans.clicked.connect(lambda: self._copy_with_feedback(self._translated, self._btn_copy_trans))
        self._btn_copy_orig.clicked.connect(lambda: self._copy_with_feedback(self._original, self._btn_copy_orig))
        self._btn_again.clicked.connect(self.recapture_requested.emit)
        footer.addWidget(self._btn_copy_trans)
        footer.addWidget(self._btn_copy_orig)
        footer.addStretch(1)
        footer.addWidget(self._btn_again)
        root.addLayout(footer)

        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Preferred)
        self.apply_config_style()
        self._motion = Driver(self)
        self._reveal_effects = [(RevealEffect(w), delay) for w, delay in
                                ((self._pill, 0), (self._trans_caption, 25),
                                 (self._trans_view, 25), (self._orig_caption, 60),
                                 (self._orig_view, 60), (self._btn_copy_trans, 95),
                                 (self._btn_copy_orig, 95), (self._btn_again, 95))]

    # ------------------------------------------------------------------ 样式
    def apply_config_style(self) -> None:
        """按当前字号/显示设置刷新文本区域样式。"""
        self._orig_view.setStyleSheet(
            browser_qss()
            + f"QTextBrowser {{ color: {d.hexs(d.TEXT_2)};"
              f" font-family: '{d.FONT_CJK}';"
              f" font-size: {int(d.F_SMALL)}px; }}")
        self._trans_view.setStyleSheet(
            browser_qss()
            + f"QTextBrowser {{ color: {d.hexs(d.TEXT_HI)};"
              f" font-family: '{d.FONT_CJK}';"
              f" font-size: {int(self._font_size)}px; }}")

    def refresh_theme(self) -> None:
        self.apply_config_style()
        self._orig_caption.setStyleSheet(f"color: {d.hexs(d.TEXT_2)};")
        self._trans_caption.setStyleSheet(f"color: {d.hexs(d.TEXT_2)};")
        self._pill._restyle()
        if self._pill._tone == "error":
            self._trans_view.setStyleSheet(self._trans_qss(d.hexs(d.ERROR)))
        self.update()

    def _trans_qss(self, color: str | None = None) -> str:
        """兼容旧接口：错误态用珊瑚色。"""
        return (browser_qss()
                + f"QTextBrowser {{ color: {color or d.hexs(d.TEXT_HI)};"
                  f" font-family: '{d.FONT_CJK}';"
                  f" font-size: {int(self._font_size)}px; }}")

    def apply_config(self, cfg) -> None:
        self._font_size = int(cfg.get("ui.result_font_size", 17) or 17)
        self._show_original = bool(cfg.get("ui.show_original", True))
        ratio = int(cfg.get("ui.result_max_height_ratio", 85) or 85)
        self._max_ratio = max(0.4, min(0.95, ratio / 100.0))
        self.apply_config_style()

    @staticmethod
    def _copy(text: str) -> None:
        if text:
            QGuiApplication.clipboard().setText(text)

    def _copy_with_feedback(self, text, button) -> None:
        if text:
            self._copy(text)
            button.feedback("已复制")

    def _on_close(self) -> None:
        self.hide()
        self.closed.emit()

    @staticmethod
    def _set_rich_text(browser: QTextBrowser, text: str) -> None:
        """写入文本并设置舒适行距。

        用 Qt 原生 block format 控制行距，而不是 HTML 的 line-height —
        后者在 Qt 富文本引擎里解析不可靠（会算出错误高度、留下大片空白）。
        """
        browser.setPlainText(text)
        cursor = QTextCursor(browser.document())
        cursor.select(QTextCursor.SelectionType.Document)
        fmt = QTextBlockFormat()
        # heightType 需要 int：1 = ProportionalHeight（按百分比行距）
        fmt.setLineHeight(150.0, 1)
        cursor.mergeBlockFormat(fmt)

    # ------------------------------------------------------------------ 展示
    def show_result(self, original: str, translated: str,
                    src_lang: str, note: str = "") -> None:
        self._original = original
        self._translated = translated

        lang_name = core_translate.lang_name(src_lang)
        if note:
            self._pill.setText(f"{lang_name} · {note}")
            self._pill.set_tone("accent", dot=True)
        elif translated == original:
            self._pill.setText(f"已是{lang_name}")
            self._pill.set_tone("neutral", dot=True)
        else:
            # 只用一套强调色系（琥珀），避免多种彩色标签造成的杂乱
            self._pill.setText(f"{lang_name} → 译文")
            self._pill.set_tone("accent", dot=True)

        if self._show_original:
            self._orig_caption.show()
            self._orig_view.show()
        else:
            self._orig_caption.hide()
            self._orig_view.hide()
        self._set_rich_text(self._orig_view, original)

        self._trans_caption.show()
        self._trans_view.show()
        self._trans_view.setStyleSheet(self._trans_qss())
        self._set_rich_text(self._trans_view, translated)

        self._btn_copy_trans.set_enabled(bool(translated))
        self._btn_copy_orig.set_enabled(bool(original))
        self.update()

    def show_error(self, message: str) -> None:
        self._original = ""
        self._translated = ""
        self._pill.setText("出错")
        self._pill.set_tone("error", dot=True)

        self._orig_caption.hide()
        self._orig_view.hide()
        self._trans_caption.hide()
        self._trans_view.show()
        self._trans_view.setStyleSheet(self._trans_qss(d.hexs(d.ERROR)))
        self._set_rich_text(self._trans_view, message)

        self._btn_copy_trans.set_enabled(False)
        self._btn_copy_orig.set_enabled(False)
        self.update()

    def reset_style(self) -> None:
        self._trans_view.setStyleSheet(self._trans_qss())

    # ------------------------------------------------------------------ 动画
    def showEvent(self, event):  # noqa: N802
        super().showEvent(event)
        self._motion.timeline("reveal", [
            (effect.set_progress, 0.0, 1.0, 270, delay, "out")
            for effect, delay in self._reveal_effects
        ])

    # ------------------------------------------------------------------ 拖动
    def mousePressEvent(self, event):  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_offset = (event.globalPosition().toPoint()
                                 - self.frameGeometry().topLeft())
            self._dragging = True
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):  # noqa: N802
        if self._dragging and event.buttons() & Qt.MouseButton.LeftButton:
            target = event.globalPosition().toPoint() - self._drag_offset
            self.move(self._drag_clamp(target))
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            self._dragging = False
            self._drag_offset = None
        super().mouseReleaseEvent(event)

    def _drag_clamp(self, target: QPoint) -> QPoint:
        vg = QGuiApplication.primaryScreen().availableGeometry()
        keep = 56
        x, y = target.x(), target.y()
        if self.width() >= vg.width():
            x = vg.left()
        else:
            x = max(vg.left() + keep - self.width(), min(x, vg.right() - keep))
        if self.height() >= vg.height():
            y = vg.top()
        else:
            y = max(vg.top() + keep - self.height(), min(y, vg.bottom() - keep))
        return QPoint(x, y)

    # ------------------------------------------------------------------ 尺寸
    def _content_width(self) -> int:
        """文本区可用宽度（窗口宽 - 左右内边距 - 滚动条余量）。"""
        return max(80, self.width() - 2 * d.S6 - 12)

    def _doc_height(self, browser: QTextBrowser, max_h: int) -> int:
        """按渲染后的文档高度计算文本框应有的高度。"""
        doc = browser.document()
        doc.setTextWidth(self._content_width())
        return max(0, min(max_h, int(doc.size().height()) + 2))

    def _fit_browsers(self, trans_max: int = 4000) -> None:
        """让文本框贴合内容：短内容不留空白，超长内容由滚动条接管。

        注意：这里用 isHidden() 而不是 isVisible() —— 父窗口尚未 show 时
        isVisible() 恒为 False，会导致高度没被设置（曾造成原文区异常高）。
        """
        if self._show_original and not self._orig_view.isHidden():
            self._orig_view.setFixedHeight(self._doc_height(self._orig_view, 160))
        if not self._trans_view.isHidden():
            self._trans_view.setFixedHeight(
                max(34, self._doc_height(self._trans_view, trans_max)))

    # ------------------------------------------------------------------ 布局
    def place_near(self, anchor: QRect, work_geom: QRect) -> None:
        """放到选区下方（放不下则上方），并保证完全在屏内。"""
        margin = d.S4
        avail_w = work_geom.width() - 2 * margin
        self.setMinimumHeight(0)
        self.setMaximumHeight(16777215)
        w = max(380, min(avail_w, anchor.width() + 180))
        if avail_w <= 0:
            w = 420
        w = min(w, avail_w)
        self.setFixedWidth(w)

        max_h = max(160, int(work_geom.height() * self._max_ratio))

        # 第一遍：文本框按内容定高 → 窗口高度贴合内容
        self.layout().activate()
        self._fit_browsers()
        self.layout().activate()
        self.adjustSize()
        h = self.height()

        # 第二遍：内容超过屏幕预算时，压缩译文区（滚动条生效），不裁切
        if h > max_h:
            over = h - max_h
            self._trans_view.setFixedHeight(
                max(44, self._trans_view.height() - over))
            self.layout().activate()
            self.adjustSize()
            h = self.height()

        x = anchor.center().x() - w // 2
        below_y = anchor.bottom() + d.S4
        if h <= (work_geom.bottom() - margin) - below_y:
            y = below_y
        else:
            above_y = anchor.top() - d.S4 - h
            if above_y >= work_geom.top() + margin:
                y = above_y
            else:
                y = work_geom.top() + margin

        rect = QRect(x, y, w, h)
        self.move(d.fit_in(rect, work_geom, margin).topLeft())

    # ------------------------------------------------------------------ 绘制
    def paintEvent(self, event):  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)

        # 双层卡片：外壳 + 内芯 + 顶部内高光
        inner = d.paint_card(p, rect, radius=d.R_WINDOW,
                             shell=d.INK_800, core=d.INK_700,
                             glow=True, shadow=True)
        # 极淡噪点（打破数字平面感）
        d.paint_grain(p, inner, d.R_LG - 2, opacity=0.35)
        p.end()
        super().paintEvent(event)
