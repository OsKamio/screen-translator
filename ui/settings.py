# -*- coding: utf-8 -*-
"""设置窗口：翻译后端与密钥、目标语言、界面外观等。"""
from __future__ import annotations

import logging
import os
import threading

from PySide6.QtCore import QEvent, QUrl, Qt, Signal
from PySide6.QtGui import QDesktopServices, QPainter
from PySide6.QtWidgets import (
    QButtonGroup, QCheckBox, QComboBox, QDialog, QDoubleSpinBox, QFormLayout,
    QGroupBox, QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem,
    QMessageBox, QPlainTextEdit, QPushButton, QRadioButton, QScrollArea,
    QSpinBox, QTabWidget, QVBoxLayout, QWidget,
)

from core import config as core_config
from core import translate as core_translate

from . import appicon
from . import design as d
from .widgets import HintLabel, SettingsCard
from .motion import MotionButton, PageTransition
from .navigation import CapsuleNavigation
from .glass import GlassCanvas
from . import glass
from . import windowframe

log = logging.getLogger(__name__)

def settings_qss() -> str:
    asset = os.path.join(os.path.dirname(__file__), "../assets").replace(chr(92), "/")
    mark = "check-mark-dark.svg" if d.CURRENT_THEME == "dark" else "check-mark.svg"
    glass_qss = ""
    if glass.active():
        glass_qss = f"""
QWidget#settingsPage {{ background: transparent; }}
QLineEdit, QPlainTextEdit, QSpinBox, QDoubleSpinBox, QComboBox {{
    background: {d.hexs(d.INK_600, .84)}; border: 1px solid rgba(255,255,255,150);
}}
QListWidget {{ background: {d.hexs(d.INK_700, .70)}; border: 1px solid rgba(255,255,255,125); }}
QLabel#workspaceBadge {{ background: {d.hexs(d.INK_700, .65)}; border: 1px solid rgba(255,255,255,130); }}
"""
    return f"""
QDialog {{ background: {d.hexs(d.INK_900)}; font-family: "Microsoft YaHei UI"; font-size: 14px; }}
QDialog#settingsWindow {{ background: transparent; }}
QLabel#windowCaption {{ color: {d.hexs(d.TEXT_2)}; font-size: 12px; }}
QLabel {{ color: {d.hexs(d.TEXT)}; font-size: {int(d.F_BODY)}px; }}
QLabel#hint {{ color: {d.hexs(d.TEXT_3)}; font-size: {int(d.F_SMALL)}px; }}
QLabel#ok {{ color: {d.hexs(d.OK)}; font-size: {int(d.F_SMALL)}px; }}
QLabel#bad {{ color: {d.hexs(d.ERROR)}; font-size: {int(d.F_SMALL)}px; }}
QLabel#title {{
    color: {d.hexs(d.TEXT_HI)}; font-size: {int(d.F_DISPLAY)}px; font-weight: 600;
}}

/* 分组面板：外壳 + 内芯（留白加倍、发丝边代替灰色粗框）*/
QGroupBox {{
    background: {d.hexs(d.INK_800)};
    border: 1px solid {d.hexs(d.LINE)};
    border-radius: {int(d.R_LG)}px;
    margin-top: {d.S5}px;
    padding: {d.S5}px {d.S5}px {d.S4}px {d.S5}px;
}}
QGroupBox::title {{
    subcontrol-origin: margin; left: {d.S4}px; padding: 0 {d.S2}px;
    color: {d.hexs(d.TEXT_2)}; font-size: {int(d.F_CAPTION)}px;
}}
QGroupBox::title:hover {{ color: {d.hexs(d.TEXT)}; }}

QLineEdit, QPlainTextEdit, QSpinBox, QDoubleSpinBox, QComboBox {{
    background: {d.hexs(d.INK_600)};
    border: 1px solid {d.hexs(d.LINE)};
    border-radius: {int(d.R_SM)}px;
    padding: 7px 12px;
    color: {d.hexs(d.TEXT)};
    selection-background-color: {d.hexs(d.ACCENT, 0.34)};
    selection-color: {d.hexs(d.TEXT_HI)};
}}
QLineEdit:hover, QPlainTextEdit:hover, QSpinBox:hover,
QDoubleSpinBox:hover, QComboBox:hover {{ border: 1px solid {d.hexs(d.LINE_STRONG)}; }}
QLineEdit:focus, QPlainTextEdit:focus, QSpinBox:focus,
QDoubleSpinBox:focus, QComboBox:focus {{
    border: 1px solid {d.hexs(d.ACCENT, 0.72)};
}}
QComboBox::drop-down {{ border: none; width: 22px; }}
QComboBox QAbstractItemView {{
    background: {d.hexs(d.INK_700)}; color: {d.hexs(d.TEXT)};
    border: 1px solid {d.hexs(d.LINE)}; border-radius: {int(d.R_SM)}px;
    selection-background-color: {d.hexs(d.INK_500)};
    selection-color: {d.hexs(d.TEXT_HI)};
    padding: 4px;
}}

QCheckBox, QRadioButton {{ color: {d.hexs(d.TEXT)}; spacing: 10px; }}
QCheckBox::indicator {{
    width: 16px; height: 16px; border-radius: 5px;
    border: 1px solid {d.hexs(d.LINE_STRONG)}; background: {d.hexs(d.INK_600)};
}}
QCheckBox::indicator:hover {{ border: 1px solid {d.hexs(d.TEXT_3)}; }}
QCheckBox::indicator:checked {{
    background: {d.hexs(d.ACTION)}; border: 1px solid {d.hexs(d.ACTION)};
}}
QRadioButton::indicator {{
    width: 18px; height: 18px; border: none; background: transparent;
    image: url("{asset}/radio-unchecked-{d.CURRENT_THEME}.svg");
}}
QRadioButton::indicator:checked {{
    image: url("{asset}/radio-checked-{d.CURRENT_THEME}.svg");
}}

QPushButton {{
    min-height: 19px;
    background: {d.hexs(d.INK_600)}; color: {d.hexs(d.TEXT)};
    border: 1px solid {d.hexs(d.LINE)}; border-radius: 18px;
    padding: 9px 18px; font-size: {int(d.F_BODY)}px;
}}
QPushButton:hover {{ background: {d.hexs(d.INK_500)}; border-color: {d.hexs(d.LINE_STRONG)}; }}
QPushButton:pressed {{ background: {d.hexs(d.INK_800)}; }}
QPushButton#primary {{
    background: {d.hexs(d.ACTION)}; color: {d.hexs(d.ON_ACTION)};
    border: 1px solid {d.hexs(d.ACTION)}; font-weight: 600;
}}
QPushButton#primary:hover {{ background: {d.hexs(d.ACTION_HI)}; }}
QPushButton#primary:pressed {{ background: {d.hexs(d.ACTION)}; }}
QPushButton:disabled {{ background: {d.hexs(d.INK_700)}; color: {d.hexs(d.TEXT_3)}; }}

QTabWidget::pane {{
    border: none;
    background: transparent;
}}
QTabBar::tab {{
    background: transparent; color: {d.hexs(d.TEXT_3)};
    padding: 10px 20px; margin-right: 6px;
    border-radius: {int(d.R_SM)}px;
}}
QTabBar::tab:hover {{ color: {d.hexs(d.TEXT)}; background: {d.hexs(d.INK_800)}; }}
QTabBar::tab:selected {{
    background: {d.hexs(d.INK_700)}; color: {d.hexs(d.TEXT_HI)};
    border-bottom: 2px solid {d.hexs(d.ACCENT)};
}}

QListWidget {{
    background: {d.hexs(d.INK_900)}; border: 1px solid {d.hexs(d.LINE)};
    border-radius: {int(d.R_MD)}px; color: {d.hexs(d.TEXT)};
    padding: 6px; outline: none;
}}
QListWidget::item {{ padding: 7px 8px; border-radius: {int(d.R_SM)}px; }}
QListWidget::item:hover {{ background: {d.hexs(d.INK_600)}; }}
QListWidget::item:selected {{
    background: {d.hexs(d.ACCENT, 0.16)}; color: {d.hexs(d.TEXT_HI)};
}}

QScrollArea {{ border: none; background: transparent; }}
QScrollBar:vertical {{ background: transparent; width: 10px; margin: 2px; }}
QScrollBar::handle:vertical {{
    background: {d.hexs(d.LINE_STRONG)}; border-radius: 5px; min-height: 30px;
}}
QScrollBar::handle:vertical:hover {{ background: {d.hexs(d.TEXT_3)}; }}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}

QWidget#settingsPage {{ background: {d.hexs(d.INK_900)}; }}
QListWidget::indicator {{ width: 16px; height: 16px; border-radius: 4px;
    border: 1px solid {d.hexs(d.LINE_STRONG)}; background: {d.hexs(d.INK_700)}; }}
QListWidget::indicator:checked {{ background: {d.hexs(d.ACTION)}; border: 1px solid {d.hexs(d.ACTION)};
    image: url("{asset}/{mark}"); }}
QListWidget#navigation {{ background: transparent; border: none; padding: 0; }}
QListWidget#navigation::item {{ padding: 13px 16px; margin: 2px 0; border-radius: 8px; }}
QListWidget#navigation::item:selected {{ background: {d.hexs(d.ACCENT_SOFT)}; color: {d.hexs(d.ACCENT)}; }}
QLabel#pageTitle {{ font-size: 28px; font-weight: 600; color: {d.hexs(d.TEXT_HI)}; }}
QLabel#pageSubtitle {{ font-size: 12px; color: {d.hexs(d.TEXT_2)}; }}
QLabel#workspaceBadge {{ background: {d.hexs(d.INK_500)}; border-radius: 14px;
    padding: 8px 14px; font-size: 11px; color: {d.hexs(d.TEXT_2)}; }}
QPushButton:focus {{ border: 1px solid {d.hexs(d.ACCENT)}; }}
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{ background: transparent; }}
QPushButton#quiet {{ border: none; background: transparent; color: {d.hexs(d.TEXT_2)}; }}
QPushButton#quiet:hover {{ background: {d.hexs(d.INK_500)}; }}
QSpinBox::up-button, QDoubleSpinBox::up-button {{ subcontrol-origin: border;
    subcontrol-position: top right; width: 20px; height: 14px; margin: 3px 4px 0 0; border: none; }}
QSpinBox::down-button, QDoubleSpinBox::down-button {{ subcontrol-origin: border;
    subcontrol-position: bottom right; width: 20px; height: 14px; margin: 0 4px 3px 0; border: none; }}
QSpinBox::up-arrow, QDoubleSpinBox::up-arrow {{ image: url("{asset}/chevron-up-{d.CURRENT_THEME}.svg"); width: 10px; height: 8px; }}
QSpinBox::down-arrow, QDoubleSpinBox::down-arrow, QComboBox::down-arrow {{ image: url("{asset}/chevron-down-{d.CURRENT_THEME}.svg"); width: 10px; height: 8px; }}
QCheckBox::indicator:checked {{ image: url("{asset}/{mark}"); }}
""" + glass_qss

APP_VERSION = "0.2.0"


def _dset(data: dict, dotted: str, value) -> None:
    """按点分路径写入嵌套 dict。"""
    parts = dotted.split(".")
    cur = data
    for part in parts[:-1]:
        nxt = cur.get(part)
        if not isinstance(nxt, dict):
            nxt = {}
            cur[part] = nxt
        cur = nxt
    cur[parts[-1]] = value


def _page(inner: QWidget) -> QScrollArea:
    """把一页内容放进滚动区域。"""
    inner.setObjectName("settingsPage")
    area = QScrollArea()
    area.setWidgetResizable(True)
    area.setWidget(inner)
    return area


class SettingsWindow(QDialog):
    """设置窗口（非模态，保存后发 saved 信号）。"""

    saved = Signal(dict)
    test_finished = Signal(str, str)
    toggle_live_requested = Signal()

    def __init__(self, cfg: core_config.Config, parent=None):
        super().__init__(parent)
        self.setWindowFlag(Qt.WindowType.FramelessWindowHint, True)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setObjectName('settingsWindow')
        self.setMouseTracking(True)
        # 实时译文为置顶窗口，设置也需能被正常提到它前面。
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
        self.setWindowTitle("屏幕翻译 · 设置")
        self.setMinimumSize(760, 540)
        screen = self.screen().availableGeometry()
        self.resize(min(920, screen.width()-40), min(740, screen.height()-60))
        self.setStyleSheet(settings_qss())
        self.setFont(d.font(d.F_BODY))
        # 标题栏左上角图标（显式设置，避免某些环境下不继承应用图标）
        icon = appicon.window_icon()
        if icon is not None:
            self.setWindowIcon(icon)

        self._cfg = cfg
        self._binds: list[tuple[str, object, object]] = []
        self._test_labels: dict[str, QLabel] = {}
        self._test_buttons: dict[str, QPushButton] = {}

        frame_layout = QVBoxLayout(self)
        frame_layout.setContentsMargins(0, 0, 0, 0)
        frame_layout.setSpacing(0)
        self._title_bar = windowframe.TitleBar(self)
        self._rounded_frame = windowframe.RoundedFrame(self)
        frame_layout.addWidget(self._title_bar)
        root = QVBoxLayout()
        frame_layout.addLayout(root, 1)
        root.setContentsMargins(d.SET_CARD_PAD_X, d.S4,
                                d.SET_CARD_PAD_X, d.S4)
        root.setSpacing(18)

        heading = QHBoxLayout()
        titles = QVBoxLayout()
        titles.setSpacing(4)
        title = QLabel("屏幕翻译.")
        title.setObjectName("pageTitle")
        subtitle = QLabel("少一点打扰，多一点理解。")
        subtitle.setObjectName("pageSubtitle")
        titles.addWidget(title)
        titles.addWidget(subtitle)
        heading.addLayout(titles)
        heading.addStretch(1)
        self._workspace_badge = QLabel("●  桌面翻译工作台")
        self._workspace_badge.setObjectName("workspaceBadge")
        heading.addWidget(self._workspace_badge, 0, Qt.AlignmentFlag.AlignVCenter)
        root.addLayout(heading)

        self._tabs = QTabWidget()
        self._tabs.addTab(_page(self._build_translate_tab()), "翻译")
        self._tabs.addTab(_page(self._build_api_tab()), "翻译接口")
        self._tabs.addTab(_page(self._build_live_tab()), "实时翻译")
        self._tabs.addTab(_page(self._build_ui_tab()), "界面")
        self._tabs.addTab(self._build_about_tab(), "关于")
        self._tabs.tabBar().hide()
        self._navigation = CapsuleNavigation()
        self._navigation.addItems(["翻译", "翻译接口", "实时翻译", "界面", "关于"])
        self._navigation.currentRowChanged.connect(self._tabs.setCurrentIndex)
        self._tabs.currentChanged.connect(self._navigation.setCurrentRow)
        self._navigation.setCurrentRow(0)
        self._navigation_marker = self._navigation
        self._page_transition = PageTransition(self._tabs)
        self._previous_page = 0
        self._tabs.currentChanged.connect(self._animate_page)
        root.addWidget(self._navigation)
        root.addWidget(self._tabs, 1)

        # ---- 底部按钮 ----
        bottom = QHBoxLayout()
        self._status = QLabel("")
        self._status.setObjectName("hint")
        bottom.addWidget(self._status, 1)
        btn_reset = MotionButton("恢复默认")
        btn_reset.setObjectName("quiet")
        btn_cancel = MotionButton("关闭")
        btn_save = MotionButton("保存更改")
        btn_save.setObjectName("primary")
        self._save_button = btn_save
        btn_reset.clicked.connect(self._on_reset)
        btn_cancel.clicked.connect(self.reject)
        btn_save.clicked.connect(self._on_save)
        bottom.addWidget(btn_reset)
        bottom.addWidget(btn_cancel)
        bottom.addWidget(btn_save)
        root.addLayout(bottom)

        self.test_finished.connect(self._on_test_finished)
        self._load_from_cfg()

    # ================================================================== 绑定
    def _bind(self, path: str, getter, setter) -> None:
        self._binds.append((path, getter, setter))

    def _load_from_cfg(self) -> None:
        for path, _getter, setter in self._binds:
            try:
                setter(self._cfg.get(path))
            except Exception as exc:  # noqa: BLE001
                log.warning("载入配置项 %s 失败：%s", path, exc)
        self._load_backends()

    def _collect(self) -> dict:
        """把界面上的当前值收集成完整配置 dict（不落盘）。"""
        data = self._cfg.copy_data()
        for path, getter, _setter in self._binds:
            try:
                _dset(data, path, getter())
            except Exception as exc:  # noqa: BLE001
                log.warning("读取界面值 %s 失败：%s", path, exc)
        order, enabled = [], {}
        for i in range(self._backend_list.count()):
            item = self._backend_list.item(i)
            name = item.data(Qt.ItemDataRole.UserRole)
            order.append(name)
            enabled[name] = item.checkState() == Qt.CheckState.Checked
        data.setdefault("translate", {})
        data["translate"]["backends"] = order
        data["translate"]["enabled"] = enabled
        return data

    # ============================================================== 翻译页
    def _build_translate_tab(self) -> QWidget:
        page = GlassCanvas()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(d.SET_PAGE_PAD, d.SET_PAGE_PAD,
                               d.SET_PAGE_PAD, d.SET_PAGE_PAD)
        lay.setSpacing(d.SET_CARD_SPACING)

        # ---- 通用 ----
        box, form = self._group("通用")
        combo = QComboBox()
        for code, label in core_config.TARGET_LANGS:
            combo.addItem(f"{label}（{code}）", code)
        self._add_form(form, "目标语言", combo,
                       "识别到文字后翻译成该语言")
        self._bind("translate.target_lang", lambda: combo.currentData(),
                   lambda v: self._select_combo(combo, v))

        skip = QCheckBox("原文已是目标语言时跳过翻译")
        self._bind("translate.skip_if_already_target", skip.isChecked, skip.setChecked)
        form.addRow(skip)

        timeout = QSpinBox()
        timeout.setRange(3, 60)
        timeout.setSuffix(" 秒")
        self._add_form(form, "请求超时", timeout)
        self._bind("translate.timeout", timeout.value, timeout.setValue)
        lay.addWidget(box)

        # ---- 后端顺序 ----
        box, form = self._group("翻译接口启用与顺序")
        hint = HintLabel(
            "勾选要使用的接口，按列表顺序依次尝试。"
            "密钥在「翻译接口」页填写；可用上移、下移调整优先级。")
        form.addRow(hint)

        self._backend_list = QListWidget()
        self._backend_list.setMinimumHeight(220)
        self._backend_list.itemChanged.connect(self._on_backend_item_changed)
        row = QHBoxLayout()
        row.addWidget(self._backend_list, 1)
        side = QVBoxLayout()
        up = MotionButton("上移")
        down = MotionButton("下移")
        refresh = MotionButton("刷新状态")
        up.clicked.connect(lambda: self._move_backend(-1))
        down.clicked.connect(lambda: self._move_backend(1))
        refresh.clicked.connect(self._refresh_backend_states)
        side.addWidget(up)
        side.addWidget(down)
        side.addWidget(refresh)
        side.addStretch(1)
        row.addLayout(side)
        form.addRow(row)

        self._chain_hint = HintLabel("")
        form.addRow(self._chain_hint)
        lay.addWidget(box)

        # ---- 文字识别 ----
        box, form = self._group("文字识别（OCR）")
        conf = QDoubleSpinBox()
        conf.setRange(0.0, 1.0)
        conf.setSingleStep(0.05)
        conf.setDecimals(2)
        self._add_form(form, "最低置信度", conf,
                       "低于该置信度的识别结果会被丢弃")
        self._bind("ocr.min_confidence", conf.value, conf.setValue)

        merge = QCheckBox("多行合并为整段后再翻译（推荐开启，译文更连贯）")
        self._bind("ocr.merge_lines", merge.isChecked, merge.setChecked)
        form.addRow(merge)
        lay.addWidget(box)

        lay.addStretch(1)
        return page

    def _load_backends(self) -> None:
        self._backend_list.clear()
        order = self._cfg.get("translate.backends", None) or list(core_translate.BACKEND_ORDER)
        enabled = self._cfg.get("translate.enabled", {}) or {}
        names = [n for n in order if n in core_translate.BACKENDS]
        for n in core_translate.BACKEND_ORDER:      # 补齐缺失的后端
            if n not in names:
                names.append(n)
        for name in names:
            item = QListWidgetItem()
            item.setData(Qt.ItemDataRole.UserRole, name)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Checked if enabled.get(name)
                               else Qt.CheckState.Unchecked)
            self._backend_list.addItem(item)
        self._refresh_backend_states()

    def _refresh_backend_states(self) -> None:
        data = self._collect()
        tmp = core_config.Config(self._cfg.path)
        tmp.replace_data(data)
        self._backend_list.blockSignals(True)
        for i in range(self._backend_list.count()):
            item = self._backend_list.item(i)
            name = item.data(Qt.ItemDataRole.UserRole)
            ok, why = core_translate.backend_ready(name, tmp)
            label = core_translate.backend_label(name)
            short = why.replace("缺少配置：", "缺 ")
            if item.checkState() == Qt.CheckState.Checked:
                item.setText(f"{label}  ·  " + ("可用" if ok else short))
            elif ok:
                # 已配置好但没勾选：这是最容易踩的坑，明确提示
                item.setText(f"{label}  ·  已配置，待勾选")
            else:
                item.setText(f"{label}  ·  未启用")
        self._backend_list.blockSignals(False)
        chain = core_translate.build_chain(tmp)
        if chain:
            self._chain_hint.setText(
                "当前实际调用顺序：" +
                " → ".join(core_translate.backend_label(n) for n in chain))
        else:
            self._chain_hint.setText(
                "当前没有可用接口，翻译会失败。请勾选并配置至少一个接口。")
        self._update_tab_badge(bool(chain))

    def _update_tab_badge(self, has_chain: bool) -> None:
        """在“翻译”页标签上标记问题，避免用户找不到要勾选的地方。"""
        try:
            self._tabs.setTabText(0, "翻译" if has_chain else "翻译 ⚠")
            self._navigation.item(0).setText("翻译" if has_chain else "翻译 · 未就绪")
        except Exception:  # noqa: BLE001
            pass

    def _on_backend_item_changed(self, _item) -> None:
        self._refresh_backend_states()

    def _set_backend_checked(self, name: str, checked: bool = True) -> bool:
        """勾选/取消某个后端；返回是否发生了改变。"""
        for i in range(self._backend_list.count()):
            item = self._backend_list.item(i)
            if item.data(Qt.ItemDataRole.UserRole) == name:
                want = Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked
                changed = item.checkState() != want
                self._backend_list.blockSignals(True)
                item.setCheckState(want)
                self._backend_list.blockSignals(False)
                self._refresh_backend_states()
                return changed
        return False

    def _move_backend(self, delta: int) -> None:
        row = self._backend_list.currentRow()
        if row < 0:
            return
        target = row + delta
        if not (0 <= target < self._backend_list.count()):
            return
        item = self._backend_list.takeItem(row)
        self._backend_list.insertItem(target, item)
        self._backend_list.setCurrentRow(target)
        self._refresh_backend_states()

    # ============================================================ 接口页
    def _build_api_tab(self) -> QWidget:
        page = GlassCanvas()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(d.SET_PAGE_PAD, d.SET_PAGE_PAD,
                               d.SET_PAGE_PAD, d.SET_PAGE_PAD)
        lay.setSpacing(d.SET_CARD_SPACING)

        tip = HintLabel(
            "使用步骤：<b>① 在下面填好密钥</b> → <b>② 点「测试连接」</b>"
            "（测试通过会自动帮你勾选启用）<br>"
            "→ <b>③ 点右下角「保存」</b>。"
            "若只在「翻译」页勾选却没填密钥，同样无法使用；密钥仅保存在本机配置文件。")
        lay.addWidget(tip)

        # DeepL
        box, form = self._group("DeepL（推荐，质量好）")
        key = self._password_edit(form, "API Key", "api.deepl.api_key",
                                 "在 DeepL 账号后台获取，免费版每月 50 万字符")
        plan = QComboBox()
        plan.addItem("免费版（api-free.deepl.com）", "free")
        plan.addItem("专业版（api.deepl.com）", "pro")
        self._add_form(form, "账号类型", plan)
        self._bind("api.deepl.plan", lambda: plan.currentData(),
                   lambda v: self._select_combo(plan, v))
        self._add_test_row(form, "deepl")
        lay.addWidget(box)

        # 百度
        box, form = self._group("百度翻译开放平台")
        self._password_edit(form, "APP ID", "api.baidu.appid",
                            "百度翻译开放平台控制台 → 开发者信息")
        self._password_edit(form, "密钥", "api.baidu.key", "标准版每月 5 万字符免费")
        self._add_test_row(form, "baidu")
        lay.addWidget(box)

        # 微软
        box, form = self._group("微软翻译（Azure 认知服务）")
        self._password_edit(form, "订阅密钥", "api.microsoft.key",
                            "Azure 翻译资源 → 密钥和终结点")
        reg = QLineEdit()
        reg.setPlaceholderText("global")
        self._add_form(form, "区域", reg, "如 global / eastasia / japaneast")
        self._bind("api.microsoft.region", reg.text, reg.setText)
        self._add_test_row(form, "microsoft")
        lay.addWidget(box)

        # OpenAI 兼容
        box, form = self._group("LLM 翻译（OpenAI 兼容接口）")
        base = QLineEdit()
        base.setPlaceholderText("https://api.openai.com/v1")
        self._add_form(form, "Base URL", base,
                       "可填任意兼容服务：DeepSeek / 通义 / Ollama 等")
        self._bind("api.openai.base_url", base.text, base.setText)
        self._password_edit(form, "API Key", "api.openai.api_key", "")
        model = QLineEdit()
        model.setPlaceholderText("gpt-4o-mini")
        self._add_form(form, "模型名", model)
        self._bind("api.openai.model", model.text, model.setText)
        sys_prompt = QPlainTextEdit()
        sys_prompt.setPlaceholderText("留空使用默认提示词：只输出译文、保持段落")
        sys_prompt.setFixedHeight(64)
        self._add_form(form, "自定义提示词", sys_prompt, "可选")
        self._bind("api.openai.system_prompt",
                   lambda: sys_prompt.toPlainText(), sys_prompt.setPlainText)
        self._add_test_row(form, "openai")
        lay.addWidget(box)

        # 自定义 HTTP
        box, form = self._group("自定义 HTTP 接口")
        ctip = HintLabel("模板占位符：{text} 待翻译文本、{src} 源语言、{dst} 目标语言。"
                         "响应取值路径支持点号与数组下标，如 data.translation、"
                         "result.0.text。")
        form.addRow(ctip)
        url = QLineEdit()
        url.setPlaceholderText("https://example.com/api/translate")
        self._add_form(form, "请求地址", url)
        self._bind("api.custom.url", url.text, url.setText)
        method = QComboBox()
        method.addItem("POST（JSON 请求体）", "POST")
        method.addItem("GET（参数拼在地址后）", "GET")
        self._add_form(form, "请求方式", method)
        self._bind("api.custom.method", lambda: method.currentData(),
                   lambda v: self._select_combo(method, v))
        headers = QPlainTextEdit()
        headers.setPlaceholderText('{"Authorization": "Bearer xxx"}')
        headers.setFixedHeight(56)
        self._add_form(form, "请求头", headers, "JSON 文本")
        self._bind("api.custom.headers",
                   lambda: headers.toPlainText(), headers.setPlainText)
        body = QPlainTextEdit()
        body.setPlaceholderText('{"text": "{text}", "source": "{src}", "target": "{dst}"}')
        body.setFixedHeight(56)
        self._add_form(form, "请求体模板", body, "GET 时作为查询参数")
        self._bind("api.custom.body", lambda: body.toPlainText(), body.setPlainText)
        path_edit = QLineEdit()
        path_edit.setPlaceholderText("data.translation")
        self._add_form(form, "响应取值路径", path_edit, "留空则把响应正文当作译文")
        self._bind("api.custom.response_path", path_edit.text, path_edit.setText)
        self._add_test_row(form, "custom")
        lay.addWidget(box)

        # 免密钥
        box, form = self._group("免密钥接口")
        mtip = HintLabel("MyMemory 与 Google 网页翻译无需密钥。MyMemory 国内可直连但较慢；"
                         "Google 需要国际网络。")
        form.addRow(mtip)
        self._add_test_row(form, "mymemory", label="测试 MyMemory")
        self._add_test_row(form, "google", label="测试 Google")
        lay.addWidget(box)

        lay.addStretch(1)
        return page

    # ========================================================== 实时翻译页
    def _build_live_tab(self) -> QWidget:
        page = GlassCanvas()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(d.SET_PAGE_PAD, d.SET_PAGE_PAD,
                               d.SET_PAGE_PAD, d.SET_PAGE_PAD)
        lay.setSpacing(d.SET_CARD_SPACING)

        # ---- 工作模式（模式切换开关）----
        box, form = self._group("工作模式")
        tip = HintLabel("两种方式随时都能用（悬浮球右键菜单里也能开关实时窗口）；"
                        "这里决定启动时默认用哪种。")
        form.addRow(tip)

        mode_manual = QRadioButton("手动框选：单击悬浮球 → 拖框 → 翻译一次")
        mode_live = QRadioButton("自动实时翻译：桌面显示半透明取景框，框内文字持续自动翻译")
        grp = QButtonGroup(self)
        grp.addButton(mode_manual)
        grp.addButton(mode_live)
        form.addRow(mode_manual)
        form.addRow(mode_live)
        self._bind(
            "live.enabled",
            lambda: mode_live.isChecked(),
            lambda v: (mode_live.setChecked(bool(v)),
                       mode_manual.setChecked(not bool(v))),
        )
        btn_toggle = MotionButton("立即显示 / 隐藏实时窗口")
        btn_toggle.clicked.connect(self.toggle_live_requested.emit)
        row = QHBoxLayout()
        row.addWidget(btn_toggle)
        row.addStretch(1)
        form.addRow("", self._wrap(row))
        lay.addWidget(box)

        # ---- 外观 ----
        box, form = self._group("实时窗口外观")
        bg = QSpinBox()
        bg.setRange(0, 100)
        bg.setSuffix(" %")
        self._add_form(form, "背景不透明度", bg, "0 = 只有文字、背景全透明")
        self._bind("live.bg_opacity", bg.value, bg.setValue)

        fs = QSpinBox()
        fs.setRange(12, 40)
        fs.setSuffix(" px")
        self._add_form(form, "译文字号", fs)
        self._bind("live.font_size", fs.value, fs.setValue)

        show_org = QCheckBox("同时显示识别到的原文（小字）")
        self._bind("live.show_original", show_org.isChecked, show_org.setChecked)
        form.addRow(show_org)

        stats = QCheckBox("在顶部显示识别/翻译耗时")
        self._bind("live.show_stats", stats.isChecked, stats.setChecked)
        form.addRow(stats)

        click_through = QCheckBox("点击穿透（鼠标操作落到下层窗口；开启后无法拖动/缩放本窗口）")
        self._bind("live.click_through", click_through.isChecked,
                   click_through.setChecked)
        form.addRow(click_through)

        cap = QCheckBox("不被截屏 / 录屏 / 投屏捕获")
        self._bind("live.capture_excluded", cap.isChecked, cap.setChecked)
        form.addRow(cap)
        cap_hint = HintLabel(
            "开启时本窗口不会出现在任何截图、录屏、共享屏幕里（也避免翻译时把自己的字截进去）。"
            "<b>远程桌面 / 投屏本身就是屏幕捕获 —— 如果你那样用，必须关掉它才能看到本窗口</b>；"
            "关闭后优先直接读取下层应用窗口，保留覆盖显示；应用不支持时自动分开取景与译文，避免闪烁。可在实时窗口右键菜单重新选择取景区域。")
        form.addRow(cap_hint)
        lay.addWidget(box)

        # ---- 检测参数 ----
        box, form = self._group("检测与性能")
        phint = HintLabel("只在画面变化时才识别；单次识别约 1~2 秒。"
                          "间隔短 = 更及时但更耗 CPU，间隔长 = 更省电。")
        form.addRow(phint)

        merge = QCheckBox("把识别到的多行合并成整段再翻译（推荐：否则换行会把一句话拆开翻错）")
        self._bind("live.merge_lines", merge.isChecked, merge.setChecked)
        form.addRow(merge)

        interval = QSpinBox()
        interval.setRange(300, 10000)
        interval.setSingleStep(100)
        interval.setSuffix(" ms")
        self._add_form(form, "检查间隔", interval)
        self._bind("live.interval_ms", interval.value, interval.setValue)

        thresh = QDoubleSpinBox()
        thresh.setRange(0.002, 0.200)
        thresh.setSingleStep(0.005)
        thresh.setDecimals(3)
        self._add_form(form, "画面变化阈值", thresh,
                       "越小越灵敏；画面有噪点/动画时可调大，避免频繁识别")
        self._bind("live.diff_threshold", thresh.value, thresh.setValue)
        lay.addWidget(box)

        # ---- 窗口位置 ----
        box, form = self._group("窗口位置")
        remember = QCheckBox("记住窗口位置与大小")
        self._bind("live.remember_geometry", remember.isChecked, remember.setChecked)
        form.addRow(remember)

        btn_reset = MotionButton("重置窗口位置")
        btn_reset.clicked.connect(self._on_reset_live_geometry)
        row2 = QHBoxLayout()
        row2.addWidget(btn_reset)
        row2.addStretch(1)
        form.addRow("", self._wrap(row2))
        lay.addWidget(box)

        lay.addStretch(1)
        return page

    def _on_reset_live_geometry(self) -> None:
        self._cfg.set("live.geometry", None)
        self._status.setText("窗口位置已重置，点「保存」生效")

    # ============================================================== 界面页
    def _build_ui_tab(self) -> QWidget:
        page = GlassCanvas()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(d.SET_PAGE_PAD, d.SET_PAGE_PAD,
                               d.SET_PAGE_PAD, d.SET_PAGE_PAD)
        lay.setSpacing(d.SET_CARD_SPACING)

        box, form = self._group("主题与外观")
        theme = QComboBox()
        theme.addItem("跟随系统", "system")
        theme.addItem("浅色", "light")
        theme.addItem("深色", "dark")
        theme.addItem("液态玻璃", "glass")
        self._add_form(form, "界面主题", theme, "保存后立即生效；液态玻璃会跟随系统明暗与透明效果偏好")
        self._bind("ui.theme", theme.currentData, lambda value: self._select_combo(theme, value))
        animations = QCheckBox("启用轻量界面动效")
        animations.setToolTip("同时遵循 Windows 辅助功能中的动画效果设置")
        self._bind("ui.animations", animations.isChecked, animations.setChecked)
        form.addRow(animations)
        lay.addWidget(box)

        box, form = self._group("悬浮球")
        size = QSpinBox()
        size.setRange(44, 88)
        size.setSuffix(" px")
        self._add_form(form, "直径", size)
        self._bind("ui.ball_size", size.value, size.setValue)
        opacity = QSpinBox()
        opacity.setRange(40, 100)
        opacity.setSuffix(" %")
        self._add_form(form, "不透明度", opacity)
        self._bind("ui.ball_opacity", opacity.value, opacity.setValue)
        lay.addWidget(box)

        box, form = self._group("结果卡片")
        font = QSpinBox()
        font.setRange(12, 28)
        font.setSuffix(" px")
        self._add_form(form, "译文字号", font)
        self._bind("ui.result_font_size", font.value, font.setValue)

        ratio = QSpinBox()
        ratio.setRange(40, 95)
        ratio.setSuffix(" %")
        self._add_form(form, "最大高度", ratio, "占屏幕可用高度的比例，超出部分滚动")
        self._bind("ui.result_max_height_ratio", ratio.value, ratio.setValue)

        show_orig = QCheckBox("显示识别到的原文")
        self._bind("ui.show_original", show_orig.isChecked, show_orig.setChecked)
        form.addRow(show_orig)

        auto_copy = QCheckBox("翻译完成后自动复制译文到剪贴板")
        self._bind("ui.auto_copy", auto_copy.isChecked, auto_copy.setChecked)
        form.addRow(auto_copy)
        lay.addWidget(box)

        lay.addStretch(1)
        return page

    # ============================================================== 关于页
    def _build_about_tab(self) -> QWidget:
        page = GlassCanvas()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(d.S6, d.S6, d.S6, d.S6)
        lay.setSpacing(d.SET_FORM_ROW)

        title = QLabel("屏幕翻译")
        title.setFont(d.font(d.F_DISPLAY, d.W_SEMI, tight=True))
        title.setObjectName("pageTitle")
        lay.addWidget(title)

        version = QLabel(f"v{APP_VERSION}")
        version.setFont(d.mono_font(d.F_CAPTION))
        version.setObjectName("hint")
        lay.addWidget(version)

        desc = HintLabel(
            "点击悬浮球框选屏幕区域，本地 OCR 识别后用你配置的接口翻译；"
            "也可以打开实时翻译窗口，让框内文字持续自动翻译。",
            size=d.F_BODY, color=d.TEXT_2)   # 正文级说明：字号与色阶都比 hint 高一档
        desc.setMaximumWidth(620)      # 控制段落宽度，避免长行阅读疲劳
        lay.addWidget(desc)

        path_label = HintLabel(f"配置文件：{self._cfg.path}")
        path_label.setMaximumWidth(620)
        lay.addWidget(path_label)

        row = QHBoxLayout()
        btn_open = MotionButton("打开配置所在文件夹")
        btn_open.clicked.connect(self._open_config_dir)
        btn_reload = MotionButton("重新载入配置文件")
        btn_reload.clicked.connect(self._reload_from_disk)
        row.addWidget(btn_open)
        row.addWidget(btn_reload)
        row.addStretch(1)
        lay.addLayout(row)

        lay.addStretch(1)
        return page

    def _open_config_dir(self) -> None:
        folder = os.path.dirname(os.path.abspath(self._cfg.path))
        QDesktopServices.openUrl(QUrl.fromLocalFile(folder))

    def _reload_from_disk(self) -> None:
        self._cfg.load()
        self._load_from_cfg()
        self.saved.emit(self._cfg.copy_data())
        self._status.setText("配置已重新载入")

    # ============================================================== 小工具
    def _group(self, title: str):
        """返回自绘分组卡片（双层壳 + eyebrow 标题）与其表单布局。"""
        card = SettingsCard(title)
        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignmentFlag.AlignLeft
                               | Qt.AlignmentFlag.AlignVCenter)
        form.setFormAlignment(Qt.AlignmentFlag.AlignLeft
                              | Qt.AlignmentFlag.AlignTop)
        form.setContentsMargins(0, 0, 0, 0)
        form.setSpacing(d.SET_FORM_ROW)
        card.body().addLayout(form)
        return card, form

    def _add_form(self, form: QFormLayout, label: str, widget,
                  hint: str = "") -> None:
        # 统一标签列宽与字段宽度：跨卡片对齐，输入框不再被拉满整行
        limit = 520 if isinstance(widget, QPlainTextEdit) else SettingsCard.FIELD_MAX_W
        if hasattr(widget, "setMaximumWidth"):
            widget.setMaximumWidth(limit)
        cap = QLabel(label)
        cap.setMinimumWidth(SettingsCard.LABEL_W)
        cap.setAlignment(Qt.AlignmentFlag.AlignLeft
                         | Qt.AlignmentFlag.AlignVCenter)
        if hint:
            holder = QWidget()
            v = QVBoxLayout(holder)
            v.setContentsMargins(0, 0, 0, 0)
            v.setSpacing(d.SET_CONTROL_GAP)
            v.addWidget(widget)
            hint_label = HintLabel(hint)
            hint_label.setMaximumWidth(limit + 40)
            v.addWidget(hint_label)
            form.addRow(cap, holder)
        else:
            form.addRow(cap, widget)

    def _password_edit(self, form: QFormLayout, label: str, path: str,
                       hint: str = "") -> QLineEdit:
        edit = QLineEdit()
        edit.setEchoMode(QLineEdit.EchoMode.Password)
        edit.setPlaceholderText("未填写")
        self._add_form(form, label, edit, hint)
        self._bind(path, edit.text, edit.setText)
        return edit

    def _add_test_row(self, form: QFormLayout, name: str,
                      label: str | None = None) -> None:
        row = QHBoxLayout()
        btn = MotionButton(label or "测试连接")
        btn.setFixedWidth(110)
        result = HintLabel("")
        btn.clicked.connect(lambda _c=False, n=name: self._on_test(n))
        self._test_labels[name] = result
        self._test_buttons[name] = btn
        row.addWidget(btn)
        row.addWidget(result, 1)
        # 测试按钮是"动作"，与上方字段/说明之间多留一点，自成一块
        row.setContentsMargins(0, d.SET_TEST_ROW_GAP, 0, 0)
        holder = QWidget()
        holder.setLayout(row)
        form.addRow("", holder)

    @staticmethod
    def _wrap(layout) -> QWidget:
        holder = QWidget()
        holder.setLayout(layout)
        layout.setContentsMargins(0, 0, 0, 0)
        return holder

    @staticmethod
    def _select_combo(combo: QComboBox, value) -> None:
        idx = combo.findData(value)
        combo.setCurrentIndex(idx if idx >= 0 else 0)

    # ============================================================== 测试
    def _on_test(self, name: str) -> None:
        data = self._collect()
        tmp = core_config.Config(self._cfg.path)
        tmp.replace_data(data)
        btn = self._test_buttons.get(name)
        if btn:
            btn.setEnabled(False)
        label = self._test_labels.get(name)
        if label:
            label.set_color(d.TEXT_2)          # 进行中：中性灰
            label.setText("测试中，请稍候…")
        threading.Thread(target=self._run_test, args=(name, tmp),
                         daemon=True).start()

    def _run_test(self, name: str, cfg: core_config.Config) -> None:
        try:
            out = core_translate.test_backend(name, cfg, "Hello, how are you?")
            self.test_finished.emit(name, f"✔ 可用：{out}")
        except Exception as exc:  # noqa: BLE001
            msg = str(exc).strip().replace("\n", " ")[:200]
            self.test_finished.emit(name, f"✘ {msg}")

    def _on_test_finished(self, name: str, message: str) -> None:
        btn = self._test_buttons.get(name)
        if btn:
            btn.setEnabled(True)

        # 测试通过 → 自动勾选启用，避免“能用但没勾选”的坑
        extra = ""
        if message.startswith("✔"):
            if self._set_backend_checked(name, True):
                extra = "　（已自动勾选启用，记得点「保存」）"

        label = self._test_labels.get(name)
        if label:
            label.set_color(d.OK if message.startswith("✔") else d.ERROR)
            label.setText(message + extra)
        self._refresh_backend_states()

    # ============================================================== 保存
    def _on_reset(self) -> None:
        if QMessageBox.question(
            self, "恢复默认",
            "确定把所有设置恢复为默认值吗？（点「保存」后才会写入文件）"
        ) != QMessageBox.StandardButton.Yes:
            return
        self._cfg.replace_data(core_config.DEFAULTS)
        self._load_from_cfg()
        self._status.setText("已恢复默认值，点「保存」生效")

    def _on_save(self) -> None:
        # 保存前检查：一个可用接口都没有时，主动帮忙启用已配置好的接口
        data = self._collect()
        tmp = core_config.Config(self._cfg.path)
        tmp.replace_data(data)
        if not core_translate.build_chain(tmp):
            ready_unchecked = [
                (n, core_translate.backend_label(n))
                for n in core_translate.BACKEND_ORDER
                if core_translate.backend_ready(n, tmp)[0]
                and not (data.get("translate", {}).get("enabled", {}) or {}).get(n, False)
            ]
            if ready_unchecked:
                names = "、".join(label for _n, label in ready_unchecked)
                answer = QMessageBox.question(
                    self, "还没有启用翻译接口",
                    f"你已经配置好了：{names}\n"
                    "但它们都没有被勾选启用，所以翻译会报错。\n\n"
                    "是否现在自动启用它们？",
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                    QMessageBox.StandardButton.Yes,
                )
                if answer == QMessageBox.StandardButton.Yes:
                    for name, _label in ready_unchecked:
                        self._set_backend_checked(name, True)
                    data = self._collect()

        self._cfg.replace_data(data)
        try:
            path = self._cfg.save()
        except OSError as exc:
            QMessageBox.critical(self, "保存失败", str(exc))
            return
        self.saved.emit(self._cfg.copy_data())
        self._status.setText("已保存，设置立即生效")
        self._save_button.feedback("保存成功")
        self._refresh_backend_states()

    def _animate_page(self, index) -> None:
        previous = self._tabs.widget(self._previous_page)
        self._previous_page = index
        self._page_transition.play(previous, self._tabs.widget(index))

    def paintEvent(self, event):  # noqa: N802
        p = QPainter(self)
        glass.paint_background(p, self, radius=windowframe.radius(self))
        p.end()

    def _sync_motion(self):
        if d.is_glass() and glass.refresh_preferences():
            self.refresh_theme()

    def refresh_theme(self) -> None:
        self._page_transition.finish()
        self.setStyleSheet(settings_qss())
        for label in self.findChildren(HintLabel):
            label.refresh_theme()
        windowframe.apply(self)
        self.update()

    def refresh_from_config(self) -> None:
        """外部（如重新载入）后刷新界面。"""
        self._load_from_cfg()

    def showEvent(self, event):  # noqa: N802
        super().showEvent(event)
        windowframe.apply(self)
        self._navigation_marker.sync()
        self._page_transition.play(None, self._tabs.currentWidget())

    def changeEvent(self, event):  # noqa: N802
        super().changeEvent(event)
        if event.type() == QEvent.Type.ActivationChange:
            windowframe.apply(self)
        if event.type() == QEvent.Type.WindowStateChange:
            self.update()
