"""项目全量测试入口选择器。

`project.json` 的 `test_entry` 保存操作系统到命令参数数组的映射：
`default`（默认）、`windows`、`linux`、`darwin`（macOS）。当前操作系统优先使用
同名配置，没有时才使用 `default`。参数数组直接交给进程执行器，不经过 Shell；
需要管道、重定向或多条命令时，必须调用项目自己的统一入口脚本。
"""

from __future__ import annotations

import os
import sys

# 允许的平台键
PLATFORM_KEYS = ("windows", "linux", "darwin", "default")
# 参数中不允许出现的 Shell 元字符：这些能力属于项目脚本，不属于参数数组
_SHELL_META_CHARS = set("|&;<>\n`$()")
_SCRIPT_SUFFIXES = {
    ".sh",
    ".bash",
    ".zsh",
    ".ps1",
    ".cmd",
    ".bat",
    ".py",
    ".js",
    ".mjs",
    ".cjs",
}


def current_platform_key() -> str:
    """返回当前操作系统对应的平台键。"""
    if sys.platform.startswith("win"):
        return "windows"
    if sys.platform == "darwin":
        return "darwin"
    return "linux"


def validate_entry_config(config) -> list[str]:
    """校验入口配置；返回错误列表（为空表示配置合法）。

    只接受 平台键 → 非空字符串数组 的映射。空映射合法（表示尚未配置）。
    """
    errors: list[str] = []
    if not isinstance(config, dict):
        return [f"测试入口必须是平台到参数数组的映射，不能是 {type(config).__name__}"]
    for key, argv in config.items():
        if key not in PLATFORM_KEYS:
            errors.append(f"未知平台键: {key}（只接受 {'/'.join(PLATFORM_KEYS)}）")
            continue
        if not isinstance(argv, list) or not argv:
            errors.append(f"平台 {key} 的入口必须是非空参数数组")
            continue
        for argument in argv:
            if not isinstance(argument, str):
                errors.append(f"平台 {key} 的参数必须是字符串: {argument!r}")
                continue
            if not argument:
                errors.append(f"平台 {key} 包含空参数")
                continue
            bad_chars = sorted(set(argument) & _SHELL_META_CHARS)
            if bad_chars:
                errors.append(
                    f"平台 {key} 的参数 {argument!r} 包含 Shell 运算符 {bad_chars}；"
                    "需要管道、重定向或多条命令时，请放入项目统一入口脚本"
                )
    return errors


def normalized_entry_config(raw) -> dict[str, list[str]]:
    """把外部输入规范化为合法配置；不合法时抛 ValueError。"""
    errors = validate_entry_config(raw)
    if errors:
        raise ValueError("；".join(errors))
    return {key: list(argv) for key, argv in raw.items()}


def select_entry(
    config: dict[str, list[str]],
    platform_key: str | None = None,
) -> list[str] | None:
    """按当前操作系统选择入口参数数组；同名配置优先，缺少时用 default。

    返回 None 表示当前平台没有可用入口（配置缺失）。
    """
    if not isinstance(config, dict):
        return None
    key = platform_key or current_platform_key()
    argv = config.get(key) or config.get("default")
    if not argv:
        return None
    return list(argv)


def describe_config(config: dict[str, list[str]]) -> str:
    """给用户看的入口配置说明。"""
    if not config:
        return "（尚未配置项目全量测试入口）"
    parts = []
    for key in PLATFORM_KEYS:
        if key in config:
            parts.append(f"{key}: {config[key]}")
    return "；".join(parts)


def referenced_project_scripts(config: dict[str, list[str]]) -> list[str]:
    """列出入口参数中明确引用的项目脚本相对路径。"""
    scripts: set[str] = set()
    for argv in config.values():
        for argument in argv:
            normalized = argument.replace("\\", "/")
            if (
                not normalized
                or os.path.isabs(argument)
                or normalized.startswith("-")
                or ".." in normalized.split("/")
            ):
                continue
            if os.path.splitext(normalized)[1].lower() in _SCRIPT_SUFFIXES:
                scripts.add(normalized)
    return sorted(scripts)
