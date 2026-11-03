# -*- coding: utf-8 -*-
"""验证：保存设置不会误关「手动打开」的实时窗口。

回归背景（用户反馈"实时翻译窗口又没了"）：
``Controller._on_settings_saved`` 曾按 ``live.enabled`` 的**当前值**同步窗口显隐，
而手动打开实时窗口（悬浮球右键 / 设置页按钮）时 ``live.enabled`` 仍是 False
（工作模式是"手动框选"），于是**保存任何设置**都会命中"切到手动模式"分支
→ ``hide_live_window()`` → 窗口消失。用户验收设置排版时反复保存，就反复中招。

三个场景：
  1. 手动打开窗口 + 保存一份"模式没变"的设置 → 窗口必须**还在**（真实可见性）；
  2. 模式 false→true → 应当显示；
  3. 模式 true→false → 应当隐藏。
场景 2/3 只验证**决策**（打桩记录调用），避免在自检里真的启动 OCR 引擎。

用 offscreen 即可（不需要真桌面：窗口可见性与调用决策都与平台无关）。
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

from core import config as C  # noqa: E402

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001
        pass

import main as M  # noqa: E402
from ui.livewin import LiveWindow  # noqa: E402


def main() -> int:
    app = QApplication([])
    M.setup_application(app)                 # 与生产同一条初始化路径
    # 保存后会检查翻译链，没接口会弹 QMessageBox —— 自检里挡掉
    M.core_translate.build_chain = lambda _cfg: True

    tmp = os.path.join(HERE, "_tmp_cfg")
    os.makedirs(tmp, exist_ok=True)
    cfg = C.Config(os.path.join(tmp, "live_after_settings.json"))
    cfg.load()
    cfg.set("live.enabled", False)           # 工作模式：手动框选
    ctrl = M.Controller(cfg)

    problems: list[str] = []

    # ---- 场景 1：手动打开 → 保存一份模式没变的设置 ----
    live = LiveWindow()
    live.apply_config(cfg)
    ctrl._live = live
    live.show()
    app.processEvents()
    if not live.isVisible():
        problems.append("前置条件失败：窗口没能显示出来（测试环境问题，不是产品问题）")

    ctrl._on_settings_saved(cfg.copy_data())   # 模式仍是 False
    app.processEvents()
    if not live.isVisible():
        problems.append("保存一份『模式没变』的设置后，手动打开的实时窗口被关掉了"
                        "（= 用户反馈的现象）")
    else:
        print("· 场景1 手动打开 + 无关保存：窗口仍在 ✓", flush=True)

    # ---- 场景 2/3：模式切换才同步（打桩只看决策）----
    calls: list[str] = []
    ctrl.show_live_window = lambda: calls.append("show")
    ctrl.hide_live_window = lambda: calls.append("hide")

    was = bool(cfg.get("live.enabled", False))
    data = cfg.copy_data()
    data.setdefault("live", {})["enabled"] = not was
    ctrl._on_settings_saved(data)
    if calls == ["show"]:
        print("· 场景2 手动框选 → 自动实时翻译：触发显示 ✓", flush=True)
    else:
        problems.append(f"切到自动实时翻译模式应触发 show，实际 {calls}")

    calls.clear()
    data = cfg.copy_data()
    data.setdefault("live", {})["enabled"] = was
    ctrl._on_settings_saved(data)
    if calls == ["hide"]:
        print("· 场景3 自动实时翻译 → 手动框选：触发隐藏 ✓", flush=True)
    else:
        problems.append(f"切回手动框选模式应触发 hide，实际 {calls}")

    print(flush=True)
    if problems:
        for p in problems:
            print(f"  ✘ {p}", flush=True)
        print("LIVE_AFTER_SETTINGS_FAIL", flush=True)
        return 1
    print("保存设置不会误关手动打开的实时窗口，模式切换仍会同步", flush=True)
    print("LIVE_AFTER_SETTINGS_PASS", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())