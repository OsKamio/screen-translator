# -*- coding: utf-8 -*-
"""
配置管理：默认值 / 读写 / 路径回退。

配置文件位置：
  1. %APPDATA%\\ScreenTranslator\\config.json （首选，规范位置）
  2. 若该目录不可写，回退到程序目录下的 config.json

配置以点分路径访问：
    cfg.get("ui.ball_size")        -> 58
    cfg.set("translate.timeout", 10)
"""
from __future__ import annotations

import copy
import json
import logging
import os
import sys

log = logging.getLogger(__name__)

APP_DIR_NAME = "ScreenTranslator"
CONFIG_FILE_NAME = "config.json"

# --------------------------------------------------------------------------
# 默认配置
# --------------------------------------------------------------------------
DEFAULTS: dict = {
    "version": 1,
    "translate": {
        # 目标语言（默认翻译成简体中文）
        "target_lang": "zh-CN",
        # 原文已是目标语言时直接返回，不调用接口
        "skip_if_already_target": True,
        # 单次请求超时（秒）
        "timeout": 8,
        # 后端尝试顺序（仅启用的后端会参与）
        "backends": ["deepl", "baidu", "microsoft", "openai",
                     "custom", "mymemory", "google"],
        # 各后端是否启用
        "enabled": {
            "deepl": False,
            "baidu": False,
            "microsoft": False,
            "openai": False,
            "custom": False,
            "mymemory": True,
            "google": True,
        },
    },
    "api": {
        "deepl": {
            "api_key": "",
            # free = api-free.deepl.com；pro = api.deepl.com
            "plan": "free",
        },
        "baidu": {
            "appid": "",
            "key": "",
        },
        "microsoft": {
            "key": "",
            # 例如 global / eastasia / japaneast
            "region": "global",
        },
        "openai": {
            "base_url": "https://api.openai.com/v1",
            "api_key": "",
            "model": "gpt-4o-mini",
            "system_prompt": "",
        },
        "custom": {
            "url": "",
            "method": "POST",
            # 请求头（JSON 文本）
            "headers": "{}",
            # 请求体模板，占位符：{text} {src} {dst}（GET 时作为查询参数）
            "body": '{"text": "{text}", "source": "{src}", "target": "{dst}"}',
            # 从响应 JSON 中取译文的路径，如 data.translation / result.0.text
            "response_path": "data.translation",
        },
    },
    "ui": {
        "animations": True,         # 轻量界面动效；同时尊重 Windows 动画开关
        "theme": "system",          # system / light / dark / glass
        "ball_size": 58,            # 悬浮球直径（44 ~ 88）
        "ball_opacity": 100,        # 悬浮球不透明度（40 ~ 100）
        "result_font_size": 17,     # 结果卡片译文字号（12 ~ 28）
        "show_original": True,      # 结果卡片是否显示识别到的原文
        "auto_copy": False,         # 翻译完成后自动复制译文
        "result_max_height_ratio": 85,  # 结果卡片最大高度占屏比（%）
    },
    "ocr": {
        "min_confidence": 0.5,      # 低于该置信度的识别行丢弃（0 ~ 1）
        "merge_lines": False,       # True = 多行合并为整段（更适合翻译）
    },
    "live": {
        "enabled": False,           # 启动时自动显示“实时翻译窗口”
        "interval_ms": 1200,        # 检查画面变化的间隔（毫秒）
        "diff_threshold": 0.02,     # 画面变化阈值（0.005 ~ 0.2，越小越灵敏）
        "bg_opacity": 55,           # 窗口背景不透明度（%）
        "font_size": 22,            # 译文字号（12 ~ 40）
        "show_original": False,     # 是否同时显示识别到的原文
        "show_stats": False,        # 是否显示 OCR/翻译耗时
        "merge_lines": True,        # 把识别到的多行合并成整段再翻译（译文更连贯）
        "remember_geometry": True,  # 记住窗口位置与大小
        "geometry": None,           # [x, y, w, h]
        "click_through": False,     # 点击穿透（开启后只能用悬浮球菜单操作）
        "separate_capture": False,  # 不支持下层窗口抓取时，自动分开取景与译文
        "show_source_frame": True,  # 是否显示独立取景区域黄框（不影响翻译）
        "source_geometry": None,    # 独立取景区域 [x, y, w, h]
        "capture_excluded": True,   # 本窗口不被截屏/录屏/投屏捕获（关掉才能在投屏里看到它）
    },
}

# 目标语言可选项（供设置界面使用）
TARGET_LANGS: list[tuple[str, str]] = [
    ("zh-CN", "中文（简体）"),
    ("zh-TW", "中文（繁体）"),
    ("en", "英语"),
    ("ja", "日语"),
    ("ko", "韩语"),
    ("fr", "法语"),
    ("de", "德语"),
    ("es", "西班牙语"),
    ("ru", "俄语"),
    ("pt", "葡萄牙语"),
    ("it", "意大利语"),
    ("ar", "阿拉伯语"),
    ("th", "泰语"),
    ("vi", "越南语"),
]


# --------------------------------------------------------------------------
# 路径
# --------------------------------------------------------------------------
def _project_dir() -> str:
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _preferred_dir() -> str:
    appdata = os.environ.get("APPDATA")
    if appdata:
        return os.path.join(appdata, APP_DIR_NAME)
    return _project_dir()


def _writable(path_dir: str) -> bool:
    try:
        os.makedirs(path_dir, exist_ok=True)
        probe = os.path.join(path_dir, ".write_test")
        with open(probe, "w", encoding="utf-8") as fh:
            fh.write("ok")
        os.remove(probe)
        return True
    except Exception:  # noqa: BLE001
        return False


def config_path() -> str:
    """返回实际使用的配置文件路径（优先 APPDATA，不可写则回退程序目录）。"""
    preferred = _preferred_dir()
    if _writable(preferred):
        return os.path.join(preferred, CONFIG_FILE_NAME)
    fallback = _project_dir()
    return os.path.join(fallback, CONFIG_FILE_NAME)


# --------------------------------------------------------------------------
# 工具
# --------------------------------------------------------------------------
def deep_merge(base: dict, override: dict) -> dict:
    """把 override 深合并进 base 的副本（用于补齐缺失的默认项）。"""
    out = copy.deepcopy(base)
    for key, value in (override or {}).items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = deep_merge(out[key], value)
        else:
            out[key] = copy.deepcopy(value)
    return out


def _get_in(data: dict, dotted: str, default=None):
    cur = data
    for part in dotted.split("."):
        if not isinstance(cur, dict) or part not in cur:
            return default
        cur = cur[part]
    return cur


def _set_in(data: dict, dotted: str, value) -> None:
    parts = dotted.split(".")
    cur = data
    for part in parts[:-1]:
        nxt = cur.get(part)
        if not isinstance(nxt, dict):
            nxt = {}
            cur[part] = nxt
        cur = nxt
    cur[parts[-1]] = value


# --------------------------------------------------------------------------
# Config
# --------------------------------------------------------------------------
class Config:
    """配置对象（线程内使用；保存为原子写入）。"""

    def __init__(self, path: str | None = None):
        self.path: str = path or config_path()
        self.data: dict = copy.deepcopy(DEFAULTS)

    # ---------------- 读写 ----------------
    def load(self) -> "Config":
        try:
            if os.path.exists(self.path):
                with open(self.path, "r", encoding="utf-8") as fh:
                    raw = json.load(fh)
                if isinstance(raw, dict):
                    self.data = deep_merge(DEFAULTS, raw)
                else:
                    log.warning("配置文件内容不是对象，已忽略：%s", self.path)
        except json.JSONDecodeError as exc:
            log.warning("配置文件解析失败（%s），已使用默认配置：%s", self.path, exc)
            self._backup_broken()
        except Exception as exc:  # noqa: BLE001
            log.warning("读取配置失败，使用默认配置：%s", exc)
        return self

    def _backup_broken(self) -> None:
        try:
            if os.path.exists(self.path):
                os.replace(self.path, self.path + ".bak")
        except Exception:  # noqa: BLE001
            pass

    def save(self) -> str:
        """保存到磁盘；APPDATA 不可写时自动回退到程序目录。"""
        target = self.path
        for candidate in (self.path, os.path.join(_project_dir(), CONFIG_FILE_NAME)):
            try:
                os.makedirs(os.path.dirname(candidate), exist_ok=True)
                tmp = candidate + ".tmp"
                with open(tmp, "w", encoding="utf-8") as fh:
                    json.dump(self.data, fh, ensure_ascii=False, indent=2)
                os.replace(tmp, candidate)
                self.path = candidate
                return candidate
            except Exception as exc:  # noqa: BLE001
                log.warning("写入配置失败（%s）：%s", candidate, exc)
                target = candidate
        raise OSError(f"无法写入配置文件：{target}")

    # ---------------- 访问 ----------------
    def get(self, dotted: str, default=None):
        value = _get_in(self.data, dotted, default)
        return default if value is None else value

    def set(self, dotted: str, value) -> None:
        _set_in(self.data, dotted, value)

    def copy_data(self) -> dict:
        return copy.deepcopy(self.data)

    def replace_data(self, data: dict) -> None:
        self.data = deep_merge(DEFAULTS, data)


def load_config(path: str | None = None) -> Config:
    """便捷入口：加载（不存在时用默认值，不落盘）。"""
    cfg = Config(path)
    cfg.load()
    return cfg
