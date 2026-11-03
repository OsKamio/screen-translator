# -*- coding: utf-8 -*-
"""
屏幕翻译 —— 入口与主控制器。

流程：悬浮球点击 → 全屏框选 → 后台线程(截图+OCR+翻译) → 结果面板。
右键悬浮球可打开「设置」，配置翻译接口（DeepL / 百度 / 微软 / LLM / 自定义）与界面外观。

运行：python main.py
"""
from __future__ import annotations

import ctypes
import logging
import os
import sys
import threading
import time

from PySide6.QtCore import QObject, QRect, Qt, QTimer, Signal, Slot
from PySide6.QtGui import QGuiApplication, QIcon
from PySide6.QtNetwork import QLocalServer, QLocalSocket
from PySide6.QtWidgets import QApplication, QMessageBox

from core import config as core_config
from core import ocr, translate as core_translate
from core.live import CaptureDeferred, LiveEngine, LiveResult
from core.window_capture import capture_window
from core.screen import CaptureSpec, capture
from ui import motion as ui_motion
from ui import design as ui_design
from ui.floatball import FloatBall
from ui.livewin import LiveWindow
from ui.sourceframe import SourceFrame
from ui.overlay import CaptureOverlay
from ui.resultwin import ResultWindow
from ui.settings import SettingsWindow

APP_NAME = "ScreenTranslator"
SINGLETON_KEY = "screen-translator-singleton"
OVERLAY_DISMISS_MS = 110  # 遮罩隐藏后等待一帧再抓屏，避免截到遮罩本身
LIVE_GEOMETRY_SAVE_DELAY_MS = 600

log = logging.getLogger(__name__)


def app_icon_path() -> str:
    """应用图标路径（assets/screen-translator.ico）。"""
    return os.path.join(os.path.dirname(os.path.abspath(__file__)),
                        "assets", "screen-translator.ico")


def _set_windows_app_id() -> None:
    """给进程一个 AppUserModelID，否则 Windows 任务栏会显示 python 的图标。"""
    try:
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
            "ScreenTranslator.Desktop.1")
    except Exception:  # noqa: BLE001
        log.debug("设置 AppUserModelID 失败", exc_info=True)


def setup_application(app: QApplication) -> None:
    """应用级初始化：退出策略、字体、图标、全局样式。

    抽成函数是为了让自检脚本调用同一段代码 —— 否则脚本自己建 QApplication
    会绕过这些设置，测出来的行为和生产不一致（曾在别处因此漏掉一个真实 bug）。
    """
    # 关键：不要因为“最后一个普通窗口关闭”就退出程序。
    # 悬浮球 / 实时窗口 / 结果卡片都是 Qt.Tool（不算主窗口），设置窗口是唯一的普通窗口，
    # 默认行为下关闭设置窗口会导致整个程序退出、悬浮球一起消失。
    # 现在只有用户在菜单里显式“退出”才结束。
    app.setQuitOnLastWindowClosed(False)

    ui_design.set_theme("system")
    # 使用 Windows 原生阅读字体，字号统一按逻辑像素。
    app.setFont(ui_design.font(ui_design.F_BODY))

    # 应用图标：设置窗口标题栏左上角、任务栏、消息框都用它
    _set_windows_app_id()
    icon_file = app_icon_path()
    if os.path.exists(icon_file):
        app.setWindowIcon(QIcon(icon_file))
    else:
        log.warning("未找到图标文件：%s", icon_file)

    # 工具提示也用设计系统（否则弹回系统浅色外观）
    app.setStyleSheet(f"""
        QToolTip {{
            background: {ui_design.hexs(ui_design.INK_700)};
            color: {ui_design.hexs(ui_design.TEXT)};
            border: 1px solid {ui_design.hexs(ui_design.LINE)};
            border-radius: {int(ui_design.R_SM)}px;
            padding: 6px 9px;
        }}
    """)


class Controller(QObject):
    """把悬浮球 / 遮罩 / 结果面板 / 实时窗口 / 设置窗口与后台任务串起来。"""

    # (原文, 译文, 源语言, 错误, 选区QRect)
    task_done = Signal(str, str, str, str, QRect)
    # 实时翻译引擎的结果（后台线程 → 主线程）
    live_result = Signal(object)
    # 后台线程请求在主线程执行一次界面操作（PySide6 里不能用 Q_ARG(object))
    gui_call = Signal(object)

    def __init__(self, cfg: core_config.Config):
        super().__init__()

        self.cfg = cfg
        self._live_mode_enabled = bool(cfg.get("live.enabled", False))
        ui_design.set_theme(cfg.get("ui.theme", "system"))
        ui_motion.configure(cfg.get("ui.animations", True))
        self.primary = QGuiApplication.primaryScreen()
        self.ball = FloatBall()
        self.overlay = CaptureOverlay()
        self.result = ResultWindow()

        self._running_task = False
        self._settings: SettingsWindow | None = None
        self._live: LiveWindow | None = None
        self._engine: LiveEngine | None = None
        self._source_frame: SourceFrame | None = None
        self._selecting_live_source = False
        self._capture_generation = 0
        self._geometry_timer = QTimer(self)
        self._geometry_timer.setSingleShot(True)
        self._geometry_timer.setInterval(LIVE_GEOMETRY_SAVE_DELAY_MS)
        self._geometry_timer.timeout.connect(self._save_live_geometry)

        # ---- 信号接线 ----
        self.ball.clicked.connect(self.start_capture)
        self.ball.settings_requested.connect(self.open_settings)
        self.ball.live_toggle_requested.connect(self.toggle_live_window)
        self.ball.exit_requested.connect(self.quit)
        self.overlay.region_selected.connect(self._on_region_selected)
        self.overlay.cancelled.connect(self._on_capture_cancelled)
        self.result.closed.connect(self.result.hide)
        self.result.recapture_requested.connect(self.start_capture)
        self.task_done.connect(self._on_task_done)
        self.live_result.connect(self._on_live_result)
        self.gui_call.connect(self._run_in_gui_slot)
        QGuiApplication.styleHints().colorSchemeChanged.connect(self._on_system_scheme_changed)

        # ---- 应用配置 + 初始位置 ----
        self.apply_ui_config()
        self._place_ball_initial()
        if self.cfg.get("live.enabled", False):
            QTimer.singleShot(300, self.show_live_window)

    # ====================================================================
    # 配置
    # ====================================================================
    def apply_ui_config(self) -> None:
        """把配置中的界面参数应用到悬浮球、结果卡片与实时窗口。"""
        ui_motion.configure(self.cfg.get("ui.animations", True))
        self._refresh_theme()
        self.ball.apply_config(self.cfg)
        self.result.apply_config(self.cfg)
        if self._live is not None:
            self._live.apply_config(self.cfg)
            self._live.apply_click_through(bool(self.cfg.get("live.click_through", False)))
            self._live.set_paused(self._engine.is_paused() if self._engine else False)
            self._sync_live_capture_mode()
            self._push_live_spec()
        if self._engine is not None:
            self._engine.update_config(self.cfg.copy_data())
        if not core_translate.build_chain(self.cfg):
            self.ball.setToolTip("⚠ 还没有可用的翻译接口\n右键悬浮球 → 设置…")

    def _refresh_theme(self, scheme=None) -> None:
        ui_design.set_theme(self.cfg.get("ui.theme", "system"), scheme)
        self.result.refresh_theme()
        if self._settings is not None:
            self._settings.refresh_theme()
        for widget in (self.ball, self.overlay, self._live, self._source_frame):
            if widget is not None:
                widget.update()
        app = QApplication.instance()
        app.setStyleSheet(f"""QToolTip {{ background: {ui_design.hexs(ui_design.INK_700)};
            color: {ui_design.hexs(ui_design.TEXT)}; border: 1px solid {ui_design.hexs(ui_design.LINE)};
            padding: 7px 10px; }}""")

    def _on_system_scheme_changed(self, scheme) -> None:
        if self.cfg.get("ui.theme", "system") in ("system", "glass"):
            self._refresh_theme(scheme)

    def open_settings(self) -> None:
        """打开设置窗口（非模态，可复用）。"""
        if self._settings is None:
            self._settings = SettingsWindow(self.cfg)
            self._settings.saved.connect(self._on_settings_saved)
            self._settings.toggle_live_requested.connect(self.toggle_live_window)
        self._settings.show()
        self._settings.raise_()
        self._settings.activateWindow()
        self._sync_live_capture_mode()  # 排除新建的设置窗，避免下层抓屏识别自己的设置。

    def _on_settings_saved(self, data: dict) -> None:
        # 设置窗口与 Controller 共享 Config，saved 发出前它已写入新值。
        was_enabled = self._live_mode_enabled
        self.cfg.replace_data(data)
        self.apply_ui_config()
        # 只在「工作模式」**真的切换**时才同步窗口显隐。
        # 不能按"当前值"判断：手动打开的实时窗口（悬浮球右键 / 设置页按钮）
        # 并不会改变 live.enabled（工作模式仍是"手动框选"），
        # 于是保存任何一项设置都会被当成"切到手动模式"→ 窗口被关掉
        # —— 就是用户反复反馈的"实时翻译窗口又没了"（2026-09-21）。
        now_enabled = bool(self.cfg.get("live.enabled", False))
        self._live_mode_enabled = now_enabled
        if now_enabled != was_enabled:
            if now_enabled:
                self.show_live_window()
            else:
                self.hide_live_window()
        if not core_translate.build_chain(self.cfg):
            QMessageBox.warning(None, "屏幕翻译",
                               core_translate.no_backend_message(self.cfg))

    # ====================================================================
    # 实时翻译窗口
    # ====================================================================
    def show_live_window(self) -> None:
        """显示实时翻译窗口并启动引擎。"""
        if self._live is None:
            self._live = LiveWindow()
            self._live.capture_mode_changed.connect(self._sync_live_capture_mode)
            self._live.source_select_requested.connect(self.select_live_source)
            self._live.source_frame_toggled.connect(self._on_live_source_frame_toggled)
            self._live.overlay_mode_requested.connect(self.restore_live_overlay)
            self._live.closed.connect(self.hide_live_window)
            self._live.quit_requested.connect(self.quit)
            self._live.settings_requested.connect(self.open_settings)
            self._live.refresh_requested.connect(self._on_live_refresh)
            self._live.pause_toggled.connect(self._on_live_pause)
            self._live.geometry_changed.connect(self._on_live_geometry_changed)
            self._live.font_size_changed.connect(self._on_live_font_size)
            self._live.apply_config(self.cfg)

        self._live.suppress_content(False)
        self._live.show()
        self._live.raise_()
        self._live.apply_click_through(bool(self.cfg.get("live.click_through", False)))
        self.ball.set_live_visible(True)

        if self._engine is None:
            self._engine = LiveEngine(
                self.cfg.copy_data(),
                on_result=lambda res: self.live_result.emit(res),
                # 窗口稳定后选择桌面排除、直接读取应用窗口或独立取景。
            )
        self._engine.update_config(self.cfg.copy_data())
        self._engine.start()
        self._engine.reset_cache()
        self._engine.force_refresh()

        # 窗口位置稍后才稳定（show + 点击穿透会重建窗口），延迟同步抓取区域
        QTimer.singleShot(120, self._after_live_shown)

    def _after_live_shown(self) -> None:
        if self._live is None:
            return
        if not self._live.isVisible():
            return
        self._sync_live_capture_mode()
        self._push_live_spec()

    def _sync_live_capture_mode(self) -> None:
        if self._live is None or not self._live.isVisible():
            return
        self._capture_generation += 1
        generation = self._capture_generation
        self._live.suppress_content(False)
        if self._engine is None:
            return
        # 本机排除 / 独立取景 / 直接抓下层窗口，三条路径均不清空译文。
        self._engine.set_capture_hooks(None, None)
        separate = bool(self.cfg.get("live.separate_capture", False))
        if separate or self._live.capture_excluded():
            self._engine.set_capture_provider(None)
        else:
            ignored = tuple(int(w.winId()) for w in
                            (self._live, self.ball, self.overlay, self.result, self._source_frame, self._settings)
                            if w is not None)
            def native_capture(spec, rect):
                image = capture_window(spec, rect, ignored)
                if image is None:
                    self._post_to_gui(lambda: self._fallback_live_source(QRect(rect), generation))
                    raise CaptureDeferred()
                return image
            self._engine.set_capture_provider(native_capture)
        if self._source_frame is not None and not separate:
            self._source_frame.hide()

    def _fallback_live_source(self, source: QRect, generation: int) -> None:
        if generation != self._capture_generation or self._live is None or not self._live.isVisible():
            return
        self.cfg.set("live.separate_capture", True)
        self.cfg.set("live.source_geometry", [source.x(), source.y(), source.width(), source.height()])
        self._sync_live_capture_mode()
        if self._push_live_spec():
            self._live.set_status("已分开取景，右键可重新选择区域")
        self._geometry_timer.start()

    def _place_live_outside_source(self, source: QRect) -> bool:
        """选择原文旁边的空位；不够放时暂停，绝不恢复周期性清空。"""
        live = self._live
        if live is None:
            return False
        if not live.geometry().intersects(source.adjusted(-6, -6, 6, 6)):
            return True
        screen = self.primary.availableGeometry()
        gap = 12
        spaces = [
            QRect(screen.left(), screen.top(), screen.width(), max(0, source.top()-screen.top()-gap)),
            QRect(screen.left(), source.bottom()+1+gap, screen.width(), max(0, screen.bottom()-source.bottom()-gap)),
            QRect(screen.left(), screen.top(), max(0, source.left()-screen.left()-gap), screen.height()),
            QRect(source.right()+1+gap, screen.top(), max(0, screen.right()-source.right()-gap), screen.height()),
        ]
        spaces = [r for r in spaces if r.width() >= live.MIN_W and r.height() >= live.MIN_H]
        if not spaces:
            return False
        room = max(spaces, key=lambda r: min(r.width(), live.width())*min(r.height(), live.height()))
        width, height = min(live.width(), room.width()), min(live.height(), room.height())
        x = max(room.left(), min(source.left(), room.right()-width+1))
        y = max(room.top(), min(source.top(), room.bottom()-height+1))
        live.setGeometry(x, y, width, height)
        return True

    def select_live_source(self) -> None:
        if self._running_task or self.overlay.isVisible() or self._live is None:
            return
        self._selecting_live_source = True
        if self._engine is not None:
            self._engine.pause(True)
        self._live.hide()
        if self._source_frame is not None:
            self._source_frame.hide()
        self.overlay.begin_capture()

    def _finish_live_source_selection(self, rect: QRect | None) -> None:
        self._selecting_live_source = False
        self.overlay.hide()
        if rect is not None:
            self.cfg.set("live.separate_capture", True)
            self.cfg.set("live.source_geometry", [rect.x(), rect.y(), rect.width(), rect.height()])
        self._live.show()
        self._live.raise_()
        self._sync_live_capture_mode()
        # 遮罩退出合成后才恢复取景，避免 OCR 识别到框选说明文字。
        def resume():
            if self._live is None or not self._live.isVisible():
                return
            self._push_live_spec()
            if self._engine is not None:
                self._engine.pause(self._live.is_paused())
            self._geometry_timer.start()
        QTimer.singleShot(OVERLAY_DISMISS_MS, resume)

    def restore_live_overlay(self) -> None:
        geom = self.cfg.get("live.source_geometry", None)
        if self._live is not None and isinstance(geom, (list, tuple)) and len(geom) == 4:
            self._live.setGeometry(self._live._clamp_to_screen(QRect(*map(int, geom))))
        self.cfg.set("live.separate_capture", False)
        self.cfg.set("live.source_geometry", None)
        self._sync_live_capture_mode()
        self._push_live_spec()
        self._on_live_refresh()
        self._geometry_timer.start()

    def _post_to_gui(self, func) -> None:
        """把一次 GUI 操作投递到主线程执行（不阻塞当前线程）。

        用 Signal(object) 而不是 QMetaObject.invokeMethod + Q_ARG(object, ...)：
        PySide6 找不到 "object" 的 QMetaType，Q_ARG 会直接失败。
        """
        try:
            self.gui_call.emit(func)
        except Exception:  # noqa: BLE001
            log.warning("无法把实时抓屏操作投递到主线程", exc_info=True)

    @Slot(object)
    def _run_in_gui_slot(self, func) -> None:
        func()

    def hide_live_window(self) -> None:
        self._capture_generation += 1
        if self._source_frame is not None:
            self._source_frame.hide()
        if self._engine is not None:
            # 停止前断开外部钩子，避免退出时出现额外界面操作。
            self._engine.set_capture_hooks(None, None)
            self._engine.stop()
        if self._live is not None:
            self._live.suppress_content(False)
            self._live.hide()                    # 用户主动隐藏：真 hide
        self.ball.set_live_visible(False)

    def toggle_live_window(self) -> None:
        if self._live is not None and self._live.isVisible():
            self.hide_live_window()
        else:
            self.show_live_window()

    def _push_live_spec(self) -> bool:
        """把实时窗口的位置与大小同步给引擎（逻辑坐标 + 屏幕 DPR 快照）。"""
        if self._live is None or self._engine is None:
            return False
        rect = self._live.window_geometry_for_capture()
        if self.cfg.get("live.separate_capture", False):
            geom = self.cfg.get("live.source_geometry", None)
            if isinstance(geom, (list, tuple)) and len(geom) == 4:
                rect = QRect(*map(int, geom)).intersected(self.primary.geometry())
            else:
                self.cfg.set("live.source_geometry", [rect.x(), rect.y(), rect.width(), rect.height()])
            if not rect.isEmpty():
                if self._source_frame is None:
                    self._source_frame = SourceFrame()
                self._source_frame.set_source(rect)
                self._sync_source_frame_visibility()
                if not self._place_live_outside_source(rect):
                    self._engine.update_spec(None, None)
                    self._live.set_status("取景区域太大，右键重新选择较小区域")
                    return False
        if rect.isEmpty():
            self._engine.update_spec(None, None)
            self._live.set_status("取景区域不在当前屏幕，右键重新选择")
            return False
        spec = CaptureSpec(self.primary.geometry(), self.primary.devicePixelRatio())
        self._engine.update_spec(spec, QRect(rect))
        return True

    def _on_live_geometry_changed(self, _rect: QRect) -> None:
        self._push_live_spec()
        if self.cfg.get("live.remember_geometry", True):
            self._geometry_timer.start()

    def _save_live_geometry(self) -> None:
        """防抖保存实时窗口的状态（位置、尺寸、字号等）。"""
        if self._live is not None:
            g = self._live.geometry()
            self.cfg.set("live.geometry", [g.x(), g.y(), g.width(), g.height()])
        try:
            self.cfg.save()
        except OSError:
            log.warning("保存实时窗口配置失败")

    def _sync_source_frame_visibility(self) -> None:
        if self._source_frame is None:
            return
        visible = bool(self._live is not None and self._live.isVisible()
                       and self.cfg.get("live.separate_capture", False)
                       and self.cfg.get("live.show_source_frame", True)
                       and not self._selecting_live_source)
        if self._source_frame.isVisible() != visible:
            self._source_frame.setVisible(visible)

    def _on_live_source_frame_toggled(self, visible: bool) -> None:
        """只控制黄框外观，不重启引擎或改变取景位置。"""
        self.cfg.set("live.show_source_frame", bool(visible))
        self._sync_source_frame_visibility()
        self._geometry_timer.start()

    def _on_live_font_size(self, size: int) -> None:
        """顶部管理栏调整了字号 → 写回配置并防抖保存。"""
        self.cfg.set("live.font_size", int(size))
        self._geometry_timer.start()

    def _on_live_refresh(self) -> None:
        if self._engine is not None:
            self._engine.force_refresh()

    def _on_live_pause(self, paused: bool) -> None:
        if self._live is not None:
            self._live.set_paused(paused)
        if self._engine is not None:
            self._engine.pause(paused)

    @Slot(object)
    def _on_live_result(self, res: LiveResult) -> None:
        if self._live is None or not self._live.isVisible() or self._selecting_live_source:
            return
        if self._engine is not None and not self._engine.is_current(res):
            return
        if self._live.is_paused():
            return
        if res.busy:
            self._live.set_status(res.note or "识别中…")
            return
        if res.error:
            self._live.set_error(res.error)
            return

        status = ""
        if self.cfg.get("live.show_stats", False):
            bits = [f"OCR {res.ocr_ms}ms"]
            if res.tr_ms:
                bits.append(f"翻译 {res.tr_ms}ms")
            if res.cache_hit:
                bits.append("缓存命中")
            status = " · ".join(bits)
        if res.note and not res.translated:
            status = res.note
        self._live.set_result(res.translated, res.original, status=status)

    # ====================================================================
    # 状态流
    # ====================================================================
    def _place_ball_initial(self) -> None:
        avail = self.primary.availableGeometry()
        self.ball.move(avail.right() - self.ball.width() - 24,
                       avail.top() + 48)
        self.ball.show()

    def start_capture(self) -> None:
        """进入框选模式（悬浮球/结果窗都先隐藏）。"""
        if self._running_task or self.overlay.isVisible():
            return
        self.result.hide()
        self.ball.hide()
        self.overlay.begin_capture()

    def _on_capture_cancelled(self) -> None:
        if self._selecting_live_source:
            self._finish_live_source_selection(None)
            return
        self.overlay.hide()
        self._running_task = False
        self.ball.show()

    def _on_region_selected(self, rect: QRect) -> None:
        """用户松手框定区域：隐藏遮罩，进入后台识别+翻译。"""
        if self._selecting_live_source:
            self._finish_live_source_selection(QRect(rect))
            return
        self.overlay.hide()
        self._running_task = True

        self.ball.show()
        self.ball.set_busy(True, "识别中")
        self.ball.raise_()

        spec = CaptureSpec(self.primary.geometry(),
                           self.primary.devicePixelRatio())
        # 配置快照：避免后台线程读取时配置被并发修改
        snapshot = self.cfg.copy_data()
        thread = threading.Thread(
            target=self._do_task, args=(spec, QRect(rect), snapshot),
            name="translate-worker", daemon=True,
        )
        thread.start()

    # ------------------------------------------------------------------ 任务
    def _do_task(self, spec: CaptureSpec, rect: QRect, cfg: dict) -> None:
        """后台线程：截图 → OCR → 翻译。"""
        try:
            time.sleep(OVERLAY_DISMISS_MS / 1000.0)
            image = capture(spec, rect)
            if image is None:
                raise RuntimeError("抓取屏幕区域失败，请重试。")

            ocr_cfg = cfg.get("ocr", {}) or {}
            text = ocr.recognize_as_text(
                image,
                min_confidence=float(ocr_cfg.get("min_confidence", 0.5) or 0.5),
                merge_lines=bool(ocr_cfg.get("merge_lines", False)),
            )
            if not text.strip():
                raise RuntimeError("所选区域没有识别到文字。\n"
                                   "请框选包含文字的部分再试。")

            translated, lang = core_translate.translate(text, cfg)
            self.task_done.emit(text, translated, lang, "", QRect(rect))
        except Exception as exc:  # noqa: BLE001
            self.task_done.emit("", "", "", str(exc), QRect(rect))

    @Slot(str, str, str, str, QRect)
    def _on_task_done(self, original: str, translated: str,
                      lang: str, error: str, rect: QRect) -> None:
        """回到主线程：收尾展示。"""
        self._running_task = False
        self.ball.set_busy(False)

        if error:
            self.result.reset_style()
            self.result.show_error(error)
        else:
            note = ""
            if translated == original:
                target = self.cfg.get("translate.target_lang", "zh-CN")
                note = f"原文已是{core_translate.lang_name(target)}，未翻译"
            self.result.reset_style()
            self.result.show_result(original, translated, lang, note)
            if self.cfg.get("ui.auto_copy", False) and translated:
                QGuiApplication.clipboard().setText(translated)
                self.ball.setToolTip("已复制译文到剪贴板")

        self.ball.show()
        self.ball.raise_()
        if error:
            # 错误提示优先放在屏幕中部附近
            work = self.primary.availableGeometry()
            anchor = QRect(work.center().x() - 100, work.center().y(),
                           200, 10)
            self.result.place_near(anchor, work)
        else:
            self.result.place_near(rect, self.primary.availableGeometry())
        self.result.show()
        self.result.raise_()
        self.result.activateWindow()
        self._nudge_ball_away_from_result()

    def _nudge_ball_away_from_result(self) -> None:
        """若悬浮球被结果窗盖住，把它挪到结果窗右侧。"""
        rr = self.result.frameGeometry()
        br = self.ball.frameGeometry()
        if rr.intersects(br):
            self.ball.move(rr.right() + 12, self.ball.y())
            avail = self.primary.availableGeometry()
            if self.ball.frameGeometry().right() > avail.right():
                self.ball.move(avail.right() - self.ball.width() - 8,
                               rr.bottom() + 12)

    # ------------------------------------------------------------------ 退出
    def quit(self) -> None:
        self.hide_live_window()
        QApplication.quit()


def _is_already_running() -> bool:
    """通过本地命名管道检测是否已有实例在运行。"""
    probe = QLocalSocket()
    probe.connectToServer(SINGLETON_KEY)
    if probe.waitForConnected(150):
        probe.disconnectFromServer()
        return True
    return False


def main() -> int:
    if len(sys.argv) == 3 and sys.argv[1] == "--self-test":
        from core.selftest import run
        return run(sys.argv[2])
    # 控制台/日志统一 UTF-8，避免中文或符号在 GBK 环境下输出报错
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:  # noqa: BLE001
            pass

    QApplication.setApplicationName(APP_NAME)
    app = QApplication(sys.argv)
    setup_application(app)

    if _is_already_running():
        QMessageBox.warning(None, "屏幕翻译",
                            "屏幕翻译已经在运行了，请查看屏幕右上角的悬浮球。")
        return 1

    server = QLocalServer()
    server.removeServer(SINGLETON_KEY)
    server.listen(SINGLETON_KEY)

    cfg = core_config.load_config()
    ctrl = Controller(cfg)

    exit_code = app.exec()
    server.close()
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
