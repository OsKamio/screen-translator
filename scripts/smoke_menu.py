# -*- coding: utf-8 -*-
"""悬浮球右键菜单行为测试（offscreen）。"""
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from ui.floatball import FloatBall  # noqa: E402


def main() -> int:
    app = QApplication(sys.argv)
    ball = FloatBall()

    menu = ball._build_menu()
    texts = [a.text() for a in menu.actions()]
    print("menu actions:", texts, flush=True)
    assert texts == ["框选翻译", "实时翻译窗口", "", "设置…", "", "退出"], \
        f"unexpected menu: {texts}"

    clicked = []
    quit_ = []
    settings_ = []
    live_ = []
    ball.clicked.connect(lambda: clicked.append(1))
    ball.exit_requested.connect(lambda: quit_.append(1))
    ball.settings_requested.connect(lambda: settings_.append(1))
    ball.live_toggle_requested.connect(lambda: live_.append(1))

    acts = menu.actions()
    acts[0].trigger()   # 框选翻译
    acts[1].trigger()   # 实时翻译窗口
    acts[3].trigger()   # 设置…
    acts[5].trigger()   # 退出

    print("clicked fired:", len(clicked), "live fired:", len(live_),
          "settings fired:", len(settings_), "quit fired:", len(quit_),
          flush=True)
    assert clicked == [1], "框选翻译 action 未触发 clicked"
    assert live_ == [1], "实时窗口 action 未触发 live_toggle_requested"
    assert settings_ == [1], "设置 action 未触发 settings_requested"
    assert quit_ == [1], "退出 action 未触发 exit_requested"

    # 实时窗口显示时菜单文案应变
    ball.set_live_visible(True)
    texts2 = [a.text() for a in ball._build_menu().actions()]
    assert texts2[1].startswith("隐藏实时翻译窗口"), texts2

    print("MENU_PASS", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
