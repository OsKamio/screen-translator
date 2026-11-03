# -*- coding: utf-8 -*-
"""
设计系统：浅色 / 深色 / 跟随 Windows / 液态玻璃主题。

参考视频的暖纸白 / 墨黑胶囊 / 橙色信号点，搭配轻浮层与柔和形态变化。
集中管理颜色、逻辑像素字号、间距、图标和绘制工具；
主题切换原地更新颜色对象，不重建悬浮窗口。
"""
from __future__ import annotations

import math
from functools import lru_cache

from PySide6.QtCore import (
    QEasingCurve, QPoint, QPointF, QPropertyAnimation, QRect, QRectF, Qt,
)
from PySide6.QtGui import (
    QColor, QFont, QGuiApplication, QImage, QLinearGradient, QPainter,
    QPainterPath, QPen, QPixmap, QRadialGradient, QPalette,
)

# ==========================================================================
# 1. Tokens
# ==========================================================================
# ---- 可变颜色对象：实际色值由下面的 PALETTES 统一应用 ----
INK_1000 = QColor("#080A0C")   # 最深的窗底
INK_900 = QColor("#0D1013")    # 窗口背景
INK_800 = QColor("#12171B")    # 卡片外壳
INK_700 = QColor("#171D22")    # 卡片内芯
INK_600 = QColor("#1E252B")    # 输入框 / 悬浮层
INK_500 = QColor("#252D35")    # hover 抬升
INK_400 = QColor("#2E3740")    # 边界区域

TEXT_HI = QColor("#F0F3F6")    # 主要文字
TEXT = QColor("#D3DAE1")       # 正文
TEXT_2 = QColor("#98A3AF")     # 次要文字
TEXT_3 = QColor("#6B7480")     # 极弱文字 / 占位
LINE = QColor(255, 255, 255, 18)      # 发丝边（≈7%）
LINE_STRONG = QColor(255, 255, 255, 30)
HILIGHT = QColor(255, 255, 255, 20)   # 顶部内高光

ACCENT = QColor("#E0A85C")     # 暖琥珀（唯一强调色）
ACCENT_HI = QColor("#F3CB8C")  # hover / 高光
ACCENT_DEEP = QColor("#A9762F")
ACCENT_SOFT = QColor(224, 168, 92, 34)
ON_ACCENT = QColor("#1A1206")  # 压在琥珀上的深字

OK = QColor("#6FBF9A")         # 柔和薄荷（成功）
INFO = QColor("#7FA8C9")       # 柔和雾蓝（中性提示）
WARN = QColor("#D9A65C")       # 琥珀（警告，与强调同族）
ERROR = QColor("#D9736B")      # 柔和珊瑚（错误，不用纯红）

SHADOW = QColor(4, 6, 8, 120)  # tinted 阴影（冷色相，非纯黑）

# ---- 遮罩 / 选区（框选界面）----
OVERLAY_DIM = QColor(6, 8, 11, 150)
SELECT_LINE = QColor(ACCENT_HI)
SELECT_FILL = QColor(224, 168, 92, 30)

# 颜色对象原地更新，兼容 theme.py 引用；切换主题不重建原生悬浮窗口。
SOURCE_FRAME = QColor("#CCA143")
ACTION = QColor("#17181B")
ACTION_HI = QColor("#303135")
ON_ACTION = QColor("#FFFFFF")
SIGNAL = QColor("#F36942")
CURRENT_THEME = "light"
_THEME_MODE = "system"
PALETTES = {'light': {'INK_1000': '#E9E6DE',
           'INK_900': '#F3F1EB',
           'INK_800': '#FEFEFC',
           'INK_700': '#FEFEFC',
           'INK_600': '#F4F3EF',
           'INK_500': '#EAE8E1',
           'INK_400': '#CCC9C1',
           'TEXT_HI': '#17181B',
           'TEXT': '#333437',
           'TEXT_2': '#6C6C68',
           'TEXT_3': '#777771',
           'LINE': '#E5E3DC',
           'LINE_STRONG': '#CAC7BF',
           'HILIGHT': '#FFFFFF',
           'ACCENT': '#B64C2B',
           'ACCENT_HI': '#D25D39',
           'ACCENT_DEEP': '#923C24',
           'ACCENT_SOFT': '#F9E8DF',
           'ON_ACCENT': '#FFFFFF',
           'OK': '#50705D',
           'INFO': '#6C6C68',
           'WARN': '#946B28',
           'ERROR': '#B34B40',
           'SHADOW': '#39332B',
           'SELECT_LINE': '#F36942',
           'SELECT_FILL': '#F1A483',
           'ACTION': '#17181B',
           'ACTION_HI': '#303135',
           'ON_ACTION': '#FFFFFF',
           'SIGNAL': '#F36942'},
 'dark': {'INK_1000': '#111214',
          'INK_900': '#191A1D',
          'INK_800': '#242529',
          'INK_700': '#242529',
          'INK_600': '#2D2E32',
          'INK_500': '#303135',
          'INK_400': '#55555A',
          'TEXT_HI': '#F5F3EC',
          'TEXT': '#DEDDD7',
          'TEXT_2': '#B5B3AC',
          'TEXT_3': '#9B9993',
          'LINE': '#3A3B3F',
          'LINE_STRONG': '#54555A',
          'HILIGHT': '#45464B',
          'ACCENT': '#FFAD8B',
          'ACCENT_HI': '#FFC3A8',
          'ACCENT_DEEP': '#DD8664',
          'ACCENT_SOFT': '#48352E',
          'ON_ACCENT': '#231913',
          'OK': '#ABC2AE',
          'INFO': '#B5B3AC',
          'WARN': '#D6B77A',
          'ERROR': '#EDA49C',
          'SHADOW': '#070708',
          'SELECT_LINE': '#FFAD8B',
          'SELECT_FILL': '#F1A483',
          'ACTION': '#F3F1EB',
          'ACTION_HI': '#FFFFFF',
          'ON_ACTION': '#1B1C1F',
          'SIGNAL': '#FF8058'}}


PALETTES['glass-light'] = {**PALETTES['light'],
    'INK_900':'#E9EEF3', 'INK_800':'#EEF4FA', 'INK_700':'#EEF4FA', 'INK_600':'#F5F9FC',
    'INK_500':'#D5E2EF', 'INK_400':'#9DAFC3', 'TEXT_HI':'#163048', 'TEXT':'#28445E',
    'TEXT_2':'#485F76', 'TEXT_3':'#576C81', 'LINE':'#D3E1ED', 'LINE_STRONG':'#A1B7CB',
    'ACCENT':'#245F96', 'ACCENT_HI':'#3479B5', 'ACCENT_SOFT':'#D2E8F9',
    'ACTION':'#245F96', 'ACTION_HI':'#3479B5', 'ON_ACTION':'#FFFFFF', 'SIGNAL':'#2174B4'}
PALETTES['glass-dark'] = {**PALETTES['dark'],
    'INK_900':'#1D2733', 'INK_800':'#23394D', 'INK_700':'#23394D', 'INK_600':'#293E54',
    'INK_500':'#354E67', 'INK_400':'#5D7A98', 'TEXT_HI':'#F0F7FF', 'TEXT':'#E0EBF8',
    'TEXT_2':'#C1D1E4', 'TEXT_3':'#ACBED5', 'LINE':'#526C87', 'LINE_STRONG':'#718CA5',
    'ACCENT':'#A9D7FF', 'ACCENT_HI':'#D0E9FF', 'ACCENT_SOFT':'#2D4D6C',
    'ACTION':'#416F99', 'ACTION_HI':'#588AB7', 'ON_ACTION':'#FFFFFF', 'SIGNAL':'#9FD8FF'}


def is_glass() -> bool:
    return _THEME_MODE == 'glass'


def theme_key() -> str:
    return 'glass-'+CURRENT_THEME if is_glass() else CURRENT_THEME


def set_theme(mode: str = "system", scheme=None) -> bool:
    global CURRENT_THEME, _THEME_MODE
    previous = theme_key()
    mode = mode if mode in ("system", "light", "dark", "glass") else "system"
    if scheme is None and QGuiApplication.instance() is not None:
        scheme = QGuiApplication.styleHints().colorScheme()
    effective = ("dark" if scheme == Qt.ColorScheme.Dark else "light") if mode in ("system", "glass") else mode
    _THEME_MODE = mode
    CURRENT_THEME = effective
    changed = previous != theme_key()
    for name, value in PALETTES[theme_key()].items():
        globals()[name].setRgba(QColor(value).rgba())
    SHADOW.setAlpha(16 if effective == "light" else 35)
    SELECT_FILL.setAlpha(24)
    app = QGuiApplication.instance()
    if app is not None:
        from . import glass
        glass.refresh_preferences()
        if changed:
            glass.clear_cache()
        palette = QPalette(app.palette())
        for role, color in ((QPalette.Window, INK_900), (QPalette.WindowText, TEXT),
                            (QPalette.Base, INK_700), (QPalette.AlternateBase, INK_600),
                            (QPalette.Text, TEXT), (QPalette.Button, INK_600),
                            (QPalette.ButtonText, TEXT), (QPalette.Highlight, ACCENT),
                            (QPalette.HighlightedText, ON_ACCENT), (QPalette.ToolTipBase, INK_700),
                            (QPalette.ToolTipText, TEXT), (QPalette.PlaceholderText, TEXT_3)):
            palette.setColor(role, color)
        palette.setColor(QPalette.Disabled, QPalette.Text, TEXT_3)
        palette.setColor(QPalette.Disabled, QPalette.ButtonText, TEXT_3)
        app.setPalette(palette)
    return changed


set_theme()

# ---- 半径：外层大、内层小（同心曲线）----
R_XL = 24.0
R_LG = 20.0
R_MD = 18.0
R_SM = 12.0
R_XS = 10.0
R_WINDOW = 28.0  # 外层窗口比内部分组更圆润。

# ---- 间距刻度（相比原实现整体加倍留白）----
S1, S2, S3, S4, S5, S6, S7, S8 = 4, 8, 12, 16, 20, 24, 32, 40

# ---- 字号阶梯（逻辑 px，Qt 随屏幕 DPI 缩放）----
F_DISPLAY = 26.0
F_TITLE = 20.0
F_H1 = 16.0
F_BODY = 14.0
F_SMALL = 12.0
F_CAPTION = 12.0
F_MICRO = 11.0

# ---- 多行文字行距（px）----
# 必须显式给：真实中文字体下 fm.lineSpacing == fm.height、leading == 0，
# 说明文字相邻行之间没有任何空隙，视觉上会黏连甚至重叠（2026-09-20 用户截图）。
# 由 widgets.HintLabel 使用（自绘 QTextDocument，QLabel 无法设行距）。
# 这两个值是**下限**：实际行距取 max(下面的值, 字体自身行距 + 1px)，只加呼吸、不压缩字体。
# 取值口径：≈ 字高 × 1.45（中文舒适区间 1.4~1.5）。F_SMALL 字高 15 → 22；
# 早期用 18/20 时行间只剩 3~5px，物理像素下就是"两行字贴着"。
LH_SMALL = 22.0    # 配 F_SMALL
LH_BODY = 24.0     # 配 F_BODY

# ---- 设置窗口排版节奏（2026-09-20 排版重做）----
# 起因：控件与它下面的说明只隔 3px、说明行间只剩 5px、表单行距 12px，
# 在 DPR 1.5 的物理像素下整片文字糊在一起（用户反复反馈的"重叠"）。
# 这里是**设置窗口**的节奏，刻意不动全项目共用的 S1..S8 刻度。
SET_PAGE_PAD = 20        # 页面内边距（滚动区内容四周）
SET_CARD_SPACING = 20    # 卡片与卡片之间
SET_CARD_PAD_X = 26      # 卡片左右内边距
SET_CARD_PAD_TOP = 22    # 卡片标题上边距（标题区 = 此值 + 标题行高 + SET_TITLE_GAP）
SET_CARD_PAD_BOTTOM = 24 # 卡片底部内边距
SET_TITLE_GAP = 12       # eyebrow 标题 → 首行内容
SET_CONTROL_GAP = 8      # 控件 ↔ 它自己的说明文字（原来 3px，贴死）
SET_FORM_ROW = 16        # 表单行与行（含相邻复选框/单选项）
SET_TEST_ROW_GAP = 8     # 「测试连接」行与上方内容的额外留白
SET_GROUP_GAP = 12       # 卡片内 说明 ↔ 其下方区块（如列表）

# ---- 字重（引入 500/600 中间层次）----
W_REG = 400
W_MED = 500
W_SEMI = 600
W_BOLD = 700

# ---- 动效 ----
DUR_FAST = 140
DUR_BASE = 240
DUR_SLOW = 420


def ease_standard() -> QEasingCurve:
    c = QEasingCurve(QEasingCurve.Type.OutCubic)
    return c


def ease_emphasis() -> QEasingCurve:
    return QEasingCurve(QEasingCurve.Type.InOutQuint)


def ease_spring() -> QEasingCurve:
    """近似弹簧：先过冲再回落。"""
    return QEasingCurve(QEasingCurve.Type.OutBack)


# ==========================================================================
# 2. 字体
# ==========================================================================
# 中文优先使用微软雅黑 UI；拉丁回退 Segoe UI，等宽数字使用 Cascadia Mono。
FONT_LATIN = "Segoe UI"
FONT_CJK = "Microsoft YaHei UI"
FONT_CJK_FALLBACK = "Microsoft YaHei"
FONT_MONO = "Cascadia Mono"


@lru_cache(maxsize=256)
def font(size: float, weight: int = W_REG, *, mono: bool = False,
         tight: bool = False, wide: bool = False, italic: bool = False) -> QFont:
    """构造字体：微软雅黑 UI / Segoe UI，字号使用逻辑像素。

    tight：大字号用负字距（更紧、更有存在感）
    wide ：小标签用正字距（eyebrow 感）
    """
    f = QFont()
    if mono:
        f.setFamilies([FONT_MONO, "Consolas", FONT_CJK])
    else:
        f.setFamilies([FONT_CJK, FONT_LATIN, FONT_CJK_FALLBACK])
    f.setPixelSize(max(1, int(round(size))))
    f.setWeight(QFont.Weight(int(weight)))
    f.setItalic(italic)
    if tight:
        f.setLetterSpacing(QFont.SpacingType.PercentageSpacing, 97.0)
    elif wide:
        f.setLetterSpacing(QFont.SpacingType.PercentageSpacing, 103.0)
    return f


def mono_font(size: float, weight: int = W_REG) -> QFont:
    """等宽（耗时、计数等数字场景，避免跳动）。"""
    return font(size, weight, mono=True)


# ==========================================================================
# 3. 绘制工具
# ==========================================================================
def rounded_path(rect: QRectF, radius: float) -> QPainterPath:
    path = QPainterPath()
    path.addRoundedRect(rect, radius, radius)
    return path


def paint_shadow(p: QPainter, rect: QRectF, radius: float,
                 *, spread: int = 14, color: QColor | None = None,
                 y_offset: int = 6) -> None:
    """带色相的柔和阴影（多层叠加模拟扩散，不用纯黑）。"""
    base = color or SHADOW
    layers = 4
    for i in range(layers, 0, -1):
        alpha = int(base.alpha() * (0.16 + 0.20 * (layers - i) / layers))
        c = QColor(base)
        c.setAlpha(max(4, alpha // 2))
        grow = spread * i / layers
        r = QRectF(rect).adjusted(-grow, -grow + y_offset, grow, grow + y_offset)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(c)
        p.drawRoundedRect(r, radius + grow, radius + grow)


def paint_hairline(p: QPainter, rect: QRectF, radius: float,
                   color: QColor | None = None, width: float = 1.0) -> None:
    """1px 发丝边（代替厚重的灰色描边）。"""
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.setPen(QPen(color or LINE, width))
    p.drawRoundedRect(QRectF(rect).adjusted(0.5, 0.5, -0.5, -0.5), radius, radius)


def paint_inner_highlight(p: QPainter, rect: QRectF, radius: float,
                          strength: int = 20) -> None:
    """保留兼容入口；简洁主题不绘制玻璃高光。"""
    return


def paint_card(p: QPainter, rect: QRectF, *, radius: float = R_LG,
               shell: QColor | None = None, core: QColor | None = None,
               pad: float = 2.0, shadow: bool = True,
               highlight: bool = True, glow: bool = False) -> QRectF:
    """单层柔和表面，使用细边界与留白区分层级。"""
    from . import glass
    opacity = core.alphaF() if core is not None else 1.0
    if glass.paint_on(p, rect, radius, opacity=opacity):
        return QRectF(rect).adjusted(pad, pad, -pad, -pad)
    if shadow:
        paint_shadow(p, rect, radius, spread=8, y_offset=3)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(core or INK_700)
    p.drawRoundedRect(rect, radius, radius)
    paint_hairline(p, rect, radius, LINE)
    return QRectF(rect).adjusted(pad, pad, -pad, -pad)


def paint_accent_glow(p: QPainter, rect: QRectF, radius: float,
                      *, alpha: int = 26) -> None:
    """保留兼容入口；不绘制装饰光晕。"""
    return

_GRAIN_ATTR = "_dsh_design_grain_tile"


def _grain_tile() -> QPixmap:
    """噪点贴图：缓存在 QApplication 实例上。

    不能用模块级 lru_cache —— QPixmap 依赖 GUI 应用的图形资源，
    跨 QApplication 生命周期复用会访问已释放的资源而崩溃。
    """
    app = QGuiApplication.instance()
    if app is not None:
        cached = getattr(app, _GRAIN_ATTR, None)
        if cached is not None:
            return cached

    size = 64
    img = QImage(size, size, QImage.Format.Format_ARGB32_Premultiplied)
    img.fill(QColor(0, 0, 0, 0))
    seed = 20260101
    for y in range(size):
        for x in range(size):
            seed = (seed * 1103515245 + 12345) & 0x7FFFFFFF
            v = (seed >> 16) & 0xFF
            if v > 214:                      # 稀疏亮点，避免糊成灰雾
                img.setPixelColor(x, y, QColor(255, 255, 255, 16))
            elif v < 30:
                img.setPixelColor(x, y, QColor(0, 0, 0, 18))
    tile = QPixmap.fromImage(img)
    if app is not None:
        setattr(app, _GRAIN_ATTR, tile)
    return tile


def paint_grain(p: QPainter, rect: QRectF, radius: float,
                *, opacity: float = 0.5) -> None:
    """简洁主题不绘制噪点。"""
    return


def mix(a: QColor, b: QColor, t: float) -> QColor:
    """颜色插值（用于 hover / 过渡）。"""
    t = max(0.0, min(1.0, t))
    return QColor(
        int(a.red() + (b.red() - a.red()) * t),
        int(a.green() + (b.green() - a.green()) * t),
        int(a.blue() + (b.blue() - a.blue()) * t),
        int(a.alpha() + (b.alpha() - a.alpha()) * t),
    )


def hexs(c: QColor, alpha: float | None = None) -> str:
    """Qt QSS 的 alpha 使用 0..255，同时保留 QColor 原有透明度。"""
    opacity = c.alpha() if alpha is None else max(0, min(255, int(round(alpha * 255))))
    if opacity == 255:
        return c.name()
    return f"rgba({c.red()},{c.green()},{c.blue()},{opacity})"


# --------------------------------------------------------------------------
# 细线图标（统一笔画，替代文字符号与粗线条图标）
# --------------------------------------------------------------------------
def paint_icon(p: QPainter, rect: QRectF, name: str,
               color: QColor | None = None, *, width: float = 1.25) -> None:
    """在 rect 内绘制极细线图标（stroke 统一 1.25px，圆头圆角）。"""
    c = color or TEXT_2
    pen = QPen(c, width)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    p.save()
    p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    p.setPen(pen)
    p.setBrush(Qt.BrushStyle.NoBrush)

    r = QRectF(rect)
    size = min(r.width(), r.height())
    cx, cy = r.center().x(), r.center().y()
    s = size / 2.0

    if name == "close":
        k = s * 0.52
        p.drawLine(QPointF(cx - k, cy - k), QPointF(cx + k, cy + k))
        p.drawLine(QPointF(cx + k, cy - k), QPointF(cx - k, cy + k))
    elif name == "refresh":
        k = s * 0.62
        rect = QRectF(cx - k, cy - k, 2 * k, 2 * k)
        # 圆环留缺口在右上，再在缺口处补一个实心箭头
        p.drawArc(rect, int(-55 * 16), int(300 * 16))
        a = math.radians(-55)
        tip = QPointF(cx + k * math.cos(a), cy + k * math.sin(a))
        d = k * 0.56
        arrow = QPainterPath(tip)
        arrow.lineTo(QPointF(tip.x() - d * 0.95, tip.y() - d * 0.5))
        arrow.lineTo(QPointF(tip.x() + d * 0.35, tip.y() - d * 1.05))
        arrow.closeSubpath()
        p.save()
        p.setBrush(c)
        p.setPen(Qt.PenStyle.NoPen)
        p.drawPath(arrow)
        p.restore()
    elif name == "source_frame":
        k = s * 0.70
        arm = k * 0.55
        for dx, dy in ((-1, -1), (1, -1), (-1, 1), (1, 1)):
            x, y = cx + dx * k, cy + dy * k
            p.drawLine(QPointF(x, y), QPointF(x - dx * arm, y))
            p.drawLine(QPointF(x, y), QPointF(x, y - dy * arm))
    elif name == "grip":
        k = s * 0.58
        for i in (-1, 0, 1):                 # 三条横线（≡），不是两条
            y = cy + i * s * 0.26
            p.drawLine(QPointF(cx - k, y), QPointF(cx + k, y))
    elif name == "pause":
        k = s * 0.5
        p.drawLine(QPointF(cx - k * 0.45, cy - k), QPointF(cx - k * 0.45, cy + k))
        p.drawLine(QPointF(cx + k * 0.45, cy - k), QPointF(cx + k * 0.45, cy + k))
    elif name == "play":
        k = s * 0.6
        path = QPainterPath(QPointF(cx - k * 0.6, cy - k))
        path.lineTo(QPointF(cx + k * 0.75, cy))
        path.lineTo(QPointF(cx - k * 0.6, cy + k))
        path.closeSubpath()
        p.drawPath(path)
    elif name == "settings":
        # 滑块风格（三条带滑块的横线）：比齿轮更现代，也不会被误读成太阳
        k = s * 0.72
        for i, off in ((-1, -0.32), (0, 0.34), (1, -0.08)):
            y = cy + i * s * 0.44
            p.drawLine(QPointF(cx - k, y), QPointF(cx + k, y))
            p.save()
            p.setBrush(c)
            p.setPen(Qt.PenStyle.NoPen)
            p.drawEllipse(QPointF(cx + off * k, y), s * 0.17, s * 0.17)
            p.restore()
    elif name == "chevron_right":
        k = s * 0.5
        p.drawLine(QPointF(cx - k * 0.4, cy - k), QPointF(cx + k * 0.5, cy))
        p.drawLine(QPointF(cx + k * 0.5, cy), QPointF(cx - k * 0.4, cy + k))
    elif name == "check":
        k = s * 0.62
        p.drawLine(QPointF(cx - k, cy), QPointF(cx - k * 0.15, cy + k * 0.7))
        p.drawLine(QPointF(cx - k * 0.15, cy + k * 0.7), QPointF(cx + k, cy - k * 0.6))
    elif name == "alert":
        k = s * 0.66
        p.drawEllipse(QRectF(cx - k, cy - k, 2 * k, 2 * k))
        p.drawLine(QPointF(cx, cy - k * 0.45), QPointF(cx, cy + k * 0.15))
        p.drawPoint(QPointF(cx, cy + k * 0.5))
    elif name == "dot":
        p.setBrush(c)
        p.setPen(Qt.PenStyle.NoPen)
        p.drawEllipse(QPointF(cx, cy), s * 0.22, s * 0.22)
    p.restore()


def icon_rect(rect: QRect, size: int = 14) -> QRectF:
    """在给定矩形内居中放置图标。"""
    return QRectF(rect.center().x() - size / 2, rect.center().y() - size / 2,
                  size, size)


# --------------------------------------------------------------------------
# 动画助手
# --------------------------------------------------------------------------
def animate(widget, prop: bytes, start, end, *, duration: int = DUR_BASE,
            easing: QEasingCurve | None = None, on_done=None) -> QPropertyAnimation:
    """创建并启动一个属性动画（默认标准缓动）。"""
    anim = QPropertyAnimation(widget, prop, widget)
    anim.setDuration(duration)
    anim.setStartValue(start)
    anim.setEndValue(end)
    anim.setEasingCurve(easing or ease_standard())
    if on_done is not None:
        anim.finished.connect(on_done)
    anim.start(QPropertyAnimation.DeletionPolicy.DeleteWhenStopped)
    return anim


def fade_in_window(window, *, duration: int = DUR_BASE, from_opacity: float = 0.0,
                   to_opacity: float | None = None) -> None:
    """窗口淡入（用窗口不透明度，不动 layout 属性）。"""
    target = window.windowOpacity() if to_opacity is None else to_opacity
    window.setWindowOpacity(from_opacity)
    animate(window, b"windowOpacity", from_opacity, target, duration=duration)


def style_menu(menu) -> None:
    """统一深色圆角菜单外观（替代系统默认菜单）。"""
    from PySide6.QtWidgets import QMenu  # 局部导入，避免循环依赖

    if not isinstance(menu, QMenu):
        return
    menu.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
    menu.setWindowFlags(menu.windowFlags()
                        | Qt.WindowType.FramelessWindowHint
                        | Qt.WindowType.NoDropShadowWindowHint)
    menu.setStyleSheet(f"""
        QMenu {{
            background: {hexs(INK_700, 0.98)};
            border: 1px solid {hexs(LINE)};
            border-radius: {int(R_MD)}px;
            padding: 6px;
        }}
        QMenu::item {{
            padding: 7px 22px 7px 14px;
            border-radius: {int(R_SM)}px;
            color: {hexs(TEXT)};
        }}
        QMenu::item:selected {{
            background: {hexs(INK_500)};
            color: {hexs(TEXT_HI)};
        }}
        QMenu::separator {{
            height: 1px; background: {hexs(LINE)}; margin: 5px 8px;
        }}
    """)


def fit_in(rect: QRect, bounds: QRect, margin: int = S3) -> QRect:
    r = QRect(rect)
    if r.width() > bounds.width():
        r.setWidth(bounds.width())
    if r.height() > bounds.height():
        r.setHeight(bounds.height())
    if r.left() < bounds.left() + margin:
        r.moveLeft(bounds.left() + margin)
    if r.top() < bounds.top() + margin:
        r.moveTop(bounds.top() + margin)
    if r.right() > bounds.right() - margin:
        r.moveRight(bounds.right() - margin)
    if r.bottom() > bounds.bottom() - margin:
        r.moveBottom(bounds.bottom() - margin)
    return r
