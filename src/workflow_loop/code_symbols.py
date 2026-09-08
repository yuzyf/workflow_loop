"""代码符号索引与引用核对（机器采集延伸）。

用 Python 标准库 ast 解析项目内全部 .py 文件，建立 相对路径→符号集合
索引（模块级函数、类、类的直接方法）；设计同步门禁用它核对架构文档中
的 文件::符号 引用，AI 不再手写格式、抄错时报相近符号建议。
非 Python 文件按文件级核对（只查存在）；不存在的文件报路径无效。
"""

from __future__ import annotations

import ast
import os
from typing import Iterable

# 参与符号索引的源码目录（项目内相对路径前缀）
SOURCE_DIRECTORY_PREFIXES = ("src/", "tests/")

# 引用形态：文件::符号（符号可含点号表示类.方法）
_FILE_SYMBOL_RE_PART = r"[A-Za-z0-9_./\\-]+"


def _iter_python_files(project_root: str) -> Iterable[str]:
    for prefix in SOURCE_DIRECTORY_PREFIXES:
        base = os.path.join(project_root, prefix)
        if not os.path.isdir(base):
            continue
        for dirpath, _dirnames, filenames in os.walk(base):
            for filename in filenames:
                if not filename.endswith(".py"):
                    continue
                full = os.path.join(dirpath, filename)
                relative = os.path.relpath(full, project_root).replace(os.sep, "/")
                yield relative


def _symbols_of_source(content: str) -> set[str]:
    """单文件符号集合：模块级函数、类、类的直接方法（含异步变体）。"""
    tree = ast.parse(content)
    symbols: set[str] = set()
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            symbols.add(node.name)
        elif isinstance(node, ast.ClassDef):
            symbols.add(node.name)
            for child in node.body:
                if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    symbols.add(f"{node.name}.{child.name}")
    return symbols


def build_symbol_index(project_root: str) -> tuple[dict[str, set[str]], list[str]]:
    """建立项目符号索引；返回 (索引, 解析失败文件清单)。

    单文件语法错误不中断整体索引：跳过并记录，调用方可提示。
    """
    index: dict[str, set[str]] = {}
    failures: list[str] = []
    for relative in _iter_python_files(project_root):
        full = os.path.join(project_root, relative)
        try:
            with open(full, "r", encoding="utf-8") as stream:
                content = stream.read()
            index[relative] = _symbols_of_source(content)
        except (OSError, SyntaxError, ValueError):
            failures.append(relative)
    return index, failures


def suggest_similar(symbols: Iterable[str], target: str, limit: int = 5) -> list[str]:
    """给出相近符号建议：前缀匹配优先，其次包含匹配，按名称排序。"""
    names = sorted(set(symbols))
    target_lower = target.lower()
    prefixed = [name for name in names if name.lower().startswith(target_lower)]
    contained = [
        name
        for name in names
        if target_lower in name.lower() and name not in prefixed
    ]
    return (prefixed + contained)[:limit]


def extract_file_symbol_references(text: str) -> list[tuple[str, str]]:
    """从一段文字提取 文件::符号 引用；返回 [(文件, 符号)]。

    只匹配项目内源码路径形态（src/ 或 tests/ 开头）；同一引用去重。
    """
    import re

    pattern = re.compile(
        r"`?(" + _FILE_SYMBOL_RE_PART + r")::(" + _FILE_SYMBOL_RE_PART + r")`?"
    )
    references: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for match in pattern.finditer(text):
        relative = match.group(1).replace("\\", "/")
        symbol = match.group(2)
        if not (relative.startswith("src/") or relative.startswith("tests/")):
            continue
        key = (relative, symbol)
        if key in seen:
            continue
        seen.add(key)
        references.append(key)
    return references


def check_reference(
    project_root: str,
    index: dict[str, set[str]],
    relative: str,
    symbol: str,
) -> tuple[bool, str]:
    """核对单个 文件::符号 引用；返回 (通过, 说明)。

    .py 文件核对符号存在性（不存在给相近符号建议）；
    非 Python 文件只查文件存在；不存在的文件报路径无效。
    """
    normalized = relative.replace("\\", "/")
    full = os.path.join(project_root, normalized)
    if not os.path.isfile(full):
        return False, f"文件不存在：{normalized}"
    if not normalized.endswith(".py"):
        return True, f"非 Python 文件按存在性核对通过：{normalized}"
    symbols = index.get(normalized)
    if symbols is None:
        return False, f"文件不在符号索引中（可能解析失败）：{normalized}"
    if symbol in symbols:
        return True, f"符号存在：{normalized}::{symbol}"
    similar = suggest_similar(symbols, symbol.split(".")[-1])
    hint = f"；相近符号：{similar}" if similar else "；该文件没有相近符号"
    return False, f"符号不存在：{normalized}::{symbol}{hint}"


def check_text_references(
    project_root: str,
    index: dict[str, set[str]],
    text: str,
) -> list[str]:
    """核对一段文字里的全部引用；返回问题清单（空为全部通过）。"""
    problems: list[str] = []
    for relative, symbol in extract_file_symbol_references(text):
        ok, detail = check_reference(project_root, index, relative, symbol)
        if not ok:
            problems.append(detail)
    return problems
