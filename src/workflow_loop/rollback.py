"""按文件保存实施前内容，并在整个工作流中止时恢复。"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import tempfile
from pathlib import PurePosixPath

from . import artifact_paths as artifact_paths_mod
from . import project as project_mod
from . import state as state_mod
from . import test_entry as test_entry_mod
from . import verification as verification_mod
from .topic import topic_paths


ROLLBACK_ROOT = ".workflow_loop/rollback"
MANIFEST_VERSION = 1
PROCESS_ROOTS = {"spec", "acceptance", "qa", "impl", "bug", ".workflow_loop", ".git"}
GLOB_CHARS = set("*?[]{}")
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


def _normalized_relative_path(project_root: str, raw_path: str) -> str:
    if not isinstance(raw_path, str):
        raise ValueError(f"代码修改计划包含无法定位的文件路径：{raw_path!r}")
    value = raw_path.strip().strip("`").replace("\\", "/")
    if not value or value in {"新增", "暂无", "无", "相关文件"}:
        raise ValueError(f"代码修改计划包含无法定位的文件路径：{raw_path!r}")
    if any(character in value for character in GLOB_CHARS):
        raise ValueError(f"代码修改计划不能使用通配符：{value}")
    path = PurePosixPath(value)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise ValueError(f"代码修改计划必须使用项目内相对路径：{value}")
    if path.parts[0] in PROCESS_ROOTS or value in MANAGED_DOC_FILES:
        raise ValueError(f"代码修改计划不能把工作流过程文档当成实施代码：{value}")

    return _safe_project_relative_path(
        project_root,
        value,
        purpose="代码修改计划路径",
    )


def _section(content: str, heading: str) -> str:
    match = re.search(
        rf"^###\s+{re.escape(heading)}\s*$\n(.*?)(?=^###\s+|^##\s+|\Z)",
        content,
        re.MULTILINE | re.DOTALL,
    )
    if match is None:
        raise ValueError(f"实施文档缺少“{heading}”")
    return match.group(1).strip()


def _table_file_paths(section: str) -> list[str]:
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
                raise ValueError("代码修改计划表的数据列数与表头不一致")
            paths.append(cells[file_index])
        if not paths:
            raise ValueError("代码修改计划表没有任何文件")
        return paths
    raise ValueError("代码修改计划缺少包含“文件”列的表格")


def planned_code_paths(project_root: str, topics: list[str]) -> list[str]:
    paths: list[str] = []
    for topic in topics:
        relative_path = topic_paths(project_root, topic)["impl_doc"]
        full_path = os.path.join(project_root, relative_path)
        if not os.path.isfile(full_path):
            raise ValueError(f"缺少主题实施文档：{relative_path}")
        with open(full_path, "r", encoding="utf-8") as stream:
            content = stream.read()
        for raw_path in _table_file_paths(_section(content, "2.2 代码修改计划")):
            paths.append(_normalized_relative_path(project_root, raw_path))
    return sorted(set(paths))


def compute_plan_hash(project_root: str, topics: list[str]) -> str:
    payload: list[str] = []
    for topic in topics:
        relative_path = topic_paths(project_root, topic)["impl_doc"]
        full_path = os.path.join(project_root, relative_path)
        with open(full_path, "r", encoding="utf-8") as stream:
            section = _section(stream.read(), "2.2 代码修改计划")
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
            path = _normalized_relative_path(project_root, raw_path)
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


def _validate_backup_entries(project_root: str, manifest: dict) -> None:
    workflow_id = _validated_workflow_id(manifest.get("workflow_id", ""))
    manifest_dir = os.path.dirname(_manifest_full_path(project_root, workflow_id))
    _validated_manifest_entries(
        project_root,
        manifest,
        manifest_dir,
        allow_process_documents=False,
    )


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
    if os.path.isfile(manifest_full_path):
        # 再次准备：允许已登记路径按计划变化；首次原内容始终保留，不被覆盖
        manifest, raw = _read_manifest(project_root, manifest_path)
        if manifest.get("workflow_id") != wf_state.workflow_id:
            raise ValueError("现有回退清单不属于当前工作流，不能覆盖")
        _validate_backup_entries(project_root, manifest)
        initial_inventory = manifest.get("initial_inventory", {})
        entries = manifest.setdefault("entries", {})
        current_inventory = verification_mod.compute_project_file_hashes(project_root)
        for path in paths:
            if path in entries:
                continue
            # 新加入计划的路径：只有当前内容仍等于第一次准备时的内容才允许补副本，
            # 否则没有可信的原内容
            if current_inventory.get(path) != initial_inventory.get(path):
                raise ValueError(
                    f"计划新增的路径已经被修改，没有可信的实施前原内容：{path}；"
                    "先恢复该文件到实施前内容，或返回计划重新讨论"
                )
    else:
        # 第一次准备：代码必须仍等于讨论确认时的基线，不能把修改后的内容当成原内容
        current_code_hash = verification_mod.compute_non_test_code_snapshot_hash(project_root)
        if current_code_hash != stage_state.code_baseline_hash:
            raise ValueError("代码已经在回退基线保存前发生变化，不能把修改后的内容当成原内容")
        manifest = {
            "version": MANIFEST_VERSION,
            "workflow_id": wf_state.workflow_id,
            "created_at": state_mod.now_iso(),
            "initial_inventory": verification_mod.compute_project_file_hashes(project_root),
            "entries": {},
            "prepares": [],
        }

    entries = manifest.setdefault("entries", {})
    for path in paths:
        if path not in entries:
            entries[path] = _backup_entry(project_root, manifest_dir, path)

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


def changed_paths_since_prepare(project_root: str, manifest: dict) -> list[str]:
    """实际变化始终和第一次项目清单比较，早期修改不会因再次准备消失。"""
    prepares = manifest.get("prepares", [])
    if not prepares:
        raise ValueError("实施前回退清单没有准备记录")
    raw_before = manifest.get("initial_inventory") or prepares[0].get("inventory_before", {})
    before = {
        path: content_hash
        for path, content_hash in raw_before.items()
        if verification_mod.is_implementation_related_path(path)
    }
    current = verification_mod.compute_project_file_hashes(project_root)
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


def validate_implementation_changes(
    project_root: str,
    wf_state: state_mod.WorkflowState,
) -> tuple[bool, str]:
    valid, detail, manifest = validate_prepared(project_root, wf_state)
    if not valid or manifest is None:
        return False, detail
    changed = changed_paths_since_prepare(project_root, manifest)
    planned = set(wf_state.rollback.planned_paths)
    unexpected = sorted(set(changed) - planned)
    if unexpected:
        return False, f"发现实施计划外的文件变化：{unexpected}"
    if not changed:
        return False, "实施计划列出的文件没有相对回退基线发生变化"
    return True, f"实施前回退副本完整，实际变化文件均在计划内：{changed}"


def restore(project_root: str, wf_state: state_mod.WorkflowState) -> list[str]:
    valid, detail, manifest = validate_prepared(
        project_root,
        wf_state,
        require_current_plan=False,
    )
    if not valid or manifest is None:
        raise ValueError(detail)

    initial_inventory = manifest.get("initial_inventory", {})
    current_inventory = verification_mod.compute_project_file_hashes(project_root)
    allowed = set(manifest.get("entries", {}))
    unexpected = sorted(
        path
        for path in set(initial_inventory) | set(current_inventory)
        if initial_inventory.get(path) != current_inventory.get(path) and path not in allowed
    )
    if unexpected:
        raise ValueError(
            "存在没有实施前副本的文件变化，不能安全中止：" + str(unexpected)
        )

    manifest_dir = os.path.dirname(os.path.join(project_root, wf_state.rollback.manifest_path or ""))
    restored: list[str] = []
    try:
        for relative_path, entry in manifest.get("entries", {}).items():
            _normalized_relative_path(project_root, relative_path)
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
    if manifest.get("version") != MANIFEST_VERSION:
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
        workflow_id = _validated_workflow_id(wf_state.workflow_id)
        if wf_state.run_status != "active":
            raise ValueError("只有仍在进行的工作流可以预检整轮作废")
        source_hashes, sources = _source_manifest_hashes(project_root, wf_state)
        existing = _read_abort_manifest(project_root, workflow_id)
        if existing is not None:
            if existing.get("source_hashes") != source_hashes:
                raise ValueError("源回退清单在作废恢复开始后发生变化")
            _validate_abort_against_sources(
                project_root,
                workflow_id,
                existing,
                sources,
            )
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
            "version": MANIFEST_VERSION,
            "workflow_id": workflow_id,
            "created_at": state_mod.now_iso(),
            "source_hashes": source_hashes,
            "derived_managed_paths": sorted(derived_managed_paths),
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
