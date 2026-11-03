# -*- coding: utf-8 -*-
"""检查设置窗口里说明文字（HintLabel）是否被压扁 / 裁掉 / 行距黏连。

背景（2026-09-20 用户截图"不同行的字相互遮挡"）：
说明文字原来是 QLabel，有三个坑，都在真实桌面下复现过：
  1. Qt 的 QSS 不支持 ``line-height``，QLabel 根本没有调行距的手段；
  2. 真实中文字体下字体自身行距几乎等于字高（leading 极小），相邻行没有空隙；
  3. 容器空间紧张时布局把多行文字压到 ``minimumSize`` 高度（实测 53px = 正好一行），
     多行文字于是叠在一起 —— ``minimumSizeHint()`` 压不住，必须 ``setMinimumHeight()``。

本脚本在**两种窗口尺寸**下逐个 tab 检查每个 HintLabel：
  * 实际高度 >= heightForWidth(实际宽度) —— 内容不被裁；
  * 实际高度是行距的整数倍 —— 行距真的按块生效，而不是"看着差不多"；
  * 行距不小于字体自身行距 +1 —— 没有把字体压紧。

用法：
    .venv\\Scripts\\python.exe scripts\\check_hint_layout.py             # 真实桌面
    .venv\\Scripts\\python.exe scripts\\check_hint_layout.py --shot       # 顺带存样本 PNG
    .venv\\Scripts\\python.exe scripts\\check_hint_layout.py --offscreen  # 只做结构检查
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

# 默认走真实桌面：offscreen 的字体库是空的（family 退化成 "Sans Serif"），
# 字体行距与字宽都不真实；--offscreen 只用来做不依赖字体的结构检查。
if "--offscreen" in sys.argv:
    os.environ["QT_QPA_PLATFORM"] = "offscreen"

from PySide6.QtGui import QFontMetrics  # noqa: E402
from PySide6.QtWidgets import QApplication, QTabWidget, QVBoxLayout  # noqa: E402

from core import config as C  # noqa: E402
from ui import design as d  # noqa: E402
from ui import settings as S  # noqa: E402
from ui.widgets import HintLabel, SettingsCard  # noqa: E402

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001
        pass

SHOT_DIR = os.path.join(HERE, "_design_shots")
SIZES = [(820, 700), (1100, 820)]      # 最小尺寸 + 放大一档
MIN_TITLE_GAP = 6                      # 卡片标题 ink 底 与 首行内容顶 的最小间隙
MIN_CONTROL_GAP = 6                    # 控件与其说明文字之间的最小间隙


def check_gaps(page) -> list[str]:
    """控件与它自己的说明文字之间不能贴死。

    排版重做前这里只有 3px：物理像素下说明文字的顶边紧贴输入框底边，
    就是用户反复反馈的"字叠在一起"。间距由 design.SET_CONTROL_GAP 决定，
    这里按**实际几何**复核，避免以后有人又改小。
    """
    problems = []
    for lab in page.findChildren(HintLabel):
        parent = lab.parentWidget()
        lay = parent.layout() if parent is not None else None
        if not isinstance(lay, QVBoxLayout):
            continue                      # 只看 _add_form 那种"控件 + 说明"的竖排
        idx = lay.indexOf(lab)
        if idx <= 0:
            continue
        prev = lay.itemAt(idx - 1).widget()
        if prev is None or prev.height() <= 0:
            continue
        gap = lab.y() - (prev.y() + prev.height())
        if gap < MIN_CONTROL_GAP:
            problems.append(
                f"[间距] 「{lab.text()[:16]}」与上方控件只隔 {gap}px"
                f"（需 ≥ {MIN_CONTROL_GAP}）")
    return problems


def check_cards(cards) -> list[str]:
    """卡片自绘标题不能与首行内容贴在一起。

    中文标题（F_CAPTION）的字形几乎填满字高，标题 ink 与紧邻内容只差 1px 时，
    视觉上就是"两行字糊在一起"（用户截图 2026-09-20）；
    修法见 SettingsCard.content_top（标题高 + 间隙，与绘制共用同一个值）。

    注意：只检查**当前已布局**的卡片 —— 未显示的 tab 里 geometry 还是 0，
    拿它来比会全体误报。
    """
    problems = []
    for card in cards:
        lay = card.layout()
        item = lay.itemAt(0) if lay is not None else None
        if item is None or card.height() <= 0:
            continue
        first_y = item.geometry().top()
        title_bottom = d.SET_CARD_PAD_TOP + card.title_height()
        gap = first_y - title_bottom
        if gap < MIN_TITLE_GAP:
            problems.append(
                f"[标题贴字] 「{card._title}」标题底≈{title_bottom:.0f} "
                f"内容起点={first_y} → 间隙仅 {gap:.0f}px（需 ≥ {MIN_TITLE_GAP}）")
    return problems


def scan(win, app, shot: bool):
    tabs = win.findChild(QTabWidget)
    checked, problems, tight = 0, [], []

    for (ww, hh) in SIZES:
        win.resize(ww, hh)
        app.processEvents()
        for idx in range(tabs.count()):
            tabs.setCurrentIndex(idx)
            app.processEvents()
            if ww == SIZES[0][0]:
                # 卡片标题几何与控件间距只查一次（与窗口尺寸无关），
                # 且必须在切到该 tab 之后（未显示的 tab geometry 还是 0）
                page = tabs.widget(idx)
                problems.extend(check_cards(page.findChildren(SettingsCard)))
                problems.extend(check_gaps(page))
            tabs.setCurrentIndex(idx)
            app.processEvents()
            for lab in tabs.widget(idx).findChildren(HintLabel):
                if not lab.text().strip():
                    continue
                checked += 1
                where = f"{tabs.tabText(idx)}@{ww}x{hh}"
                w, h = lab.width(), lab.height()
                need = lab.heightForWidth(w)
                lh = lab.line_height()
                font_ls = QFontMetrics(lab.font()).lineSpacing()

                if h + 1 < need:
                    problems.append(f"[裁切] {where} w={w} 实际h={h} < 需要{need}")
                # 行距是否真的按块生效：文档高度必须是设定行距的整数倍。
                # （widget 自身高度允许被拉伸得更高——同一行里其它控件更高时布局会给更多，
                #   那不是问题，所以这里量的是"内容需要的高度"而不是 widget 高度。）
                rows = need / lh
                if abs(rows - round(rows)) > 0.02:
                    problems.append(
                        f"[行距] {where} w={w} 内容需要{need}px 不是行距 {lh:g} 的整数倍"
                        f"（{rows:.2f} 行）")
                if font_ls + 1 > lh:
                    tight.append(f"{where} 字体行距={font_ls} 设定行距={lh:g}")

                if shot and "模板占位符" in lab.text():
                    os.makedirs(SHOT_DIR, exist_ok=True)
                    lab.grab().save(os.path.join(SHOT_DIR, "hint_custom_http.png"))

    return checked, problems, tight


def main() -> int:
    shot = "--shot" in sys.argv
    app = QApplication([])
    print(f"平台: {app.platformName()}  DPR={app.devicePixelRatio():.2f}  "
          f"尺寸: {', '.join(f'{w}x{h}' for w, h in SIZES)}\n", flush=True)

    tmp = os.path.join(HERE, "_tmp_cfg")
    os.makedirs(tmp, exist_ok=True)
    cfg = C.Config(os.path.join(tmp, "hint_layout.json"))

    win = S.SettingsWindow(cfg)
    win.resize(*SIZES[0])
    win.show()
    app.processEvents()

    checked, problems, tight = scan(win, app, shot)
    n_cards = len(win.findChildren(SettingsCard))
    print(f"共检查 {checked} 处说明文字（HintLabel）+ {n_cards} 个卡片标题", flush=True)

    if tight:
        print("✘ 行距小于字体自身行距 +1（等于压紧字体，仍可能贴行）：", flush=True)
        for t in tight:
            print(f"  · {t}", flush=True)
        problems.extend(f"[压紧] {t}" for t in tight)

    if problems:
        print(f"\n发现 {len(problems)} 个问题：", flush=True)
        for p in problems:
            print(f"  ✘ {p}", flush=True)
        print("\nHINT_LAYOUT_FAIL", flush=True)
        return 1

    print("\n说明文字高度充足、行距一致，卡片标题与内容留有间隙", flush=True)
    if shot:
        print(f"样本截图：{os.path.join(SHOT_DIR, 'hint_custom_http.png')}", flush=True)
    print("HINT_LAYOUT_PASS", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
