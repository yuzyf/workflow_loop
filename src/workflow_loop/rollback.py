"""按文件保存实施前内容，并在整个工作流中止时恢复。"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import tempfile
from pathlib import PurePosixPath

from . import state as state_mod
from . import verification as verification_mod


ROLLBACK_ROOT = os.path.join(".workflow_loop", "rollback")
MANIFEST_VERSION = 1
PROCESS_ROOTS = {"spec", "acceptance", "qa", "impl", "bug", ".workflow_loop", ".git"}
GLOB_CHARS = set("*?[]{}")


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


def _safe_backup_path(manifest_dir: str, raw_path: str, code_path: str) -> str:
    value = str(raw_path).replace("\\", "/")
    path = PurePosixPath(value)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise ValueError(f"回退清单中的文件副本路径不安全：{code_path}")
    full_path = os.path.join(manifest_dir, *path.parts)
    manifest_real = os.path.realpath(manifest_dir)
    backup_real = os.path.realpath(full_path)
    if os.path.commonpath([manifest_real, backup_real]) != manifest_real:
        raise ValueError(f"回退清单中的文件副本超出回退目录：{code_path}")
    if os.path.islink(full_path):
        raise ValueError(f"实施前文件副本不能是符号链接：{code_path}")
    return full_path


def _manifest_rel_path(workflow_id: str) -> str:
    return os.path.join(ROLLBACK_ROOT, workflow_id, "impl", "manifest.json")


def _manifest_full_path(project_root: str, workflow_id: str) -> str:
    return os.path.join(project_root, _manifest_rel_path(workflow_id))


def _normalized_relative_path(project_root: str, raw_path: str) -> str:
    value = raw_path.strip().strip("`").replace("\\", "/")
    if not value or value in {"新增", "暂无", "无", "相关文件"}:
        raise ValueError(f"代码修改计划包含无法定位的文件路径：{raw_path!r}")
    if any(character in value for character in GLOB_CHARS):
        raise ValueError(f"代码修改计划不能使用通配符：{value}")
    path = PurePosixPath(value)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise ValueError(f"代码修改计划必须使用项目内相对路径：{value}")
    if path.parts[0] in PROCESS_ROOTS or value == "traceability.md":
        raise ValueError(f"代码修改计划不能把工作流过程文档当成实施代码：{value}")

    normalized = path.as_posix()
    full_path = os.path.join(project_root, *path.parts)
    project_real = os.path.realpath(project_root)
    parent_real = os.path.realpath(os.path.dirname(full_path) or project_root)
    if os.path.commonpath([project_real, parent_real]) != project_real:
        raise ValueError(f"代码修改计划路径超出项目目录：{value}")

    current = project_root
    for part in path.parts[:-1]:
        current = os.path.join(current, part)
        if os.path.lexists(current) and os.path.islink(current):
            raise ValueError(f"代码修改计划路径经过符号链接，无法安全回退：{value}")
    if os.path.lexists(full_path):
        if os.path.islink(full_path):
            raise ValueError(f"代码修改计划不能直接修改符号链接：{value}")
        if not os.path.isfile(full_path):
            raise ValueError(f"代码修改计划必须指向具体文件，不能是目录：{value}")
    return normalized


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
        relative_path = os.path.join("impl", f"{topic}.md")
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
        full_path = os.path.join(project_root, "impl", f"{topic}.md")
        with open(full_path, "r", encoding="utf-8") as stream:
            section = _section(stream.read(), "2.2 代码修改计划")
        payload.append(f"{topic}\n{section}")
    return hashlib.sha256("\n\n".join(payload).encode("utf-8")).hexdigest()


def _read_manifest(project_root: str, relative_path: str) -> tuple[dict, bytes]:
    full_path = os.path.join(project_root, relative_path)
    if not os.path.isfile(full_path):
        raise ValueError(f"实施前回退清单不存在：{relative_path}")
    with open(full_path, "rb") as stream:
        raw = stream.read()
    try:
        data = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"实施前回退清单无法读取：{exc}") from exc
    return data, raw


def _validate_backup_entries(project_root: str, manifest: dict) -> None:
    manifest_dir = os.path.dirname(
        _manifest_full_path(project_root, manifest.get("workflow_id", ""))
    )
    entries = manifest.get("entries")
    if not isinstance(entries, dict):
        raise ValueError("实施前回退清单缺少文件记录")
    for path, entry in entries.items():
        if not isinstance(path, str) or not isinstance(entry, dict):
            raise ValueError("实施前回退清单包含无效文件记录")
        _normalized_relative_path(project_root, path)
        if entry.get("original_exists"):
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
    current_code_hash = verification_mod.compute_non_test_code_snapshot_hash(project_root)
    if current_code_hash != stage_state.code_baseline_hash:
        raise ValueError("代码已经在回退基线保存前发生变化，不能把修改后的内容当成原内容")

    paths = planned_code_paths(project_root, wf_state.topics)
    plan_hash = compute_plan_hash(project_root, wf_state.topics)
    manifest_path = _manifest_rel_path(wf_state.workflow_id)
    manifest_full_path = os.path.join(project_root, manifest_path)
    manifest_dir = os.path.dirname(manifest_full_path)
    os.makedirs(manifest_dir, exist_ok=True)

    manifest: dict
    if os.path.isfile(manifest_full_path):
        manifest, raw = _read_manifest(project_root, manifest_path)
        if manifest.get("workflow_id") != wf_state.workflow_id:
            raise ValueError("现有回退清单不属于当前工作流，不能覆盖")
        _validate_backup_entries(project_root, manifest)
    else:
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
        "inventory_before": verification_mod.compute_project_file_hashes(project_root),
    }
    prepares = manifest.setdefault("prepares", [])
    if not prepares or any(
        prepares[-1].get(key) != prepare_record.get(key)
        for key in ("plan_hash", "code_baseline_hash", "planned_paths")
    ):
        prepares.append(prepare_record)
    else:
        prepares[-1] = prepare_record

    raw = json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True).encode("utf-8")
    temp_path = manifest_full_path + ".tmp"
    with open(temp_path, "wb") as stream:
        stream.write(raw)
    os.replace(temp_path, manifest_full_path)

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
    manifest_full_path = os.path.join(project_root, wf_state.rollback.manifest_path)
    raw = json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True).encode("utf-8")
    temp_path = manifest_full_path + ".tmp"
    with open(temp_path, "wb") as stream:
        stream.write(raw)
    os.replace(temp_path, manifest_full_path)
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
    prepares = manifest.get("prepares", [])
    if not prepares:
        raise ValueError("实施前回退清单没有准备记录")
    before = prepares[-1].get("inventory_before", {})
    current = verification_mod.compute_project_file_hashes(project_root)
    return sorted(
        path
        for path in set(before) | set(current)
        if before.get(path) != current.get(path)
    )


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
    relative_path = os.path.join(ROLLBACK_ROOT, workflow_id)
    full_path = os.path.join(project_root, relative_path)
    if not os.path.exists(full_path):
        return []
    shutil.rmtree(full_path)
    parent = os.path.dirname(full_path)
    if os.path.isdir(parent) and not os.listdir(parent):
        os.rmdir(parent)
    return [relative_path]
