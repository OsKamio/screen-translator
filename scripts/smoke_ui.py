# -*- coding: utf-8 -*-
"""UI 冒烟测试（offscreen 平台）：
构建悬浮球/遮罩/结果面板/主控制器，验证信号流与绘制不崩溃。
"""
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QRect, QTimer  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ui.floatball import FloatBall  # noqa: E402
from ui.overlay import CaptureOverlay  # noqa: E402
from ui.resultwin import ResultWindow  # noqa: E402


def main() -> int:
    app = QApplication(sys.argv)
    ok = []

    ball = FloatBall()
    ball.show()
    ball.set_busy(True, "识别中")
    ball.set_busy(False)

    overlay = CaptureOverlay()
    overlay.show()
    # 模拟框选过程中的选区绘制路径（含尺寸标注、角落块）
    from PySide6.QtCore import QPoint  # noqa: E402
    overlay._begin = QPoint(120, 90)
    overlay._cur = QPoint(430, 260)
    img = overlay.grab()          # 强制离屏渲染 paintEvent
    assert not img.isNull(), "overlay grab failed"
    overlay._begin = None
    overlay._cur = None
    ok.append("overlay selection paint OK")

    result = ResultWindow()
    result.show_result(
        original="Hello World OCR 123\n屏幕翻译中文测试",
        translated="你好，世界 OCR 123\n屏幕翻译中文测试",
        src_lang="en", note="",
    )
    result.show()
    result.show_error("所选区域没有识别到文字。\n请框选包含文字的部分再试。")
    result.reset_style()
    result.show_result(
        original="已是最新版本", translated="已是最新版本",
        src_lang="zh-CN", note="原文已是中文",
    )
    result.show()
    ok.append("result windows OK")

    # 信号流：模拟点击悬浮球 -> 进入框选
    ball.clicked.connect(lambda: ok.append("clicked fired"))
    ball.clicked.emit()
    ok.append("ball show state busy=%s visible=%s" % (ball.is_busy(), ball.isVisible()))

    # place_near 布局不越界
    result.place_near(QRect(100, 100, 300, 200), overlay.geometry())
    ok.append("place_near OK at %s" % result.geometry())

    print("; ".join(ok), flush=True)
    print("SMOKE_UI_PASS", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
