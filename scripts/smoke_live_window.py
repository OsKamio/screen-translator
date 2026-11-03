# -*- coding: utf-8 -*-
"""实时翻译窗口交互测试（offscreen）：管理栏按钮、字号调整、滚轮滚动。"""
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

from PySide6.QtCore import QPoint, Qt  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from core import config as C  # noqa: E402
from ui.livewin import LiveWindow  # noqa: E402

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001
        pass

LONG_TEXT = "\n".join(
    f"第 {i} 行译文内容，用来把内容撑得足够长，以便验证滚动查看上下文的功能。"
    for i in range(24))


def main() -> int:
    app = QApplication(sys.argv)
    cfg = C.Config(os.path.join(HERE, "_tmp_cfg", "livewin.json"))
    cfg.load()

    win = LiveWindow()
    win.apply_config(cfg)
    win.resize(560, 180)
    win.show()
    app.processEvents()

    ok = []

    # ---- 1) 顶部管理栏按钮命中 ----
    btns = win._bar_buttons()
    names = set(btns.keys())
    assert names == {"close", "refresh", "font_inc", "font_dec", "source_frame"}, names
    for name, rect in btns.items():
        assert win._button_at(rect.center()) == name, name
    # 按钮应位于窗口右侧且不重叠
    xs = sorted((r.left(), name) for name, r in btns.items())
    lefts = [x for x, _ in xs]
    assert len(set(lefts)) == len(lefts), "按钮位置重叠"
    ok.append(f"管理栏按钮 {sorted(names)}")

    # ---- 2) 字号调整 + 信号 ----
    sizes = []
    win.font_size_changed.connect(sizes.append)
    before = win._font_size
    win._adjust_font(+2)
    assert win._font_size == before + 2, win._font_size
    win._adjust_font(-4)
    assert win._font_size == max(12, before - 2), win._font_size
    assert sizes == [before + 2, max(12, before - 2)], sizes
    # 越界保护
    for _ in range(40):
        win._adjust_font(+5)
    assert win._font_size <= 40, win._font_size
    for _ in range(60):
        win._adjust_font(-5)
    assert win._font_size >= 12, win._font_size
    ok.append("字号调整与边界保护")

    # ---- 3) 长内容应产生滚动范围 ----
    win._font_size = 22
    win.set_result(LONG_TEXT, "source text", status="")
    app.processEvents()
    total, visible = win._content_extent()
    assert total > visible, f"长内容应超出可视区（total={total}, visible={visible}）"
    assert win._max_scroll > 0, win._max_scroll
    ok.append(f"内容总高 {total} > 可视 {visible}，可滚动 {win._max_scroll}px")

    # ---- 4) 滚轮向下 / 向上（应吸附到整行，避免半行残影）----
    from PySide6.QtGui import QFontMetrics  # noqa: E402
    from ui import design as d  # noqa: E402

    line_h = max(1, QFontMetrics(d.font(win._font_size, d.W_MED)).lineSpacing())
    win._scroll_by(60)
    assert win._scroll > 0, win._scroll
    assert win._scroll % line_h == 0, f"未按整行对齐：{win._scroll} / 行高 {line_h}"
    win._scroll_by(100000)
    assert win._scroll == win._max_scroll, (win._scroll, win._max_scroll)
    win._scroll_by(-100000)
    assert win._scroll == 0, win._scroll
    ok.append(f"滚动上下与边界钳制（行高 {line_h}px 对齐）")

    # ---- 5) 短内容不应有滚动范围 ----
    win.set_result("短译文", "", status="")
    total2, visible2 = win._content_extent()
    assert win._max_scroll == 0, win._max_scroll
    assert win._scroll == 0
    win._scroll_by(120)
    assert win._scroll == 0, "短内容不该能滚动"
    ok.append("短内容不可滚动")

    # ---- 6) 内容更新时的滚动策略 ----
    win.set_result(LONG_TEXT, "", status="")
    win._scroll_by(80)
    keep = win._scroll
    assert keep > 0
    # 用户正在翻上下文时来新内容：应保持位置（不跳回顶部）
    win.set_result(LONG_TEXT + "\n追加一行。", "", status="")
    assert win._scroll > 0, "查看上下文时不应被拽回顶部"
    ok.append(f"内容更新时保持滚动位置（{keep} → {win._scroll}）")

    print("checks:", " | ".join(ok), flush=True)
    print("LIVEWIN_PASS", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
