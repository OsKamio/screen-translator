# -*- coding: utf-8 -*-
"""
翻译后端：多后端注册表 + 配置驱动回退链。

内置后端
--------
| name      | 说明                             | 需要配置            |
|-----------|----------------------------------|---------------------|
| deepl     | DeepL 官方 API（质量高）         | API Key             |
| baidu     | 百度翻译开放平台                 | APP ID + 密钥       |
| microsoft | Azure 认知服务翻译               | 订阅密钥 (+区域)    |
| openai    | 任意 OpenAI 兼容接口（LLM 翻译） | Base URL + Key + 模型 |
| custom    | 自定义 HTTP 接口（模板化）       | 请求地址等          |
| mymemory  | MyMemory 免费接口（无需密钥）    | —                   |
| google    | Google 网页翻译（需国际网络）    | —                   |

调用顺序由配置 translate.backends + translate.enabled 决定；
失败自动回退到下一个可用后端。
"""
from __future__ import annotations

import hashlib
from contextlib import contextmanager
from contextvars import ContextVar
import json
import logging
import re
import urllib.parse
from dataclasses import dataclass, field
from typing import Callable

import requests

log = logging.getLogger(__name__)

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)

CJK_RE = re.compile(r"[\u4e00-\u9fff]")
HIRAGANA_KATAKANA_RE = re.compile(r"[\u3040-\u30ff]")
HANGUL_RE = re.compile(r"[\uac00-\ud7af]")
CYRILLIC_RE = re.compile(r"[\u0400-\u04ff]")
ARABIC_RE = re.compile(r"[\u0600-\u06ff]")

# 语言标签 -> 可读名
LANG_NAMES = {
    "en": "英语", "ja": "日语", "ko": "韩语", "zh-CN": "简体中文",
    "zh-TW": "繁体中文", "zh": "中文", "fr": "法语", "de": "德语",
    "es": "西班牙语", "ru": "俄语", "it": "意大利语", "pt": "葡萄牙语",
    "th": "泰语", "vi": "越南语", "ar": "阿拉伯语", "auto": "自动",
}

# 各后端单次请求的字符上限（长文本按此分块）
CHUNK_LIMIT = {
    "deepl": 4000,
    "baidu": 1800,
    "microsoft": 4000,
    "openai": 3000,
    "custom": 1000,
    "mymemory": 460,
    "google": 1800,
}

MAX_CHARS = 20000  # 单次翻译任务总上限


class TranslateError(RuntimeError):
    """翻译失败（带面向用户的中文提示）。"""


class TranslationCancelled(TranslateError):
    """旧实时任务被停止或换区；不再请求后续分块/后备接口。"""


_cancelled = ContextVar('translation_cancelled', default=None)


@contextmanager
def cancellation_scope(callback):
    token = _cancelled.set(callback)
    try:
        yield
    finally:
        _cancelled.reset(token)


def _check_cancelled():
    callback = _cancelled.get()
    if callback is not None and callback():
        raise TranslationCancelled('翻译已取消')


def _safe_error(exc, cfg):
    """接口异常不把含原文/密钥的请求 URL 回显到界面或日志。"""
    if isinstance(exc, requests.Timeout):
        return '请求超时，请检查网络或增加超时时间'
    if isinstance(exc, requests.ConnectionError):
        return '连接失败，请检查网络、代理和接口地址'
    if isinstance(exc, requests.HTTPError):
        response = getattr(exc, 'response', None)
        return f'接口返回 HTTP {response.status_code}' if response is not None else '接口请求失败'
    msg = str(exc).strip().replace('\n', ' ')
    def redact(node):
        nonlocal msg
        if not isinstance(node, dict):
            return
        for key, value in node.items():
            if isinstance(value, dict):
                redact(value)
            elif isinstance(value, str):
                if any(part in key.lower() for part in ('key', 'token', 'secret', 'password', 'authorization', 'appid')) and len(value) >= 4:
                    msg = msg.replace(value, '[已隐藏]')
                if key.lower() == 'headers':
                    try:
                        redact(json.loads(value))
                    except (ValueError, TypeError):
                        pass
    redact(_get_cfg(cfg, 'api', {}))
    return re.sub(r'https?://\S+', '[接口地址已隐藏]', msg)[:160]


# --------------------------------------------------------------------------
# 后端定义
# --------------------------------------------------------------------------
@dataclass(frozen=True)
class Backend:
    name: str
    label: str
    func: Callable[..., str]
    # ((配置点分路径, 显示名), ...)  —— 用于判断是否已配置完整
    required: tuple[tuple[str, str], ...] = field(default_factory=tuple)


BACKENDS: dict[str, Backend] = {}
# 界面展示顺序
BACKEND_ORDER = ["deepl", "baidu", "microsoft", "openai", "custom",
                 "mymemory", "google"]


def register_backend(backend: Backend) -> None:
    BACKENDS[backend.name] = backend


def backend_label(name: str) -> str:
    b = BACKENDS.get(name)
    return b.label if b else name


def _get_cfg(cfg, dotted: str, default=None):
    """按点分路径读取配置。

    支持两种形态：
    - dict（主程序后台线程传递的配置快照）
    - Config 对象（设置界面/独立测试使用，自带点分 get）

    注意：不能只用 hasattr(cfg, "get") 判定——dict 同样有 .get，
    否则会把 "translate.enabled" 当成字面键去查，导致所有配置都读不到。
    """
    if cfg is None:
        return default
    if isinstance(cfg, dict):
        cur = cfg
        for part in dotted.split("."):
            if not isinstance(cur, dict) or part not in cur:
                return default
            cur = cur[part]
        return default if cur is None else cur
    try:
        value = cfg.get(dotted, default)
    except Exception:  # noqa: BLE001
        return default
    return default if value is None else value


def backend_ready(name: str, cfg) -> tuple[bool, str]:
    """返回 (是否配置完整, 缺失说明)。"""
    b = BACKENDS.get(name)
    if b is None:
        return False, f"未知后端 {name}"
    missing = [label for path, label in b.required
               if not str(_get_cfg(cfg, path, "") or "").strip()]
    if missing:
        return False, "缺少配置：" + "、".join(missing)
    return True, ""


def enabled_backends(cfg) -> list[str]:
    """按配置顺序返回已启用的后端名。"""
    order = _get_cfg(cfg, "translate.backends", None) or BACKEND_ORDER
    enabled_map = _get_cfg(cfg, "translate.enabled", {}) or {}
    out = []
    for name in order:
        if name in BACKENDS and enabled_map.get(name, False):
            out.append(name)
    # 配置里漏掉的已启用后端补在后面
    for name in BACKEND_ORDER:
        if name in BACKENDS and enabled_map.get(name, False) and name not in out:
            out.append(name)
    return out


def build_chain(cfg) -> list[str]:
    """可用的后端链（已启用 + 配置完整）。"""
    chain = []
    for name in enabled_backends(cfg):
        ok, _why = backend_ready(name, cfg)
        if ok:
            chain.append(name)
    return chain


def chain_report(cfg) -> list[tuple[str, bool, str]]:
    """给设置界面用：列出所有后端及其状态 (name, 启用, 状态说明)。"""
    rows = []
    for name in BACKEND_ORDER:
        enabled = bool((_get_cfg(cfg, "translate.enabled", {}) or {}).get(name, False))
        ok, why = backend_ready(name, cfg)
        if not enabled:
            state = "未启用"
        elif ok:
            state = "可用"
        else:
            state = why
        rows.append((name, enabled, state))
    return rows


# --------------------------------------------------------------------------
# 语言猜测与映射
# --------------------------------------------------------------------------
def guess_lang(text: str) -> str:
    """按字符范围猜测语言；纯拉丁文本默认 en。"""
    if not text:
        return "auto"
    cjk = len(CJK_RE.findall(text))
    hira = len(HIRAGANA_KATAKANA_RE.findall(text))
    hang = len(HANGUL_RE.findall(text))
    cyr = len(CYRILLIC_RE.findall(text))
    arab = len(ARABIC_RE.findall(text))
    meaningful = sum(1 for ch in text if not ch.isspace())
    if meaningful == 0:
        return "auto"
    if hang / meaningful >= 0.3:
        return "ko"
    if hira / meaningful >= 0.15:
        return "ja"
    if cjk / meaningful >= 0.35:
        return "zh"
    if cyr / meaningful >= 0.3:
        return "ru"
    if arab / meaningful >= 0.3:
        return "ar"
    return "en"


def is_already_target(text: str, dst: str) -> bool:
    """判断原文是否已是目标语言。"""
    if not text or not dst:
        return False
    g = guess_lang(text)
    if dst.startswith("zh"):
        return g == "zh"
    if dst.startswith("en") and g == "en":
        # 纯数字/符号也算“已是英文”，避免无意义调用
        return True
    return g == dst.split("-")[0]


def lang_name(code: str) -> str:
    return LANG_NAMES.get(code, code)


# DeepL / 百度 语言码映射（其余通用 BCP-47 直接透传）
_DEEPL_LANGS = {
    "zh-CN": "ZH-HANS", "zh-TW": "ZH-HANT", "zh": "ZH",
    "en": "EN", "ja": "JA", "ko": "KO", "fr": "FR", "de": "DE",
    "es": "ES", "ru": "RU", "pt": "PT", "it": "IT",
}
_BAIDU_LANGS = {
    "zh-CN": "zh", "zh-TW": "cht", "zh": "zh",
    "en": "en", "ja": "jp", "ko": "kor", "fr": "fra", "de": "de",
    "es": "spa", "ru": "ru", "pt": "pt", "it": "it",
    "ar": "ara", "th": "th", "vi": "vie",
}


def _ms_lang(code: str) -> str:
    return {"zh-CN": "zh-Hans", "zh-TW": "zh-Hant", "zh": "zh-Hans"}.get(code, code)


# --------------------------------------------------------------------------
# 各后端实现：func(text, src, dst, api_cfg, timeout) -> str
# --------------------------------------------------------------------------
def _mymemory(text: str, src: str, dst: str, api: dict, timeout: int) -> str:
    pair = f"{src if src != 'auto' else 'en'}|{dst}"
    resp = requests.get(
        "https://api.mymemory.translated.net/get",
        params={"q": text[:500], "langpair": pair},
        timeout=timeout,
        headers={"User-Agent": USER_AGENT},
    )
    resp.raise_for_status()
    data = resp.json()
    if data.get("responseStatus") != 200:
        raise TranslateError(f"MyMemory：{data.get('responseDetails')}")
    out = ((data.get("responseData") or {}).get("translatedText") or "").strip()
    if not out:
        raise TranslateError("MyMemory：返回空结果")
    return out


def _google(text: str, src: str, dst: str, api: dict, timeout: int) -> str:
    resp = requests.get(
        "https://translate.googleapis.com/translate_a/single",
        params={"client": "gtx", "sl": src, "tl": dst, "dt": "t", "q": text},
        timeout=timeout,
        headers={"User-Agent": USER_AGENT},
    )
    resp.raise_for_status()
    data = resp.json()
    out = "".join(seg[0] for seg in data[0] if seg and seg[0]).strip()
    if not out:
        raise TranslateError("Google：返回空结果")
    return out


def _deepl(text: str, src: str, dst: str, api: dict, timeout: int) -> str:
    key = (api.get("api_key") or "").strip()
    if not key:
        raise TranslateError("DeepL：未配置 API Key")
    target = _DEEPL_LANGS.get(dst)
    if not target:
        raise TranslateError(f"DeepL 不支持目标语言 {dst}")
    plan = (api.get("plan") or "free").lower()
    host = "api.deepl.com" if plan == "pro" else "api-free.deepl.com"
    payload = {"text": [text], "target_lang": target}
    src_code = _DEEPL_LANGS.get(src) if src != "auto" else None
    if src_code:
        payload["source_lang"] = src_code
    resp = requests.post(
        f"https://{host}/v2/translate",
        data=payload,
        headers={"Authorization": f"DeepL-Auth-Key {key}",
                 "User-Agent": USER_AGENT},
        timeout=timeout,
    )
    if resp.status_code in (401, 403):
        raise TranslateError("DeepL：API Key 无效或额度用尽")
    resp.raise_for_status()
    data = resp.json()
    out = "".join(item.get("text", "") for item in data.get("translations", [])).strip()
    if not out:
        raise TranslateError("DeepL：返回空结果")
    return out


def _baidu(text: str, src: str, dst: str, api: dict, timeout: int) -> str:
    appid = (api.get("appid") or "").strip()
    key = (api.get("key") or "").strip()
    if not appid or not key:
        raise TranslateError("百度翻译：未配置 APP ID / 密钥")
    to_lang = _BAIDU_LANGS.get(dst)
    if not to_lang:
        raise TranslateError(f"百度翻译不支持目标语言 {dst}")
    from_lang = _BAIDU_LANGS.get(src, "auto") if src != "auto" else "auto"
    salt = str(int.from_bytes(hashlib.sha256(text.encode("utf-8")).digest()[:4], "big") % 100000)
    sign = hashlib.md5(
        f"{appid}{text}{salt}{key}".encode("utf-8")
    ).hexdigest()
    resp = requests.post(
        "https://api.fanyi.baidu.com/api/trans/vip/translate",
        data={"q": text, "from": from_lang, "to": to_lang,
              "appid": appid, "salt": salt, "sign": sign},
        timeout=timeout,
        headers={"User-Agent": USER_AGENT},
    )
    resp.raise_for_status()
    data = resp.json()
    if "error_code" in data and str(data["error_code"]) != "52000":
        raise TranslateError(
            f"百度翻译错误 {data.get('error_code')}：{data.get('error_msg')}")
    out = "".join(item.get("dst", "") for item in data.get("trans_result", [])).strip()
    if not out:
        raise TranslateError("百度翻译：返回空结果")
    return out


def _microsoft(text: str, src: str, dst: str, api: dict, timeout: int) -> str:
    key = (api.get("key") or "").strip()
    if not key:
        raise TranslateError("微软翻译：未配置订阅密钥")
    headers = {
        "Ocp-Apim-Subscription-Key": key,
        "Content-Type": "application/json",
        "User-Agent": USER_AGENT,
    }
    region = (api.get("region") or "").strip()
    if region and region.lower() != "global":
        headers["Ocp-Apim-Subscription-Region"] = region
    params = {"api-version": "3.0", "to": _ms_lang(dst)}
    if src != "auto":
        params["from"] = _ms_lang(src)
    resp = requests.post(
        "https://api.cognitive.microsofttranslator.com/translate",
        params=params, json=[{"Text": text}], headers=headers, timeout=timeout,
    )
    if resp.status_code in (401, 403):
        raise TranslateError("微软翻译：密钥无效或区域不正确")
    resp.raise_for_status()
    data = resp.json()
    out = "".join(
        t.get("text", "")
        for item in data for t in item.get("translations", [])
    ).strip()
    if not out:
        raise TranslateError("微软翻译：返回空结果")
    return out


def _openai(text: str, src: str, dst: str, api: dict, timeout: int) -> str:
    base = (api.get("base_url") or "").strip().rstrip("/")
    key = (api.get("api_key") or "").strip()
    model = (api.get("model") or "").strip()
    if not base or not key or not model:
        raise TranslateError("LLM 翻译：请填写 Base URL、API Key 与模型名")
    target_name = lang_name(dst)
    system = (api.get("system_prompt") or "").strip() or (
        f"你是专业翻译引擎。把用户提供的文本翻译成{target_name}，"
        "只输出译文本身，不要解释、不要加引号、保持原有段落与换行。"
    )
    resp = requests.post(
        f"{base}/chat/completions",
        json={
            "model": model,
            "temperature": 0,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": text},
            ],
        },
        headers={"Authorization": f"Bearer {key}",
                 "Content-Type": "application/json",
                 "User-Agent": USER_AGENT},
        timeout=max(timeout, 20),   # LLM 生成较慢
    )
    if resp.status_code in (401, 403):
        raise TranslateError("LLM 翻译：API Key 无效或无权限")
    resp.raise_for_status()
    data = resp.json()
    try:
        out = data["choices"][0]["message"]["content"].strip()
    except (KeyError, IndexError, TypeError) as exc:
        raise TranslateError(f"LLM 翻译：响应格式异常（{exc}）") from exc
    if not out:
        raise TranslateError("LLM 翻译：返回空结果")
    return out


def _dig(data, path: str):
    """按 data.translation / result.0.text 形式取嵌套值。"""
    cur = data
    for part in (path or "").split("."):
        if not part:
            continue
        if isinstance(cur, list):
            if not part.lstrip("-").isdigit():
                raise TranslateError(f"响应路径 {path} 与数据结构不匹配")
            idx = int(part)
            if idx >= len(cur) or idx < -len(cur):
                raise TranslateError(f"响应路径 {path} 越界")
            cur = cur[idx]
        elif isinstance(cur, dict):
            if part not in cur:
                raise TranslateError(f"响应中找不到字段 {part}（路径 {path}）")
            cur = cur[part]
        else:
            raise TranslateError(f"响应路径 {path} 与数据结构不匹配")
    return cur


def _render_template(tpl: str, mapping: dict, for_url: bool) -> str:
    """替换模板占位符；JSON 体走转义，URL 查询走百分号编码。

    注意：这里用逐项替换而不是 str.format()，因为 JSON 模板里的
    ``{"key": ...}`` 花括号会被 format 误当成格式字段。
    """
    out = tpl
    for key, value in mapping.items():
        if for_url:
            repl = urllib.parse.quote(str(value))
        else:
            repl = json.dumps(str(value), ensure_ascii=False)[1:-1]
        out = out.replace("{" + key + "}", repl)
    return out


def _custom(text: str, src: str, dst: str, api: dict, timeout: int) -> str:
    url = (api.get("url") or "").strip()
    if not url:
        raise TranslateError("自定义接口：未填写请求地址")
    method = (api.get("method") or "POST").upper()
    try:
        headers = json.loads(api.get("headers") or "{}")
        if not isinstance(headers, dict):
            raise ValueError("请求头必须是 JSON 对象")
    except (json.JSONDecodeError, ValueError) as exc:
        raise TranslateError(f"自定义接口请求头不是合法 JSON：{exc}") from exc
    headers.setdefault("User-Agent", USER_AGENT)

    mapping = {"text": text, "src": src, "dst": dst}
    body_tpl = (api.get("body") or "").strip()

    if method == "GET":
        rendered = _render_template(url, mapping, for_url=True) if "{" in url else url
        params = {}
        if body_tpl:
            rendered_body = _render_template(body_tpl, mapping, for_url=True)
            params = dict(urllib.parse.parse_qsl(rendered_body))
        resp = requests.get(rendered, params=params, headers=headers, timeout=timeout)
    else:
        rendered = _render_template(url, mapping, for_url=False) if "{" in url else url
        rendered_body = _render_template(body_tpl, mapping, for_url=False) if body_tpl else ""
        try:
            payload = json.loads(rendered_body) if rendered_body else None
        except json.JSONDecodeError:
            payload = None
        if payload is not None:
            resp = requests.post(rendered, json=payload, headers=headers, timeout=timeout)
        else:
            hdrs = dict(headers)
            hdrs.setdefault("Content-Type", "application/json")
            resp = requests.post(rendered, data=rendered_body.encode("utf-8"),
                                 headers=hdrs, timeout=timeout)

    if resp.status_code in (401, 403):
        raise TranslateError("自定义接口：认证失败（401/403），请检查请求头中的密钥")
    resp.raise_for_status()

    path = (api.get("response_path") or "").strip()
    text_body = resp.text
    try:
        data = resp.json()
    except ValueError:
        data = None
    if not path:
        out = (text_body or "").strip()
    elif data is None:
        raise TranslateError("自定义接口：响应不是 JSON，无法按路径取值")
    else:
        value = _dig(data, path)
        out = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
        out = out.strip()
    if not out:
        raise TranslateError("自定义接口：取到的译文为空")
    return out


register_backend(Backend("deepl", "DeepL 官方 API", _deepl,
                         (("api.deepl.api_key", "DeepL API Key"),)))
register_backend(Backend("baidu", "百度翻译开放平台", _baidu,
                         (("api.baidu.appid", "百度 APP ID"),
                          ("api.baidu.key", "百度密钥"))))
register_backend(Backend("microsoft", "微软翻译（Azure）", _microsoft,
                         (("api.microsoft.key", "订阅密钥"),)))
register_backend(Backend("openai", "LLM 翻译（OpenAI 兼容）", _openai,
                         (("api.openai.base_url", "Base URL"),
                          ("api.openai.api_key", "API Key"),
                          ("api.openai.model", "模型名"))))
register_backend(Backend("custom", "自定义 HTTP 接口", _custom,
                         (("api.custom.url", "请求地址"),)))
register_backend(Backend("mymemory", "MyMemory（免费，无需密钥）", _mymemory))
register_backend(Backend("google", "Google 网页翻译（需国际网络）", _google))


# --------------------------------------------------------------------------
# 主入口
# --------------------------------------------------------------------------
def _chunks(text: str, limit: int) -> list[str]:
    """按行切分成不超过 limit 字符的块（超长行硬切）。"""
    chunks: list[str] = []
    cur = ""
    for line in text.split("\n"):
        candidate = line if not cur else cur + "\n" + line
        if len(candidate) <= limit:
            cur = candidate
            continue
        if cur:
            chunks.append(cur)
            cur = ""
        while len(line) > limit:
            chunks.append(line[:limit])
            line = line[limit:]
        cur = line
    if cur:
        chunks.append(cur)
    return chunks


def _call_backend(name: str, text: str, src: str, dst: str, cfg) -> str:
    _check_cancelled()
    backend = BACKENDS[name]
    api = _get_cfg(cfg, f"api.{name}", {}) or {}
    timeout = int(_get_cfg(cfg, "translate.timeout", 8) or 8)
    return backend.func(text, src, dst, api, timeout)


def _call_with_chunks(name: str, text: str, src: str, dst: str, cfg) -> str:
    limit = CHUNK_LIMIT.get(name, 1000)
    if len(text) <= limit:
        return _call_backend(name, text, src, dst, cfg)
    parts = [_call_backend(name, c, src, dst, cfg) for c in _chunks(text, limit)]
    return "\n".join(p for p in parts if p)


def test_backend(name: str, cfg, text: str = "Hello, this is a connection test.") -> str:
    """设置界面「测试」按钮：直接调用单个后端，失败抛异常。"""
    if name not in BACKENDS:
        raise TranslateError(f"未知后端：{name}")
    ok, why = backend_ready(name, cfg)
    if not ok:
        raise TranslateError(why)
    src = guess_lang(text)
    api = _get_cfg(cfg, f"api.{name}", {}) or {}
    timeout = int(_get_cfg(cfg, "translate.timeout", 8) or 8)
    return BACKENDS[name].func(text, src, "zh-CN", api, timeout)


def no_backend_message(cfg) -> str:
    """没有任何可用后端时的引导文案（区分“没配置”和“配置了但没启用”）。"""
    enabled = enabled_backends(cfg)
    if enabled:
        details = "\n".join(
            f"· {backend_label(n)}：{backend_ready(n, cfg)[1]}" for n in enabled
        )
        return ("已启用的翻译接口还没配置完整：\n" + details
                + "\n\n请到「设置 → 翻译接口」补齐上面的密钥/参数后重试。")

    ready = [n for n in BACKEND_ORDER
             if n in BACKENDS and backend_ready(n, cfg)[0]]
    if ready:
        names = "、".join(backend_label(n) for n in ready)
        return (f"你已经配置好了 {names}，但还没有勾选启用它们。\n\n"
                "请右键悬浮球 →「设置…」→「翻译」页，"
                "在“翻译接口启用与顺序”里勾选要用的接口，再点「保存」。")

    return ("还没有配置任何翻译接口。\n\n"
            "请右键悬浮球 →「设置…」→「翻译接口」填写一个接口的密钥"
            "（或勾选免密钥的 MyMemory / Google），"
            "然后到「翻译」页勾选启用。")


def translate(text: str, cfg=None, dst: str | None = None) -> tuple[str, str]:
    """
    把 text 翻译成目标语言（默认取配置 translate.target_lang）。

    返回 (结果文本, 源语言代码)：
    - 原文已是目标语言且开启跳过时，返回 (原文, 猜测语言)；
    - 否则按后端链依次尝试，全部失败抛 TranslateError。
    """
    text = (text or "").strip()
    if not text:
        raise TranslateError("没有需要翻译的内容。")
    if len(text) > MAX_CHARS:
        raise TranslateError(f"文本过长（>{MAX_CHARS} 字符），请缩小框选范围。")

    if dst is None:
        dst = _get_cfg(cfg, "translate.target_lang", "zh-CN") or "zh-CN"
    src = guess_lang(text)

    if (_get_cfg(cfg, "translate.skip_if_already_target", True)
            and is_already_target(text, dst)):
        return text, (src if src != "auto" else dst)

    chain = build_chain(cfg)
    if not chain:
        raise TranslateError(no_backend_message(cfg))

    errors = []
    for name in chain:
        _check_cancelled()
        try:
            out = _call_with_chunks(name, text, src, dst, cfg)
            _check_cancelled()
            if out:
                return out, src
            errors.append(f"{backend_label(name)}：结果为空")
        except TranslationCancelled:
            raise
        except Exception as exc:  # noqa: BLE001
            msg = _safe_error(exc, cfg)
            errors.append(f"{backend_label(name)}：{msg}")
            log.warning("翻译后端 %s 失败 (%s)", name, type(exc).__name__)

    raise TranslateError("翻译失败，已尝试所有后端：\n" + "\n".join(errors))
