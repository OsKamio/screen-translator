# -*- coding: utf-8 -*-
"""静态检查：找出“被使用但从未绑定”的名字。

专治这类事故：在绘制代码里用了 QPointF 却忘了 import →
paintEvent 每帧抛 NameError → QPainter 未结束 → Qt 状态损坏 → 进程崩溃。

做法（保守，宁可漏报不可误报）：
1. 遍历全项目，收集所有“绑定处”的名字：import / def / class / 赋值目标 /
   函数参数 / for 目标 / with as / except as / lambda 参数 / 推导式目标 /
   global 与 nonlocal 声明；
2. 再遍历所有“加载处”（ast.Load）的名字，凡不在绑定集合、也不是内置名，
   即报告为可疑。
"""
from __future__ import annotations

import ast
import builtins
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
TARGET_DIRS = [os.path.join(ROOT, "core"), os.path.join(ROOT, "ui")]
TARGET_FILES = [os.path.join(ROOT, "main.py")]

BUILTINS = set(dir(builtins)) | {"__file__", "__name__", "__doc__", "self", "cls"}


def collect_bound(tree: ast.AST) -> set[str]:
    """收集整份文件里所有被绑定过的名字（粗粒度，但足够抓漏导入）。"""
    bound: set[str] = set()

    class Visitor(ast.NodeVisitor):
        def visit_Import(self, node: ast.Import) -> None:
            for alias in node.names:
                bound.add((alias.asname or alias.name.split(".")[0]))

        def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
            for alias in node.names:
                bound.add(alias.asname or alias.name)

        def visit_FunctionDef(self, node) -> None:
            bound.add(node.name)
            args = node.args
            for a in (list(args.posonlyargs) + list(args.args)
                      + list(args.kwonlyargs) + ([args.vararg] if args.vararg else [])
                      + ([args.kwarg] if args.kwarg else [])):
                bound.add(a.arg)
            self.generic_visit(node)

        visit_AsyncFunctionDef = visit_FunctionDef

        def visit_Lambda(self, node) -> None:
            args = node.args
            for a in (list(args.args) + list(args.kwonlyargs)
                      + ([args.vararg] if args.vararg else [])
                      + ([args.kwarg] if args.kwarg else [])):
                bound.add(a.arg)
            self.generic_visit(node)

        def visit_ClassDef(self, node) -> None:
            bound.add(node.name)
            self.generic_visit(node)

        def visit_Name(self, node) -> None:
            if isinstance(node.ctx, (ast.Store, ast.Del)):
                bound.add(node.id)
            self.generic_visit(node)

        def visit_Global(self, node) -> None:
            bound.update(node.names)

        def visit_Nonlocal(self, node) -> None:
            bound.update(node.names)

        def visit_arg(self, node) -> None:
            bound.add(node.arg)
            self.generic_visit(node)

        def visit_ExceptHandler(self, node) -> None:
            if node.name:
                bound.add(node.name)
            self.generic_visit(node)

    Visitor().visit(tree)
    return bound


def collect_loaded(tree: ast.AST) -> set[tuple[str, int]]:
    out: set[tuple[str, int]] = set()

    class Visitor(ast.NodeVisitor):
        def visit_Name(self, node) -> None:
            if isinstance(node.ctx, ast.Load):
                out.add((node.id, node.lineno))
            self.generic_visit(node)

    Visitor().visit(tree)
    return out


def check_file(path: str) -> list[str]:
    with open(path, "r", encoding="utf-8") as fh:
        src = fh.read()
    try:
        tree = ast.parse(src, filename=path)
    except SyntaxError as exc:
        return [f"{path}:{exc.lineno}: 语法错误 {exc.msg}"]

    bound = collect_bound(tree)
    loaded = collect_loaded(tree)
    problems = []
    for name, lineno in sorted(loaded, key=lambda x: x[1]):
        if name in bound or name in BUILTINS:
            continue
        problems.append(f"{os.path.relpath(path, ROOT)}:{lineno}: 使用未定义的名字 '{name}'")
    return problems


def main() -> int:
    files: list[str] = list(TARGET_FILES)
    for d in TARGET_DIRS:
        files += [os.path.join(d, f) for f in sorted(os.listdir(d))
                  if f.endswith(".py")]
    all_problems: list[str] = []
    for path in files:
        all_problems += check_file(path)

    if all_problems:
        print("发现可疑的未定义名字：", flush=True)
        for line in all_problems:
            print("  " + line, flush=True)
        print(f"\n共 {len(all_problems)} 处", flush=True)
        return 1
    print(f"检查 {len(files)} 个文件：未发现未定义名字", flush=True)
    print("NAMES_PASS", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
