"""按显式登记路径计算核心代码/测试快照。

快照模块不遍历项目，也不根据文件后缀猜测范围。调用方必须提供项目内相对
文件路径；未登记的依赖、构建产物、缓存和运行时文件不会进入结果。
"""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Iterable


# 这些目录保存依赖、构建、缓存、覆盖率或工作流运行资料。即使误写进计划，
# 也不能把它们冒充成核心代码；真实源码中同名的单个文件不受影响。
NON_CORE_DIRECTORY_NAMES = {
    ".git",
    ".workflow_loop",
    ".next",
    ".nuxt",
    ".svelte-kit",
    ".venv",
    "venv",
    "node_modules",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    ".tox",
    ".nox",
    ".cache",
    "dist",
    "build",
    "coverage",
    ".coverage",
    "target",
    "out",
}


@dataclass(frozen=True)
class FileFact:
    """一个登记文件在某一时刻的可核对事实。"""

    path: str
    exists: bool
    file_type: str
    content_hash: str | None

    def to_dict(self) -> dict[str, object]:
        return {
            "path": self.path,
            "exists": self.exists,
            "type": self.file_type,
            "content_hash": self.content_hash,
        }


@dataclass(frozen=True)
class Snapshot:
    """一组登记文件的快照及其稳定聚合哈希。"""

    files: tuple[FileFact, ...]

    @property
    def aggregate_hash(self) -> str:
        payload = "\n".join(
            json.dumps(item.to_dict(), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
            for item in self.files
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def to_dict(self) -> dict[str, object]:
        return {
            "aggregate_hash": self.aggregate_hash,
            "files": [item.to_dict() for item in self.files],
        }


def _sha256(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def normalize_registered_paths(project_root: str, paths: Iterable[str]) -> list[str]:
    """校验并去重项目内普通相对路径。"""
    normalized: set[str] = set()
    root_real = os.path.realpath(project_root)
    for raw in paths:
        if not isinstance(raw, str):
            raise ValueError(f"登记路径必须是字符串：{raw!r}")
        value = raw.strip().strip("`").replace("\\", "/")
        path = PurePosixPath(value)
        if (
            not value
            or "\x00" in value
            or path.is_absolute()
            or any(part in {"", ".", ".."} for part in path.parts)
        ):
            raise ValueError(f"登记路径必须是项目内相对路径：{raw!r}")
        generated_parts = [part for part in path.parts[:-1] if part in NON_CORE_DIRECTORY_NAMES]
        if generated_parts:
            raise ValueError(
                f"登记路径位于依赖、构建、缓存或运行资料目录，不能作为核心代码："
                f"{value}（目录 {generated_parts[0]}）"
            )
        full = os.path.join(project_root, *path.parts)
        parent = os.path.realpath(os.path.dirname(full) or project_root)
        try:
            if os.path.commonpath((root_real, parent)) != root_real:
                raise ValueError(f"登记路径超出项目目录：{value}")
        except ValueError as exc:
            raise ValueError(f"登记路径超出项目目录：{value}") from exc
        current = project_root
        for part in path.parts:
            current = os.path.join(current, part)
            if os.path.lexists(current) and os.path.islink(current):
                raise ValueError(f"登记路径不能经过符号链接：{value}")
        normalized.add(path.as_posix())
    return sorted(normalized)


def collect_snapshot(project_root: str, paths: Iterable[str]) -> Snapshot:
    """只读取登记路径，保存缺失文件事实而不猜测其内容。"""
    registered = normalize_registered_paths(project_root, paths)
    facts: list[FileFact] = []
    for relative in registered:
        full = os.path.join(project_root, *relative.split("/"))
        if not os.path.lexists(full):
            facts.append(FileFact(relative, False, "missing", None))
            continue
        if os.path.islink(full):
            raise ValueError(f"登记路径不能是符号链接：{relative}")
        if os.path.isfile(full):
            facts.append(FileFact(relative, True, "file", _sha256(full)))
        elif os.path.isdir(full):
            facts.append(FileFact(relative, True, "directory", None))
        else:
            facts.append(FileFact(relative, True, "other", None))
    return Snapshot(tuple(facts))


def snapshot_from_dict(data: object) -> Snapshot:
    """从机器记录恢复快照，拒绝重复或缺少必要字段。"""
    if not isinstance(data, dict) or not isinstance(data.get("files"), list):
        raise ValueError("逐文件快照必须包含 files 数组")
    facts: list[FileFact] = []
    seen: set[str] = set()
    for raw in data["files"]:
        if not isinstance(raw, dict):
            raise ValueError("逐文件快照包含无效记录")
        path = raw.get("path")
        if not isinstance(path, str) or path in seen:
            raise ValueError(f"逐文件快照路径缺失或重复：{path!r}")
        exists = raw.get("exists")
        file_type = raw.get("type")
        content_hash = raw.get("content_hash")
        if not isinstance(exists, bool) or not isinstance(file_type, str):
            raise ValueError(f"逐文件快照字段无效：{path}")
        if content_hash is not None and not isinstance(content_hash, str):
            raise ValueError(f"逐文件快照哈希无效：{path}")
        seen.add(path)
        facts.append(FileFact(path, exists, file_type, content_hash))
    snapshot = Snapshot(tuple(sorted(facts, key=lambda item: item.path)))
    expected = data.get("aggregate_hash")
    if expected is not None and expected != snapshot.aggregate_hash:
        raise ValueError("逐文件快照与聚合哈希不一致")
    return snapshot


def compare_snapshots(
    baseline: Snapshot | None,
    current: Snapshot,
) -> dict[str, list[str]]:
    """返回 added/modified/deleted/type_changed/not_checked 五类差异。"""
    if baseline is None:
        return {"added": [], "modified": [], "deleted": [], "type_changed": [], "not_checked": sorted(item.path for item in current.files)}
    before = {item.path: item for item in baseline.files}
    after = {item.path: item for item in current.files}
    result = {"added": [], "modified": [], "deleted": [], "type_changed": [], "not_checked": []}
    for path in sorted(set(before) | set(after)):
        old = before.get(path)
        new = after.get(path)
        if old is None:
            result["added"].append(path)
        elif new is None:
            result["deleted"].append(path)
        elif not old.exists and new.exists:
            result["added"].append(path)
        elif old.exists and not new.exists:
            result["deleted"].append(path)
        elif old.file_type != new.file_type:
            result["type_changed"].append(path)
        elif old.content_hash != new.content_hash:
            result["modified"].append(path)
    return result


def registered_snapshot_hash(project_root: str, paths: Iterable[str]) -> str:
    """计算登记路径集合的聚合哈希。"""
    return collect_snapshot(project_root, paths).aggregate_hash
