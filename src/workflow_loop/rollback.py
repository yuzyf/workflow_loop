"""按文件保存实施前内容，并在整个工作流中止时恢复。"""

from __future__ import annotations

import difflib
import hashlib
import json
import os
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import PurePosixPath

from . import artifact_paths as artifact_paths_mod
from . import diagnostics as diagnostics_mod
from . import project as project_mod
from . import state as state_mod
from . import test_entry as test_entry_mod
from . import verification as verification_mod
from .topic import topic_paths


ROLLBACK_ROOT = ".workflow_loop/rollback"
MANIFEST_VERSION = 1
# 作废进度清单在版本 2 起冻结穿刺资产的保留/删除边界。开工和实施
# 回退清单仍使用版本 1；分开版本号可避免把无关清单一并误判为不兼容。
ABORT_MANIFEST_VERSION = 2
PROCESS_ROOTS = {"spec", "acceptance", "qa", "impl", "bug", ".workflow_loop", ".git"}
GLOB_CHARS = set("*?{}")
WORKFLOW_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,159}$")
ABORT_ITEM_STATES = {"pending", "restoring", "restored"}
WINDOWS_RESERVED_NAMES = {
    "CON",
    "PRN",
    "AUX",
    "NUL",
    *{f"COM{number}" for number in range(1, 10)},
    *{f"LPT{number}" for number in range(1, 10)},
}

# 开工基线：受管正式文档目录与根级文件（清场范围与作废恢复范围共用同一份约定）
MANAGED_DOC_DIRS = ["spec", "acceptance", "qa", "impl", "bug"]
MANAGED_DOC_FILES = [artifact_paths_mod.TRACEABILITY_DOC]
# 清场开工事务记录：未完成时任何日常命令都不得继续正常流程
START_TRANSACTION_FILE = ".workflow_loop/start_transaction.json"


@dataclass(frozen=True)
class RecordedCodeChange:
    """实施记录中的一条可定位事实。"""

    topic: str
    document_path: str
    line: int
    path: str
    location_column: str
    requires_line_range: bool
    location: str
    logic: str
    observable_change: str
    acceptance_conditions: str


@dataclass(frozen=True)
class PlannedCodeChange:
    """实施前计划中的一条可定位文件事实。"""

    topic: str
    document_path: str
    line: int
    path: str


@dataclass(frozen=True)
class _ImplementationChangeValidation:
    """三方核对的结构化失败事实和兼容旧调用方的成功说明。"""

    report: diagnostics_mod.ValidationReport
    detail: str


@dataclass(frozen=True)
class _RecordedLineRange:
    """实施记录中声明的代码行范围及其相对的文件版本。"""

    basis: str
    start: int
    end: int


_RECORD_PLACEHOLDERS = {
    "",
    "-",
    "无",
    "暂无",
    "todo",
    "tbd",
    "待补充",
    "待确认",
    "稍后确认",
    "实施后确认",
    "符合预期",
    "正确处理",
    "相关逻辑",
    "实际修改逻辑",
    "返回可检查结果",
}
IMPL_CODE_BASELINE_SNAPSHOT_KEY = "impl_code_baseline_snapshot"
IMPL_COMPLETE_BASELINE_SNAPSHOT_KEY = "impl_complete_baseline_snapshot"
IMPL_COMPLETE_INVENTORY_MANIFEST_KEY = "implementation_inventory_before"
_FINAL_LINE_RANGE_PATTERN = re.compile(
    r"^L(?P<start>[1-9][0-9]*)[ \t]*-[ \t]*L(?P<end>[1-9][0-9]*)$"
)
_FILE_DELETION_LOCATIONS = {"文件删除", "删除整个文件", "deleted", "filedeleted"}
_LOCATION_GENERIC_TERMS = {
    "组件",
    "页面",
    "模块",
    "函数",
    "类",
    "配置项",
    "相关组件",
    "相关页面",
    "相关模块",
    "相关函数",
    "相关类",
    "相关配置项",
    "component",
    "page",
    "module",
    "function",
    "class",
    "configuration",
}


def _sha256_bytes(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _sha256_file(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _copy_file(source: str, destination: str) -> None:
    with open(source, "rb") as source_stream, open(destination, "wb") as destination_stream:
        shutil.copyfileobj(source_stream, destination_stream, length=1024 * 1024)


def _validated_workflow_id(workflow_id: str) -> str:
    """校验工作流编号，禁止它影响回退目录之外的路径。"""
    if (
        not isinstance(workflow_id, str)
        or workflow_id in {".", ".."}
        or WORKFLOW_ID_PATTERN.fullmatch(workflow_id) is None
    ):
        raise ValueError(f"工作流编号不安全：{workflow_id!r}")
    return workflow_id


def _safe_project_relative_path(
    project_root: str,
    raw_path: str,
    *,
    purpose: str,
    allow_directory: bool = False,
) -> str:
    """把清单路径限制为项目内、不经过符号链接的相对路径。"""
    if not isinstance(raw_path, str):
        raise ValueError(f"{purpose}不是字符串路径：{raw_path!r}")
    value = raw_path.strip().strip("`").replace("\\", "/")
    if (
        not value
        or "\x00" in value
        or re.match(r"^[A-Za-z]:", value)
        or any(character in value for character in GLOB_CHARS)
    ):
        raise ValueError(f"{purpose}不是安全的项目内相对路径：{raw_path!r}")
    path = PurePosixPath(value)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise ValueError(f"{purpose}不是安全的项目内相对路径：{raw_path!r}")
    for part in path.parts:
        windows_base = part.split(".", 1)[0].upper()
        if (
            any(character in part for character in '<>:"|')
            or part.endswith((" ", "."))
            or windows_base in WINDOWS_RESERVED_NAMES
        ):
            raise ValueError(f"{purpose}不能在 Windows 上安全使用：{raw_path!r}")

    normalized = path.as_posix()
    project_real = os.path.realpath(project_root)
    full_path = os.path.join(project_root, *path.parts)
    parent_real = os.path.realpath(os.path.dirname(full_path) or project_root)
    try:
        inside_project = os.path.commonpath([project_real, parent_real]) == project_real
    except ValueError:
        inside_project = False
    if not inside_project:
        raise ValueError(f"{purpose}超出项目目录：{normalized}")

    current = project_root
    for part in path.parts[:-1]:
        current = os.path.join(current, part)
        if os.path.lexists(current) and os.path.islink(current):
            raise ValueError(f"{purpose}经过符号链接：{normalized}")
    if os.path.lexists(full_path):
        if os.path.islink(full_path):
            raise ValueError(f"{purpose}不能是符号链接：{normalized}")
        if not allow_directory and not os.path.isfile(full_path):
            raise ValueError(f"{purpose}必须指向普通文件：{normalized}")
    return normalized


def _atomic_write_bytes(path: str, content: bytes) -> None:
    directory = os.path.dirname(path) or "."
    os.makedirs(directory, exist_ok=True)
    descriptor, temp_path = tempfile.mkstemp(prefix=".workflow-write-", dir=directory)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp_path, path)
    finally:
        if os.path.exists(temp_path):
            os.remove(temp_path)


def _atomic_write_json(path: str, data: dict) -> bytes:
    raw = json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True).encode("utf-8")
    _atomic_write_bytes(path, raw)
    return raw


def _atomic_restore_file(source: str, destination: str, mode: int | None) -> None:
    destination_dir = os.path.dirname(destination) or "."
    os.makedirs(destination_dir, exist_ok=True)
    descriptor, temp_path = tempfile.mkstemp(prefix=".workflow-rollback-", dir=destination_dir)
    os.close(descriptor)
    try:
        _copy_file(source, temp_path)
        if isinstance(mode, int):
            os.chmod(temp_path, mode)
        os.replace(temp_path, destination)
    finally:
        if os.path.exists(temp_path):
            os.remove(temp_path)


def _safe_backup_path(manifest_dir: str, raw_path: str, code_path: str) -> str:
    if not isinstance(raw_path, str):
        raise ValueError(f"回退清单缺少有效的文件副本路径：{code_path}")
    value = raw_path.replace("\\", "/")
    path = PurePosixPath(value)
    if (
        not value
        or "\x00" in value
        or re.match(r"^[A-Za-z]:", value)
        or any(character in value for character in GLOB_CHARS)
        or path.is_absolute()
        or any(part in {"", ".", ".."} for part in path.parts)
    ):
        raise ValueError(f"回退清单中的文件副本路径不安全：{code_path}")
    full_path = os.path.join(manifest_dir, *path.parts)
    manifest_real = os.path.realpath(manifest_dir)
    backup_real = os.path.realpath(full_path)
    try:
        inside_manifest = os.path.commonpath([manifest_real, backup_real]) == manifest_real
    except ValueError:
        inside_manifest = False
    if not inside_manifest:
        raise ValueError(f"回退清单中的文件副本超出回退目录：{code_path}")
    current = manifest_dir
    for part in path.parts[:-1]:
        current = os.path.join(current, part)
        if os.path.lexists(current) and os.path.islink(current):
            raise ValueError(f"回退清单中的文件副本路径经过符号链接：{code_path}")
    if os.path.islink(full_path):
        raise ValueError(f"实施前文件副本不能是符号链接：{code_path}")
    return full_path


def _manifest_rel_path(workflow_id: str) -> str:
    return f"{ROLLBACK_ROOT}/{_validated_workflow_id(workflow_id)}/impl/manifest.json"


def _manifest_full_path(project_root: str, workflow_id: str) -> str:
    return os.path.join(project_root, _manifest_rel_path(workflow_id))


def _normalized_relative_path(
    project_root: str,
    raw_path: str,
    *,
    purpose: str = "代码修改计划",
) -> str:
    if not isinstance(raw_path, str):
        raise ValueError(f"{purpose}包含无法定位的文件路径：{raw_path!r}")
    value = raw_path.strip().strip("`").replace("\\", "/")
    if not value or value in {"新增", "暂无", "无", "相关文件"}:
        raise ValueError(f"{purpose}包含无法定位的文件路径：{raw_path!r}")
    if any(character in value for character in GLOB_CHARS):
        raise ValueError(f"{purpose}不能使用通配符：{value}")
    path = PurePosixPath(value)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise ValueError(f"{purpose}必须使用项目内相对路径：{value}")
    if path.parts[0] in PROCESS_ROOTS or value in MANAGED_DOC_FILES:
        raise ValueError(f"{purpose}不能把工作流过程文档当成实施代码：{value}")

    return _safe_project_relative_path(
        project_root,
        value,
        purpose=f"{purpose}路径",
    )


def _section(content: str, heading: str) -> str:
    match = re.search(
        rf"^(?P<marks>#{{2,6}})\s+{re.escape(heading)}\s*$\n",
        content,
        re.MULTILINE,
    )
    if match is None:
        raise ValueError(f"实施文档缺少“{heading}”")
    level = len(match.group("marks"))
    body_start = match.end()
    boundary = re.search(
        rf"^#{{2,{level}}}\s+",
        content[body_start:],
        re.MULTILINE,
    )
    body_end = body_start + boundary.start() if boundary else len(content)
    return content[body_start:body_end].strip()


def _first_section(content: str, *headings: str) -> str:
    for heading in headings:
        try:
            return _section(content, heading)
        except ValueError:
            continue
    raise ValueError(f"实施文档缺少“{headings[0]}”")


def _code_plan_section(content: str) -> str:
    return _first_section(content, "2.3 代码修改计划", "2.2 代码修改计划")


def _code_result_section(content: str) -> str:
    return _first_section(content, "3.4.1 实际代码修改", "3.1 实际代码修改")


def _table_file_paths(section: str, *, context: str = "代码修改计划") -> list[str]:
    lines = section.splitlines()
    for index, line in enumerate(lines):
        if not line.strip().startswith("|"):
            continue
        headers = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if "文件" not in headers:
            continue
        file_index = headers.index("文件")
        paths: list[str] = []
        for row in lines[index + 1 :]:
            stripped = row.strip()
            if not stripped.startswith("|"):
                if paths:
                    break
                continue
            cells = [cell.strip() for cell in stripped.strip("|").split("|")]
            if all(re.fullmatch(r"[-:]+", cell) for cell in cells):
                continue
            if len(cells) != len(headers):
                raise ValueError(f"{context}表的数据列数与表头不一致")
            paths.append(cells[file_index])
        if not paths:
            raise ValueError(f"{context}表没有任何文件")
        return paths
    raise ValueError(f"{context}缺少包含“文件”列的表格")


def _table_rows(
    section: str,
    *,
    context: str,
    required_headers: tuple[str, ...],
) -> list[tuple[int, dict[str, str]]]:
    """读取一张固定表，并保留每行在章节内的行号。"""
    lines = section.splitlines()
    for index, line in enumerate(lines):
        if not line.strip().startswith("|"):
            continue
        headers = [cell.strip() for cell in line.strip().strip("|").split("|")]
        missing = [header for header in required_headers if header not in headers]
        if missing:
            continue
        rows: list[tuple[int, dict[str, str]]] = []
        for row_index, row in enumerate(lines[index + 1 :], index + 2):
            stripped = row.strip()
            if not stripped.startswith("|"):
                if rows:
                    break
                continue
            cells = [cell.strip() for cell in stripped.strip("|").split("|")]
            if all(re.fullmatch(r"[-:]+", cell) for cell in cells):
                continue
            if len(cells) != len(headers):
                raise ValueError(
                    f"{context}表第 {row_index} 行有 {len(cells)} 列，"
                    f"表头有 {len(headers)} 列"
                )
            rows.append((row_index, dict(zip(headers, cells))))
        if not rows:
            raise ValueError(f"{context}表没有任何数据行")
        return rows
    raise ValueError(
        f"{context}缺少固定表头：{'、'.join(required_headers)}"
    )


def _is_record_placeholder(value: str) -> bool:
    normalized = re.sub(r"[\s`*_。，；;：:]+", "", value).casefold()
    return normalized in _RECORD_PLACEHOLDERS or bool(
        re.search(r"(?i)(?:^|\W)(?:todo|tbd)(?:$|\W)", value)
    )


def _normalized_location_value(value: str) -> str:
    return re.sub(r"[\s`*_。，；;：:]+", "", value).casefold()


def _is_location_placeholder(value: str) -> bool:
    """位置列仍拒绝泛称；具体旧名称不再需要匹配某种语言声明。"""

    if _is_record_placeholder(value):
        return True
    normalized = _normalized_location_value(value)
    if normalized in _LOCATION_GENERIC_TERMS:
        return True
    return bool(
        re.search(
            r"(?i)(?:^|[\s`*_，,；;：:])(?:"
            + "|".join(re.escape(term) for term in _LOCATION_GENERIC_TERMS)
            + r")(?:$|[\s`*_，,；;：:])",
            value,
        )
    )


def _unwrapped_location_value(value: str) -> str:
    """移除一层 Markdown 行内代码标记，保留普通旧位置文本。"""

    normalized = value.strip()
    if len(normalized) >= 2 and normalized.startswith("`") and normalized.endswith("`"):
        return normalized[1:-1].strip()
    return normalized


def _parse_recorded_line_range(location: str) -> _RecordedLineRange | None:
    """解析新位置格式；None 表示仍在兼容期内的旧名称记录。"""

    value = _unwrapped_location_value(location)
    basis = "final"
    if value.startswith("基线"):
        basis = "baseline"
        value = _unwrapped_location_value(value.removeprefix("基线").strip())

    match = _FINAL_LINE_RANGE_PATTERN.fullmatch(value)
    if match is not None:
        start = int(match.group("start"))
        end = int(match.group("end"))
        if start > end:
            raise ValueError(f"起始行 L{start} 不能大于结束行 L{end}")
        return _RecordedLineRange(basis=basis, start=start, end=end)

    # 只有看起来已经在填写行号的人才报告格式错误，旧的具体名称继续兼容。
    if basis == "baseline" or re.match(r"^[Ll][ \t]*[0-9]", value):
        raise ValueError("行号范围必须写成 L起始-L结束，例如 L12-L34")
    return None


def _is_file_deletion_location(location: str) -> bool:
    return _normalized_location_value(location) in _FILE_DELETION_LOCATIONS


def _line_count(content: str) -> int:
    return len(content.splitlines(keepends=True))


def _changed_line_hunks(
    before: str,
    after: str,
) -> list[tuple[tuple[int, int] | None, tuple[int, int] | None]]:
    """返回每个差异块在实施前和最终文件中的 1 起始行号范围。"""

    hunks: list[tuple[tuple[int, int] | None, tuple[int, int] | None]] = []
    matcher = difflib.SequenceMatcher(
        a=before.splitlines(keepends=True),
        b=after.splitlines(keepends=True),
        autojunk=False,
    )
    for tag, before_start, before_end, after_start, after_end in matcher.get_opcodes():
        if tag == "equal":
            continue
        before_range = (
            (before_start + 1, before_end)
            if before_start != before_end
            else None
        )
        after_range = (
            (after_start + 1, after_end) if after_start != after_end else None
        )
        hunks.append((before_range, after_range))
    return hunks


def _changed_line_ranges(before: str, after: str) -> tuple[list[tuple[int, int]], list[tuple[int, int]]]:
    """返回实施前和最终文件中分别发生改变的 1 起始行号范围。"""

    hunks = _changed_line_hunks(before, after)
    return (
        [before_range for before_range, _after_range in hunks if before_range],
        [after_range for _before_range, after_range in hunks if after_range],
    )


def _line_range_intersects(
    line_range: _RecordedLineRange,
    changed_ranges: list[tuple[int, int]],
) -> bool:
    return any(
        line_range.start <= changed_end and changed_start <= line_range.end
        for changed_start, changed_end in changed_ranges
    )


def _format_line_ranges(ranges: list[tuple[int, int]]) -> str:
    return "、".join(f"L{start}-L{end}" for start, end in ranges) or "无"


def _manifest_entry_for_recorded_path(manifest: dict, path: str) -> dict:
    entries = manifest.get("entries")
    entry = entries.get(path) if isinstance(entries, dict) else None
    if not isinstance(entry, dict):
        raise ValueError(f"实施前回退清单没有 {path!r} 的文件副本")
    return entry


def _read_utf8_file(path: str, *, description: str) -> str:
    try:
        with open(path, "rb") as stream:
            raw = stream.read()
    except OSError as exc:
        raise ValueError(f"无法读取{description}：{exc}") from exc
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError(f"{description}不是 UTF-8 文本，不能使用行号范围定位") from exc


def _recorded_path_texts(
    project_root: str,
    manifest: dict,
    path: str,
) -> tuple[dict, str | None, str | None]:
    """读取清单中的实施前副本和当前最终文本；None 表示该版本不存在。"""

    entry = _manifest_entry_for_recorded_path(manifest, path)
    original_exists = entry.get("original_exists")
    if not isinstance(original_exists, bool):
        raise ValueError(f"实施前回退清单没有明确 {path!r} 的原文件状态")

    before: str | None = None
    if original_exists:
        workflow_id = _validated_workflow_id(manifest.get("workflow_id", ""))
        manifest_dir = os.path.dirname(_manifest_full_path(project_root, workflow_id))
        backup_path = _safe_backup_path(
            manifest_dir,
            entry.get("backup_path"),
            path,
        )
        before = _read_utf8_file(backup_path, description=f"{path} 的实施前副本")

    full_path = os.path.join(project_root, path)
    if not os.path.lexists(full_path):
        return entry, before, None
    if os.path.islink(full_path) or not os.path.isfile(full_path):
        raise ValueError(f"当前文件不是普通文件：{path}")
    return entry, before, _read_utf8_file(full_path, description=f"当前文件 {path}")


def _acceptance_ids(project_root: str, topic: str) -> tuple[set[str], str | None]:
    relative_path = topic_paths(project_root, topic)["acceptance_plan"]
    full_path = os.path.join(project_root, relative_path)
    if not os.path.isfile(full_path):
        return set(), f"缺少主题验收计划：{relative_path}"
    try:
        with open(full_path, "r", encoding="utf-8") as stream:
            content = stream.read()
    except OSError as exc:
        return set(), f"无法读取主题验收计划 {relative_path}：{exc}"
    identifiers = {
        match.upper()
        for match in re.findall(
            r"<a\s+[^>]*id=[\"'](ac-\d+)[\"']",
            content,
            re.IGNORECASE,
        )
    }
    if not identifiers:
        return set(), f"主题验收计划没有显式 AC 定位编号：{relative_path}"
    return identifiers, None


def _recorded_code_changes_with_diagnostics(
    project_root: str,
    topics: list[str],
) -> tuple[list[RecordedCodeChange], list[diagnostics_mod.Diagnostic]]:
    """读取实施后记录，并在事实产生处保留每个单元格的诊断。"""
    changes: list[RecordedCodeChange] = []
    diagnostics: list[diagnostics_mod.Diagnostic] = []
    required_headers = (
        "文件",
        "实际修改的代码逻辑",
        "数据、状态或输出的实际变化",
    )
    for topic in topics:
        relative_path = topic_paths(project_root, topic)["impl_doc"]
        full_path = os.path.join(project_root, relative_path)
        if not os.path.isfile(full_path):
            evidence = f"{relative_path}：缺少主题实施文档"
            diagnostics.append(
                diagnostics_mod.Diagnostic(
                    kind="error",
                    check_id="impl.implementation_record.document_missing",
                    location=relative_path,
                    expected="当前验收主题有一份实施记录文档，并包含实施后记录",
                    actual="主题实施文档不存在",
                    evidence=evidence,
                    impact="无法读取本主题实际修改记录，不能核对实施记录与真实文件差异",
                    next_action="创建或恢复本主题的实施记录文档，并填写实施后记录",
                )
            )
            continue
        try:
            with open(full_path, "r", encoding="utf-8") as stream:
                content = stream.read()
            section = _code_result_section(content)
            section_offset = content.find(section)
            section_start_line = content[:section_offset].count("\n") + 1
            rows = _table_rows(
                section,
                context=f"{relative_path} 的实际代码修改记录",
                required_headers=required_headers,
            )
        except (OSError, ValueError) as exc:
            evidence = str(exc)
            diagnostics.append(
                diagnostics_mod.Diagnostic(
                    kind="error",
                    check_id="impl.implementation_record.table_invalid",
                    location=f"{relative_path}，“3.4.1 实际代码修改”",
                    expected="实施后记录包含字段完整、列数正确的实际代码修改表",
                    actual=evidence,
                    evidence=evidence,
                    impact="无法从实施记录得到可核对的文件集合",
                    next_action="修正该章节的实际代码修改表头、列数和数据行后再核对",
                )
            )
            continue

        accepted_ids, acceptance_error = _acceptance_ids(project_root, topic)
        if acceptance_error:
            evidence = f"{relative_path}：验收条件未检查；原因：{acceptance_error}"
            diagnostics.append(
                diagnostics_mod.Diagnostic(
                    kind="error",
                    check_id="impl.implementation_record.acceptance_source_invalid",
                    location=relative_path,
                    expected="对应验收条件能从当前主题的验收计划读取明确 AC 编号",
                    actual=f"无法读取可用验收条件：{acceptance_error}",
                    evidence=evidence,
                    impact="实施记录中的 AC 编号不能被验证，不能确认修改对应了本主题验收条件",
                    next_action="修正或恢复本主题验收计划中的 AC 定位编号，再核对实施记录",
                )
            )
        for local_line, row in rows:
            line = section_start_line + local_line - 1
            prefix = f"{relative_path}:{line}"
            if "代码位置（最终文件）" in row:
                location_column = "代码位置（最终文件）"
                requires_line_range = True
            elif "类、函数或配置项" in row:
                location_column = "类、函数或配置项"
                requires_line_range = False
            else:
                diagnostics.append(
                    diagnostics_mod.Diagnostic(
                        kind="error",
                        check_id="impl.implementation_record.location_column_missing",
                        location=f"{prefix}，实际代码修改表",
                        expected=(
                            "表头包含新列“代码位置（最终文件）”，"
                            "或兼容旧列“类、函数或配置项”"
                        ),
                        actual="实际代码修改表缺少代码位置列",
                        evidence=(
                            f"{prefix}，实际代码修改表的列={sorted(row)}；"
                            "没有可读取的代码位置列"
                        ),
                        impact="无法将该行实施记录对应到真实文件中的改动范围",
                        next_action="新增“代码位置（最终文件）”列，并填写 L起始-L结束，例如 L12-L34",
                    )
                )
                continue
            location = row[location_column].strip()
            logic = row["实际修改的代码逻辑"].strip()
            observable = row["数据、状态或输出的实际变化"].strip()
            acceptance = (
                row.get("对应验收条件")
                or row.get("对应验收条件和测试项")
                or ""
            ).strip()
            try:
                path = _normalized_relative_path(
                    project_root,
                    row["文件"],
                    purpose="实施后记录的“文件”列",
                )
            except ValueError as exc:
                evidence = f"{prefix}，“文件”列：{exc}"
                diagnostics.append(
                    diagnostics_mod.Diagnostic(
                        kind="error",
                        check_id="impl.implementation_record.path_invalid",
                        location=f"{prefix}，“文件”列",
                        expected="文件列写入实际修改文件的项目内相对路径，不能使用流程文档或占位值",
                        actual=f"文件列值为 {row['文件']!r}，不能作为实施文件路径：{exc}",
                        evidence=evidence,
                        impact="这行实施记录不能映射到真实文件，三方文件集合无法完整核对",
                        next_action="把“文件”列改为这次实际修改文件的项目内相对路径；不要填写“暂无”等占位值",
                    )
                )
                continue

            if _is_location_placeholder(location):
                evidence = (
                    f"{prefix}，“{location_column}”列使用占位内容：{location!r}；"
                    f"文件={path!r}，记录位置={location!r}；"
                    "填写最终文件行号范围，例如 L12-L34；不能使用“组件”等泛称"
                )
                diagnostics.append(
                    diagnostics_mod.Diagnostic(
                        kind="error",
                        check_id="impl.implementation_record.location_placeholder",
                        location=f"{prefix}，“{location_column}”列",
                        expected=(
                            "填写最终文件行号范围（例如 L12-L34），或保留具体的旧代码名称；"
                            "不能使用“组件”等泛称"
                        ),
                        actual=f"位置值为占位内容 {location!r}",
                        evidence=evidence,
                        impact="无法确认这条记录描述了文件中的哪一处实际改动",
                        next_action=(
                            "把该列改为最终文件行号范围，例如 L12-L34；"
                            "旧记录中的具体代码名称可以保留，不必为了门禁改成别的名称"
                        ),
                    )
                )
            if _is_record_placeholder(logic):
                evidence = (
                    f"{prefix}，“实际修改的代码逻辑”列："
                    f"实际修改的代码逻辑使用占位内容 {logic!r}"
                )
                diagnostics.append(
                    diagnostics_mod.Diagnostic(
                        kind="error",
                        check_id="impl.implementation_record.logic_placeholder",
                        location=f"{prefix}，“实际修改的代码逻辑”列",
                        expected="说明该位置实际改变的判断、数据处理或调用逻辑",
                        actual=f"实际修改逻辑为占位内容 {logic!r}",
                        evidence=evidence,
                        impact="无法从记录判断本次实现具体做了什么",
                        next_action="写出该代码位置实际修改的逻辑，不要保留 TODO 或“暂无”等占位内容",
                    )
                )
            if _is_record_placeholder(observable):
                evidence = (
                    f"{prefix}，“数据、状态或输出的实际变化”列："
                    f"数据、状态或输出的实际变化使用占位内容 {observable!r}"
                )
                diagnostics.append(
                    diagnostics_mod.Diagnostic(
                        kind="error",
                        check_id="impl.implementation_record.observable_placeholder",
                        location=f"{prefix}，“数据、状态或输出的实际变化”列",
                        expected="说明可以观察到的数据、状态或输出变化",
                        actual=f"实际变化为占位内容 {observable!r}",
                        evidence=evidence,
                        impact="无法验证实现是否产生了可检查的结果",
                        next_action="写出可从代码、状态或输出观察到的实际变化",
                    )
                )
            referenced_ids = {
                match.upper()
                for match in re.findall(r"\bAC-\d+\b", acceptance, re.IGNORECASE)
            }
            if not acceptance or _is_record_placeholder(acceptance):
                evidence = (
                    f"{prefix}，“对应验收条件”列缺少具体 AC 编号：{acceptance!r}"
                )
                diagnostics.append(
                    diagnostics_mod.Diagnostic(
                        kind="error",
                        check_id="impl.implementation_record.acceptance_missing",
                        location=f"{prefix}，“对应验收条件”列",
                        expected="至少写入一个当前主题验收计划中存在的 AC 编号",
                        actual=f"对应验收条件为 {acceptance!r}，没有具体 AC 编号",
                        evidence=evidence,
                        impact="无法将这条实际修改追溯到验收条件",
                        next_action="填写本主题验收计划中的具体 AC 编号，例如 AC-01",
                    )
                )
            elif not referenced_ids:
                evidence = (
                    f"{prefix}，“对应验收条件”列没有可识别的 AC 编号：{acceptance!r}"
                )
                diagnostics.append(
                    diagnostics_mod.Diagnostic(
                        kind="error",
                        check_id="impl.implementation_record.acceptance_unreadable",
                        location=f"{prefix}，“对应验收条件”列",
                        expected="使用 AC-数字 格式引用当前主题的验收条件",
                        actual=f"对应验收条件为 {acceptance!r}，没有可识别的 AC 编号",
                        evidence=evidence,
                        impact="无法将这条实际修改追溯到验收条件",
                        next_action="把该列改为当前主题验收计划中的 AC-数字编号",
                    )
                )
            elif accepted_ids:
                missing_ids = sorted(referenced_ids - accepted_ids)
                if missing_ids:
                    evidence = (
                        f"{prefix}，“对应验收条件”列引用 {missing_ids}，"
                        f"但验收计划中不存在；实际可用编号={sorted(accepted_ids)}"
                    )
                    diagnostics.append(
                        diagnostics_mod.Diagnostic(
                            kind="error",
                            check_id="impl.implementation_record.acceptance_unknown",
                            location=f"{prefix}，“对应验收条件”列",
                            expected="只引用当前主题验收计划中存在的 AC 编号",
                            actual=(
                                f"引用了 {missing_ids}；当前可用编号为 {sorted(accepted_ids)}"
                            ),
                            evidence=evidence,
                            impact="实施记录无法证明该修改满足了本主题的验收条件",
                            next_action="把该列改为当前主题验收计划中实际存在的 AC 编号",
                        )
                    )

            changes.append(
                RecordedCodeChange(
                    topic=topic,
                    document_path=relative_path,
                    line=line,
                    path=path,
                    location_column=location_column,
                    requires_line_range=requires_line_range,
                    location=location,
                    logic=logic,
                    observable_change=observable,
                    acceptance_conditions=acceptance,
                )
            )
    return changes, diagnostics


def _recorded_line_range_diagnostics(
    project_root: str,
    manifest: dict,
    changes: list[RecordedCodeChange],
) -> list[diagnostics_mod.Diagnostic]:
    """核对新行号位置是否覆盖实施前副本与最终文件之间的真实差异。"""

    diagnostics: list[diagnostics_mod.Diagnostic] = []
    texts_by_path: dict[str, tuple[dict, str | None, str | None]] = {}
    text_errors: dict[str, str] = {}
    valid_line_ranges_by_path: dict[str, list[_RecordedLineRange]] = {}
    valid_whole_file_deletions: set[str] = set()

    def recorded_texts(path: str) -> tuple[dict, str | None, str | None] | None:
        if path in texts_by_path:
            return texts_by_path[path]
        if path in text_errors:
            return None
        try:
            texts_by_path[path] = _recorded_path_texts(project_root, manifest, path)
        except ValueError as exc:
            text_errors[path] = str(exc)
            return None
        return texts_by_path[path]

    for change in changes:
        prefix = f"{change.document_path}:{change.line}"
        diagnostic_location = f"{prefix}，“{change.location_column}”列"
        if _is_file_deletion_location(change.location):
            texts = recorded_texts(change.path)
            if texts is None:
                detail = text_errors[change.path]
                diagnostics.append(
                    diagnostics_mod.Diagnostic(
                        kind="error",
                        check_id="impl.implementation_record.location_range_baseline_unavailable",
                        location=diagnostic_location,
                        expected="删除整个文件时能从实施前回退清单读取该文件的原始状态",
                        actual=f"无法核对删除位置：{detail}",
                        evidence=(
                            f"{prefix}，记录位置={change.location!r}，文件={change.path!r}；"
                            f"{detail}"
                        ),
                        impact="无法证明“删除整个文件”对应本轮可恢复的真实文件删除",
                        next_action="恢复或重新准备该文件的实施前副本，再记录删除整个文件",
                    )
                )
                continue
            entry, _before, after = texts
            if entry.get("original_exists") is True and after is None:
                valid_whole_file_deletions.add(change.path)
                continue
            actual = (
                "当前文件仍存在"
                if after is not None
                else "实施前该文件不存在，不能声称删除整个文件"
            )
            diagnostics.append(
                diagnostics_mod.Diagnostic(
                    kind="error",
                    check_id="impl.implementation_record.location_deletion_marker_invalid",
                    location=diagnostic_location,
                    expected="“删除整个文件”只能用于实施前存在且最终已删除的文件",
                    actual=actual,
                    evidence=(
                        f"{prefix}，记录位置={change.location!r}，文件={change.path!r}；"
                        f"实施前存在={entry.get('original_exists')!r}，最终文件存在={after is not None}"
                    ),
                    impact="删除记录没有对应到可验证的整文件删除",
                    next_action=(
                        "文件仍存在时改为最终文件行号范围，例如 L12-L34；"
                        "只有整文件已删除时才填写“删除整个文件”"
                    ),
                )
            )
            continue

        try:
            line_range = _parse_recorded_line_range(change.location)
        except ValueError as exc:
            diagnostics.append(
                diagnostics_mod.Diagnostic(
                    kind="error",
                    check_id="impl.implementation_record.location_range_invalid",
                    location=diagnostic_location,
                    expected=(
                        "使用最终文件行号范围 L起始-L结束，例如 L12-L34；"
                        "删除的旧行使用“基线 L起始-L结束”"
                    ),
                    actual=f"位置值为 {change.location!r}，格式无效：{exc}",
                    evidence=f"{prefix}，文件={change.path!r}，记录位置={change.location!r}；{exc}",
                    impact="无法计算记录位置是否覆盖本轮真实改动",
                    next_action=(
                        "把该列改为 L12-L34；删除了最终文件中不存在的旧行时，"
                        "改为“基线 L12-L34”"
                    ),
                )
            )
            continue
        if line_range is None:
            # 旧文档中的名称记录保留可读性，但不再由语言声明正则阻断。
            if change.requires_line_range:
                diagnostics.append(
                    diagnostics_mod.Diagnostic(
                        kind="error",
                        check_id="impl.implementation_record.location_range_required",
                        location=diagnostic_location,
                        expected="新表头的代码位置使用最终文件行号范围，例如 L12-L34",
                        actual=f"位置值为 {change.location!r}，不是行号范围",
                        evidence=(
                            f"{prefix}，文件={change.path!r}，记录位置={change.location!r}；"
                            "当前表头要求使用最终文件行号范围"
                        ),
                        impact="新实施记录无法证明它描述了本轮真实改动的具体范围",
                        next_action="把该列改为覆盖真实差异的 L起始-L结束，例如 L12-L34",
                    )
                )
            continue

        texts = recorded_texts(change.path)
        if texts is None:
            detail = text_errors[change.path]
            diagnostics.append(
                diagnostics_mod.Diagnostic(
                    kind="error",
                    check_id="impl.implementation_record.location_range_baseline_unavailable",
                    location=diagnostic_location,
                    expected="目标文件有可读取的实施前副本，供行号范围与真实差异核对",
                    actual=f"无法核对行号范围：{detail}",
                    evidence=(
                        f"{prefix}，文件={change.path!r}，记录位置={change.location!r}；"
                        f"{detail}"
                    ),
                    impact="无法证明记录位置覆盖了本轮真实代码变化",
                    next_action="重新准备该文件的实施前基线，或把实施记录改回已存在的计划文件",
                )
            )
            continue

        _entry, before, after = texts
        if line_range.basis == "final":
            if after is None:
                diagnostics.append(
                    diagnostics_mod.Diagnostic(
                        kind="error",
                        check_id="impl.implementation_record.location_range_final_missing",
                        location=diagnostic_location,
                        expected="最终文件存在时使用 L起始-L结束；整文件删除填写“删除整个文件”",
                        actual=f"文件 {change.path!r} 在最终工作区不存在，不能使用最终行号范围",
                        evidence=(
                            f"{prefix}，文件={change.path!r}，记录位置={change.location!r}；"
                            "最终文件不存在"
                        ),
                        impact="最终文件没有可定位的行号范围",
                        next_action=(
                            "整文件删除时填写“删除整个文件”；"
                            "只删除部分旧行且文件仍存在时填写“基线 L起始-L结束”"
                        ),
                    )
                )
                continue
            target_content = after
            target_name = "最终文件"
        else:
            if before is None:
                diagnostics.append(
                    diagnostics_mod.Diagnostic(
                        kind="error",
                        check_id="impl.implementation_record.location_range_baseline_missing",
                        location=diagnostic_location,
                        expected="只有实施前存在的文件才能使用“基线 L起始-L结束”",
                        actual=f"文件 {change.path!r} 是本轮新增文件，没有实施前行号",
                        evidence=(
                            f"{prefix}，文件={change.path!r}，记录位置={change.location!r}；"
                            "实施前文件不存在"
                        ),
                        impact="新增文件不能用不存在的旧行号证明改动位置",
                        next_action="为新增文件填写最终文件行号范围，例如 L1-L12",
                    )
                )
                continue
            target_content = before
            target_name = "实施前副本"

        line_count = _line_count(target_content)
        if line_range.end > line_count:
            diagnostics.append(
                diagnostics_mod.Diagnostic(
                    kind="error",
                    check_id="impl.implementation_record.location_range_out_of_bounds",
                    location=diagnostic_location,
                    expected=(
                        f"{target_name}共 {line_count} 行，位置范围必须在 L1-L{line_count} 内"
                    ),
                    actual=(
                        f"记录位置为 {change.location!r}，结束行 L{line_range.end} "
                        f"超过 {target_name}的 L{line_count}"
                    ),
                    evidence=(
                        f"{prefix}，文件={change.path!r}，记录位置={change.location!r}；"
                        f"{target_name}行数={line_count}"
                    ),
                    impact="记录位置不能指向目标文件中的真实行",
                    next_action=f"把该列改为 {target_name}内的 L1-L{line_count} 范围",
                )
            )
            continue

        before_ranges, after_ranges = _changed_line_ranges(before or "", after or "")
        changed_ranges = after_ranges if line_range.basis == "final" else before_ranges
        if _line_range_intersects(line_range, changed_ranges):
            valid_line_ranges_by_path.setdefault(change.path, []).append(line_range)
            continue
        diagnostics.append(
            diagnostics_mod.Diagnostic(
                kind="error",
                check_id="impl.implementation_record.location_range_unchanged",
                location=diagnostic_location,
                expected=(
                    f"记录范围必须与{target_name}中的本轮真实差异相交；"
                    f"当前真实差异范围={_format_line_ranges(changed_ranges)}"
                ),
                actual=(
                    f"记录位置 {change.location!r} 在{target_name}内有效，"
                    "但没有覆盖本轮真实变化"
                ),
                evidence=(
                    f"{prefix}，文件={change.path!r}，记录位置={change.location!r}；"
                    f"{target_name}真实差异范围={_format_line_ranges(changed_ranges)}"
                ),
                impact="实施记录可以指向文件中的旧内容，不能证明它描述了本轮改动",
                next_action=(
                    f"把该列改为与真实差异相交的范围："
                    f"{_format_line_ranges(changed_ranges)}"
                ),
            )
        )

    changes_by_path: dict[str, list[RecordedCodeChange]] = {}
    for change in changes:
        changes_by_path.setdefault(change.path, []).append(change)
    for path, path_changes in changes_by_path.items():
        # 旧表头只是兼容读取，不倒灌新的“每个差异块都要覆盖”要求。
        if not all(change.requires_line_range for change in path_changes):
            continue
        if path in valid_whole_file_deletions:
            continue
        recorded_ranges = valid_line_ranges_by_path.get(path, [])
        if len(recorded_ranges) != len(path_changes):
            continue
        texts = recorded_texts(path)
        if texts is None:
            continue
        _entry, before, after = texts
        if before is None and after is None:
            continue
        uncovered_locations: list[str] = []
        for before_range, after_range in _changed_line_hunks(before or "", after or ""):
            covered = (
                after_range is not None
                and any(
                    line_range.basis == "final"
                    and _line_range_intersects(line_range, [after_range])
                    for line_range in recorded_ranges
                )
            ) or (
                before_range is not None
                and any(
                    line_range.basis == "baseline"
                    and _line_range_intersects(line_range, [before_range])
                    for line_range in recorded_ranges
                )
            )
            if not covered:
                labels: list[str] = []
                if after_range is not None:
                    labels.append(f"最终 {_format_line_ranges([after_range])}")
                if before_range is not None:
                    labels.append(f"基线 {_format_line_ranges([before_range])}")
                uncovered_locations.append(" / ".join(labels))
        if not uncovered_locations:
            continue
        diagnostics.append(
            diagnostics_mod.Diagnostic(
                kind="error",
                check_id="impl.implementation_record.location_range_coverage_missing",
                location=f"{path}（本轮真实差异）",
                expected="新格式的实施记录覆盖该文件中的每个本轮真实差异块",
                actual=(
                    "以下差异块没有被任何代码位置范围覆盖："
                    f"{uncovered_locations}"
                ),
                evidence=(
                    f"文件={path!r}；记录范围="
                    f"{[f'{line_range.basis}:{line_range.start}-{line_range.end}' for line_range in recorded_ranges]}；"
                    f"未覆盖差异={uncovered_locations}"
                ),
                impact="同一文件中的部分真实改动没有实施记录，不能完整追溯到实际逻辑和验收条件",
                next_action=(
                    "在“3.4.1 实际代码修改”中为每个未覆盖差异增加一行，"
                    "填写对应的最终 L起始-L结束 或基线 L起始-L结束"
                ),
            )
        )
    return diagnostics


def _recorded_code_changes(
    project_root: str,
    topics: list[str],
) -> tuple[list[RecordedCodeChange], list[str]]:
    """兼容旧调用方的文字接口；新门禁应使用结构化版本。"""
    changes, diagnostics = _recorded_code_changes_with_diagnostics(
        project_root,
        topics,
    )
    return changes, list(dict.fromkeys(item.evidence for item in diagnostics))


def _planned_code_changes(
    project_root: str,
    topics: list[str],
) -> tuple[list[PlannedCodeChange], list[diagnostics_mod.Diagnostic]]:
    """读取实施前计划，并保留每个文件单元格的实际位置。"""
    changes: list[PlannedCodeChange] = []
    diagnostics: list[diagnostics_mod.Diagnostic] = []
    for topic in topics:
        relative_path = topic_paths(project_root, topic)["impl_doc"]
        full_path = os.path.join(project_root, relative_path)
        if not os.path.isfile(full_path):
            evidence = f"缺少主题实施文档：{relative_path}"
            diagnostics.append(
                diagnostics_mod.Diagnostic(
                    kind="error",
                    check_id="impl.implementation_plan.document_missing",
                    location=relative_path,
                    expected="当前验收主题有一份包含代码修改计划的实施记录文档",
                    actual="主题实施文档不存在",
                    evidence=evidence,
                    impact="无法确定本轮允许修改的文件范围",
                    next_action="创建或恢复本主题实施记录文档，并填写代码修改计划",
                )
            )
            continue
        try:
            with open(full_path, "r", encoding="utf-8") as stream:
                content = stream.read()
            section = _code_plan_section(content)
            section_offset = content.find(section)
            section_start_line = content[:section_offset].count("\n") + 1
            rows = _table_rows(
                section,
                context=f"{relative_path} 的代码修改计划",
                required_headers=("文件",),
            )
        except (OSError, ValueError) as exc:
            evidence = str(exc)
            diagnostics.append(
                diagnostics_mod.Diagnostic(
                    kind="error",
                    check_id="impl.implementation_plan.table_invalid",
                    location=f"{relative_path}，“2.3 代码修改计划”",
                    expected="代码修改计划包含带“文件”列且列数正确的表格",
                    actual=evidence,
                    evidence=evidence,
                    impact="无法确定本轮实施计划覆盖的文件范围",
                    next_action="修正该章节的代码修改计划表头、列数和数据行",
                )
            )
            continue
        for local_line, row in rows:
            line = section_start_line + local_line - 1
            raw_path = row["文件"]
            prefix = f"{relative_path}:{line}"
            try:
                path = _normalized_relative_path(project_root, raw_path)
            except ValueError as exc:
                evidence = f"{prefix}，“文件”列：{exc}"
                diagnostics.append(
                    diagnostics_mod.Diagnostic(
                        kind="error",
                        check_id="impl.implementation_plan.path_invalid",
                        location=f"{prefix}，“文件”列",
                        expected="文件列写入实际修改文件的项目内相对路径，不能使用流程文档或占位值",
                        actual=f"文件列值为 {raw_path!r}，不能作为实施文件路径：{exc}",
                        evidence=evidence,
                        impact="实施计划范围不完整，不能判断哪些真实改动应由本轮实施解释",
                        next_action="把“文件”列改为实际修改文件的项目内相对路径；不要填写“暂无”等占位值",
                    )
                )
                continue
            changes.append(
                PlannedCodeChange(
                    topic=topic,
                    document_path=relative_path,
                    line=line,
                    path=path,
                )
            )
    return changes, diagnostics


def planned_code_paths(project_root: str, topics: list[str]) -> list[str]:
    changes, diagnostics = _planned_code_changes(project_root, topics)
    if diagnostics:
        raise ValueError("\n".join(item.evidence for item in diagnostics))
    return sorted({change.path for change in changes})


def recorded_code_paths(project_root: str, topics: list[str]) -> list[str]:
    """读取并核对实施后记录；不能只凭“文件”列宣称实现已完成。"""
    changes, errors = _recorded_code_changes(project_root, topics)
    if errors:
        raise ValueError("\n".join(errors))
    return sorted({change.path for change in changes})


def compute_plan_hash(project_root: str, topics: list[str]) -> str:
    payload: list[str] = []
    for topic in topics:
        relative_path = topic_paths(project_root, topic)["impl_doc"]
        full_path = os.path.join(project_root, relative_path)
        with open(full_path, "r", encoding="utf-8") as stream:
            content = stream.read()
            section = _first_section(
                content,
                "2. 实施前计划（代码计划）",
                "2. 实施前计划",
            )
        payload.append(f"{topic}\n{section}")
    return hashlib.sha256("\n\n".join(payload).encode("utf-8")).hexdigest()


def _read_manifest(project_root: str, relative_path: str) -> tuple[dict, bytes]:
    normalized = _safe_project_relative_path(
        project_root,
        relative_path,
        purpose="回退清单路径",
    )
    full_path = os.path.join(project_root, normalized)
    if not os.path.isfile(full_path):
        raise ValueError(f"回退清单不存在：{normalized}")
    with open(full_path, "rb") as stream:
        raw = stream.read()
    try:
        data = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"回退清单无法读取：{exc}") from exc
    if not isinstance(data, dict):
        raise ValueError(f"回退清单顶层必须是对象：{normalized}")
    return data, raw


def _validated_manifest_entries(
    project_root: str,
    manifest: dict,
    manifest_dir: str,
    *,
    allow_process_documents: bool,
) -> dict[str, dict]:
    entries = manifest.get("entries")
    if not isinstance(entries, dict):
        raise ValueError("回退清单缺少文件记录")
    normalized_entries: dict[str, dict] = {}
    normalized_keys: set[str] = set()
    for raw_path, entry in entries.items():
        if not isinstance(raw_path, str) or not isinstance(entry, dict):
            raise ValueError("回退清单包含无效文件记录")
        if allow_process_documents:
            path = _safe_project_relative_path(
                project_root,
                raw_path,
                purpose="受管文件路径",
            )
        else:
            path = _normalized_relative_path(
                project_root,
                raw_path,
                purpose="回退清单文件记录",
            )
        comparison_key = path.casefold()
        if comparison_key in normalized_keys:
            raise ValueError(f"回退清单包含重复文件路径：{path}")
        normalized_keys.add(comparison_key)
        original_exists = entry.get("original_exists")
        if not isinstance(original_exists, bool):
            raise ValueError(f"回退清单缺少明确的原文件存在状态：{path}")
        if original_exists:
            backup_path = entry.get("backup_path")
            if not backup_path:
                raise ValueError(f"回退清单缺少文件副本位置：{path}")
            full_backup = _safe_backup_path(manifest_dir, backup_path, path)
            if not os.path.isfile(full_backup):
                raise ValueError(f"实施前文件副本缺失：{path}")
            content_hash = _sha256_file(full_backup)
            if content_hash != entry.get("content_hash"):
                raise ValueError(f"实施前文件副本内容已损坏：{path}")
        elif entry.get("backup_path") is not None or entry.get("content_hash") is not None:
            raise ValueError(f"原本不存在的文件不能带有内容副本：{path}")
        normalized_entries[path] = dict(entry)
    return normalized_entries


def _validated_initial_inventory(
    project_root: str,
    manifest: dict,
) -> dict[str, str]:
    """校验旧清单用于证明首次内容的逐文件哈希，避免损坏结构泄漏类型异常。"""
    inventory = manifest.get("initial_inventory")
    if not isinstance(inventory, dict):
        raise ValueError("回退清单的 initial_inventory（初始文件哈希表）必须是对象")
    normalized_inventory: dict[str, str] = {}
    normalized_keys: set[str] = set()
    for raw_path, content_hash in inventory.items():
        if not isinstance(raw_path, str):
            raise ValueError("初始文件哈希表包含非字符串路径")
        path = _normalized_relative_path(
            project_root,
            raw_path,
            purpose="初始文件哈希表记录",
        )
        comparison_key = path.casefold()
        if comparison_key in normalized_keys:
            raise ValueError(f"初始文件哈希表包含重复文件路径：{path}")
        normalized_keys.add(comparison_key)
        if not isinstance(content_hash, str) or re.fullmatch(
            r"[0-9a-f]{64}", content_hash
        ) is None:
            raise ValueError(
                f"初始文件哈希表包含无效 SHA-256：{path}={content_hash!r}"
            )
        normalized_inventory[path] = content_hash
    return normalized_inventory


def _validate_backup_entries(project_root: str, manifest: dict) -> None:
    workflow_id = _validated_workflow_id(manifest.get("workflow_id", ""))
    manifest_dir = os.path.dirname(_manifest_full_path(project_root, workflow_id))
    _validated_manifest_entries(
        project_root,
        manifest,
        manifest_dir,
        allow_process_documents=False,
    )
    _validated_initial_inventory(project_root, manifest)


def validate_prepared(
    project_root: str,
    wf_state: state_mod.WorkflowState,
    *,
    require_current_plan: bool = True,
) -> tuple[bool, str, dict | None]:
    rollback = wf_state.rollback
    if not rollback.manifest_path or not rollback.manifest_hash:
        return False, "尚未执行 workflow gate impl --prepare-code 保存实施前文件内容", None
    try:
        manifest, raw = _read_manifest(project_root, rollback.manifest_path)
        if _sha256_bytes(raw) != rollback.manifest_hash:
            raise ValueError("实施前回退清单哈希与 state.json 不一致")
        if manifest.get("version") != MANIFEST_VERSION:
            raise ValueError("实施前回退清单版本不受支持")
        if manifest.get("workflow_id") != wf_state.workflow_id:
            raise ValueError("实施前回退清单不属于当前工作流")
        _validate_backup_entries(project_root, manifest)
        if require_current_plan:
            paths = planned_code_paths(project_root, wf_state.topics)
            plan_hash = compute_plan_hash(project_root, wf_state.topics)
            latest = manifest.get("prepares", [])[-1] if manifest.get("prepares") else {}
            if rollback.plan_hash != plan_hash or latest.get("plan_hash") != plan_hash:
                raise ValueError("实施前计划已经变化，必须重新执行 workflow gate impl --prepare-code")
            if rollback.planned_paths != paths or latest.get("planned_paths") != paths:
                raise ValueError("实施前回退清单与当前代码修改计划不一致")
    except (OSError, ValueError) as exc:
        return False, str(exc), None
    return True, "实施前回退清单和文件副本完整", manifest


def _backup_entry(project_root: str, manifest_dir: str, relative_path: str) -> dict:
    full_path = os.path.join(project_root, relative_path)
    if not os.path.exists(full_path):
        return {
            "original_exists": False,
            "backup_path": None,
            "content_hash": None,
            "mode": None,
        }
    backup_name = hashlib.sha256(relative_path.encode("utf-8")).hexdigest() + ".bin"
    backup_rel_path = os.path.join("files", backup_name)
    backup_full_path = os.path.join(manifest_dir, backup_rel_path)
    os.makedirs(os.path.dirname(backup_full_path), exist_ok=True)
    _copy_file(full_path, backup_full_path)
    return {
        "original_exists": True,
        "backup_path": backup_rel_path.replace(os.sep, "/"),
        "content_hash": _sha256_file(backup_full_path),
        "mode": os.stat(full_path).st_mode & 0o777,
    }


def _backup_entry_from_bytes(
    manifest_dir: str,
    relative_path: str,
    content: bytes,
    mode: int,
) -> dict:
    """把已经验证的原始字节写入副本，不再从可能变化的工作区重读。"""

    backup_name = hashlib.sha256(relative_path.encode("utf-8")).hexdigest() + ".bin"
    backup_rel_path = os.path.join("files", backup_name)
    backup_full_path = os.path.join(manifest_dir, backup_rel_path)
    _atomic_write_bytes(backup_full_path, content)
    return {
        "original_exists": True,
        "backup_path": backup_rel_path.replace(os.sep, "/"),
        "content_hash": _sha256_bytes(content),
        "mode": mode,
    }


def _trusted_git_head_baseline(
    project_root: str,
    relative_path: str,
    *,
    expected_content_hash: str | None = None,
) -> tuple[tuple[bytes, int] | None, str]:
    """返回可证明等于实施前事实的 HEAD 字节，以及可直接报告的证明结果。"""

    git_environment = dict(os.environ)
    for variable in (
        "GIT_DIR",
        "GIT_WORK_TREE",
        "GIT_INDEX_FILE",
        "GIT_OBJECT_DIRECTORY",
        "GIT_ALTERNATE_OBJECT_DIRECTORIES",
        "GIT_COMMON_DIR",
        "GIT_NAMESPACE",
    ):
        git_environment.pop(variable, None)
    git_environment["GIT_OPTIONAL_LOCKS"] = "0"

    def run_git(*arguments: str) -> subprocess.CompletedProcess[bytes] | None:
        try:
            return subprocess.run(
                ["git", *arguments],
                cwd=project_root,
                env=git_environment,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                check=False,
                timeout=10,
            )
        except (OSError, subprocess.TimeoutExpired):
            return None

    prefix_result = run_git("rev-parse", "--show-prefix")
    if prefix_result is None or prefix_result.returncode != 0:
        return None, "无法确认项目所在的 Git 工作树"
    prefix = os.fsdecode(prefix_result.stdout).rstrip("\r\n")
    tree_path = f"{prefix}{relative_path}"

    head_result = run_git("rev-parse", "--verify", "HEAD^{commit}")
    if head_result is None or head_result.returncode != 0:
        return None, "Git 仓库没有可读取的 HEAD 提交"
    head_revision = os.fsdecode(head_result.stdout).strip()
    if re.fullmatch(r"[0-9a-fA-F]{40,64}", head_revision) is None:
        return None, f"Git HEAD 提交编号格式无效：{head_revision!r}"

    pathspec = f":(top,literal){tree_path}"
    tree_entry = run_git(
        "ls-tree",
        "-z",
        "--full-tree",
        head_revision,
        "--",
        pathspec,
    )
    if tree_entry is None or tree_entry.returncode != 0:
        return None, f"无法读取 Git HEAD 中的路径记录：{relative_path}"
    records = tree_entry.stdout.rstrip(b"\0").split(b"\0")
    if len(records) != 1 or b"\t" not in records[0]:
        return None, f"Git HEAD 不包含唯一的普通文件路径：{relative_path}"
    metadata, recorded_path = records[0].split(b"\t", 1)
    metadata_parts = metadata.split()
    if (
        len(metadata_parts) != 3
        or metadata_parts[1] != b"blob"
        or os.fsdecode(recorded_path) != tree_path
    ):
        return None, f"Git HEAD 路径记录无法唯一对应当前项目文件：{relative_path}"
    git_mode = os.fsdecode(metadata_parts[0])
    if git_mode not in {"100644", "100755"}:
        kind = "符号链接" if git_mode == "120000" else "非普通文件"
        return None, (
            f"Git HEAD 文件模式={git_mode}（{kind}）；"
            "只接受 100644 或 100755 的普通文件，不能把链接目标文字当作文件原文"
        )
    mode = 0o644 if git_mode == "100644" else 0o755
    blob = run_git("cat-file", "blob", os.fsdecode(metadata_parts[2]))
    if blob is None or blob.returncode != 0:
        return None, f"无法读取 Git HEAD 文件对象：{relative_path}"
    head_content_hash = _sha256_bytes(blob.stdout)
    head_fact = f"Git HEAD SHA-256={head_content_hash}，文件模式={git_mode}"

    if expected_content_hash is not None:
        expected_fact = f"首次清单 SHA-256={expected_content_hash}"
        if head_content_hash != expected_content_hash:
            return None, f"{expected_fact}；{head_fact}；两个哈希不一致"
        return (blob.stdout, mode), f"{expected_fact}；{head_fact}；两个哈希完全一致"

    # 清洁工作区只能证明“当前内容等于 HEAD”；首次清单已经记录过哈希时，
    # 上面的哈希比较才负责证明“HEAD 内容等于实施前内容”。
    staged = run_git(
        "diff",
        "--cached",
        "--quiet",
        "--no-ext-diff",
        head_revision,
        "--",
        relative_path,
    )
    unstaged = run_git(
        "diff",
        "--quiet",
        "--no-ext-diff",
        "--",
        relative_path,
    )
    if (
        staged is None
        or unstaged is None
    ):
        return None, f"{head_fact}；无法检查索引或工作区是否有未提交差异"
    if staged.returncode == 1:
        return None, f"{head_fact}；Git 索引相对 HEAD 有未提交差异"
    if staged.returncode != 0:
        return None, f"{head_fact}；无法检查 Git 索引差异，退出码={staged.returncode}"
    if unstaged.returncode == 1:
        return None, f"{head_fact}；Git 工作区相对索引有未提交差异"
    if unstaged.returncode != 0:
        return None, f"{head_fact}；无法检查 Git 工作区差异，退出码={unstaged.returncode}"
    full_path = os.path.join(project_root, relative_path)
    try:
        with open(full_path, "rb") as stream:
            current = stream.read()
    except OSError as exc:
        return None, f"{head_fact}；当前工作区文件无法读取：{exc}"
    if current != blob.stdout:
        return None, (
            f"{head_fact}；当前工作区 SHA-256={_sha256_bytes(current)}；"
            "当前字节与 HEAD 不一致"
        )
    return (blob.stdout, mode), f"{head_fact}；索引和工作区均与 HEAD 完全一致"


def prepare_impl(
    project_root: str,
    wf_state: state_mod.WorkflowState,
) -> tuple[str, list[str]]:
    stage_state = wf_state.stages.get("impl")
    if stage_state is None or not stage_state.gate.discussion_complete:
        raise ValueError("必须先通过 workflow gate impl --discuss-done")
    if stage_state.code_baseline_hash is None:
        raise ValueError("缺少实施计划确认时的代码基线")

    paths = planned_code_paths(project_root, wf_state.topics)
    plan_hash = compute_plan_hash(project_root, wf_state.topics)
    # 每次准备必须匹配用户最后确认的实施计划；计划调整后先重新确认再准备
    if (
        stage_state.plan_confirmed_hash is not None
        and plan_hash != stage_state.plan_confirmed_hash
    ):
        raise ValueError(
            "当前实施计划与用户最后确认的版本不一致；"
            "先更新实施前计划并重新通过 workflow gate impl --discuss-done"
        )
    manifest_path = _manifest_rel_path(wf_state.workflow_id)
    manifest_full_path = os.path.join(project_root, manifest_path)
    manifest_dir = os.path.dirname(manifest_full_path)
    os.makedirs(manifest_dir, exist_ok=True)

    manifest: dict
    trusted_git_baselines: dict[str, tuple[bytes, int]] = {}
    if os.path.isfile(manifest_full_path):
        # 再次准备：允许已登记路径按计划变化；首次原内容始终保留，不被覆盖
        manifest, raw = _read_manifest(project_root, manifest_path)
        if (
            not wf_state.rollback.manifest_hash
            or _sha256_bytes(raw) != wf_state.rollback.manifest_hash
        ):
            raise ValueError("实施前回退清单哈希与 state.json 不一致，不能补充副本")
        if manifest.get("version") != MANIFEST_VERSION:
            raise ValueError("实施前回退清单版本不受支持")
        if manifest.get("workflow_id") != wf_state.workflow_id:
            raise ValueError("现有回退清单不属于当前工作流，不能覆盖")
        _validate_backup_entries(project_root, manifest)
        initial_inventory = _validated_initial_inventory(project_root, manifest)
        entries = manifest.setdefault("entries", {})
        raw_registered_paths = manifest.get("core_registered_paths")
        if isinstance(raw_registered_paths, list) and all(
            isinstance(path, str) for path in raw_registered_paths
        ):
            initially_sampled_paths = (
                set(raw_registered_paths) | set(initial_inventory) | set(entries)
            )
        else:
            initially_sampled_paths = set(initial_inventory) | set(entries)
        current_inventory = verification_mod.compute_project_file_hashes(
            project_root,
            registered_paths=paths,
        )
        for path in paths:
            if path in entries:
                continue
            baseline_detail = ""
            if path in initially_sampled_paths:
                current_hash = current_inventory.get(path)
                original_hash = initial_inventory.get(path)
                unchanged = current_hash == original_hash
                if not unchanged and isinstance(original_hash, str):
                    baseline, baseline_detail = _trusted_git_head_baseline(
                        project_root,
                        path,
                        expected_content_hash=original_hash,
                    )
                    if baseline is not None:
                        trusted_git_baselines[path] = baseline
                        unchanged = True
                elif not unchanged:
                    baseline_detail = (
                        "首次清单记录该路径当时不存在；"
                        f"当前工作区 SHA-256={current_hash or '不存在'}"
                    )
            else:
                # 首次清单没有看过该路径，不能凭当前工作区倒推原内容。只有 Git
                # 能同时证明它受 HEAD 跟踪、没有未提交差异且当前字节等于 HEAD，
                # 才能用 HEAD 字节补齐首次副本。
                baseline, baseline_detail = _trusted_git_head_baseline(project_root, path)
                unchanged = baseline is not None
                if baseline is not None:
                    trusted_git_baselines[path] = baseline
            if not unchanged:
                raise ValueError(
                    f"当前计划新增的路径没有可信的实施前原内容：{path}；"
                    f"核对结果：{baseline_detail}；"
                    "不能把当前修改后内容当作基线。恢复可信原内容，或返回计划重新讨论"
                )
    else:
        # 第一次准备：代码必须仍等于讨论确认时的基线，不能把修改后的内容当成原内容
        complete_baseline = wf_state.meta.get(IMPL_COMPLETE_BASELINE_SNAPSHOT_KEY)
        if isinstance(complete_baseline, dict):
            differences = (
                verification_mod.compare_complete_implementation_file_snapshot(
                    project_root,
                    complete_baseline,
                    scope="all",
                )
            )
            changed_before_prepare = {
                path
                for category, difference_paths in differences.items()
                if category != "not_checked"
                for path in difference_paths
            }
            if changed_before_prepare:
                raise ValueError(
                    "代码已经在回退基线保存前发生变化，不能把修改后的内容当成原内容；"
                    "相对进入 impl 时完整实施范围的逐文件差异："
                    f"{verification_mod.format_registered_differences(differences)}"
                )
        current_code_hash = verification_mod.compute_non_test_code_snapshot_hash(project_root)
        if current_code_hash != stage_state.code_baseline_hash:
            raise ValueError("代码已经在回退基线保存前发生变化，不能把修改后的内容当成原内容")
        core_paths = sorted(
            set(paths) | set(verification_mod.registered_code_design_paths(project_root))
        )
        manifest = {
            "version": MANIFEST_VERSION,
            "workflow_id": wf_state.workflow_id,
            "created_at": state_mod.now_iso(),
            "core_registered_paths": core_paths,
            "initial_inventory": verification_mod.compute_project_file_hashes(
                project_root,
                registered_paths=core_paths,
            ),
            "entries": {},
            "prepares": [],
        }
        if isinstance(complete_baseline, dict):
            manifest[IMPL_COMPLETE_INVENTORY_MANIFEST_KEY] = complete_baseline

    entries = manifest.setdefault("entries", {})
    for path in paths:
        if path not in entries:
            trusted = trusted_git_baselines.get(path)
            if trusted is None:
                entries[path] = _backup_entry(project_root, manifest_dir, path)
            else:
                content, mode = trusted
                entries[path] = _backup_entry_from_bytes(
                    manifest_dir,
                    path,
                    content,
                    mode,
                )
                manifest.setdefault("initial_inventory", {})[path] = _sha256_bytes(content)
    raw_registered_paths = manifest.get("core_registered_paths")
    if isinstance(raw_registered_paths, list) and all(
        isinstance(path, str) for path in raw_registered_paths
    ):
        manifest["core_registered_paths"] = sorted(set(raw_registered_paths) | set(paths))

    prepare_record = {
        "prepared_at": state_mod.now_iso(),
        "plan_hash": plan_hash,
        "code_baseline_hash": stage_state.code_baseline_hash,
        "planned_paths": paths,
        "inventory_before": manifest.get("initial_inventory", {}),
    }
    prepares = manifest.setdefault("prepares", [])
    if not prepares or any(
        prepares[-1].get(key) != prepare_record.get(key)
        for key in ("plan_hash", "code_baseline_hash", "planned_paths")
    ):
        prepares.append(prepare_record)
    else:
        prepares[-1] = prepare_record

    raw = _atomic_write_json(manifest_full_path, manifest)

    wf_state.rollback.manifest_path = manifest_path
    wf_state.rollback.manifest_hash = _sha256_bytes(raw)
    wf_state.rollback.prepared_at = prepare_record["prepared_at"]
    wf_state.rollback.plan_hash = plan_hash
    wf_state.rollback.code_baseline_hash = stage_state.code_baseline_hash
    wf_state.rollback.planned_paths = paths

    valid, detail, _ = validate_prepared(project_root, wf_state)
    if not valid:
        raise ValueError(detail)
    return detail, paths


def _write_manifest(project_root: str, wf_state: state_mod.WorkflowState, manifest: dict) -> None:
    if not wf_state.rollback.manifest_path:
        raise ValueError("当前工作流还没有实施前回退清单")
    normalized = _safe_project_relative_path(
        project_root,
        wf_state.rollback.manifest_path,
        purpose="实施回退清单路径",
    )
    manifest_full_path = os.path.join(project_root, normalized)
    raw = _atomic_write_json(manifest_full_path, manifest)
    wf_state.rollback.manifest_hash = _sha256_bytes(raw)


def prepare_test_code_baseline(
    project_root: str,
    wf_state: state_mod.WorkflowState,
) -> list[str]:
    """测试代码开始前保存已有测试文件和测试配置。"""
    valid, detail, manifest = validate_prepared(
        project_root,
        wf_state,
        require_current_plan=False,
    )
    if not valid or manifest is None:
        raise ValueError(detail)
    test_files = verification_mod.compute_test_related_file_hashes(project_root)
    manifest_dir = os.path.dirname(os.path.join(project_root, wf_state.rollback.manifest_path or ""))
    entries = manifest.setdefault("entries", {})
    for path in sorted(test_files):
        if path not in entries:
            entries[path] = _backup_entry(project_root, manifest_dir, path)
    manifest["test_code_prepared_at"] = state_mod.now_iso()
    manifest["test_code_inventory_before"] = test_files
    _write_manifest(project_root, wf_state, manifest)
    return sorted(test_files)


def finalize_test_code_changes(
    project_root: str,
    wf_state: state_mod.WorkflowState,
) -> list[str]:
    """登记 test_code 阶段新建的测试文件，供中止时删除。"""
    valid, detail, manifest = validate_prepared(
        project_root,
        wf_state,
        require_current_plan=False,
    )
    if not valid or manifest is None:
        raise ValueError(detail)
    before = manifest.get("test_code_inventory_before")
    if not isinstance(before, dict):
        raise ValueError("缺少 test_code 开始前的测试文件基线")
    current = verification_mod.compute_test_related_file_hashes(project_root)
    changed = sorted(
        path
        for path in set(before) | set(current)
        if before.get(path) != current.get(path)
    )
    entries = manifest.setdefault("entries", {})
    for path in changed:
        if path not in before and path not in entries:
            entries[path] = {
                "original_exists": False,
                "backup_path": None,
                "content_hash": None,
                "mode": None,
            }
        elif path in before and path not in entries:
            raise ValueError(f"测试文件修改前没有保存真实内容：{path}")
    manifest["test_code_changed_paths"] = changed
    _write_manifest(project_root, wf_state, manifest)
    return changed


def accept_test_code_inventory(
    project_root: str,
    wf_state: state_mod.WorkflowState,
) -> list[str]:
    """在测试代码经用户确认时保存当时状态，供后续返回实施时区分旧修改。"""
    valid, detail, manifest = validate_prepared(
        project_root,
        wf_state,
        require_current_plan=False,
    )
    if not valid or manifest is None:
        raise ValueError(detail)
    before = manifest.get("test_code_inventory_before")
    if not isinstance(before, dict):
        raise ValueError("缺少 test_code 开始前的测试文件基线")
    current = verification_mod.compute_test_related_file_hashes(project_root)
    previous = manifest.get("test_code_inventory_after")
    previous_paths = set(previous) if isinstance(previous, dict) else set()
    all_paths = set(before) | set(current) | previous_paths
    manifest["test_code_inventory_after"] = {
        path: current.get(path)
        for path in sorted(all_paths)
    }
    manifest["test_code_accepted_at"] = state_mod.now_iso()
    _write_manifest(project_root, wf_state, manifest)
    return sorted(all_paths)


def _accepted_test_code_inventory(manifest: dict) -> dict[str, str | None]:
    """读取测试文件确认状态；未确认时返回只可用于比对未变文件的入场清单。"""
    raw = manifest.get("test_code_inventory_after")
    if not isinstance(raw, dict):
        raw = manifest.get("test_code_inventory_before")
    if not isinstance(raw, dict):
        return {}
    return {
        path: content_hash
        for path, content_hash in raw.items()
        if isinstance(path, str)
        and (content_hash is None or isinstance(content_hash, str))
    }


def changed_paths_since_prepare(project_root: str, manifest: dict) -> list[str]:
    """实际变化始终和第一次项目清单比较，早期修改不会因再次准备消失。"""
    prepares = manifest.get("prepares", [])
    if not prepares:
        raise ValueError("实施前回退清单没有准备记录")
    complete_before = manifest.get(IMPL_COMPLETE_INVENTORY_MANIFEST_KEY)
    if isinstance(complete_before, dict):
        differences = verification_mod.compare_complete_implementation_file_snapshot(
            project_root,
            complete_before,
            scope="all",
        )
        changed = {
            path
            for category, difference_paths in differences.items()
            if category != "not_checked"
            for path in difference_paths
        }
    else:
        raw_before = manifest.get("initial_inventory") or prepares[0].get(
            "inventory_before",
            {},
        )
        before = {
            path: content_hash
            for path, content_hash in raw_before.items()
            if verification_mod.is_implementation_related_path(path)
        }
        raw_registered_paths = manifest.get("core_registered_paths")
        if isinstance(raw_registered_paths, list) and all(
            isinstance(path, str) for path in raw_registered_paths
        ):
            registered_paths = sorted(set(raw_registered_paths))
        else:
            # 旧清单只比较它在准备时真正采样或保存过的文件。后来扩大的登记规则
            # 没有旧值可比，不能把未采样且未修改的文件倒推成“新增”。
            registered_paths = sorted(
                set(raw_before) | set(manifest.get("entries", {}))
            )
        current = verification_mod.compute_project_file_hashes(
            project_root,
            registered_paths=registered_paths,
        )
        changed = {
            path
            for path in set(before) | set(current)
            if before.get(path) != current.get(path)
        }

    # 项目清单只扫描代码、脚本和配置；计划明确列出的其它资源文件仍逐项
    # 与第一次副本比较，避免文档型产品或二进制资源的计划内修改被漏掉。
    for path, entry in manifest.get("entries", {}).items():
        full_path = os.path.join(project_root, path)
        if entry.get("original_exists"):
            current_hash = (
                _sha256_file(full_path)
                if os.path.isfile(full_path) and not os.path.islink(full_path)
                else None
            )
            if current_hash != entry.get("content_hash"):
                changed.add(path)
        elif os.path.lexists(full_path):
            changed.add(path)
    return sorted(changed)


def _implementation_change_sets(
    project_root: str,
    manifest: dict,
) -> tuple[list[str], list[str]]:
    """区分本轮实施变化和测试阶段登记但未再变化的非实施文件。"""
    changed = changed_paths_since_prepare(project_root, manifest)
    current = (
        verification_mod.compute_complete_implementation_file_hashes(project_root)
        if isinstance(manifest.get(IMPL_COMPLETE_INVENTORY_MANIFEST_KEY), dict)
        else verification_mod.compute_project_file_hashes(project_root)
    )
    accepted_tests = _accepted_test_code_inventory(manifest)
    prepares = manifest.get("prepares")
    latest_prepare = prepares[-1] if isinstance(prepares, list) and prepares else {}
    planned_paths = latest_prepare.get("planned_paths", [])
    implementation_plan = {
        path for path in planned_paths if isinstance(path, str)
    }
    unchanged_accepted_tests = {
        path
        for path in changed
        if path not in implementation_plan
        and path in accepted_tests
        and current.get(path) == accepted_tests[path]
    }
    implementation_changes = sorted(set(changed) - unchanged_accepted_tests)
    return implementation_changes, sorted(unchanged_accepted_tests)


def implementation_changed_paths_since_prepare(
    project_root: str,
    manifest: dict,
) -> list[str]:
    """返回需要由实施计划和记录解释的真实文件变化。"""
    implementation_changes, _ = _implementation_change_sets(project_root, manifest)
    return implementation_changes


def _implementation_change_validation(
    project_root: str,
    wf_state: state_mod.WorkflowState,
) -> _ImplementationChangeValidation:
    """在同一处核对计划、实际差异和实施记录，不把事实压成文字清单。"""
    report = diagnostics_mod.ValidationReport(
        stage="impl",
        gate="实施代码变化和三方核对",
    )
    planned_changes, plan_diagnostics = _planned_code_changes(
        project_root,
        wf_state.topics,
    )
    recorded_changes, record_diagnostics = _recorded_code_changes_with_diagnostics(
        project_root,
        wf_state.topics,
    )
    report.extend(plan_diagnostics)
    report.extend(record_diagnostics)
    plan_file_set_blocked = any(
        item.check_id
        in {
            "impl.implementation_plan.document_missing",
            "impl.implementation_plan.table_invalid",
            "impl.implementation_plan.path_invalid",
        }
        for item in plan_diagnostics
    )
    record_file_set_blocked = any(
        item.check_id
        in {
            "impl.implementation_record.document_missing",
            "impl.implementation_record.table_invalid",
            "impl.implementation_record.path_invalid",
        }
        for item in record_diagnostics
    )

    baseline_ok, baseline_detail, manifest = validate_prepared(
        project_root,
        wf_state,
        require_current_plan=False,
    )
    baseline_check_id = "impl.implementation_baseline.invalid"
    if not baseline_ok or manifest is None:
        report.add_error(
            check_id=baseline_check_id,
            location=wf_state.rollback.manifest_path or "state.json 的 rollback（实施回退状态）",
            expected="实施前回退清单、文件副本和 state.json 中的清单哈希一致",
            actual=f"实施前回退依据不可用：{baseline_detail}",
            evidence=baseline_detail,
            impact="无法安全计算基线后的真实文件差异，三方文件集合不能核对",
            next_action="先按回退依据错误修正或重新准备实施前基线，再核对实施变化",
        )

    current_plan_ok = False
    current_plan_check_id = "impl.implementation_plan.prepare_mismatch"
    if baseline_ok and manifest is not None and not plan_file_set_blocked:
        current_plan_ok, current_plan_detail, _ = validate_prepared(project_root, wf_state)
        if not current_plan_ok:
            report.add_error(
                check_id=current_plan_check_id,
                location=wf_state.rollback.manifest_path or "state.json 的 rollback（实施回退状态）",
                expected="当前代码修改计划与实施前回退清单中已确认的计划完全一致",
                actual=f"当前实施计划不能与保存的实施前基线对应：{current_plan_detail}",
                evidence=current_plan_detail,
                impact="不能用当前计划解释基线后的真实改动",
                next_action="先重新确认实施前计划并按门禁要求准备可信的实施前基线",
            )

    implementation_changes: list[str] | None = None
    unchanged_accepted_tests: list[str] = []
    diff_check_id = "impl.implementation_diff.unavailable"
    if baseline_ok and manifest is not None:
        try:
            implementation_changes, unchanged_accepted_tests = _implementation_change_sets(
                project_root,
                manifest,
            )
        except ValueError as exc:
            report.add_error(
                check_id=diff_check_id,
                location=wf_state.rollback.manifest_path or "实施前回退清单",
                expected="能从保存的实施前清单计算每个登记文件的当前差异",
                actual=f"无法计算基线后的真实文件差异：{exc}",
                evidence=str(exc),
                impact="不能确认哪些文件在实施前基线后真正改变",
                next_action="修正回退清单或受管文件状态，使真实差异可以重新计算",
            )
        report.extend(
            _recorded_line_range_diagnostics(
                project_root,
                manifest,
                recorded_changes,
            )
        )

    dependency_ids = tuple(
        item.check_id for item in report.diagnostics if item.kind == "error"
    )
    ready_for_relation = (
        baseline_ok
        and manifest is not None
        and current_plan_ok
        and implementation_changes is not None
        and not plan_file_set_blocked
        and not record_file_set_blocked
    )
    if not ready_for_relation:
        reasons: list[str] = []
        if not baseline_ok or manifest is None:
            reasons.append("实施前回退依据不可用")
        if plan_file_set_blocked:
            reasons.append("代码修改计划存在无法解析的条目")
        elif not current_plan_ok:
            reasons.append("当前代码修改计划与实施前清单不一致")
        if implementation_changes is None:
            reasons.append("真实文件差异无法计算")
        if record_file_set_blocked:
            reasons.append("实施后记录存在无法解析或不完整的条目")
        report.add_not_checked(
            check_id="impl.implementation_relation.not_checked",
            location="实施计划、基线后真实差异和实施后记录（三方文件集合）",
            expected="三个文件集合均可读取且前置基线可信后逐文件比较",
            actual=f"未检查：{'；'.join(reasons)}",
            evidence=(
                "计划可读取文件="
                f"{sorted({change.path for change in planned_changes})}；"
                "实际差异文件="
                f"{implementation_changes if implementation_changes is not None else '未取得'}；"
                "实施记录可读取文件="
                f"{sorted({change.path for change in recorded_changes})}"
            ),
            impact="不能可靠判断计划、实际差异和实施记录是否一一对应",
            next_action="先处理本报告列出的前置错误；前置事实完整后门禁会自动逐文件比较三方集合",
            depends_on=dependency_ids or ("impl.implementation_relation.prerequisite",),
        )
        return _ImplementationChangeValidation(
            report=report,
            detail="实施代码变化和计划范围尚未完成三方核对",
        )

    actual = set(implementation_changes)
    planned_by_path = {change.path: change for change in planned_changes}
    recorded_by_path = {change.path: change for change in recorded_changes}
    planned = set(planned_by_path)
    recorded = set(recorded_by_path)

    for path in sorted(planned - actual):
        change = planned_by_path[path]
        report.add_error(
            check_id="impl.implementation_relation.planned_but_unchanged",
            location=f"{change.document_path}:{change.line}，“文件”列",
            expected="计划列出的文件在实施前基线后有真实修改，或从计划中删除该文件",
            actual=f"计划列出但实际未修改：计划包含 {path!r}，但基线后没有检测到该文件变化",
            evidence=(
                f"计划列出但实际未修改：{path!r}；计划位置={change.document_path}:{change.line}；"
                f"基线后真实差异文件={sorted(actual)}"
            ),
            impact="实施计划声称会修改该文件，但当前工作区没有可验证的对应实现",
            next_action="确实需要该改动时修改该文件；不再需要时从代码修改计划中删除这一行并重新确认计划",
        )
    for path in sorted(actual - planned):
        report.add_error(
            check_id="impl.implementation_relation.actual_outside_plan",
            location=f"{path}（实施前基线后的真实文件差异）",
            expected="每个基线后真实修改文件都已在确认后的代码修改计划中列出",
            actual=f"实际修改但不在实施计划：检测到 {path!r} 已修改，但当前代码修改计划没有该文件",
            evidence=(
                f"实际修改但不在实施计划：{path!r}；基线后真实差异文件={sorted(actual)}；"
                f"确认后的计划文件={sorted(planned)}"
            ),
            impact="该修改没有可信的实施前计划和回退依据，不能作为本轮实施结果确认",
            next_action="恢复该文件到实施前内容，或回到实施前计划确认流程后按工作流重新准备可信基线再实施",
        )
    for path in sorted(actual - recorded):
        report.add_error(
            check_id="impl.implementation_relation.actual_unrecorded",
            location=f"{path}（实施前基线后的真实文件差异）",
            expected="每个基线后真实修改文件在实施后记录中都有一条对应行",
            actual=f"实际修改但实施后记录未列出：检测到 {path!r} 已修改，但实施后记录没有列出该文件",
            evidence=(
                f"实际修改但实施后记录未列出：{path!r}；基线后真实差异文件={sorted(actual)}；"
                f"实施后记录文件={sorted(recorded)}"
            ),
            impact="后续测试和验收无法知道该文件改了什么、对应哪个验收条件",
            next_action="在实施后记录的“3.4.1 实际代码修改”表中增加该文件的真实位置、逻辑、可观察变化和 AC 编号",
        )
    for path in sorted(recorded - actual):
        change = recorded_by_path[path]
        report.add_error(
            check_id="impl.implementation_relation.recorded_without_change",
            location=f"{change.document_path}:{change.line}，“文件”列",
            expected="实施后记录列出的文件在实施前基线后有对应真实变化",
            actual=f"实施后记录列出但没有真实差异：实施记录列出 {path!r}，但基线后没有检测到该文件变化",
            evidence=(
                f"实施后记录列出但没有真实差异：{path!r}；记录位置={change.document_path}:{change.line}；"
                f"基线后真实差异文件={sorted(actual)}"
            ),
            impact="实施记录包含无法由当前工作区证实的改动，不能作为验收依据",
            next_action="确实修改了该文件时检查是否恢复了改动；未修改时从实施后记录删除或更正这一行",
        )

    record_facts = [
        f"{change.document_path}:{change.line} {change.path} @ {change.location}"
        for change in recorded_changes
    ]
    detail = (
        "实施前计划、基线后真实差异和实施后记录三方文件集合完全一致："
        f"{sorted(actual)}；已核对记录位置：{record_facts}"
    )
    if unchanged_accepted_tests:
        detail += (
            "；测试代码阶段登记且未再变化的非实施计划文件已保留："
            f"{unchanged_accepted_tests}"
        )
    return _ImplementationChangeValidation(report=report, detail=detail)


def validate_implementation_changes_report(
    project_root: str,
    wf_state: state_mod.WorkflowState,
) -> diagnostics_mod.ValidationReport:
    """返回三方核对的原始结构化事实，供门禁命令直接渲染。"""
    return _implementation_change_validation(project_root, wf_state).report


def validate_implementation_changes(
    project_root: str,
    wf_state: state_mod.WorkflowState,
) -> tuple[bool, str]:
    """兼容旧调用方的文字接口；新门禁应使用结构化报告。"""
    validation = _implementation_change_validation(project_root, wf_state)
    if validation.report.passed:
        return True, validation.detail
    detail = "\n".join(
        f"{index}. {diagnostic.evidence}"
        for index, diagnostic in enumerate(validation.report.sorted_diagnostics, 1)
    )
    return False, detail


def validate_existing_implementation_paths(
    project_root: str,
    wf_state: state_mod.WorkflowState,
) -> tuple[bool, str]:
    """校验用户确认的既有实现；这里只能核对计划、记录和当前文件。"""
    errors: list[str] = []
    try:
        planned = set(planned_code_paths(project_root, wf_state.topics))
    except (OSError, ValueError) as exc:
        planned = set()
        errors.append(f"无法读取实施前计划：{exc}")
    changes, record_errors = _recorded_code_changes(project_root, wf_state.topics)
    recorded = {change.path for change in changes}
    errors.extend(record_errors)

    missing_from_record = sorted(planned - recorded)
    outside_plan = sorted(recorded - planned)
    if missing_from_record:
        errors.append(f"实施计划文件未写入实施后记录：{missing_from_record}")
    if outside_plan:
        errors.append(f"实施后记录包含计划外文件：{outside_plan}")
    for relative_path in sorted(planned | recorded):
        full_path = os.path.join(project_root, relative_path)
        if os.path.islink(full_path) or not os.path.isfile(full_path):
            errors.append(f"既有实现路径不是当前项目内普通文件：{relative_path}")
    if errors:
        return False, "\n".join(
            f"{index}. {error}" for index, error in enumerate(dict.fromkeys(errors), 1)
        )
    return (
        True,
        "既有实现例外已核对实施计划与实施后记录，并确认当前文件真实存在；"
        "该例外没有声称验证基线后的真实差异",
    )


def restore(project_root: str, wf_state: state_mod.WorkflowState) -> list[str]:
    valid, detail, manifest = validate_prepared(
        project_root,
        wf_state,
        require_current_plan=False,
    )
    if not valid or manifest is None:
        raise ValueError(detail)

    allowed = set(manifest.get("entries", {}))
    unexpected = sorted(
        path
        for path in changed_paths_since_prepare(project_root, manifest)
        if path not in allowed
    )
    if unexpected:
        raise ValueError(
            "存在没有实施前副本的文件变化，不能安全中止：" + str(unexpected)
        )

    manifest_dir = os.path.dirname(os.path.join(project_root, wf_state.rollback.manifest_path or ""))
    restored: list[str] = []
    try:
        for relative_path, entry in manifest.get("entries", {}).items():
            _normalized_relative_path(
                project_root,
                relative_path,
                purpose="回退清单文件记录",
            )
            full_path = os.path.join(project_root, relative_path)
            if entry.get("original_exists"):
                backup_path = _safe_backup_path(
                    manifest_dir,
                    entry["backup_path"],
                    relative_path,
                )
                destination_dir = os.path.dirname(full_path) or project_root
                os.makedirs(destination_dir, exist_ok=True)
                temp_handle = tempfile.NamedTemporaryFile(
                    prefix=".workflow-rollback-",
                    dir=destination_dir,
                    delete=False,
                )
                temp_path = temp_handle.name
                temp_handle.close()
                try:
                    _copy_file(backup_path, temp_path)
                    os.replace(temp_path, full_path)
                finally:
                    if os.path.exists(temp_path):
                        os.remove(temp_path)
                mode = entry.get("mode")
                if isinstance(mode, int):
                    os.chmod(full_path, mode)
            elif os.path.lexists(full_path):
                if not os.path.isfile(full_path) or os.path.islink(full_path):
                    raise ValueError(f"计划新增路径现在不是普通文件，不能安全删除：{relative_path}")
                os.remove(full_path)
            restored.append(relative_path)
    except OSError as exc:
        raise ValueError(f"恢复文件时发生系统错误：{exc}") from exc

    _validate_restored(project_root, manifest)
    return restored


def _validate_restored(project_root: str, manifest: dict) -> None:
    for relative_path, entry in manifest.get("entries", {}).items():
        full_path = os.path.join(project_root, relative_path)
        if entry.get("original_exists"):
            if not os.path.isfile(full_path):
                raise ValueError(f"回退后文件缺失：{relative_path}")
            content_hash = _sha256_file(full_path)
            if content_hash != entry.get("content_hash"):
                raise ValueError(f"回退后文件内容不正确：{relative_path}")
        elif os.path.lexists(full_path):
            raise ValueError(f"回退后计划新增文件仍然存在：{relative_path}")


def cleanup(project_root: str, workflow_id: str) -> list[str]:
    workflow_id = _validated_workflow_id(workflow_id)
    relative_path = f"{ROLLBACK_ROOT}/{workflow_id}"
    normalized = _safe_project_relative_path(
        project_root,
        relative_path,
        purpose="待清理回退目录",
        allow_directory=True,
    )
    full_path = os.path.join(project_root, normalized)
    rollback_root = os.path.realpath(os.path.join(project_root, ROLLBACK_ROOT))
    full_real = os.path.realpath(full_path)
    if os.path.commonpath([rollback_root, full_real]) != rollback_root or full_real == rollback_root:
        raise ValueError("待清理路径超出当前工作流的回退目录")
    if not os.path.exists(full_path):
        return []
    if os.path.islink(full_path) or not os.path.isdir(full_path):
        raise ValueError("待清理回退路径不是普通目录")
    shutil.rmtree(full_path)
    parent = os.path.dirname(full_path)
    if os.path.isdir(parent) and not os.listdir(parent):
        os.rmdir(parent)
    return [normalized]


# ─────────────────────────────────────────────
# 开工基线与清场开工事务
# 新轮次写入前保存受管正式文档、旧 state.json 和将修改的项目字段；
# 从零清场只在副本完整后执行；失败时恢复旧内容。
# ─────────────────────────────────────────────


def managed_document_paths(project_root: str) -> list[str]:
    """兼容旧调用：列出正式文档目录中当前存在的普通文件。"""
    paths: list[str] = []
    for dir_name in MANAGED_DOC_DIRS:
        dir_path = os.path.join(project_root, dir_name)
        if not os.path.isdir(dir_path):
            continue
        if os.path.islink(dir_path):
            raise ValueError(f"受管文档目录不能是符号链接：{dir_name}")
        for root, dirs, files in os.walk(dir_path):
            for directory in dirs:
                if os.path.islink(os.path.join(root, directory)):
                    raise ValueError(
                        "受管文档目录不能经过符号链接："
                        + os.path.relpath(os.path.join(root, directory), project_root)
                    )
            for file_name in files:
                full_path = os.path.join(root, file_name)
                relative_path = os.path.relpath(full_path, project_root).replace(os.sep, "/")
                paths.append(
                    _safe_project_relative_path(
                        project_root,
                        relative_path,
                        purpose="受管文档路径",
                    )
                )
    for file_name in MANAGED_DOC_FILES:
        if os.path.isfile(os.path.join(project_root, file_name)):
            paths.append(file_name)
    return sorted(paths)


def _start_manifest_rel_path(workflow_id: str) -> str:
    return f"{ROLLBACK_ROOT}/{_validated_workflow_id(workflow_id)}/start/manifest.json"


def _abort_manifest_rel_path(workflow_id: str) -> str:
    return f"{ROLLBACK_ROOT}/{_validated_workflow_id(workflow_id)}/abort/manifest.json"


def _state_from_raw(raw: str | None):
    if not raw:
        return None
    try:
        data = json.loads(raw)
        if not isinstance(data, dict) or "workflow_id" not in data or "intent" not in data:
            return None
        return state_mod.state_from_dict(data)
    except (KeyError, TypeError, ValueError, json.JSONDecodeError):
        return None


def _expanded_clean_file_paths(
    project_root: str,
    clean_paths: list[str] | None,
) -> list[str]:
    """展开用户明确确认的清场范围，确保其中每个旧文件都有副本。"""
    result: set[str] = set()
    for raw_path in clean_paths or []:
        normalized = _safe_project_relative_path(
            project_root,
            raw_path,
            purpose="清场路径",
            allow_directory=True,
        )
        first_part = PurePosixPath(normalized).parts[0]
        if first_part not in MANAGED_DOC_DIRS and normalized not in MANAGED_DOC_FILES:
            raise ValueError(f"清场路径不属于受管正式文档范围：{normalized}")
        full_path = os.path.join(project_root, normalized)
        if not os.path.lexists(full_path):
            continue
        if os.path.isfile(full_path):
            result.add(
                _safe_project_relative_path(
                    project_root,
                    normalized,
                    purpose="清场文件路径",
                )
            )
            continue
        if not os.path.isdir(full_path):
            raise ValueError(f"清场路径既不是普通文件也不是目录：{normalized}")
        for root, dirs, files in os.walk(full_path):
            for directory in dirs:
                directory_path = os.path.join(root, directory)
                if os.path.islink(directory_path):
                    relative = os.path.relpath(directory_path, project_root).replace(os.sep, "/")
                    raise ValueError(f"清场目录不能经过符号链接：{relative}")
            for file_name in files:
                relative = os.path.relpath(
                    os.path.join(root, file_name),
                    project_root,
                ).replace(os.sep, "/")
                result.add(
                    _safe_project_relative_path(
                        project_root,
                        relative,
                        purpose="清场文件路径",
                    )
                )
    return sorted(result)


def _official_managed_paths(project_root: str, wf_state=None) -> list[str]:
    project = project_mod.load_project(project_root)
    collector = getattr(artifact_paths_mod, "managed_artifact_paths", None)
    if collector is None:
        raise ValueError("正式产物路径模块缺少 managed_artifact_paths() 受管范围接口")
    raw_paths = collector(project, wf_state, project_root=project_root)
    if not isinstance(raw_paths, (list, tuple, set)):
        raise ValueError("正式产物受管范围必须是路径列表")
    paths: set[str] = set()
    for raw_path in raw_paths:
        paths.add(
            _safe_project_relative_path(
                project_root,
                raw_path,
                purpose="正式产物路径",
            )
        )
    return sorted(paths)


def _validated_entry_script_path(project_root: str, raw_path: str) -> str:
    """校验项目测试入口引用的脚本路径，并排除工作流内部产物。"""
    normalized = _safe_project_relative_path(
        project_root,
        raw_path,
        purpose="入口脚本路径",
    )
    first_part = PurePosixPath(normalized).parts[0]
    if first_part in PROCESS_ROOTS or normalized in MANAGED_DOC_FILES:
        raise ValueError(f"入口脚本不能放在工作流过程或内部目录：{normalized}")
    return normalized


def _configured_start_entry_scripts(
    project_root: str,
    project_fields: dict,
) -> list[str]:
    """从开工时的平台参数数组中取得需要保存原内容的项目脚本。"""
    raw_config = project_fields["test_entry"]
    if isinstance(raw_config, str):
        # 旧字符串没有可靠的参数边界；受控迁移负责转换，这里不能猜路径。
        return []

    config = test_entry_mod.normalized_entry_config(raw_config)
    scripts_by_key: dict[str, str] = {}
    for raw_path in test_entry_mod.referenced_project_scripts(config):
        normalized = _validated_entry_script_path(project_root, raw_path)
        comparison_key = normalized.casefold()
        existing = scripts_by_key.get(comparison_key)
        if existing is not None and existing != normalized:
            raise ValueError(
                "入口脚本包含在大小写不敏感文件系统上冲突的路径："
                f"{existing!r} 和 {normalized!r}"
            )
        scripts_by_key[comparison_key] = normalized
    return sorted(scripts_by_key.values())


def prepare_start_baseline(
    project_root: str,
    workflow_id: str,
    project_fields: dict,
    previous_state_raw: str | None,
    clean_paths: list[str] | None = None,
) -> dict:
    """新轮次第一次持久写入前，保存受管文档、入口脚本和项目字段。

    副本保存在 `.workflow_loop/rollback/<workflow_id>/start/`，
    并入本轮整轮作废的回退依据；开工失败时按它恢复。
    """
    workflow_id = _validated_workflow_id(workflow_id)
    if not isinstance(project_fields, dict):
        raise ValueError("开工基线中的项目受管字段必须是对象")
    project_mod._validate_managed_fields(project_fields)
    entry_scripts = _configured_start_entry_scripts(project_root, project_fields)
    manifest_rel = _start_manifest_rel_path(workflow_id)
    manifest_full = os.path.join(project_root, manifest_rel)
    manifest_dir = os.path.dirname(manifest_full)
    if os.path.lexists(manifest_full):
        raise ValueError("当前工作流编号已经存在开工基线，不能覆盖第一次原内容")
    os.makedirs(manifest_dir, exist_ok=True)

    previous_state = _state_from_raw(previous_state_raw)
    official_paths = _official_managed_paths(project_root, previous_state)
    clean_file_paths = _expanded_clean_file_paths(project_root, clean_paths)
    baseline_paths = sorted(
        set(official_paths) | set(clean_file_paths) | set(entry_scripts)
    )
    entries: dict[str, dict] = {}
    for relative_path in baseline_paths:
        entries[relative_path] = _backup_entry(project_root, manifest_dir, relative_path)

    manifest = {
        "version": MANIFEST_VERSION,
        "workflow_id": workflow_id,
        "baseline_complete": True,
        "created_at": state_mod.now_iso(),
        "project_fields": project_fields,
        "previous_state_raw": previous_state_raw,
        "managed_paths": official_paths,
        "clean_paths": sorted(set(clean_paths or [])),
        "entry_scripts": entry_scripts,
        "entries": entries,
    }
    _atomic_write_json(manifest_full, manifest)
    return manifest


def read_start_baseline(project_root: str, workflow_id: str) -> dict | None:
    try:
        manifest_rel = _start_manifest_rel_path(workflow_id)
    except ValueError:
        return None
    manifest_full = os.path.join(project_root, manifest_rel)
    if not os.path.isfile(manifest_full):
        return None
    manifest, _raw = _read_manifest(project_root, manifest_rel)
    return manifest


def _write_start_baseline(project_root: str, workflow_id: str, manifest: dict) -> None:
    manifest_full = os.path.join(project_root, _start_manifest_rel_path(workflow_id))
    _atomic_write_json(manifest_full, manifest)


def register_start_entry_script(
    project_root: str,
    workflow_id: str,
    relative_path: str,
    project_fields: dict | None = None,
) -> str:
    """在修改测试入口脚本前，把它的第一次原内容加入完整开工基线。"""
    _ = project_fields  # 保留旧调用签名；禁止用当前字段补造开工基线。
    workflow_id = _validated_workflow_id(workflow_id)
    normalized = _validated_entry_script_path(project_root, relative_path)
    manifest_relative = _start_manifest_rel_path(workflow_id)
    if not os.path.isfile(os.path.join(project_root, manifest_relative)):
        raise ValueError("缺少完整开工基线，不能用当前内容补造入口脚本的开工前状态")
    manifest, _raw, validated_entries, manifest_dir = _load_source_manifest(
        project_root,
        manifest_relative,
        workflow_id,
        allow_process_documents=True,
        require_complete_start=True,
    )
    project_mod._validate_managed_fields(manifest.get("project_fields"))
    entries = manifest.setdefault("entries", {})
    if normalized in entries:
        return "该路径已有第一次原内容记录，未覆盖"
    if normalized in validated_entries:
        raise ValueError(f"入口脚本路径与开工基线中的另一种路径写法冲突：{normalized}")
    entries[normalized] = _backup_entry(project_root, manifest_dir, normalized)
    if entries[normalized]["original_exists"]:
        detail = "已保存现有脚本的真实原内容"
    else:
        detail = "已登记为“原本不存在”，整轮作废时删除"
    scripts = manifest.setdefault("entry_scripts", [])
    if normalized not in scripts:
        scripts.append(normalized)
        scripts.sort()
    _write_start_baseline(project_root, workflow_id, manifest)
    return detail


def _restore_file_entry(
    project_root: str,
    relative_path: str,
    entry: dict,
    source_manifest_dir: str | None,
) -> None:
    normalized = _safe_project_relative_path(
        project_root,
        relative_path,
        purpose="待恢复文件路径",
    )
    full_path = os.path.join(project_root, normalized)
    if entry.get("original_exists") is True:
        if source_manifest_dir is None:
            raise ValueError(f"待恢复旧文件缺少副本来源：{normalized}")
        backup_path = _safe_backup_path(
            source_manifest_dir,
            entry.get("backup_path"),
            normalized,
        )
        if not os.path.isfile(backup_path):
            raise ValueError(f"待恢复旧文件的副本缺失：{normalized}")
        expected_hash = entry.get("content_hash")
        if _sha256_file(backup_path) != expected_hash:
            raise ValueError(f"待恢复旧文件的副本内容已损坏：{normalized}")
        _atomic_restore_file(backup_path, full_path, entry.get("mode"))
        if not os.path.isfile(full_path) or _sha256_file(full_path) != expected_hash:
            raise ValueError(f"文件恢复后内容校验失败：{normalized}")
        return

    if entry.get("original_exists") is not False:
        raise ValueError(f"待恢复文件缺少明确的原文件存在状态：{normalized}")
    if os.path.lexists(full_path):
        if os.path.islink(full_path) or not os.path.isfile(full_path):
            raise ValueError(f"本轮新建路径现在不是普通文件，不能安全删除：{normalized}")
        os.remove(full_path)
    if os.path.lexists(full_path):
        raise ValueError(f"本轮新建文件删除后仍然存在：{normalized}")


def _load_source_manifest(
    project_root: str,
    relative_path: str,
    workflow_id: str,
    *,
    allow_process_documents: bool,
    require_complete_start: bool,
    expected_hash: str | None = None,
) -> tuple[dict, bytes, dict[str, dict], str]:
    manifest, raw = _read_manifest(project_root, relative_path)
    if manifest.get("version") != MANIFEST_VERSION:
        raise ValueError(f"回退清单版本不受支持：{relative_path}")
    if manifest.get("workflow_id") != workflow_id:
        raise ValueError(f"回退清单不属于当前工作流：{relative_path}")
    if require_complete_start and manifest.get("baseline_complete") is not True:
        raise ValueError(f"开工基线不是完整开工快照：{relative_path}")
    if expected_hash is not None and _sha256_bytes(raw) != expected_hash:
        raise ValueError(f"回退清单内容与工作流状态中的哈希不一致：{relative_path}")
    manifest_dir = os.path.dirname(os.path.join(project_root, relative_path))
    entries = _validated_manifest_entries(
        project_root,
        manifest,
        manifest_dir,
        allow_process_documents=allow_process_documents,
    )
    return manifest, raw, entries, manifest_dir


def _abort_manifest_full_path(project_root: str, workflow_id: str) -> str:
    return os.path.join(project_root, _abort_manifest_rel_path(workflow_id))


def _write_abort_manifest(
    project_root: str,
    workflow_id: str,
    manifest: dict,
) -> None:
    _atomic_write_json(_abort_manifest_full_path(project_root, workflow_id), manifest)


def _read_abort_manifest(project_root: str, workflow_id: str) -> dict | None:
    relative_path = _abort_manifest_rel_path(workflow_id)
    full_path = os.path.join(project_root, relative_path)
    if not os.path.isfile(full_path):
        return None
    manifest, _raw = _read_manifest(project_root, relative_path)
    return manifest


def _abort_manifest_can_add_spike_cleanup_plan(manifest: dict) -> bool:
    """旧清单还没有开始任何恢复动作时，才允许补记穿刺清理边界。"""

    if manifest.get("restored_at") is not None:
        return False
    items = manifest.get("items")
    if not isinstance(items, list) or not items:
        return False
    return all(
        isinstance(item, dict)
        and item.get("status", "pending") == "pending"
        and int(item.get("attempts") or 0) == 0
        and item.get("started_at") is None
        and item.get("restored_at") is None
        and item.get("observed_before_restore") is None
        for item in items
    )


def _migrate_abort_manifest_spike_cleanup_plan(
    project_root: str,
    workflow_id: str,
    manifest: dict,
    spike_cleanup_plan: dict[str, list[str]],
) -> dict:
    """把尚未开始恢复的版本 1 作废清单升级为带冻结清理计划的版本 2。"""

    version = manifest.get("version")
    if version == ABORT_MANIFEST_VERSION:
        return manifest
    if version != MANIFEST_VERSION:
        raise ValueError(f"作废进度清单版本不受支持：{version!r}")
    if manifest.get("spike_cleanup_plan") is not None:
        raise ValueError("旧作废进度清单版本与穿刺清理计划结构不一致")
    if not _abort_manifest_can_add_spike_cleanup_plan(manifest):
        raise ValueError(
            "旧作废进度清单已经开始恢复，不能事后补造穿刺临时内容清理计划；"
            "当前轮次保持 active（仍在进行）并保留全部回退与穿刺现场"
        )
    migrated = dict(manifest)
    migrated["version"] = ABORT_MANIFEST_VERSION
    migrated["spike_cleanup_plan"] = {
        "preserved": list(spike_cleanup_plan["preserved"]),
        "remove": list(spike_cleanup_plan["remove"]),
    }
    _write_abort_manifest(project_root, workflow_id, migrated)
    return migrated


def _snapshot_abort_item_state(project_root: str, item: dict) -> dict:
    """读取一个恢复项此刻的可比较状态，不保存文件正文。"""
    if item.get("kind") == "project_fields":
        return {
            "kind": "project_fields",
            "fields": project_mod.snapshot_managed_fields(project_root),
        }

    path = _safe_project_relative_path(
        project_root,
        item.get("path"),
        purpose="作废恢复文件路径",
    )
    full_path = os.path.join(project_root, path)
    if not os.path.lexists(full_path):
        return {
            "kind": "file",
            "exists": False,
            "content_hash": None,
            "mode": None,
        }
    return {
        "kind": "file",
        "exists": True,
        "content_hash": _sha256_file(full_path),
        "mode": os.stat(full_path).st_mode & 0o777,
    }


def _abort_item_target_state(item: dict) -> dict:
    """根据不可变源清单得到恢复项应该达到的目标状态。"""
    if item.get("kind") == "project_fields":
        return {
            "kind": "project_fields",
            "fields": item.get("fields"),
        }
    if item.get("original_exists") is True:
        return {
            "kind": "file",
            "exists": True,
            "content_hash": item.get("content_hash"),
            "mode": item.get("mode"),
        }
    return {
        "kind": "file",
        "exists": False,
        "content_hash": None,
        "mode": None,
    }


def _abort_state_matches_target(current: dict, target: dict) -> bool:
    """比较当前状态和恢复目标；旧清单没有权限时只比较内容。"""
    if current.get("kind") != target.get("kind"):
        return False
    if target.get("kind") == "project_fields":
        return current.get("fields") == target.get("fields")
    if current.get("exists") != target.get("exists"):
        return False
    if target.get("exists") is False:
        return True
    if current.get("content_hash") != target.get("content_hash"):
        return False
    target_mode = target.get("mode")
    return not isinstance(target_mode, int) or current.get("mode") == target_mode


def _validate_observed_abort_state(item: dict, observed: dict) -> None:
    """校验可变进度中的恢复前观察状态，拒绝无意义或不完整值。"""
    if not isinstance(observed, dict) or observed.get("kind") != item.get("kind"):
        raise ValueError(f"作废恢复项目的恢复前观察状态无效：{item.get('id')}")
    if item.get("kind") == "project_fields":
        project_mod._validate_managed_fields(observed.get("fields"))
        return

    exists = observed.get("exists")
    if not isinstance(exists, bool):
        raise ValueError(f"作废恢复文件的恢复前存在状态无效：{item.get('path')}")
    if exists:
        content_hash = observed.get("content_hash")
        mode = observed.get("mode")
        if (
            not isinstance(content_hash, str)
            or re.fullmatch(r"[0-9a-f]{64}", content_hash) is None
            or not isinstance(mode, int)
            or isinstance(mode, bool)
        ):
            raise ValueError(f"作废恢复文件的恢复前内容状态无效：{item.get('path')}")
    elif observed.get("content_hash") is not None or observed.get("mode") is not None:
        raise ValueError(f"作废恢复文件原本不存在时不能带内容状态：{item.get('path')}")


def _abort_item_result_name(item: dict) -> str:
    if item.get("kind") == "file":
        return item["path"]
    return ".workflow_loop/project.json 受管字段"


def _validate_abort_items(
    project_root: str,
    workflow_id: str,
    manifest: dict,
) -> list[dict]:
    if manifest.get("version") != ABORT_MANIFEST_VERSION:
        raise ValueError("作废进度清单版本不受支持")
    if manifest.get("workflow_id") != workflow_id:
        raise ValueError("作废进度清单不属于当前工作流")
    items = manifest.get("items")
    if not isinstance(items, list) or not items:
        raise ValueError("作废进度清单没有恢复项目")
    item_ids: set[str] = set()
    normalized_paths: set[str] = set()
    validated: list[dict] = []
    allowed_sources = {
        _start_manifest_rel_path(workflow_id),
        _manifest_rel_path(workflow_id),
        None,
    }
    for raw_item in items:
        if not isinstance(raw_item, dict):
            raise ValueError("作废进度清单包含无效恢复项目")
        item = raw_item
        item_id = item.get("id")
        if not isinstance(item_id, str) or not item_id or item_id in item_ids:
            raise ValueError(f"作废进度清单包含重复或无效项目编号：{item_id!r}")
        item_ids.add(item_id)
        status = item.get("status", "pending")
        if status not in ABORT_ITEM_STATES:
            raise ValueError(f"作废恢复项目状态无效：{item_id}={status!r}")
        kind = item.get("kind")
        if kind == "file":
            path = _safe_project_relative_path(
                project_root,
                item.get("path"),
                purpose="作废恢复文件路径",
            )
            comparison_key = path.casefold()
            if comparison_key in normalized_paths:
                raise ValueError(f"作废进度清单重复恢复同一文件：{path}")
            normalized_paths.add(comparison_key)
            source_manifest = item.get("source_manifest")
            if source_manifest not in allowed_sources:
                raise ValueError(f"作废恢复项目引用了未知来源清单：{path}")
            original_exists = item.get("original_exists")
            if not isinstance(original_exists, bool):
                raise ValueError(f"作废恢复项目缺少原文件存在状态：{path}")
            if original_exists and (
                not isinstance(item.get("backup_path"), str)
                or not isinstance(item.get("content_hash"), str)
            ):
                raise ValueError(f"作废恢复项目缺少旧文件副本信息：{path}")
            if not original_exists and (
                item.get("backup_path") is not None
                or item.get("content_hash") is not None
            ):
                raise ValueError(f"作废恢复项目的新文件记录不能包含副本：{path}")
        elif kind == "project_fields":
            if item_id != "project_fields" or not isinstance(item.get("fields"), dict):
                raise ValueError("作废进度清单中的项目受管字段记录无效")
        else:
            raise ValueError(f"作废进度清单包含未知恢复项目类型：{kind!r}")
        observed = item.get("observed_before_restore")
        if status == "pending" and observed is not None:
            raise ValueError(f"待恢复项目不能提前包含恢复前观察状态：{item_id}")
        if status == "restoring" and observed is None:
            raise ValueError(
                f"正在恢复的项目缺少恢复前观察状态，不能安全重试：{item_id}"
            )
        if observed is not None:
            _validate_observed_abort_state(item, observed)
        validated.append(item)
    return validated


def _validated_abort_spike_cleanup_plan(
    workflow_id: str,
    manifest: dict,
) -> dict[str, list[str]]:
    """校验作废预检冻结的穿刺保留/删除边界。"""

    raw = manifest.get("spike_cleanup_plan")
    if not isinstance(raw, dict):
        raise ValueError("作废进度清单缺少穿刺临时内容清理计划")
    preserved = raw.get("preserved")
    remove = raw.get("remove")
    if (
        not isinstance(preserved, list)
        or not isinstance(remove, list)
        or not all(isinstance(path, str) for path in preserved + remove)
    ):
        raise ValueError("作废穿刺清理计划必须包含 preserved（保留）和 remove（删除）路径数组")
    if preserved != sorted(set(preserved)) or remove != sorted(set(remove)):
        raise ValueError("作废穿刺清理计划路径必须去重并按字典序保存")
    if set(preserved) & set(remove):
        raise ValueError("作废穿刺清理计划不能同时保留和删除同一路径")

    prefix = f".workflow_loop/spike_tmp/{_validated_workflow_id(workflow_id)}/"
    for relative_path in preserved + remove:
        if not relative_path.startswith(prefix):
            raise ValueError(f"作废穿刺清理路径不属于当前工作流：{relative_path}")
        entry = relative_path[len(prefix) :]
        if not entry or "/" in entry or entry in {".", ".."}:
            raise ValueError(f"作废穿刺清理路径必须是当前工作流的直接子项：{relative_path}")
    return {"preserved": list(preserved), "remove": list(remove)}


def _source_manifest_hashes(
    project_root: str,
    wf_state: state_mod.WorkflowState,
) -> tuple[dict[str, str], dict[str, tuple[dict, dict[str, dict], str]]]:
    """读取并完整校验开工清单和可选实施清单。"""
    workflow_id = _validated_workflow_id(wf_state.workflow_id)
    hashes: dict[str, str] = {}
    sources: dict[str, tuple[dict, dict[str, dict], str]] = {}

    start_relative = _start_manifest_rel_path(workflow_id)
    start_manifest, start_raw, start_entries, start_dir = _load_source_manifest(
        project_root,
        start_relative,
        workflow_id,
        allow_process_documents=True,
        require_complete_start=True,
    )
    if not isinstance(start_manifest.get("project_fields"), dict):
        raise ValueError("开工基线缺少项目受管字段快照")
    project_mod._validate_managed_fields(start_manifest["project_fields"])
    hashes[start_relative] = _sha256_bytes(start_raw)
    sources[start_relative] = (start_manifest, start_entries, start_dir)

    expected_impl_relative = _manifest_rel_path(workflow_id)
    expected_impl_full = os.path.join(project_root, expected_impl_relative)
    configured_impl = wf_state.rollback.manifest_path
    if configured_impl is not None:
        configured_impl = _safe_project_relative_path(
            project_root,
            configured_impl,
            purpose="实施回退清单路径",
        )
        if configured_impl != expected_impl_relative:
            raise ValueError("工作流状态中的实施回退清单路径不属于当前工作流")
    if configured_impl is not None or os.path.isfile(expected_impl_full):
        expected_hash = wf_state.rollback.manifest_hash
        if configured_impl is not None and not expected_hash:
            raise ValueError("工作流状态缺少实施回退清单哈希")
        impl_manifest, impl_raw, impl_entries, impl_dir = _load_source_manifest(
            project_root,
            expected_impl_relative,
            workflow_id,
            allow_process_documents=False,
            require_complete_start=False,
            expected_hash=expected_hash,
        )
        hashes[expected_impl_relative] = _sha256_bytes(impl_raw)
        sources[expected_impl_relative] = (impl_manifest, impl_entries, impl_dir)
    return hashes, sources


def _validate_abort_against_sources(
    project_root: str,
    workflow_id: str,
    abort_manifest: dict,
    sources: dict[str, tuple[dict, dict[str, dict], str]],
) -> None:
    """确认可变进度清单没有改写不可变的恢复事实或漏掉登记项。"""
    _validated_abort_spike_cleanup_plan(workflow_id, abort_manifest)
    items = _validate_abort_items(project_root, workflow_id, abort_manifest)
    start_relative = _start_manifest_rel_path(workflow_id)
    impl_relative = _manifest_rel_path(workflow_id)
    start_manifest, start_entries, _start_dir = sources[start_relative]
    impl_entries = sources.get(impl_relative, ({}, {}, ""))[1]

    derived_paths_raw = abort_manifest.get("derived_managed_paths", [])
    if not isinstance(derived_paths_raw, list):
        raise ValueError("作废进度清单中的本轮新正式产物范围无效")
    derived_paths = {
        _safe_project_relative_path(
            project_root,
            path,
            purpose="本轮新正式产物路径",
        )
        for path in derived_paths_raw
    }
    expected_paths = set(start_entries) | set(impl_entries) | derived_paths
    file_items = {
        item["path"]: item
        for item in items
        if item.get("kind") == "file"
    }
    if set(file_items) != expected_paths:
        missing = sorted(expected_paths - set(file_items))
        extra = sorted(set(file_items) - expected_paths)
        raise ValueError(f"作废进度清单文件范围与源清单不一致：缺少 {missing}，多出 {extra}")

    for path, item in file_items.items():
        if path in start_entries:
            expected_entry = start_entries[path]
            expected_source = start_relative
        elif path in impl_entries:
            expected_entry = impl_entries[path]
            expected_source = impl_relative
        else:
            expected_entry = {
                "original_exists": False,
                "backup_path": None,
                "content_hash": None,
                "mode": None,
            }
            expected_source = None
        if item.get("source_manifest") != expected_source:
            raise ValueError(f"作废恢复项目没有使用最早原内容：{path}")
        for key in ("original_exists", "backup_path", "content_hash", "mode"):
            if item.get(key) != expected_entry.get(key):
                raise ValueError(f"作废恢复项目的原内容事实与源清单不一致：{path}")

    project_items = [item for item in items if item.get("kind") == "project_fields"]
    if len(project_items) != 1 or project_items[0].get("fields") != start_manifest["project_fields"]:
        raise ValueError("作废进度清单中的项目受管字段与开工基线不一致")


def preflight_abort(
    project_root: str,
    wf_state: state_mod.WorkflowState,
) -> tuple[bool, list[str], dict | None]:
    """完整预检整轮恢复依据，并生成或复用独立的逐项作废进度清单。

    返回（是否可恢复、问题列表、作废进度清单）。当前旧轮次缺少完整开工
    基线时明确失败，绝不使用当前项目内容补造开工前状态。
    """
    problems: list[str] = []
    try:
        from .stages.base import plan_spike_tmp_cleanup

        workflow_id = _validated_workflow_id(wf_state.workflow_id)
        if wf_state.run_status != "active":
            raise ValueError("只有仍在进行的工作流可以预检整轮作废")
        spike_cleanup_plan = plan_spike_tmp_cleanup(project_root, wf_state)
        source_hashes, sources = _source_manifest_hashes(project_root, wf_state)
        existing = _read_abort_manifest(project_root, workflow_id)
        if existing is not None:
            if existing.get("source_hashes") != source_hashes:
                raise ValueError("源回退清单在作废恢复开始后发生变化")
            existing = _migrate_abort_manifest_spike_cleanup_plan(
                project_root,
                workflow_id,
                existing,
                spike_cleanup_plan,
            )
            _validate_abort_against_sources(
                project_root,
                workflow_id,
                existing,
                sources,
            )
            if _validated_abort_spike_cleanup_plan(workflow_id, existing) != spike_cleanup_plan:
                raise ValueError("穿刺临时目录在作废预检后发生变化；未开始恢复前必须重新核对")
            return True, [], existing

        start_relative = _start_manifest_rel_path(workflow_id)
        start_manifest, start_entries, _start_dir = sources[start_relative]
        merged: dict[str, tuple[dict, str | None]] = {
            path: (dict(entry), start_relative)
            for path, entry in start_entries.items()
        }

        impl_relative = _manifest_rel_path(workflow_id)
        if impl_relative in sources:
            _impl_manifest, impl_entries, _impl_dir = sources[impl_relative]
            for path, entry in impl_entries.items():
                # 同一路径以开工时最早原内容为准；实施清单仍已独立校验。
                merged.setdefault(path, (dict(entry), impl_relative))

        # 开工时还不知道名称、但当前已能从稳定映射或正式保留命名识别的
        # 本轮新正式产物，作为“原本不存在”写入独立作废清单。
        derived_managed_paths: list[str] = []
        for path in _official_managed_paths(project_root, wf_state):
            if path not in merged and os.path.lexists(os.path.join(project_root, path)):
                merged[path] = (
                    {
                        "original_exists": False,
                        "backup_path": None,
                        "content_hash": None,
                        "mode": None,
                    },
                    None,
                )
                derived_managed_paths.append(path)

        items: list[dict] = []
        for path in sorted(merged):
            entry, source_manifest = merged[path]
            items.append(
                {
                    "id": f"file:{path}",
                    "kind": "file",
                    "path": path,
                    "original_exists": entry.get("original_exists"),
                    "source_manifest": source_manifest,
                    "backup_path": entry.get("backup_path"),
                    "content_hash": entry.get("content_hash"),
                    "mode": entry.get("mode"),
                    "status": "pending",
                    "attempts": 0,
                    "started_at": None,
                    "restored_at": None,
                    "last_error": None,
                    "observed_before_restore": None,
                }
            )
        items.append(
            {
                "id": "project_fields",
                "kind": "project_fields",
                "fields": start_manifest["project_fields"],
                "status": "pending",
                "attempts": 0,
                "started_at": None,
                "restored_at": None,
                "last_error": None,
                "observed_before_restore": None,
            }
        )
        abort_manifest = {
            "version": ABORT_MANIFEST_VERSION,
            "workflow_id": workflow_id,
            "created_at": state_mod.now_iso(),
            "source_hashes": source_hashes,
            "derived_managed_paths": sorted(derived_managed_paths),
            "spike_cleanup_plan": spike_cleanup_plan,
            "items": items,
            "restored_at": None,
        }
        _validate_abort_against_sources(
            project_root,
            workflow_id,
            abort_manifest,
            sources,
        )
        _write_abort_manifest(project_root, workflow_id, abort_manifest)
        return True, [], abort_manifest
    except (OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
        problems.append(str(exc))
        return False, problems, None


def abort_spike_cleanup_plan(
    project_root: str,
    wf_state: state_mod.WorkflowState,
) -> dict[str, list[str]]:
    """读取并验证作废预检保存的穿刺清理计划，供恢复完成后执行。"""

    workflow_id = _validated_workflow_id(wf_state.workflow_id)
    manifest = _read_abort_manifest(project_root, workflow_id)
    if manifest is None:
        raise ValueError("缺少作废进度清单，不能清理穿刺临时内容")
    source_hashes, sources = _source_manifest_hashes(project_root, wf_state)
    if manifest.get("source_hashes") != source_hashes:
        raise ValueError("源回退清单在作废恢复期间发生变化")
    _validate_abort_against_sources(
        project_root,
        workflow_id,
        manifest,
        sources,
    )
    return _validated_abort_spike_cleanup_plan(workflow_id, manifest)


def _abort_item_source_dir(
    project_root: str,
    workflow_id: str,
    item: dict,
) -> str | None:
    source_manifest = item.get("source_manifest")
    if source_manifest is None:
        return None
    if source_manifest not in {
        _start_manifest_rel_path(workflow_id),
        _manifest_rel_path(workflow_id),
    }:
        raise ValueError(f"恢复项目引用了未知来源清单：{item.get('id')}")
    return os.path.dirname(os.path.join(project_root, source_manifest))


def restore_full_run(
    project_root: str,
    wf_state: state_mod.WorkflowState,
) -> tuple[list[str], list[str]]:
    """按独立作废清单逐项恢复；失败保留进度，重试跳过 restored 项。"""
    workflow_id = _validated_workflow_id(wf_state.workflow_id)
    manifest = _read_abort_manifest(project_root, workflow_id)
    if manifest is None:
        return [], ["缺少作废进度清单；必须先完整预检，不能直接开始恢复"]
    try:
        if manifest.get("version") == MANIFEST_VERSION:
            from .stages.base import plan_spike_tmp_cleanup

            manifest = _migrate_abort_manifest_spike_cleanup_plan(
                project_root,
                workflow_id,
                manifest,
                plan_spike_tmp_cleanup(project_root, wf_state),
            )
        items = _validate_abort_items(project_root, workflow_id, manifest)
        current_hashes, sources = _source_manifest_hashes(project_root, wf_state)
        if manifest.get("source_hashes") != current_hashes:
            raise ValueError("源回退清单在逐项恢复期间发生变化")
        _validate_abort_against_sources(
            project_root,
            workflow_id,
            manifest,
            sources,
        )
    except (OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
        return [], [str(exc)]

    restored_now: list[str] = []
    failures: list[str] = []
    for item in items:
        if item.get("status") == "restored":
            continue
        item["attempts"] = int(item.get("attempts") or 0) + 1
        item["started_at"] = state_mod.now_iso()
        item["last_error"] = None
        try:
            if item.get("status") == "pending":
                item["observed_before_restore"] = _snapshot_abort_item_state(
                    project_root,
                    item,
                )
            item["status"] = "restoring"
            _write_abort_manifest(project_root, workflow_id, manifest)
            current = _snapshot_abort_item_state(project_root, item)
            target = _abort_item_target_state(item)
            if not _abort_state_matches_target(current, target):
                if current != item["observed_before_restore"]:
                    raise ValueError(
                        f"{_abort_item_result_name(item)} 在恢复中断后发生了新的修改；"
                        "当前内容既不是恢复前状态，也不是恢复目标，已停止以避免覆盖"
                    )
                if item["kind"] == "file":
                    _restore_file_entry(
                        project_root,
                        item["path"],
                        item,
                        _abort_item_source_dir(project_root, workflow_id, item),
                    )
                else:
                    project_mod.restore_managed_fields(project_root, item["fields"])
                restored_state = _snapshot_abort_item_state(project_root, item)
                if not _abort_state_matches_target(restored_state, target):
                    raise ValueError(
                        f"{_abort_item_result_name(item)} 恢复后的状态与目标不一致"
                    )
            result_name = _abort_item_result_name(item)
            item["status"] = "restored"
            item["restored_at"] = state_mod.now_iso()
            item["last_error"] = None
            _write_abort_manifest(project_root, workflow_id, manifest)
            restored_now.append(result_name)
        except (OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
            item["last_error"] = str(exc)
            try:
                _write_abort_manifest(project_root, workflow_id, manifest)
            except OSError as progress_exc:
                failures.append(f"{item['id']}：恢复失败且进度无法保存（{progress_exc}）")
                break
            failures.append(f"{item['id']}：{exc}")
            break

    pending = [
        item["id"]
        for item in items
        if item.get("status") != "restored"
    ]
    if not failures and pending:
        failures.append("仍有未完成恢复项目：" + str(pending))
    if not failures:
        manifest["restored_at"] = state_mod.now_iso()
        try:
            _write_abort_manifest(project_root, workflow_id, manifest)
        except OSError as exc:
            failures.append(f"全部项目已恢复，但无法保存完成进度：{exc}")
    return restored_now, failures


def write_start_transaction(project_root: str, workflow_id: str, clean_paths: list[str]) -> None:
    """清场前写入开工事务记录；提交或恢复完成后删除。"""
    workflow_id = _validated_workflow_id(workflow_id)
    payload = {
        "workflow_id": workflow_id,
        "created_at": state_mod.now_iso(),
        "clean_paths": clean_paths,
        "status": "prepared",
    }
    full_path = os.path.join(project_root, START_TRANSACTION_FILE)
    _atomic_write_json(full_path, payload)


def read_start_transaction(project_root: str) -> dict | None:
    full_path = os.path.join(project_root, START_TRANSACTION_FILE)
    if not os.path.isfile(full_path):
        return None
    try:
        with open(full_path, "r", encoding="utf-8") as stream:
            return json.load(stream)
    except (OSError, json.JSONDecodeError):
        return {"workflow_id": None, "status": "unreadable"}


def mark_start_transaction_committed(project_root: str, workflow_id: str) -> None:
    workflow_id = _validated_workflow_id(workflow_id)
    payload = {
        "workflow_id": workflow_id,
        "created_at": state_mod.now_iso(),
        "status": "committed",
    }
    full_path = os.path.join(project_root, START_TRANSACTION_FILE)
    _atomic_write_json(full_path, payload)


def clear_start_transaction(project_root: str) -> None:
    full_path = os.path.join(project_root, START_TRANSACTION_FILE)
    if os.path.isfile(full_path):
        os.remove(full_path)


def restore_start_baseline(project_root: str, workflow_id: str) -> tuple[list[str], list[str]]:
    """按开工基线恢复受管文档；返回（已恢复路径, 失败说明）。

    只恢复清单内的文件：写回原内容；开工后新建、不在清单中的受管文档不在
    这里处理（开工失败场景中新建内容由调用方按新旧清单差异删除）。
    """
    try:
        workflow_id = _validated_workflow_id(workflow_id)
        manifest_relative = _start_manifest_rel_path(workflow_id)
        manifest, _raw, entries, manifest_dir = _load_source_manifest(
            project_root,
            manifest_relative,
            workflow_id,
            allow_process_documents=True,
            require_complete_start=True,
        )
    except (OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
        return [], [str(exc)]
    restored: list[str] = []
    failures: list[str] = []
    for relative_path, entry in entries.items():
        try:
            _restore_file_entry(project_root, relative_path, entry, manifest_dir)
            restored.append(relative_path)
        except (OSError, TypeError, ValueError) as exc:
            failures.append(f"{relative_path}（{exc}）")
    return restored, failures
