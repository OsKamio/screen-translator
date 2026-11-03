# -*- coding: utf-8 -*-
"""自定义 HTTP 接口后端测试：本地起一个 mock 服务，验证模板替换/请求/响应取值。"""
import json
import os
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from core import config as C  # noqa: E402
from core import translate as T  # noqa: E402

SEEN = {}


class Handler(BaseHTTPRequestHandler):
    def do_POST(self):  # noqa: N802
        length = int(self.headers.get("Content-Length", 0))
        raw = self.rfile.read(length) or b"{}"
        data = json.loads(raw)
        SEEN["body"] = data
        SEEN["auth"] = self.headers.get("Authorization", "")
        reply = {
            "code": 0,
            "data": {"translation": "【译】" + str(data.get("text", ""))},
        }
        payload = json.dumps(reply, ensure_ascii=False).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, *args):  # 静默
        pass


def main() -> int:
    server = HTTPServer(("127.0.0.1", 0), Handler)
    port = server.server_address[1]
    threading.Thread(target=server.serve_forever, daemon=True).start()

    cfg = C.Config(os.path.join(HERE, "_tmp_cfg", "custom.json"))
    cfg.load()
    cfg.set("translate.enabled", {n: n == "custom" for n in T.BACKEND_ORDER})
    cfg.set("translate.backends", ["custom"])
    cfg.set("api.custom.url", f"http://127.0.0.1:{port}/api/translate")
    cfg.set("api.custom.method", "POST")
    cfg.set("api.custom.headers", '{"Authorization": "Bearer test-token"}')
    cfg.set("api.custom.body", '{"text": "{text}", "source": "{src}", "target": "{dst}"}')
    cfg.set("api.custom.response_path", "data.translation")

    ready, why = T.backend_ready("custom", cfg)
    assert ready, why
    assert T.build_chain(cfg) == ["custom"]

    out, lang = T.translate("Hello world", cfg)
    print("译文:", out, flush=True)
    print("服务端收到的请求体:", SEEN.get("body"), flush=True)

    assert out == "【译】Hello world", out
    assert SEEN["body"] == {"text": "Hello world", "source": "en", "target": "zh-CN"}, SEEN
    assert SEEN["auth"] == "Bearer test-token"

    # 测试按钮入口
    test_out = T.test_backend("custom", cfg, "How are you?")
    assert test_out == "【译】How are you?", test_out

    # 错误的响应路径应给出清晰报错
    cfg.set("api.custom.response_path", "data.nope")
    try:
        T.translate("Hello world", cfg)
        raise AssertionError("应当抛错")
    except T.TranslateError as exc:
        assert "nope" in str(exc), str(exc)
        print("路径错误提示:", str(exc).splitlines()[0], flush=True)

    server.shutdown()
    print("CUSTOM_BACKEND_PASS", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
