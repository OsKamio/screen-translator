# -*- coding: utf-8 -*-
"""
本地 OCR（文字识别）。

默认后端：RapidOCR（基于 PaddleOCR 模型 + onnxruntime 推理，
纯 pip 依赖、无需额外安装 Tesseract/Paddle 运行时）。
首次构造时会自动下载模型文件（需要网络，之后离线可用）。
"""
from __future__ import annotations

import logging
import re
import threading

import numpy as np

log = logging.getLogger(__name__)

CJK_RE = re.compile(r"[\u4e00-\u9fff]")

_engine = None
_engine_error: Exception | None = None
_engine_lock = threading.RLock()


class OcrError(RuntimeError):
    """OCR 无法使用的运行时错误（带面向用户的中文提示）。"""


def _get_engine():
    """惰性创建 RapidOCR 引擎（进程内单例）。"""
    global _engine, _engine_error
    if _engine is not None:
        return _engine
    if _engine_error is not None:
        raise _engine_error
    try:
        from rapidocr_onnxruntime import RapidOCR  # noqa: PLC0415
    except Exception as exc:  # noqa: BLE001
        _engine_error = OcrError(
            "OCR 组件未安装。请执行：\n"
            "    pip install rapidocr-onnxruntime\n"
            "（Python 3.13 请加 --ignore-requires-python）"
        )
        raise _engine_error from exc
    try:
        # 窄条截图不再强制将短边放大到 736px；保留实际文字分辨率。
        # 限制 ONNX 线程，避免三个模型的默认线程池抢占桌面响应。
        _engine = RapidOCR(intra_op_num_threads=2, inter_op_num_threads=1,
                           det_limit_type="max", det_limit_side_len=1280)
    except Exception as exc:  # noqa: BLE001
        _engine_error = OcrError(
            "OCR 模型初始化失败，请确认安装完整后重试。\n"
            f"详细信息：{exc}"
        )
        raise _engine_error from exc
    return _engine


def _text_height(box) -> float:
    """由检测框四点估算文本高度（竖直跨度）。"""
    ys = [p[1] for p in box]
    return max(ys) - min(ys)


def _assemble_lines(raw_result, min_confidence: float = 0.5) -> list[str]:
    """把 RapidOCR 的原始结果整理成「自上而下、行内从左到右」的文本行。

    raw_result: [box(4点), text, score], ...
    """
    if not raw_result:
        return []

    items = []
    for box, text, score in raw_result:
        xs = [p[0] for p in box]
        ys = [p[1] for p in box]
        items.append({
            "text": str(text).strip(),
            "score": float(score),
            "x0": min(xs), "x1": max(xs),
            "y0": min(ys), "y1": max(ys),
            "h": _text_height(box),
        })
    items = [it for it in items if it["text"] and it["score"] >= min_confidence]

    # 按 y0 升序，做简单的行聚类（同一行的 y 中心差不超过行高的 0.7 倍）
    items.sort(key=lambda it: it["y0"] + it["y1"])
    rows: list[list[dict]] = []
    for it in items:
        placed = False
        for row in rows:
            ref = row[0]
            cy = (it["y0"] + it["y1"]) / 2
            ref_cy = (ref["y0"] + ref["y1"]) / 2
            ref_h = max(ref["h"], it["h"], 1.0)
            if abs(cy - ref_cy) <= ref_h * 0.7:
                row.append(it)
                placed = True
                break
        if not placed:
            rows.append([it])

    lines = []
    for row in rows:
        row.sort(key=lambda it: it["x0"])
        lines.append("".join(it["text"] for it in row))
    return lines


def recognize(image: np.ndarray | bytes | str, min_confidence: float = 0.5) -> list[str]:
    """识别图像中的文字，返回按阅读顺序排列的文本行列表。

    image 可为：文件路径 / bytes / ndarray（OpenCV 习惯的 BGR 顺序）。
    min_confidence：低于该置信度的结果会被丢弃。
    """
    # RapidOCR 内含可变预处理状态；手动框选与实时识别不能并发调用同一实例。
    with _engine_lock:
        engine = _get_engine()
        try:
            result, _elapse = engine(image)
        except Exception as exc:  # noqa: BLE001
            raise OcrError(f"OCR 识别失败：{exc}") from exc
    return _assemble_lines(result, min_confidence)


def _merge_lines(lines: list[str]) -> str:
    """把多行合并为整段：CJK 之间不加空格，其余用空格连接。"""
    out = ""
    for line in lines:
        if not out:
            out = line
            continue
        if CJK_RE.search(out[-1]) and CJK_RE.search(line[0]):
            out += line
        else:
            out += " " + line
    return out


def recognize_as_text(image: np.ndarray | bytes | str,
                      min_confidence: float = 0.5,
                      merge_lines: bool = False) -> str:
    """识别并拼接为一段文本。

    merge_lines=False（默认）保留换行；True 则合并为整段，通常译文更连贯。
    """
    lines = recognize(image, min_confidence)
    if merge_lines:
        return _merge_lines(lines)
    return "\n".join(lines)
