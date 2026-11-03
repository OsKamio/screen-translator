"""实时流水线回归：用同步屏障确定性覆盖竞态，不联网。"""
from __future__ import annotations
import copy
import os
import sys
import threading
import time
import unittest
from unittest.mock import patch
import numpy as np
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from PySide6.QtCore import QRect
from core.config import DEFAULTS
from core import live as L, translate as T, ocr as O
from core.screen import CaptureSpec


class LiveQuality(unittest.TestCase):
    def setUp(self):
        self.cfg = copy.deepcopy(DEFAULTS)
        self.spec = CaptureSpec(QRect(0, 0, 1000, 800), 1.)
        self.rect = QRect(0, 0, 200, 80)
        self.image = np.full((80, 200, 3), 255, np.uint8)
        self.results = []
        self.engine = L.LiveEngine(self.cfg, self.results.append)
        self.capture = patch.object(L, 'capture', side_effect=lambda *a: self.image.copy()).start()
        self.ocr = patch.object(O, 'recognize_as_text', return_value='Hello').start()
        self.tr = patch.object(T, 'translate', side_effect=lambda text, cfg: ('tr:'+text, 'en')).start()
        self.addCleanup(patch.stopall)
        self.addCleanup(lambda: self.engine.stop(timeout=1))

    def tick(self):
        self.engine._tick(self.cfg, self.spec, self.rect)

    def test_snapshot_parameters_and_zero(self):
        self.cfg['live'].update(diff_threshold=.4, merge_lines=False)
        self.cfg['ocr'].update(min_confidence=0, merge_lines=False)
        self.tick()
        self.ocr.assert_called_once()
        self.assertEqual(self.ocr.call_args.kwargs, dict(min_confidence=0., merge_lines=False))
        self.image[:] = 200
        self.tick()
        self.assertEqual(self.ocr.call_count, 1)

    def test_gradual_changes_accumulate(self):
        self.tick()
        for shade in [254, 253, 252, 251, 250]:
            self.image[:] = shade
            self.tick()
        self.assertEqual(self.ocr.call_count, 1)
        self.image[:] = 248
        self.tick()
        self.assertEqual(self.ocr.call_count, 2)

    def test_same_text_always_finishes_busy(self):
        self.tick()
        self.image[:] = 0
        self.tick()
        self.assertFalse(self.results[-1].busy)
        self.assertEqual(self.results[-1].translated, 'tr:Hello')
        self.assertEqual(self.tr.call_count, 1)

    def test_sparse_caption_change_is_not_diluted_by_background(self):
        self.tick()
        self.image[25:30, 40:90] = 0  # 不足整图 2%，仍应识别文字局部变化
        self.ocr.return_value = 'Updated caption'
        self.tick()
        self.assertEqual(self.ocr.call_count, 2)

    def test_retry_translation_without_repeating_ocr(self):
        self.tr.side_effect = [RuntimeError('offline'), ('online', 'en')]
        self.tick()
        self.assertTrue(self.results[-1].error)
        self.tick()  # 未到重试时间，不打接口
        self.assertEqual(self.tr.call_count, 1)
        self.engine._retry_at = time.monotonic()-1
        self.tick()
        self.assertEqual(self.tr.call_count, 2)
        self.assertEqual(self.ocr.call_count, 1)
        self.assertEqual(self.results[-1].translated, 'online')

    def test_ocr_error_retries_ocr_after_backoff(self):
        self.ocr.side_effect = [RuntimeError('OCR failed'), 'Hello']
        self.tick()
        self.tick()
        self.assertEqual(self.ocr.call_count, 1)
        self.engine._retry_at = time.monotonic()-1
        self.tick()
        self.assertEqual(self.ocr.call_count, 2)
        self.assertFalse(self.results[-1].error)

    def test_force_bypasses_dedup_and_cache(self):
        self.tick()
        self.engine.force_refresh()
        self.tick()
        self.assertEqual(self.ocr.call_count, 2)
        self.assertEqual(self.tr.call_count, 2)

    def test_failed_force_retries_instead_of_restoring_old_cache(self):
        self.tick()
        self.tr.side_effect = [RuntimeError('offline'), ('fresh', 'en')]
        self.engine.force_refresh()
        self.tick()
        self.engine._retry_at = time.monotonic()-1
        self.tick()
        self.assertEqual(self.tr.call_count, 3)
        self.assertEqual(self.results[-1].translated, 'fresh')

    def test_repeated_subtitle_uses_cache_and_has_limit(self):
        self.engine.CACHE_LIMIT = 2
        for text, shade in [('A', 255), ('B', 0), ('A', 128)]:
            self.ocr.return_value = text
            self.image[:] = shade
            self.tick()
        self.assertEqual(self.tr.call_count, 2)
        self.assertTrue(self.results[-1].cache_hit)
        self.ocr.return_value = 'C'
        self.image[:] = 0
        self.tick()
        self.assertEqual(list(self.engine._cache), ['A', 'C'])

    def test_semantic_config_and_same_geometry(self):
        self.engine.update_spec(self.spec, self.rect)
        self.tick()
        old = self.engine._generation
        self.engine.update_spec(self.spec, QRect(self.rect))
        self.cfg['ui']['theme'] = 'dark'
        self.engine.update_config(copy.deepcopy(self.cfg))
        self.assertEqual(self.engine._generation, old)
        self.cfg['translate']['target_lang'] = 'de'
        self.engine.update_config(copy.deepcopy(self.cfg))
        self.assertFalse(self.engine.is_current(self.results[-1]))
        self.tick()
        self.assertEqual(self.tr.call_count, 2)

    def test_region_change_discards_inflight_ocr(self):
        started, release = threading.Event(), threading.Event()
        def slow(*a, **k):
            started.set()
            self.assertTrue(release.wait(2))
            return 'Old region'
        self.ocr.side_effect = slow
        worker = threading.Thread(target=self.tick)
        worker.start()
        try:
            self.assertTrue(started.wait(1))
            self.engine.update_spec(self.spec, QRect(30, 40, 50, 60))
        finally:
            release.set()
            worker.join(2)
        self.assertFalse(worker.is_alive())
        self.assertEqual(self.tr.call_count, 0)
        self.assertIsNone(self.engine._last_sig)

    def test_stop_nonblocking_and_reopen_has_one_pipeline(self):
        started, release, delivered = threading.Event(), threading.Event(), threading.Event()
        count = []
        def slow(*a, **k):
            count.append(1)
            if len(count) == 1:
                started.set()
                release.wait(2)
            return 'New'
        self.ocr.side_effect = slow
        self.engine._on_result = lambda res: delivered.set() if res.translated else None
        self.engine.update_spec(self.spec, self.rect)
        self.engine.start()
        try:
            self.assertTrue(started.wait(1))
            stamp = time.perf_counter()
            self.engine.stop()
            self.assertLess(time.perf_counter()-stamp, .05)
            old = self.engine._thread
            self.engine.start()
            self.assertIs(self.engine._thread, old)
            self.assertEqual(self.tr.call_count, 0)
            release.set()
            self.assertTrue(delivered.wait(1))
        finally:
            release.set()
            self.engine.stop(timeout=1)
        self.assertEqual(self.tr.call_count, 1)

    def test_refresh_interrupts_long_interval(self):
        self.cfg['live']['interval_ms'] = 10_000
        done = threading.Event()
        self.engine._on_result = lambda res: done.set() if res.translated else None
        self.engine.update_spec(self.spec, self.rect)
        self.engine.start()
        self.assertTrue(done.wait(1))
        done.clear()
        self.engine.force_refresh()
        self.assertTrue(done.wait(.5))

    def test_signature_covers_bottom_and_right_edges(self):
        image = np.zeros((109, 211, 3), np.uint8)
        before = L.signature(image)
        image[-1, :, :] = 255
        image[:, -1, :] = 255
        self.assertGreater(float(np.abs(L.signature(image)-before).sum()), 0)


class OcrSerialization(unittest.TestCase):
    def test_same_engine_never_runs_concurrently(self):
        lock, entered, release = threading.Lock(), threading.Event(), threading.Event()
        counts = [0, 0]
        def fake(image):
            with lock:
                counts[0] += 1
                counts[1] = max(counts)
            entered.set()
            release.wait(1)
            with lock:
                counts[0] -= 1
            return None, None
        with patch.object(O, '_get_engine', return_value=fake):
            a = threading.Thread(target=O.recognize, args=(np.zeros((40, 80, 3), np.uint8),))
            b = threading.Thread(target=O.recognize, args=(np.zeros((40, 80, 3), np.uint8),))
            a.start(); entered.wait(1); b.start()
            release.set(); a.join(2); b.join(2)
        self.assertEqual(counts[1], 1)


class TranslationQuality(unittest.TestCase):
    def config(self):
        cfg = copy.deepcopy(DEFAULTS)
        cfg['translate'].update(backends=['custom', 'mymemory'], enabled={'custom': True, 'mymemory': True})
        cfg['api']['custom']['url'] = 'http://127.0.0.1/translate'
        return cfg

    def test_cancel_prevents_fallback(self):
        cancelled = threading.Event()
        def first(*a):
            cancelled.set()
            raise RuntimeError('fake failure')
        with patch.dict(T.BACKENDS, custom=T.Backend('custom','Custom',first),
                        mymemory=T.Backend('mymemory','Fallback',lambda *a: self.fail('请求了后备接口'))):
            with T.cancellation_scope(cancelled.is_set):
                with self.assertRaises(T.TranslationCancelled):
                    T.translate('Hello world', self.config())

    def test_key_and_request_url_are_not_in_error_or_logs(self):
        cfg = self.config()
        cfg['translate']['enabled']['mymemory'] = False
        cfg['api']['custom']['headers'] = '{"Authorization":"Bearer private-token-123"}'
        def fail(*a):
            raise RuntimeError('Bad Bearer private-token-123 https://example.invalid/?text=private-content')
        with patch.dict(T.BACKENDS, custom=T.Backend('custom','Custom',fail)):
            with self.assertLogs('core.translate', level='WARNING') as captured:
                with self.assertRaises(T.TranslateError) as exc:
                    T.translate('Hello world', cfg)
        for output in [str(exc.exception), '\n'.join(captured.output)]:
            self.assertNotIn('private-token', output)
            self.assertNotIn('private-content', output)


if __name__ == '__main__':
    unittest.main(verbosity=2)
