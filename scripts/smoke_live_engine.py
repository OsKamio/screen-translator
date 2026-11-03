# -*- coding: utf-8 -*-
"""实时翻译引擎逻辑测试（用假的截图/OCR/翻译，验证节流与去重）。"""
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

from PySide6.QtCore import QRect  # noqa: E402

import core.live as L  # noqa: E402
from core import config as C  # noqa: E402
from core.screen import CaptureSpec  # noqa: E402

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001
        pass

FRAME = {"img": None, "text": "", "tr": "", "fail": None, "ocr_calls": 0,
         "tr_calls": 0}


def img_with(block_value: int) -> np.ndarray:
    a = np.full((100, 400, 3), 255, dtype=np.uint8)
    a[40:80, 50:350] = block_value
    return a


def fake_capture(spec, rect):
    return None if FRAME["img"] is None else FRAME["img"].copy()


def fake_ocr(image, min_confidence=0.5, merge_lines=False):
    FRAME["ocr_calls"] += 1
    return FRAME["text"]


def fake_translate(text, cfg=None, dst=None):
    FRAME["tr_calls"] += 1
    if FRAME["fail"]:
        raise RuntimeError(FRAME["fail"])
    return FRAME["tr"], "en"


def main() -> int:
    # 打桩：替换引擎内部使用的截图/OCR/翻译
    L.capture = fake_capture
    L.ocr.recognize_as_text = fake_ocr
    L.core_translate.translate = fake_translate

    cfg = C.deep_merge(C.DEFAULTS, {"live": {"diff_threshold": 0.02}})
    results = []
    engine = L.LiveEngine(cfg, on_result=results.append)
    spec = CaptureSpec(QRect(0, 0, 1920, 1080), 1.0)
    rect = QRect(10, 10, 400, 100)

    ok = []

    # 1) 首帧：应识别并翻译（busy + 结果，共 2 条事件）
    FRAME.update(img=img_with(255), text="Hello world", tr="你好，世界", fail=None)
    engine._tick(cfg, spec, rect)
    assert len(results) == 3 and all(r.busy for r in results[:-1]), results
    assert results[0].busy is True
    assert results[-1].translated == "你好，世界", results[-1]
    assert FRAME["ocr_calls"] == 1 and FRAME["tr_calls"] == 1
    ok.append("first frame -> OCR+translate")

    # 2) 画面无变化：不应再次识别
    results.clear()
    engine._tick(cfg, spec, rect)
    assert not results, results
    assert FRAME["ocr_calls"] == 1, FRAME["ocr_calls"]
    ok.append("unchanged frame -> skipped")

    # 3) 画面变化但文本相同：识别一次、不重复翻译（只会有“识别中”事件）
    results.clear()
    FRAME["img"] = img_with(180)
    engine._tick(cfg, spec, rect)
    assert results[0].busy and not results[-1].busy, results
    assert results[-1].translated == "你好，世界"  # 去重也必须结束 busy 状态
    assert FRAME["ocr_calls"] == 2, FRAME["ocr_calls"]
    assert FRAME["tr_calls"] == 1, "文本没变却重复翻译了"
    ok.append("changed frame + same text -> no retranslate")

    # 4) 文本变化：重新翻译并上报
    results.clear()
    FRAME.update(img=img_with(120), text="Second line", tr="第二行")
    engine._tick(cfg, spec, rect)
    assert len(results) == 3, results
    assert results[-1].translated == "第二行"
    assert FRAME["tr_calls"] == 2
    ok.append("text changed -> translated again")

    # 5) 识别不到文字：给出提示且不翻译
    results.clear()
    FRAME.update(img=img_with(60), text="")
    engine._tick(cfg, spec, rect)
    assert results and results[-1].note == "未识别到文字", results
    assert FRAME["tr_calls"] == 2
    ok.append("empty text -> note only")

    # 6) 翻译失败：上报错误且不崩
    results.clear()
    FRAME.update(img=img_with(20), text="Fail case", fail="模拟接口故障")
    engine._tick(cfg, spec, rect)
    assert results and "模拟接口故障" in results[-1].error, results
    ok.append("translate error -> reported")

    # 7) 强制刷新：即使画面没变也会识别
    results.clear()
    FRAME["fail"] = None
    engine._force.set()
    engine._tick(cfg, spec, rect)
    assert FRAME["ocr_calls"] == 6, FRAME["ocr_calls"]
    ok.append("force refresh works")

    # 8) 暂停时循环空转（不识别）
    FRAME["ocr_calls"] = 100
    engine.pause(True)
    FRAME.update(img=img_with(240), text="Paused text")
    engine._tick(cfg, spec, rect)   # _tick 本身仍会跑，但主循环不会调用它
    assert engine.is_paused()
    ok.append("pause flag")

    print("checks:", " | ".join(ok), flush=True)
    print("LIVE_ENGINE_PASS", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
