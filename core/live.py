"""实时翻译引擎：可中断调度、过期结果丢弃、成功结果缓存和有限重试。"""
from __future__ import annotations
from collections import OrderedDict
from dataclasses import dataclass, replace
import json
import logging
import math
import threading
import time
import cv2
import numpy as np
from . import ocr, translate as core_translate
from .screen import CaptureSpec, capture

log = logging.getLogger(__name__)
SIG_W, SIG_H = 64, 36


class CaptureDeferred(RuntimeError):
    """界面正在切换取景方式，本轮不识别。"""


@dataclass
class LiveResult:
    original: str = ''
    translated: str = ''
    lang: str = ''
    error: str = ''
    note: str = ''
    ocr_ms: int = 0
    tr_ms: int = 0
    changed: bool = False
    busy: bool = False
    generation: int = -1
    cache_hit: bool = False


def signature(image: np.ndarray) -> np.ndarray:
    """覆盖整幅图（包括右/下边缘），缩小后再转灰度，避免大数组浮点运算。"""
    if image.ndim != 3 or image.shape[2] != 3 or not image.size:
        raise ValueError('抓屏图像无效')
    small = cv2.resize(image, (SIG_W, SIG_H), interpolation=cv2.INTER_AREA)
    return cv2.cvtColor(small, cv2.COLOR_BGR2GRAY).astype(np.float32) / 255.0


def _semantic_key(cfg):
    # 外观/窗口状态变化不应让同一段文字重新调用翻译接口。
    return json.dumps([cfg.get('translate', {}), cfg.get('ocr', {}),
                       core_translate._get_cfg(cfg, 'live.merge_lines', True)],
                      sort_keys=True, ensure_ascii=False)


def _number(cfg, path, default, minimum, maximum):
    try:
        value = float(core_translate._get_cfg(cfg, path, default))
        if math.isfinite(value):
            return max(minimum, min(maximum, value))
    except (ValueError, TypeError):
        pass
    return default


class LiveEngine:
    CACHE_LIMIT = 128
    CACHE_CHAR_LIMIT = 256_000
    CACHE_TTL = 300.0

    def __init__(self, cfg, on_result, pre_capture=None, post_capture=None):
        self._cfg = cfg
        self._semantic = _semantic_key(cfg)
        self._on_result = on_result
        self._pre_capture, self._post_capture = pre_capture, post_capture
        self._capture_provider = None
        self._spec = self._rect = None
        self._lock = threading.RLock()
        self._stop, self._force, self._paused, self._wake = (threading.Event() for _ in range(4))
        self._thread = None
        self._run_requested = False
        self._generation = 0
        self._cache = OrderedDict()
        self._cache_chars = 0
        self._clear_observation()

    def _clear_observation(self):
        self._last_sig = None
        self._last_text = ''  # 只记录已经成功交付的原文
        self._observed_text = ''
        self._ocr_valid = False
        self._last_result = None
        self._retry_at = 0.0
        self._failures = 0

    def _invalidate(self):
        self._generation += 1
        self._clear_observation()
        self._wake.set()

    def _launch(self):
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, name='live-engine', daemon=True)
        self._thread.start()

    def start(self):
        with self._lock:
            self._run_requested = True
            if self._thread and self._thread.is_alive():
                return  # 旧请求退出后由 finally 启动新一轮，绝不并发启动两条识别流水线
            self._launch()

    def stop(self, timeout: float = 0.0):
        """默认立即返回，GUI 不等待 OCR/网络；测试可指定有界等待。"""
        with self._lock:
            self._run_requested = False
            self._stop.set()
            self._invalidate()
            worker = self._thread
        if timeout and worker and worker is not threading.current_thread():
            worker.join(timeout)

    def set_capture_hooks(self, pre_capture=None, post_capture=None):
        with self._lock:
            self._pre_capture, self._post_capture = pre_capture, post_capture

    def set_capture_provider(self, provider=None):
        with self._lock:
            if provider is not self._capture_provider:
                self._capture_provider = provider
                self._invalidate()

    def pause(self, paused=True):
        with self._lock:
            if bool(paused) != self._paused.is_set():
                self._paused.set() if paused else self._paused.clear()
                self._invalidate()
                if not paused:
                    self._force.set()

    def is_paused(self):
        return self._paused.is_set()

    def force_refresh(self):
        with self._lock:
            self._force.set()
            self._wake.set()

    def reset_cache(self):
        with self._lock:
            self._invalidate()

    def update_spec(self, spec, rect):
        with self._lock:
            if spec == self._spec and rect == self._rect:
                return
            self._spec, self._rect = spec, rect
            self._invalidate()

    def update_config(self, cfg):
        semantic = _semantic_key(cfg)
        with self._lock:
            self._cfg = cfg
            if semantic != self._semantic:
                self._semantic = semantic
                self._cache.clear()
                self._cache_chars = 0
                self._invalidate()
            self._wake.set()

    def _valid(self, generation):
        with self._lock:
            return generation == self._generation and not self._stop.is_set() and not self._paused.is_set()

    def is_current(self, result):
        return result.generation == -1 or self._valid(result.generation)

    def _loop(self):
        try:
            while not self._stop.is_set():
                # 先清唤醒标志，再读取快照；之后到来的刷新/配置变更不会被睡眠吃掉。
                self._wake.clear()
                with self._lock:
                    cfg, spec, rect, generation = self._cfg, self._spec, self._rect, self._generation
                interval = _number(cfg, 'live.interval_ms', 1200, 250, 60_000)/1000
                if self._paused.is_set() or spec is None or rect is None or rect.isEmpty():
                    self._wake.wait(.3)
                    continue
                started = time.perf_counter()
                try:
                    self._tick(cfg, spec, rect, generation)
                except Exception as exc:
                    self._failure(str(exc), generation)
                    log.warning('实时处理失败 (%s)', type(exc).__name__)
                if not self._stop.is_set():
                    self._wake.wait(max(.05, interval-(time.perf_counter()-started)))
        finally:
            with self._lock:
                if self._thread is threading.current_thread():
                    self._thread = None
                    if self._run_requested:
                        self._launch()

    def _failure(self, error, generation, text='', ocr_ms=0):
        with self._lock:
            if not self._valid(generation):
                return
            self._failures = min(5, self._failures+1)
            self._retry_at = time.monotonic()+min(8.0, .8*2**(self._failures-1))
        self._emit(LiveResult(original=text, error=error, ocr_ms=ocr_ms, changed=True), generation)

    def _tick(self, cfg, spec, rect, generation=None):
        with self._lock:
            generation = self._generation if generation is None else generation
            if not self._valid(generation):
                return
            pre, post = self._pre_capture, self._post_capture
            provider = self._capture_provider or capture
            forced = self._force.is_set()
            self._force.clear()
        try:
            if pre:
                pre()
            image = provider(spec, rect)
        except CaptureDeferred:
            return
        finally:
            if post:
                post()
        if not self._valid(generation):
            return
        if image is None:
            with self._lock:
                due = forced or time.monotonic() >= self._retry_at
            if due:
                self._failure('抓取屏幕区域失败', generation)
            return
        sig = signature(image)
        with self._lock:
            previous = self._last_sig
            if previous is None or previous.shape != sig.shape:
                diff = 1.0
            else:
                delta = np.abs(sig-previous).ravel()
                # 字幕往往只占截图的一小部分，整图均值会把换字信号稀释掉。
                # 取变化最大的 10% 网格的均值，保留稀疏文字变化的灵敏度。
                count = max(1, delta.size//10)
                diff = float(np.partition(delta, -count)[-count:].mean())
            threshold = _number(cfg, 'live.diff_threshold', .02, 0, 1)
            visual_change = previous is None or diff >= threshold
            retry = self._retry_at > 0
            if retry and not forced and not visual_change and time.monotonic() < self._retry_at:
                return
            if not (forced or visual_change or retry):
                return
            reuse_ocr = retry and self._ocr_valid and not forced and not visual_change
            text = self._observed_text
        ocr_ms = 0
        if not reuse_ocr:
            self._emit(LiveResult(busy=True, note='识别中…'), generation)
            started = time.perf_counter()
            try:
                text = ocr.recognize_as_text(image,
                    min_confidence=_number(cfg, 'ocr.min_confidence', .5, 0, 1),
                    merge_lines=bool(core_translate._get_cfg(cfg, 'live.merge_lines', True)) or
                                bool(core_translate._get_cfg(cfg, 'ocr.merge_lines', False)))
            except Exception as exc:
                with self._lock:
                    if self._valid(generation):
                        self._last_sig, self._ocr_valid = sig, False
                self._failure(str(exc), generation)
                return
            text = text.strip()
            ocr_ms = round((time.perf_counter()-started)*1000)
            with self._lock:
                if not self._valid(generation):
                    return
                # 与最后一次真正识别的画面比，缓慢变化也能累计到阈值。
                self._last_sig, self._observed_text = sig, text
                self._ocr_valid = True
        if not self._valid(generation):
            return
        with self._lock:
            if not forced and not retry and text == self._last_text and self._last_result is not None:
                result = replace(self._last_result, busy=False, changed=False, ocr_ms=ocr_ms)
                self._emit(result, generation)  # 必须给 busy 一个完成态
                return
            cached = None if forced or retry else self._cache.get(text)
            if cached and time.monotonic()-cached[2] > self.CACHE_TTL:
                self._cache_chars -= len(text)+len(cached[0])
                del self._cache[text]
                cached = None
        tr_ms = 0
        if not text:
            result = LiveResult(note='未识别到文字', ocr_ms=ocr_ms, changed=True)
        else:
            if cached:
                translated, lang, _timestamp = cached
            else:
                self._emit(LiveResult(original=text, busy=True, note='翻译中…', ocr_ms=ocr_ms), generation)
                started = time.perf_counter()
                try:
                    with core_translate.cancellation_scope(lambda: not self._valid(generation)):
                        translated, lang = core_translate.translate(text, cfg)
                except core_translate.TranslationCancelled:
                    return
                except Exception as exc:
                    self._failure(str(exc), generation, text, ocr_ms)
                    return
                tr_ms = round((time.perf_counter()-started)*1000)
            result = LiveResult(original=text, translated=translated, lang=lang,
                ocr_ms=ocr_ms, tr_ms=tr_ms, changed=True, cache_hit=bool(cached))
        with self._lock:
            if not self._valid(generation):
                return
            self._last_text, self._last_result = text, result
            self._retry_at, self._failures = 0.0, 0
            if text and not cached:
                old = self._cache.pop(text, None)
                if old:
                    self._cache_chars -= len(text)+len(old[0])
                self._cache[text] = (result.translated, result.lang, time.monotonic())
                self._cache_chars += len(text)+len(result.translated)
                while len(self._cache) > self.CACHE_LIMIT or self._cache_chars > self.CACHE_CHAR_LIMIT:
                    key, value = self._cache.popitem(last=False)
                    self._cache_chars -= len(key)+len(value[0])
            elif cached:
                self._cache.move_to_end(text)
        self._emit(result, generation)

    def _emit(self, result, generation=None):
        with self._lock:
            generation = self._generation if generation is None else generation
            if not self._valid(generation):
                return
            result.generation = generation
        try:
            self._on_result(result)
        except Exception:
            log.exception('实时结果回调失败')
