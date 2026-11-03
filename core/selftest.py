"""安装版离线自检：空白配置、实际 OCR、窗口与隔离擷取；不读取用户配置。"""
from __future__ import annotations

import json
from pathlib import Path
import tempfile
import threading
import time
import traceback

import numpy as np
from PySide6.QtCore import QPoint, QRect, QTimer, Qt
from PySide6.QtGui import QColor, QFont, QImage, QPainter
from PySide6.QtWidgets import QApplication, QLabel


def run(report_path: str) -> int:
    import main
    from core.config import Config
    from core.ocr import recognize_as_text
    from core.screen import CaptureSpec, capture
    from core.window_capture import capture_window
    from ui.settings import SettingsWindow
    from ui.livewin import LiveWindow
    from ui.resultwin import ResultWindow
    from ui.sourceframe import SourceFrame

    report = Path(report_path).resolve()
    report.parent.mkdir(parents=True, exist_ok=True)
    app = QApplication([])
    main.setup_application(app)
    checks = {}
    errors = []
    holder = []
    completed = threading.Event()
    started = time.perf_counter()
    with tempfile.TemporaryDirectory(prefix="screen-translator-selftest-", dir=report.parent) as temp:
        cfg = Config(str(Path(temp)/"config.json"))  # Never load the real configuration.
        cfg.set("ui.animations", False)
        cfg.set("live.capture_excluded", False)
        source = QLabel("SCREEN TRANSLATOR 2026")
        source.setWindowFlags(Qt.WindowType.WindowStaysOnTopHint)
        source.setStyleSheet("background: white; color: black; padding: 24px;")
        source.setFont(QFont("Arial", 26))
        source.resize(650, 150)
        source.move(app.primaryScreen().availableGeometry().topLeft()+QPoint(80, 80))
        source.show()
        holder.append(source)

        def worker(spec, rect, ignored):
            try:
                image = QImage(720, 110, QImage.Format.Format_RGB32)
                image.fill(QColor("white"))
                painter = QPainter(image)
                painter.setPen(QColor("black")); painter.setFont(QFont("Arial", 30))
                painter.drawText(QRect(20, 10, 680, 90), Qt.AlignmentFlag.AlignVCenter,
                                 "SCREEN TRANSLATOR 2026")
                painter.end()
                sample = np.frombuffer(image.bits(), dtype=np.uint8).reshape(110, image.bytesPerLine())
                sample = sample[:, :720*4].reshape(110, 720, 4)[:, :, :3].copy()
                value = recognize_as_text(sample)
                checks["bundled_ocr_models"] = "SCREEN" in value.upper() and "2026" in value
                checks["desktop_capture"] = capture(spec, rect) is not None
                frame = capture_window(spec, rect, ignored)
                checks["isolated_window_capture"] = frame is not None and frame.shape[:2] == (
                    round(rect.height()*spec.dpr), round(rect.width()*spec.dpr))
            except Exception:
                errors.append(traceback.format_exc())
            finally:
                completed.set()

        def prepare():
            try:
                for cls in (SettingsWindow, LiveWindow, ResultWindow, SourceFrame):
                    widget = cls(cfg) if cls is SettingsWindow else cls()
                    widget.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
                    if hasattr(widget, "apply_config"): widget.apply_config(cfg)
                    if cls is LiveWindow: widget.set_result("示例译文", "Sample", status="自检")
                    if cls is ResultWindow: widget.show_result("Sample", "示例译文", "en")
                    widget.show(); widget.grab(); holder.append(widget)
                checks["settings_live_result_windows"] = True
                checks["application_icon"] = Path(main.app_icon_path()).is_file()
                screen = source.screen()
                spec = CaptureSpec(screen.geometry(), screen.devicePixelRatio())
                rect = QRect(source.mapToGlobal(QPoint(20, 20)), source.size()).adjusted(0, 0, -40, -40)
                ignored = [int(widget.winId()) for widget in holder if widget is not source]
                threading.Thread(target=worker, args=(spec, rect, ignored), daemon=True).start()
            except Exception:
                errors.append(traceback.format_exc()); completed.set()

        timer = QTimer()
        def poll():
            if completed.is_set() or time.perf_counter()-started > 70:
                if not completed.is_set(): errors.append("Self-test timed out")
                app.quit()
        timer.timeout.connect(poll); timer.start(50)
        QTimer.singleShot(400, prepare)
        app.exec()
        for widget in holder: widget.close()
    passed = len(checks) == 5 and all(checks.values()) and not errors
    report.write_text(json.dumps({"passed": passed, "checks": checks,
        "elapsed_seconds": round(time.perf_counter()-started, 2), "errors": errors},
        ensure_ascii=False, indent=2), encoding="utf-8")
    return 0 if passed else 1
