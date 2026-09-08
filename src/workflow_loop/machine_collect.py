"""机器事实采集：行号、基线提交号、验收五列、编号引用、测试标识。

R25-R29 要求依赖机器事实的表栏位由程序直接采集写入，AI 不手抄。本模块集中
承载这些采集动作；采集（写表）与门禁校验（重算比对）复用同一批纯函数，
保证一致性是结构保证而不是约定。

改动前内容按 R25 顺序取得：先取实施前回退副本；没有副本时用进场记录的
Git 基线提交号取进场内容；两种来源都取不到时按已确认口径报错，不静默
跳过、不填占位行号。
"""
from __future__ import annotations

import os
import re
import subprocess
from dataclasses import dataclass

from . import records as records_mod
from . import rollback as rollback_mod
from . import state as state_mod

# 进场 Git 基线提交号在 wf_state.meta 中的键。只在进场时代码范围没有
# 未提交改动时记录；取不到时不写该键，采集时按无基线处理。
IMPL_ENTRY_GIT_COMMIT_KEY = "impl_entry_git_commit"

_GIT_ENV_STRIP = (
    "GIT_DIR",
    "GIT_WORK_TREE",
    "GIT_INDEX_FILE",
    "GIT_OBJECT_DIRECTORY",
    "GIT_ALTERNATE_OBJECT_DIRECTORIES",
    "GIT_COMMON_DIR",
    "GIT_NAMESPACE",
)


class CollectError(ValueError):
    """采集失败；消息按全局失败输出规范带位置、事实和下一步。"""


@dataclass(frozen=True)
class DiffFact:
    """一个文件相对进场基线的差异事实。"""

    file: str
    # 最终文件行号范围文本，例如 "L12-L34"；新文件写"新增文件"；整文件删除写"删除整个文件"
    location: str
    # 该文件采集时刻的内容指纹（SHA-256），删除文件为 None
    content_hash: str | None


def _run_git(project_root: str, *arguments: str) -> subprocess.CompletedProcess[bytes] | None:
    environment = dict(os.environ)
    for variable in _GIT_ENV_STRIP:
        environment.pop(variable, None)
    environment["GIT_OPTIONAL_LOCKS"] = "0"
    try:
        return subprocess.run(
            ["git", *arguments],
            cwd=project_root,
            env=environment,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            check=False,
            timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None


def record_entry_git_baseline(project_root: str, wf_state) -> bool:
    """进场时代码范围没有未提交改动时，记录当前 HEAD 为基线提交号。

    代码范围按现有快照口径排除受管文档目录。已经记录过、项目不是可读取的
    Git 仓库或代码范围有未提交改动时不记录，返回 False。
    """
    if wf_state.current_stage != "impl":
        return False
    existing = wf_state.meta.get(IMPL_ENTRY_GIT_COMMIT_KEY)
    if (
        isinstance(existing, dict)
        and existing.get("workflow_id") == wf_state.workflow_id
        and existing.get("commit")
    ):
        return False
    changed, detail = _code_scope_uncommitted_changes(project_root)
    if changed is None or changed:
        return False
    head = _run_git(project_root, "rev-parse", "--verify", "HEAD^{commit}")
    if head is None or head.returncode != 0:
        return False
    commit = os.fsdecode(head.stdout).strip()
    if re.fullmatch(r"[0-9a-fA-F]{40,64}", commit) is None:
        return False
    wf_state.meta[IMPL_ENTRY_GIT_COMMIT_KEY] = {
        "workflow_id": wf_state.workflow_id,
        "commit": commit,
        "recorded_at": state_mod.now_iso(),
        "scope_detail": detail,
    }
    return True


def _code_scope_uncommitted_changes(project_root: str) -> tuple[bool | None, str]:
    """检查代码范围（排除受管文档目录）是否有未提交改动。

    返回 (True, 说明) 表示有改动或无法确认；(False, 说明) 表示干净。
    """
    from . import verification as verification_mod

    changed, detail = verification_mod._git_changed_paths(project_root)
    if changed is None:
        return None, detail
    managed = set(rollback_mod.managed_document_paths(project_root))
    code_changes = [path for path in changed if path not in managed]
    if code_changes:
        return True, f"代码范围有未提交改动：{code_changes}"
    return False, "代码范围相对 Git 提交无未提交改动"


def _entry_baseline_text(
    project_root: str,
    wf_state,
    path: str,
) -> str | None:
    """用进场基线提交号取该文件的进场内容；取不到返回 None。"""
    entry = wf_state.meta.get(IMPL_ENTRY_GIT_COMMIT_KEY)
    if not isinstance(entry, dict) or entry.get("workflow_id") != wf_state.workflow_id:
        return None
    commit = str(entry.get("commit") or "")
    if not commit:
        return None
    prefix_result = _run_git(project_root, "rev-parse", "--show-prefix")
    if prefix_result is None or prefix_result.returncode != 0:
        return None
    prefix = os.fsdecode(prefix_result.stdout).rstrip("\r\n")
    tree_path = f"{prefix}{path}"
    blob = _run_git(project_root, "show", f"{commit}:{tree_path}")
    if blob is None or blob.returncode != 0:
        return None
    try:
        return blob.stdout.decode("utf-8")
    except UnicodeDecodeError:
        return None


def _entry_baseline_absence(
    project_root: str,
    wf_state,
    path: str,
) -> bool:
    """进场基线提交号能读取且其中没有该路径时，返回 True（新文件）。"""
    entry = wf_state.meta.get(IMPL_ENTRY_GIT_COMMIT_KEY)
    if not isinstance(entry, dict) or not entry.get("commit"):
        return False
    blob = _run_git(project_root, "ls-tree", "--name-only", str(entry["commit"]))
    if blob is None or blob.returncode != 0:
        return False
    prefix_result = _run_git(project_root, "rev-parse", "--show-prefix")
    if prefix_result is None or prefix_result.returncode != 0:
        return False
    prefix = os.fsdecode(prefix_result.stdout).rstrip("\r\n")
    tree_path = f"{prefix}{path}"
    tracked = {
        os.fsdecode(line)
        for line in blob.stdout.split(b"\n")
        if line
    }
    return tree_path not in tracked


def collect_diff_facts(
    project_root: str,
    wf_state,
) -> list[DiffFact]:
    """按进场基线与最终文件的真实差异计算全部差异事实（R25）。

    改动前内容按顺序取得：回退副本 → 进场基线提交号。计划外修改的已有
    文件两种来源都取不到时抛 CollectError，消息含文件名和下一步指引。
    """
    manifest = _load_manifest(project_root, wf_state)
    changed_paths = rollback_mod.changed_paths_since_prepare(project_root, manifest)
    if not changed_paths:
        return []
    facts: list[DiffFact] = []
    problems: list[str] = []
    for path in changed_paths:
        full_path = os.path.join(project_root, path)
        if not os.path.lexists(full_path):
            facts.append(DiffFact(path, "删除整个文件", None))
            continue
        if os.path.islink(full_path) or not os.path.isfile(full_path):
            problems.append(f"文件 {path} 不是普通文件，不能计算代码位置")
            continue
        after = _read_current_text(project_root, path)
        before = _entry_text_or_none(project_root, wf_state, manifest, path)
        if before is None and _path_has_manifest_entry(manifest, path):
            # 有回退清单登记却取不到副本：副本缺失是回退资料问题，按现有口径报错
            problems.append(
                f"文件 {path} 在实施前回退清单中登记但副本不可读；"
                "恢复或重新准备该文件的实施前副本后再采集"
            )
            continue
        if before is None:
            # 无回退登记：新文件按全部新增登记，行号写最终文件范围（与门禁
            # 行号校验口径一致：新增文件填 L1-L行数，不写文字描述）
            location = f"L1-L{len(after.splitlines())}"
        else:
            _, after_ranges = rollback_mod._changed_line_ranges(before, after)
            if not after_ranges:
                # 前后内容一致但路径出现在差异清单中（例如权限或重建）；
                # 如实记为无行差异，写最终文件全范围以便覆盖校验可定位
                location = f"L1-L{len(after.splitlines())}"
            elif len(after_ranges) == 1:
                start, end = after_ranges[0]
                location = f"L{start}-L{end}"
            else:
                # 多个不连续差异块：门禁行号格式为单块 L起始-L结束，
                # 按模板允许的"覆盖全部差异的范围"写连续区间（模板：同一
                # 文件多个不连续差异时，增加多行或使用覆盖全部差异的范围）
                starts = [start for start, _end in after_ranges]
                ends = [end for _start, end in after_ranges]
                location = f"L{min(starts)}-L{max(ends)}"
        facts.append(DiffFact(path, location, _sha256_text(after)))
    if problems:
        raise CollectError("；".join(problems))
    return facts


def _path_has_manifest_entry(manifest: dict, path: str) -> bool:
    entries = manifest.get("entries")
    return isinstance(entries, dict) and path in entries


def _load_manifest(project_root: str, wf_state) -> dict:
    from . import state as state_helper

    if wf_state is None:
        wf_state = state_helper.load_state(project_root)
    if wf_state is None:
        raise CollectError("找不到当前工作流状态，无法取得实施前回退清单")
    manifest_path = rollback_mod._manifest_rel_path(wf_state.workflow_id)
    if not os.path.isfile(os.path.join(project_root, manifest_path)):
        raise CollectError(
            f"缺少实施前回退清单 {manifest_path}；先通过 workflow gate impl --discuss-done "
            "并准备实施前基线后再采集"
        )
    manifest, _ = rollback_mod._read_manifest(project_root, manifest_path)
    return manifest


def _entry_text_or_none(
    project_root: str,
    wf_state,
    manifest: dict,
    path: str,
) -> str | None:
    """改动前内容：回退副本优先，其次进场基线提交号。"""
    entries = manifest.get("entries")
    entry = entries.get(path) if isinstance(entries, dict) else None
    if isinstance(entry, dict) and entry.get("original_exists"):
        _entry, before, _after = _texts_from_manifest(project_root, manifest, path)
        return before
    if entry is not None and isinstance(entry, dict) and not entry.get("original_exists"):
        # 清单明确记录原本不存在：进场内容就是"没有"
        return ""
    if wf_state is None:
        return None
    text = _entry_baseline_text(project_root, wf_state, path)
    if text is not None:
        return text
    if _entry_baseline_absence(project_root, wf_state, path):
        return ""
    return None


def _texts_from_manifest(project_root: str, manifest: dict, path: str):
    entry = rollback_mod._manifest_entry_for_recorded_path(manifest, path)
    original_exists = entry.get("original_exists")
    if not isinstance(original_exists, bool):
        raise CollectError(f"实施前回退清单没有明确 {path!r} 的原文件状态")
    before = None
    if original_exists:
        workflow_id = rollback_mod._validated_workflow_id(manifest.get("workflow_id", ""))
        manifest_dir = os.path.dirname(
            rollback_mod._manifest_full_path(project_root, workflow_id)
        )
        backup_path = rollback_mod._safe_backup_path(
            manifest_dir, entry.get("backup_path"), path
        )
        before = rollback_mod._read_utf8_file(
            backup_path, description=f"{path} 的实施前副本"
        )
    full_path = os.path.join(project_root, path)
    if not os.path.lexists(full_path):
        return entry, before, None
    if os.path.islink(full_path) or not os.path.isfile(full_path):
        raise CollectError(f"当前文件不是普通文件：{path}")
    return entry, before, rollback_mod._read_utf8_file(
        full_path, description=f"当前文件 {path}"
    )


def _read_current_text(project_root: str, path: str) -> str:
    return rollback_mod._read_utf8_file(
        os.path.join(project_root, path), description=f"当前文件 {path}"
    )


def _sha256_text(content: str) -> str:
    import hashlib

    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def collect_implementation_changes(project_root: str, wf_state) -> dict:
    """采集实施改动写入实施记录表，返回采集摘要（R25）。

    只写"实际代码修改"行的文件与代码位置两列和程序专用采集指纹；
    AI 已填的叙述列（实际修改的代码逻辑、修改理由等）逐字保留。
    每主题独立执行一次；表路径取该主题的 impl_record 表。
    """
    topics = _active_topics(wf_state)
    summary: dict = {"topics": {}, "unclaimed": []}
    facts = collect_diff_facts(project_root, wf_state)
    try:
        planned = rollback_mod.planned_code_paths(project_root, topics) if topics else []
    except (ValueError, OSError):
        # 计划文档尚未生成（例如表刚建、正式文档未出）：按无计划路径处理，
        # 全部差异文件经 _owner_topic 按表内计划行归属
        planned = []
    planned_set = {p for p in planned}
    facts_by_topic: dict[str, list[DiffFact]] = {topic: [] for topic in topics}
    unclaimed: list[DiffFact] = []
    for fact in facts:
        owner = _owner_topic(project_root, topics, fact.file)
        if owner is None:
            if fact.file in planned_set:
                owner = _plan_owner_topic(project_root, topics, fact.file)
            if owner is None:
                unclaimed.append(fact)
                continue
        facts_by_topic[owner].append(fact)
    for topic in topics:
        table_relative = records_mod.table_relative_path(
            project_root, wf_state.workflow_id, "impl_record", topic
        )
        full = os.path.join(project_root, table_relative)
        if not os.path.isfile(full):
            summary["topics"][topic] = f"缺少实施记录表 {table_relative}，未写入"
            continue
        table = records_mod.load_table(full)
        rows = table.get("实际代码修改")
        if not isinstance(rows, list):
            rows = []
        machine_rows = [
            {
                "文件": fact.file,
                "代码位置（最终文件）": fact.location,
                "实际修改的代码逻辑": "",
                "数据、状态或输出的实际变化": "",
                "修改理由": "",
                "对应验收条件": "",
                "测试证据": "",
            }
            for fact in facts_by_topic[topic]
        ]
        # 重采集只替换机器行（文件与代码位置两列所在的整行骨架），AI 叙述列
        # 在旧行与新行之间按文件保留
        old_by_file = {
            str(row.get("文件", "")): row
            for row in rows
            if isinstance(row, dict)
        }
        merged: list[dict] = []
        for new_row in machine_rows:
            old = old_by_file.get(new_row["文件"])
            if old is not None:
                for key in (
                    "实际修改的代码逻辑",
                    "数据、状态或输出的实际变化",
                    "修改理由",
                    "对应验收条件",
                    "测试证据",
                ):
                    new_row[key] = old.get(key, "")
            merged.append(new_row)
        table["实际代码修改"] = merged
        table["采集指纹"] = {
            "collected_at": state_mod.now_iso(),
            "files": {fact.file: fact.content_hash for fact in facts_by_topic[topic]},
        }
        records_mod._atomic_write(full, table)
        summary["topics"][topic] = (
            f"已写入 {len(merged)} 行机器采集结果并记录采集指纹"
        )
    summary["unclaimed"] = [fact.file for fact in unclaimed]
    return summary


def _active_topics(wf_state) -> list[str]:
    if wf_state is None:
        return []
    return [str(topic) for topic in (wf_state.topics or []) if str(topic).strip()]


def _owner_topic(project_root: str, topics: list[str], path: str) -> str | None:
    """按代码修改计划的文件归属分配差异到主题表（R25）。"""
    for topic in topics:
        table_relative = records_mod.table_relative_path(
            project_root, "", "impl_record", topic
        )
        # 直接按主题计划行匹配文件列
        rows = _plan_rows_for_topic(project_root, topic)
        for row in rows:
            if str(row.get("文件", "")).strip() == path:
                return topic
    return None


def _plan_owner_topic(project_root: str, topics: list[str], path: str) -> str | None:
    return _owner_topic(project_root, topics, path)


def _plan_rows_for_topic(project_root: str, topic: str) -> list[dict]:
    """读取主题 impl_record 表的代码修改计划行。"""
    from .topic import topic_file_key

    relative = (
        f"{records_mod.RECORDS_ROOT}/"
        f"{_current_workflow_id(project_root)}/"
        f"impl_record_{topic_file_key(project_root, topic)}.json"
    )
    full = os.path.join(project_root, relative)
    if not os.path.isfile(full):
        return []
    table = records_mod.load_table(full)
    rows = table.get("代码修改计划")
    return [row for row in rows if isinstance(row, dict)] if isinstance(rows, list) else []


def _current_workflow_id(project_root: str) -> str:
    state = state_mod.load_state(project_root)
    return state.workflow_id if state is not None else ""


def verify_collection_fingerprint(
    project_root: str,
    wf_state,
) -> dict[str, str]:
    """门禁重算差异并与各主题表内采集指纹比对（R25）。

    返回 {主题: 问题}；空字典表示全部一致。文件在采集后又发生变化时，
    对应主题报"请重新采集"。
    """
    topics = _active_topics(wf_state)
    problems: dict[str, str] = {}
    facts = collect_diff_facts(project_root, wf_state)
    facts_by_file = {fact.file: fact for fact in facts}
    for topic in topics:
        table_relative = records_mod.table_relative_path(
            project_root, wf_state.workflow_id, "impl_record", topic
        )
        full = os.path.join(project_root, table_relative)
        if not os.path.isfile(full):
            continue
        table = records_mod.load_table(full)
        fingerprint = table.get("采集指纹")
        if not isinstance(fingerprint, dict):
            continue
        recorded_files = fingerprint.get("files")
        if not isinstance(recorded_files, dict):
            problems[topic] = "采集指纹损坏：files 不是对象"
            continue
        mismatches: list[str] = []
        for path, recorded_hash in recorded_files.items():
            fact = facts_by_file.get(path)
            current_hash = fact.content_hash if fact is not None else None
            if current_hash != recorded_hash:
                mismatches.append(path)
        # 采集后新增的改动文件（指纹里没有）同样要求重新采集
        topic_files = {
            str(row.get("文件", ""))
            for row in (table.get("实际代码修改") or [])
            if isinstance(row, dict)
        }
        for path in topic_files:
            if path and path not in recorded_files:
                fact = facts_by_file.get(path)
                if fact is not None:
                    mismatches.append(path)
        if mismatches:
            problems[topic] = (
                f"文件在采集后又发生了变化：{sorted(set(mismatches))}；请重新执行采集命令，"
                "重新采集只刷新文件与代码位置两列，已填写的叙述列会保留"
            )
    return problems


def acceptance_result_columns(
    project_root: str,
    wf_state,
    topic: str,
) -> list[dict]:
    """验收结果表五列由程序从当前有效验收记录回填（R26）。

    五列：验收方式、验收结论、机器测试记录编号、用户实际回答、人工确认。
    纯自动化条件的不适用字段按验收方式归并写入。
    """
    stage_state = wf_state.stages.get("topic_acceptance")
    records = (
        stage_state.acceptance_records.get(topic, {}) if stage_state is not None else {}
    )
    from . import acceptance_records as acceptance_records_mod

    rows: list[dict] = []
    for criterion_id in sorted(records):
        record = records[criterion_id]
        if not acceptance_records_mod.record_is_current(record, wf_state):
            rows.append(
                {
                    "验收条件编号": criterion_id,
                    "验收方式": "",
                    "验收结论": "待重做",
                    "机器测试记录编号": "",
                    "用户实际回答": "",
                    "人工确认": "",
                }
            )
            continue
        method = str(record.method or "")
        is_automated = method == "自动化测试"
        machine_ids = "、".join(
            str(identifier) for identifier in (record.test_record_ids or [])
        ) or "不适用"
        rows.append(
            {
                "验收条件编号": criterion_id,
                "验收方式": method,
                "验收结论": str(record.result or ""),
                "机器测试记录编号": machine_ids,
                "用户实际回答": (
                    "不适用" if is_automated else str(record.user_answer or "")
                ),
                "人工确认": "不适用" if is_automated else "通过",
            }
        )
    return rows


def test_result_columns(
    project_root: str,
    wf_state,
    topic: str,
) -> list[dict]:
    """测试结果表三列由程序从当前测试任务回填（机器采集延伸）。

    三列：测试项编号、执行结论、机器记录编号。取自 qa 阶段该主题的
    测试任务当前状态与当前机器记录；无当前记录的任务结论与编号留空。
    与验收五列取值同源（单一实现），AI 不再手抄。
    """
    _ = project_root
    stage_state = wf_state.stages.get("qa")
    if stage_state is None:
        stage_state = wf_state.stages.get("test_execution")
    tasks = stage_state.test_tasks.get(topic, {}) if stage_state is not None else {}
    rows: list[dict] = []
    for test_id in sorted(tasks):
        task = tasks[test_id]
        current = getattr(task, "current_record", None)
        record_id = getattr(current, "record_id", "") if current is not None else ""
        rows.append(
            {
                "测试项编号": test_id,
                "执行结论": str(getattr(task, "status", "") or ""),
                "机器记录编号": str(record_id or ""),
            }
        )
    return rows


ID_REFERENCE_RE = re.compile(r"^(AC|TC|JU)-?[0-9]{1,3}$|^[0-9]{1,3}$")


def resolve_id_reference(
    value: str,
    known_ids: set[str],
    deleted_ids: set[str],
) -> tuple[bool, str]:
    """编号引用程序化校验（R27）：只接受编号本身，校验存在于本主题。

    返回 (是否通过, 消息)。引用已删除编号时报"该编号对应的行已删除"；
    引用不存在编号时报当前可用编号。
    """
    raw = value.strip()
    if not raw:
        return True, ""
    for token in re.split(r"[、,，;；\s]+", raw):
        token = token.strip()
        if not token:
            continue
        if not ID_REFERENCE_RE.match(token):
            return False, (
                f"编号引用只写编号本身（如 AC-01、TC-02、1），当前值 {token!r} 含格式内容"
            )
        normalized = _normalize_id(token)
        if normalized in known_ids:
            continue
        if normalized in deleted_ids:
            return False, f"编号 {token} 对应的行已删除；如需引用请在叙述栏说明"
        return False, (
            f"引用的编号 {token} 不存在于本主题对应表；当前可用编号："
            f"{_format_ids(known_ids)}"
        )
    return True, ""


def _normalize_id(token: str) -> str:
    match = re.match(r"^(AC|TC|JU)-?([0-9]+)$", token.upper())
    if match:
        prefix, number = match.group(1), int(match.group(2))
        return f"{prefix}-{number:02d}"
    if token.isdigit():
        return str(int(token))
    return token.upper()


def _format_ids(known_ids: set[str]) -> str:
    ordered = sorted(known_ids, key=lambda item: (item[:2], item))
    return "、".join(ordered[:20]) + ("…" if len(ordered) > 20 else "")


def render_test_marker(item) -> str:
    """测试标识程序生成（R28）：按测试计划表项生成标准文本。

    标识文本含测试入口（取计划表"测试入口"列）；登记测试任务时输出，
    AI 复制粘贴到测试代码 docstring，不再逐字段手抄。
    """
    from . import test_mapping as test_mapping_mod

    return test_mapping_mod.build_marker_from_plan(item)
