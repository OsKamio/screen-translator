# -*- coding: utf-8 -*-
"""结果窗口 place_near 位置钳制专项测试（offscreen）。"""
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QRect  # noqa: E402
from PySide6.QtGui import QGuiApplication  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from ui.resultwin import ResultWindow  # noqa: E402

LONG = "\n".join(f"这是第 {i} 行用于撑高测试窗口的译文内容，尽量让它足够长。" for i in range(120))


def run_case(result: ResultWindow, work: QRect, name: str,
             anchor: QRect, original: str, translated: str) -> bool:
    result.show_result(original, translated, "en", note="")
    result.place_near(anchor, work)
    g = result.frameGeometry()
    inside = (g.top() >= work.top() and g.bottom() <= work.bottom()
              and g.left() >= work.left() and g.right() <= work.right())
    visible = g.height() <= work.height()
    print(f"[{name}] geom={g} inside={inside} h_in_work={visible}", flush=True)
    return inside and visible


def main() -> int:
    app = QApplication(sys.argv)
    work = QGuiApplication.primaryScreen().availableGeometry()
    result = ResultWindow()
    ok = True

    # a) 短文本，选区在屏幕中央
    ok &= run_case(result, work, "a 中央+短文本",
                   QRect(work.center().x() - 100, work.center().y(), 200, 120),
                   "short", "短译文")

    # b) 超长译文，选区在屏幕中央
    ok &= run_case(result, work, "b 中央+超长文本",
                   QRect(work.center().x() - 100, work.center().y(), 200, 120),
                   "long", LONG)

    # c) 选区贴近屏幕底部
    ok &= run_case(result, work, "c 底部选区",
                   QRect(work.center().x() - 100, work.bottom() - 60, 200, 40),
                   "short", "短译文")

    # d) 选区贴近屏幕顶部
    ok &= run_case(result, work, "d 顶部选区",
                   QRect(work.center().x() - 100, work.top() + 5, 200, 40),
                   "short", "短译文")

    # e) 超长译文 + 底部选区（最坏情形）
    ok &= run_case(result, work, "e 底部选区+超长文本",
                   QRect(work.center().x() - 100, work.bottom() - 60, 200, 40),
                   "long", LONG)

    # f) 错误信息展示时也不越界
    result.show_error("所选区域没有识别到文字。\n请框选包含文字的部分再试。")
    result.place_near(QRect(work.center().x() - 100, work.center().y(), 200, 10), work)
    g = result.frameGeometry()
    ok &= (g.top() >= work.top() and g.bottom() <= work.bottom()
           and g.left() >= work.left() and g.right() <= work.right())
    print(f"[f 错误展示] geom={g}", flush=True)

    print("PLACE_PASS" if ok else "PLACE_FAIL", flush=True)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
