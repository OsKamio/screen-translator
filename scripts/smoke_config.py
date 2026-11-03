# -*- coding: utf-8 -*-
"""配置系统 + 翻译后端链 逻辑测试。"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from core import config as C  # noqa: E402
from core import translate as T  # noqa: E402

TMP = os.path.join(HERE, "_tmp_cfg")
PATH = os.path.join(TMP, "config.json")


def fresh_path() -> str:
    os.makedirs(TMP, exist_ok=True)
    if os.path.exists(PATH):
        os.remove(PATH)
    bak = PATH + ".bak"
    if os.path.exists(bak):
        os.remove(bak)
    return PATH


def main() -> int:
    ok = []

    # ---- 1) 默认值 + 保存/读取 ----
    p = fresh_path()
    cfg = C.Config(p)
    cfg.load()
    assert cfg.get("ui.ball_size") == 58, cfg.get("ui.ball_size")
    cfg.set("ui.ball_size", 72)
    cfg.set("translate.target_lang", "en")
    cfg.save()
    cfg2 = C.Config(p)
    cfg2.load()
    assert cfg2.get("ui.ball_size") == 72
    assert cfg2.get("translate.target_lang") == "en"
    ok.append("save/load")

    # ---- 2) 部分配置深合并（旧配置缺字段也能补齐默认）----
    with open(p, "w", encoding="utf-8") as fh:
        json.dump({"ui": {"ball_size": 66}}, fh)
    cfg3 = C.Config(p)
    cfg3.load()
    assert cfg3.get("ui.ball_size") == 66
    assert cfg3.get("translate.timeout") == 8     # 默认值被补齐
    assert cfg3.get("api.deepl.plan") == "free"
    ok.append("deep merge")

    # ---- 3) 损坏文件回退 ----
    with open(p, "w", encoding="utf-8") as fh:
        fh.write("{ this is not json")
    cfg4 = C.Config(p)
    cfg4.load()
    assert cfg4.get("ui.ball_size") == 58        # 回退默认
    assert os.path.exists(p + ".bak")            # 坏文件已备份
    ok.append("broken file fallback")

    # ---- 4) 后端链：默认配置 ----
    cfg = C.Config(fresh_path())
    cfg.load()
    chain = T.build_chain(cfg)
    assert chain == ["mymemory", "google"], chain
    ok.append(f"default chain {chain}")

    # ---- 5) 启用 DeepL（有 key）后应排在最前 ----
    cfg.set("translate.enabled.deepl", True)
    cfg.set("api.deepl.api_key", "dummy-key")
    chain = T.build_chain(cfg)
    assert chain[0] == "deepl", chain
    ok.append(f"deepl chain {chain}")

    # ---- 6) 启用百度但缺配置 → 不在链中，且给出缺失说明 ----
    cfg.set("translate.enabled.baidu", True)
    ready, why = T.backend_ready("baidu", cfg)
    assert not ready and "APP ID" in why, why
    assert "baidu" not in T.build_chain(cfg)
    ok.append(f"baidu missing -> {why}")

    # ---- 7) 自定义接口模板渲染与响应取值 ----
    rendered = T._render_template('{"t": "{text}"}', {"text": 'a"b'}, False)
    assert rendered == '{"t": "a\\"b"}', rendered       # JSON 转义
    assert T._render_template("q={text}", {"text": "a b"}, True) == "q=a%20b"
    assert T._dig({"data": {"translation": "hi"}}, "data.translation") == "hi"
    assert T._dig({"result": [{"text": "x"}]}, "result.0.text") == "x"
    try:
        T._dig({"a": 1}, "a.b")
        raise AssertionError("应当抛错")
    except T.TranslateError:
        pass
    ok.append("template + response path")

    # ---- 8) 语言判断 ----
    assert T.guess_lang("你好世界，这是中文") == "zh"
    assert T.guess_lang("Hello world, this is English") == "en"
    assert T.guess_lang("こんにちは世界") == "ja"
    assert T.is_already_target("你好世界", "zh-CN") is True
    assert T.is_already_target("Hello world", "zh-CN") is False
    ok.append("lang detect")

    # ---- 9) 没有任何可用后端 → 友好报错 ----
    empty = C.Config(fresh_path())
    empty.load()
    empty.replace_data(C.DEFAULTS)
    empty.set("translate.enabled", {n: False for n in T.BACKEND_ORDER})
    try:
        T.translate("Hello world", empty)
        raise AssertionError("应当抛错")
    except T.TranslateError as exc:
        assert "设置" in str(exc), str(exc)
        ok.append("no-backend error message")

    # ---- 10) 跳过已是目标语言（不联网）----
    assert T.translate("你好，这是中文", empty) == ("你好，这是中文", "zh")
    ok.append("skip already target")

    # ---- 11) 无可用接口时的引导文案要能指出真实原因 ----
    # (a) 一个都没启用，但存在已配置好的接口（用户实际踩到的情形）
    msg = T.no_backend_message(empty)
    assert "还没有勾选启用" in msg and "MyMemory" in msg, msg
    ok.append("guidance: configured-not-enabled")

    # (b) 启用了但配置不完整
    partial = C.Config(fresh_path())
    partial.load()
    partial.set("translate.enabled", {n: n == "baidu" for n in T.BACKEND_ORDER})
    msg = T.no_backend_message(partial)
    assert "还没配置完整" in msg and "APP ID" in msg, msg
    ok.append("guidance: enabled-but-unconfigured")

    # ---- 12) dict 快照路径（main.py 后台线程实际传参形式）----
    # 回归：曾因 dict 也有 .get 而被当成字面键查询，导致所有配置读不到、
    # 报“尚未启用任何翻译后端”。
    snap_cfg = C.Config(fresh_path())
    snap_cfg.load()
    snap_cfg.set("translate.enabled", {n: n == "mymemory" for n in T.BACKEND_ORDER})
    snap_cfg.set("translate.backends", ["mymemory"])
    snap_cfg.set("translate.target_lang", "zh-CN")
    snap_cfg.set("ui.ball_size", 64)
    snap = snap_cfg.copy_data()
    assert T._get_cfg(snap, "translate.timeout") == 8, T._get_cfg(snap, "translate.timeout")
    assert T._get_cfg(snap, "ui.ball_size") == 64
    assert T._get_cfg(snap, "translate.enabled.mymemory") is True
    assert T.build_chain(snap) == ["mymemory"], T.build_chain(snap)
    assert T.backend_ready("baidu", snap)[0] is False
    assert T.enabled_backends(snap) == ["mymemory"], T.enabled_backends(snap)
    # 该分支不联网：原文已是目标语言
    assert T.translate("你好，这是中文", snap) == ("你好，这是中文", "zh")
    ok.append("dict snapshot path")

    print("checks:", " | ".join(ok), flush=True)
    print("CONFIG_BACKEND_PASS", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
