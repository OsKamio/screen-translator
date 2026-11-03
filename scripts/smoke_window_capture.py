# -*- coding: utf-8 -*-
"""无 UI 测试原生截图返回校验及超时回退，不访问真实桌面。"""
import os
import sys
import struct
from types import SimpleNamespace
from unittest.mock import patch
import numpy as np
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from PySide6.QtCore import QRect
import core.window_capture as W
from core.screen import CaptureSpec

spec = CaptureSpec(QRect(0, 0, 100, 100), 1.5)
rect = QRect(4, 6, 20, 10)
image = np.full((15, 30, 4), 210, dtype=np.uint8)
valid = struct.pack("<II", 30, 15)+image.tobytes()
outputs = [SimpleNamespace(returncode=0, stdout=valid)]
requests = []
def run(args, **kwargs):
    requests.append(kwargs)
    item = outputs.pop(0)
    if isinstance(item, Exception):
        raise item
    return item
with patch.object(W, "match_monitor", return_value={"left": 50, "top": 70}), patch.object(W.subprocess, "run", side_effect=run):
    captured = W.capture_window(spec, rect, [1234])
    assert captured.shape == (15, 30, 3) and (captured == 210).all()
    import json
    request = json.loads(requests[-1]["input"])
    assert request == {"rect": [56, 79, 30, 15], "ignore": [1234]}, request
    assert requests[-1]["timeout"] == 2.5
    for reply in [b"", valid[:-1], struct.pack("<II", 1, 1)+b"x"*4,
                  struct.pack("<II", 30, 15)+bytes(30*15*4)]:
        outputs.append(SimpleNamespace(returncode=0, stdout=reply))
        assert W.capture_window(spec, rect) is None
    outputs.append(SimpleNamespace(returncode=1, stdout=valid))
    assert W.capture_window(spec, rect) is None
    outputs.append(W.subprocess.TimeoutExpired("print-window", 2.5))
    assert W.capture_window(spec, rect) is None
    outputs.append(OSError("could not start helper"))
    assert W.capture_window(spec, rect) is None
    assert W.capture_window(spec, QRect(-4, 0, 20, 10)) is None
print("WINDOW_CAPTURE_PASS")
