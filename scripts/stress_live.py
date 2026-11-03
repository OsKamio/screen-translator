# -*- coding: utf-8 -*-
"""压力测试：反复开关实时窗口 / 引擎线程 / 抓屏避让钩子 / 设置页切换。

重点覆盖跨线程交互（工作线程 → GUI 线程）与窗口生命周期，
这类问题表现为访问违例崩溃（0xc0000005 那一类）。

OCR 与翻译打桩（省时间、不消耗接口额度），但截图、线程、钩子、
窗口显示隐藏都走真实代码路径。
"""
import os
import sys
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

import core.live as L  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from core import config as C  # noqa: E402

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001
        pass

# ---- 打桩：OCR / 翻译（保留真实截图与线程）----
L.ocr.recognize_as_text = lambda *a, **k: "Stress test source text"
L.core_translate.translate = lambda text, cfg=None, dst=None: ("压力测试译文", "en")

from main import Controller  # noqa: E402


def pump(app, ms: int) -> None:
    end = time.time() + ms / 1000.0
    while time.time() < end:
        app.processEvents()
        time.sleep(0.01)


def main() -> int:
    app = QApplication(sys.argv)
    cfg = C.Config(os.path.join(HERE, "_tmp_cfg", "stress.json"))
    cfg.load()
    # 加速：检查间隔调小，让引擎多跑几轮
    cfg.set("live.interval_ms", 300)
    cfg.set("live.enabled", False)

    ctrl = Controller(cfg)
    print("controller ready", flush=True)

    rounds = 6
    for i in range(rounds):
        ctrl.show_live_window()
        pump(app, 900)                      # 引擎跑几轮（含避让钩子往返）
        if i % 2 == 0:
            ctrl.open_settings()
            for tab in range(5):
                ctrl._settings._tabs.setCurrentIndex(tab)
                pump(app, 60)
            ctrl._settings.hide()
        ctrl.hide_live_window()             # 引擎 stop（可能与避让钩子交错）
        pump(app, 250)
        if ctrl._live is not None:
            print(f"  round {i+1}: live visible={ctrl._live.isVisible()} "
                  f"excluded={ctrl._live.capture_excluded()}", flush=True)

    # 再来一轮：窗口显示状态下直接关闭窗口 + 快速重开
    ctrl.show_live_window()
    pump(app, 400)
    ctrl._live.close()
    pump(app, 200)
    ctrl.show_live_window()
    pump(app, 400)
    ctrl.hide_live_window()
    pump(app, 200)

    print("STRESS_PASS", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
