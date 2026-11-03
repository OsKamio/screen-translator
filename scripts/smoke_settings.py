# -*- coding: utf-8 -*-
"""设置窗口 UI 测试（offscreen）：构建、载入、修改→收集、保存落盘、后端列表操作。"""
import json
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001
        pass

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from core import config as C  # noqa: E402
from ui.settings import SettingsWindow  # noqa: E402

TMP = os.path.join(HERE, "_tmp_cfg")
PATH = os.path.join(TMP, "settings_test.json")


def main() -> int:
    app = QApplication(sys.argv)
    os.makedirs(TMP, exist_ok=True)
    if os.path.exists(PATH):
        os.remove(PATH)

    cfg = C.Config(PATH)
    cfg.load()

    win = SettingsWindow(cfg)
    ok = []

    # ---- 1) 结构 ----
    tabs = [win._tabs.tabText(i) for i in range(win._tabs.count())]
    assert tabs == ["翻译", "翻译接口", "实时翻译", "界面", "关于"], tabs
    ok.append(f"tabs {tabs}")

    # ---- 2) 后端列表：勾选状态与顺序 ----
    n = win._backend_list.count()
    assert n == 7, n
    first = win._backend_list.item(0).data(Qt.ItemDataRole.UserRole)
    assert first == "deepl", first
    mymem_item = None
    for i in range(n):
        it = win._backend_list.item(i)
        if it.data(Qt.ItemDataRole.UserRole) == "mymemory":
            mymem_item = it
    assert mymem_item is not None and mymem_item.checkState() == Qt.CheckState.Checked
    ok.append("backend list")

    # ---- 3) 界面值 → collect ----
    data = win._collect()
    assert data["ui"]["ball_size"] == 58, data["ui"]["ball_size"]
    win._cfg.set("ui.ball_size", 70)          # 模拟用户改控件（直接改底层数据再载入）
    # 通过真实控件修改更贴近使用：设置 spin（这里用 _binds 中的 setter 反向找不方便，
    # 改为直接改数据 + 重新载入，再收集回来）
    win._load_from_cfg()
    data = win._collect()
    assert data["ui"]["ball_size"] == 70
    ok.append("ui bind roundtrip")

    # ---- 4) 勾选 DeepL 并填 key → 顺序表与状态刷新 ----
    for i in range(n):
        it = win._backend_list.item(i)
        if it.data(Qt.ItemDataRole.UserRole) == "deepl":
            it.setCheckState(Qt.CheckState.Checked)
    win._refresh_backend_states()
    data = win._collect()
    assert data["translate"]["enabled"]["deepl"] is True
    assert data["translate"]["backends"][0] == "deepl"
    txt = win._backend_list.item(0).text()
    assert "缺 DeepL API Key" in txt, txt          # 未填 key → 状态提示
    ok.append(f"deepl state -> {txt.split('—')[-1].strip()[:24]}")

    # ---- 5) 上移/下移 ----
    win._backend_list.setCurrentRow(0)
    win._move_backend(1)
    data = win._collect()
    assert data["translate"]["backends"][1] == "deepl", data["translate"]["backends"][:3]
    ok.append("reorder")

    # ---- 6) 保存落盘 ----
    win._on_save()
    assert os.path.exists(PATH), "配置未落盘"
    with open(PATH, "r", encoding="utf-8") as fh:
        saved = json.load(fh)
    assert saved["ui"]["ball_size"] == 70
    assert saved["translate"]["enabled"]["deepl"] is True
    ok.append("saved to disk")

    # ---- 7) 恢复默认 ----
    cfg2 = C.Config(PATH)
    cfg2.load()
    win2 = SettingsWindow(cfg2)
    win2._cfg.replace_data(C.DEFAULTS)
    win2._load_from_cfg()
    assert win2._collect()["ui"]["ball_size"] == 58
    ok.append("reset defaults")

    # ---- 8) “已配置但未勾选”的提示 + tab 徽标 + 自动勾选 ----
    for i in range(win2._backend_list.count()):
        it = win2._backend_list.item(i)
        if it.data(Qt.ItemDataRole.UserRole) == "mymemory":
            it.setCheckState(Qt.CheckState.Unchecked)
    win2._refresh_backend_states()
    mem_text = None
    for i in range(win2._backend_list.count()):
        it = win2._backend_list.item(i)
        if it.data(Qt.ItemDataRole.UserRole) == "mymemory":
            mem_text = it.text()
    assert mem_text and "已配置，待勾选" in mem_text, mem_text
    # 一个都没启用 → tab 上应出现 ⚠
    for i in range(win2._backend_list.count()):
        win2._backend_list.item(i).setCheckState(Qt.CheckState.Unchecked)
    win2._refresh_backend_states()
    assert "⚠" in win2._tabs.tabText(0), win2._tabs.tabText(0)
    ok.append(f"unchecked hint -> {mem_text.split('—')[-1].strip()}")

    # 测试通过后的自动勾选
    changed = win2._set_backend_checked("mymemory", True)
    assert changed is True
    assert win2._collect()["translate"]["enabled"]["mymemory"] is True
    assert "⚠" not in win2._tabs.tabText(0), win2._tabs.tabText(0)
    ok.append("auto-enable on test success")

    print("checks:", " | ".join(ok), flush=True)
    print("SETTINGS_PASS", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
