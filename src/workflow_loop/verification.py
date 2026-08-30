import configparser
import copy
import hashlib
import json
import os
import re
import subprocess
import tomllib
from dataclasses import asdict, dataclass

from .project import load_project
from . import artifact_paths as artifact_paths_mod
from .state import (
    RecoveryContext,
    RegressionTestState,
    WorkflowState,
    StageState,
    GateState,
    ValidationCredential,
    load_state,
    now_iso,
)
from .test_mapping import (
    automated_test_items,
    automated_topics,
    planned_test_source_paths,
    test_item_path_mapping,
)
from . import test_entry as test_entry_mod
from .topic import candidate_topics, list_acceptance_index_topics, topic_paths
from . import traceability as traceability_mod
from . import acceptance_records as acceptance_records_mod
from . import snapshots as snapshots_mod
from . import diagnostics as diagnostics_mod


# 产品总说明 功能清单中的本地 Markdown 链接
# 只接受 spec/ 下的中文 功能_*.md，外部链接和其它文件不算产品功能文档
PRODUCT_FEATURE_LINK_RE = re.compile(
    r"\[[^\]]+\]\((?:\./)?(功能_[^/)#\s]+\.md)(?:#[^)]+)?\)"
)


def hash_text(content: str) -> str:
    """计算 UTF-8 文本的 SHA256，供阶段材料和状态内容绑定使用。"""
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


VALIDATION_CREDENTIAL_RULES_VERSION = "4"
PENDING_SPIKE_ASSETS_META_KEY = "pending_spike_assets"


def _canonical_hash(value: object) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _existing_files_under(project_root: str, relative_directory: str) -> list[str]:
    """展开当前阶段明确拥有的目录，不扫描其它工作流目录。"""
    full_directory = os.path.join(project_root, relative_directory)
    if not os.path.isdir(full_directory) or os.path.islink(full_directory):
        return []
    paths: list[str] = []
    for root, directories, files in os.walk(full_directory):
        directories[:] = sorted(
            directory
            for directory in directories
            if not os.path.islink(os.path.join(root, directory))
        )
        for filename in sorted(files):
            full_path = os.path.join(root, filename)
            if os.path.islink(full_path) or not os.path.isfile(full_path):
                continue
            paths.append(os.path.relpath(full_path, project_root).replace(os.sep, "/"))
    return paths


def _spike_asset_files_hash(project_root: str, state: WorkflowState) -> str:
    """绑定当前工作流穿刺目录的结构和普通文件内容，不跟随符号链接。"""

    # 复用穿刺目录的编号校验，避免状态中的工作流编号变成任意路径。
    from .stages.base import expected_spike_asset_path

    sentinel = expected_spike_asset_path(state.workflow_id, "credential_snapshot")
    relative_root = os.path.dirname(sentinel).replace(os.sep, "/")
    full_root = os.path.join(project_root, *relative_root.split("/"))

    current = project_root
    for part in relative_root.split("/"):
        current = os.path.join(current, part)
        if os.path.lexists(current) and os.path.islink(current):
            raise ValueError(f"穿刺资产快照路径不能经过符号链接：{relative_root}")

    if not os.path.lexists(full_root):
        return _canonical_hash([])
    if not os.path.isdir(full_root):
        raise ValueError(f"当前工作流穿刺资产根路径不是普通目录：{relative_root}")

    facts: list[dict[str, str]] = []
    for root, directories, files in os.walk(full_root, topdown=True, followlinks=False):
        safe_directories: list[str] = []
        for directory in sorted(directories):
            full_path = os.path.join(root, directory)
            relative_path = os.path.relpath(full_path, project_root).replace(os.sep, "/")
            if os.path.islink(full_path):
                raise ValueError(f"穿刺资产快照不接受符号链接目录：{relative_path}")
            if not os.path.isdir(full_path):
                raise ValueError(f"穿刺资产快照发现非普通目录：{relative_path}")
            safe_directories.append(directory)
            facts.append({"path": relative_path, "type": "directory"})
        directories[:] = safe_directories

        for filename in sorted(files):
            full_path = os.path.join(root, filename)
            relative_path = os.path.relpath(full_path, project_root).replace(os.sep, "/")
            if os.path.islink(full_path) or not os.path.isfile(full_path):
                raise ValueError(f"穿刺资产快照只接受普通文件：{relative_path}")
            facts.append(
                {
                    "path": relative_path,
                    "type": "file",
                    "content_hash": _hash_file_path(full_path),
                }
            )
    return _canonical_hash(sorted(facts, key=lambda item: item["path"]))


def _pending_spike_assets_hash(state: WorkflowState) -> str:
    """绑定门2生成的待确认登记，防止门2与门3之间被替换。"""

    pending = state.meta.get(PENDING_SPIKE_ASSETS_META_KEY)
    if not isinstance(pending, dict):
        raise ValueError("缺少当前第二道门生成的待确认穿刺资产登记")
    if pending.get("workflow_id") != state.workflow_id:
        raise ValueError("待确认穿刺资产登记不属于当前工作流")
    if not isinstance(pending.get("items"), list):
        raise ValueError("待确认穿刺资产登记缺少 items（登记项目）数组")
    return _canonical_hash(pending)


def stage_responsibility_paths(
    project_root: str,
    state: WorkflowState,
    stage_name: str,
) -> list[str]:
    """返回第二道门真正负责的文件，不把所有下游 Markdown 混进来。"""
    topics = state.topics or ([state.topic] if state.topic else [])
    if not topics:
        # 主题尚未写入 state.topics 时，从 topic_relations 工作记录表读（断言三：表为唯一输入）
        from . import records as records_mod
        _rel = records_mod.table_relative_path(project_root, state.workflow_id, "topic_relations", "")
        if records_mod.table_exists(project_root, _rel):
            _ttable = records_mod.load_table(os.path.join(project_root, _rel))
            topics = [
                str(r.get("验收主题", "")).strip()
                for r in _ttable.get("主题关系", [])
                if str(r.get("验收主题", "")).strip()
            ]
    paths: set[str] = set()

    if stage_name == "spec":
        _product_hash, product_paths = compute_product_design_hash(project_root)
        paths.update(product_paths)
    elif stage_name in {"code_design", "revise_code_design", "project_design_init"}:
        paths.add(artifact_paths_mod.CODE_DESIGN_DOC)
    elif stage_name == "spike":
        paths.add(artifact_paths_mod.SPIKE_INDEX_DOC)
        for relative in _existing_files_under(project_root, "spec"):
            if os.path.basename(relative).startswith("穿刺_"):
                paths.add(relative)
    elif stage_name == "acceptance_plan":
        paths.add(artifact_paths_mod.ACCEPTANCE_INDEX_DOC)
        paths.add(artifact_paths_mod.TRACEABILITY_DOC)
        paths.update(topic_paths(project_root, topic)["acceptance_plan"] for topic in topics)
    elif stage_name == "impl":
        paths.add(artifact_paths_mod.IMPL_INDEX_DOC)
        paths.update(topic_paths(project_root, topic)["impl_doc"] for topic in topics)
        from .rollback import planned_code_paths

        try:
            paths.update(planned_code_paths(project_root, topics))
        except (FileNotFoundError, OSError, ValueError):
            pass
    elif stage_name in {"qa", "test_plan", "test_code", "test_execution"}:
        paths.add(artifact_paths_mod.QA_INDEX_DOC)
        for topic in topics:
            topic_files = topic_paths(project_root, topic)
            paths.add(topic_files["test_plan"])
            if topic in automated_topics(project_root, topics):
                paths.add(topic_files["test_result"])
        try:
            paths.update(planned_test_source_paths(project_root, topics))
        except (FileNotFoundError, OSError, ValueError):
            pass
    elif stage_name == "topic_acceptance":
        paths.add(artifact_paths_mod.ACCEPTANCE_INDEX_DOC)
        paths.update(topic_paths(project_root, topic)["acceptance_result"] for topic in topics)
    elif stage_name in {"regression_test", "overall_acceptance"}:
        paths.update((_active_registered_paths(project_root) or []))
        paths.update(topic_paths(project_root, topic)["acceptance_result"] for topic in topics)
    elif stage_name == "update_code_design":
        _product_hash, product_paths = compute_product_design_hash(project_root)
        paths.update(product_paths)
        paths.add(artifact_paths_mod.CODE_DESIGN_DOC)
        paths.update((_active_registered_paths(project_root) or []))

    stage_state = state.stages.get(stage_name)
    if stage_state is not None and not paths:
        for relative in stage_state.artifact_paths:
            full = os.path.join(project_root, relative)
            if os.path.isdir(full):
                paths.update(_existing_files_under(project_root, relative))
            else:
                paths.add(relative)
    return snapshots_mod.normalize_registered_paths(project_root, paths)


def _stage_records_content_hash(
    project_root: str,
    state: WorkflowState,
    stage_name: str,
) -> str | None:
    """当前环节工作记录表的内容哈希（剔除生成文档哈希/路径等程序专用键）。

    R29：门 2 到门 3 之间工作记录表内容变化即凭据失效。只绑定剔除程序专用键
    后的 AI 内容哈希，不复制整份文档正文，避免程序重算文档哈希时误判失效。
    """
    from . import records as records_mod

    kinds = records_mod.stage_table_kinds(stage_name)
    if not kinds:
        return None
    topics = list(state.topics or ([state.topic] if state.topic else []))
    topic_keys = topics + [""]
    seen: set[str] = set()
    digest = hashlib.sha256()
    found = False
    for kind in kinds:
        for topic in topic_keys:
            relative = records_mod.table_relative_path(
                project_root, state.workflow_id, kind, topic
            )
            if relative in seen:
                continue
            full = os.path.join(project_root, relative)
            if not os.path.isfile(full):
                continue
            seen.add(relative)
            try:
                table = records_mod.load_table(full)
            except Exception:
                continue
            content = {
                key: value
                for key, value in table.items()
                if key not in (records_mod.DOC_HASH_KEY, records_mod.GENERATED_DOC_PATH_KEY)
            }
            digest.update(relative.encode("utf-8"))
            digest.update(b"\0")
            digest.update(
                json.dumps(content, ensure_ascii=False, sort_keys=True).encode("utf-8")
            )
            digest.update(b"\0")
            found = True
    return digest.hexdigest() if found else None


def _credential_bound_state(
    project_root: str,
    state: WorkflowState,
    stage_name: str,
) -> dict[str, str | int | float | bool | None]:
    stage_state = state.stages.get(stage_name)
    bound: dict[str, str | int | float | bool | None] = {
        "workflow_id": state.workflow_id,
        "intent": state.intent,
        "stage": stage_name,
        "topics_hash": _canonical_hash(state.topics or ([state.topic] if state.topic else [])),
        "discussion_material_hash": (
            stage_state.discussion_material_hash if stage_state is not None else None
        ),
        "records_content_hash": _stage_records_content_hash(
            project_root, state, stage_name
        ),
    }
    if stage_state is None:
        return bound
    if stage_name == "spike":
        bound.update(
            {
                "pending_spike_assets_hash": _pending_spike_assets_hash(state),
                "spike_asset_files_hash": _spike_asset_files_hash(project_root, state),
            }
        )
    elif stage_name == "impl":
        bound.update(
            {
                "plan_confirmed_hash": stage_state.plan_confirmed_hash,
                "reuse_decision_hash": stage_state.reuse_decision_hash,
            }
        )
        try:
            from .rollback import actual_change_fingerprint

            bound["actual_change_fingerprint"] = actual_change_fingerprint(
                project_root,
                state,
            )
        except (OSError, ValueError):
            bound["actual_change_fingerprint"] = None
    elif stage_name in {"qa", "test_plan", "test_code", "test_execution"}:
        project = load_project(project_root)
        bound.update(
            {
                "scope_confirmed_hash": stage_state.scope_confirmed_hash,
                "test_tasks_hash": _canonical_hash(
                    {
                        topic: {
                            test_id: asdict(task)
                            for test_id, task in sorted(tasks.items())
                        }
                        for topic, tasks in sorted(stage_state.test_tasks.items())
                    }
                ),
                "test_entry_hash": _canonical_hash(
                    project.test_entry if project is not None else {}
                ),
                "impl_hash": state.verification.impl_hash,
            }
        )
        try:
            test_paths, _test_detail = list_actual_test_changes(project_root)
            bound["actual_test_change_fingerprint"] = (
                _canonical_hash(test_paths) if test_paths is not None else None
            )
        except (OSError, ValueError):
            bound["actual_test_change_fingerprint"] = None
    elif stage_name == "topic_acceptance":
        bound["acceptance_records_hash"] = _canonical_hash(
            {
                topic: {
                    criterion_id: asdict(record)
                    for criterion_id, record in sorted(records.items())
                }
                for topic, records in sorted(stage_state.acceptance_records.items())
            }
        )
        bound["test_result_hash"] = state.verification.test_result_hash
    elif stage_name == "regression_test":
        bound["regression_record_hash"] = _canonical_hash(asdict(state.regression_test))
    elif stage_name == "overall_acceptance":
        bound["acceptance_result_hash"] = state.verification.acceptance_result_hash
        bound["regression_result_hash"] = state.verification.regression_test_result_hash
    return bound


def create_validation_credential(
    project_root: str,
    state: WorkflowState,
    stage_name: str,
    result_detail: str,
) -> ValidationCredential:
    """在第二道门完整校验成功后保存可供第三道门比较的责任输入。"""
    paths = stage_responsibility_paths(project_root, state, stage_name)
    snapshot = snapshots_mod.collect_snapshot(project_root, paths)
    bound_files = {item.path: item.to_dict() for item in snapshot.files}
    bound_state = _credential_bound_state(project_root, state, stage_name)
    stage_state = state.stages.get(stage_name)
    material_hash = stage_state.discussion_material_hash if stage_state else None
    return ValidationCredential(
        workflow_id=state.workflow_id,
        stage=stage_name,
        rules_version=VALIDATION_CREDENTIAL_RULES_VERSION,
        material_hash=material_hash,
        bound_files=bound_files,
        bound_state=bound_state,
        result=True,
        report_hash=hash_text(result_detail),
        result_hash=_canonical_hash(
            {
                "files": snapshot.to_dict(),
                "state": bound_state,
                "report_hash": hash_text(result_detail),
            }
        ),
        created_at=now_iso(),
    )


def compare_validation_credential_report(
    project_root: str,
    state: WorkflowState,
    stage_name: str,
) -> diagnostics_mod.ValidationReport:
    """返回第三道门凭据比较的逐项事实，不重新执行完整校验或测试进程。"""
    gate_name = "用户确认前凭据比较"
    impact = "第二道门的通过事实不能复用，当前阶段不能确认"
    retry_action = "重新执行本阶段第二道门，生成并保存与当前责任输入一致的校验凭据"
    report = diagnostics_mod.ValidationReport(stage=stage_name, gate=gate_name)

    def add_error(
        *,
        check_id: str,
        location: str,
        expected: str,
        actual: str,
        evidence: str,
        next_action: str = retry_action,
    ) -> None:
        report.add_error(
            check_id=check_id,
            location=location,
            expected=expected,
            actual=actual,
            evidence=evidence,
            impact=impact,
            next_action=next_action,
        )

    stage_state = state.stages.get(stage_name)
    credential = stage_state.validation_credential if stage_state is not None else None
    if credential is None:
        add_error(
            check_id=f"credential.{stage_name}.missing",
            location=f".workflow_loop/state.json#stages.{stage_name}.validation_credential",
            expected="存在当前阶段第二道门生成的校验凭据",
            actual="缺少第二道门校验凭据",
            evidence="当前阶段状态中的 validation_credential（校验凭据）为空",
        )
        return report

    if credential.workflow_id != state.workflow_id:
        add_error(
            check_id=f"credential.{stage_name}.workflow_id",
            location=f".workflow_loop/state.json#stages.{stage_name}.validation_credential.workflow_id",
            expected=f"当前工作流编号 {state.workflow_id!r}",
            actual=f"凭据工作流编号 {credential.workflow_id!r}",
            evidence="第二道门凭据所属工作流与当前活动工作流不同",
        )
    if credential.stage != stage_name:
        add_error(
            check_id=f"credential.{stage_name}.stage",
            location=f".workflow_loop/state.json#stages.{stage_name}.validation_credential.stage",
            expected=f"当前阶段 {stage_name!r}",
            actual=f"凭据阶段 {credential.stage!r}",
            evidence="第二道门凭据不是在当前阶段生成",
        )
    if credential.rules_version != VALIDATION_CREDENTIAL_RULES_VERSION:
        add_error(
            check_id=f"credential.{stage_name}.rules_version",
            location=f".workflow_loop/state.json#stages.{stage_name}.validation_credential.rules_version",
            expected=f"当前校验规则版本 {VALIDATION_CREDENTIAL_RULES_VERSION!r}",
            actual=f"凭据校验规则版本 {credential.rules_version!r}",
            evidence="第二道门凭据使用的校验规则版本已经不是当前版本",
        )
    if not credential.result:
        add_error(
            check_id=f"credential.{stage_name}.result",
            location=f".workflow_loop/state.json#stages.{stage_name}.validation_credential.result",
            expected="凭据记录第二道门已通过",
            actual=f"凭据 result（第二道门结果）为 {credential.result!r}",
            evidence="当前凭据没有保存可复用的第二道门通过事实",
        )

    current_paths = stage_responsibility_paths(project_root, state, stage_name)
    previous_paths = sorted(credential.bound_files)
    added_paths = sorted(set(current_paths) - set(previous_paths))
    removed_paths = sorted(set(previous_paths) - set(current_paths))
    for path in added_paths:
        add_error(
            check_id=f"credential.{stage_name}.responsibility_path.added:{path}",
            location=path,
            expected="第二道门和确认时的责任文件集合一致",
            actual="责任文件集合新增",
            evidence=f"凭据文件集合不含 {path!r}，当前责任文件集合包含它",
        )
    for path in removed_paths:
        add_error(
            check_id=f"credential.{stage_name}.responsibility_path.removed:{path}",
            location=path,
            expected="第二道门和确认时的责任文件集合一致",
            actual="责任文件集合移除",
            evidence=f"凭据文件集合包含 {path!r}，当前责任文件集合不再包含它",
        )

    current_snapshot = snapshots_mod.collect_snapshot(
        project_root,
        sorted(set(current_paths) | set(previous_paths)),
    )
    previous_snapshot = snapshots_mod.snapshot_from_dict(
        {
            "files": list(credential.bound_files.values()),
        }
    )
    differences = snapshots_mod.compare_snapshots(previous_snapshot, current_snapshot)
    for kind, label in (
        ("added", "新增"),
        ("modified", "修改"),
        ("deleted", "删除"),
        ("type_changed", "类型变化"),
    ):
        for path in differences[kind]:
            # 集合新增或移除和同一路径的快照新增/删除是同一个根因；只保留
            # 范围事实，避免 AI 看见两个看似不同的修复动作。
            if (kind == "added" and path in added_paths) or (
                kind == "deleted" and path in removed_paths
            ):
                continue
            add_error(
                check_id=f"credential.{stage_name}.file.{kind}:{path}",
                location=path,
                expected="责任文件的类型和内容与第二道门保存的快照一致",
                actual=f"责任文件{label}",
                evidence=f"逐文件快照比较结果：{kind}={path}",
            )

    current_state = _credential_bound_state(project_root, state, stage_name)
    for key in sorted(set(credential.bound_state) | set(current_state)):
        if credential.bound_state.get(key) != current_state.get(key):
            add_error(
                check_id=f"credential.{stage_name}.state:{key}",
                location=(
                    f".workflow_loop/state.json#stages.{stage_name}."
                    f"validation_credential.bound_state.{key}"
                ),
                expected=f"第二道门记录的责任状态 {credential.bound_state.get(key)!r}",
                actual=f"当前责任状态 {current_state.get(key)!r}",
                evidence=(
                    f"责任状态 {key} 已变化："
                    f"凭据={credential.bound_state.get(key)!r}，"
                    f"当前={current_state.get(key)!r}"
                ),
            )
    return report


def compare_validation_credential(
    project_root: str,
    state: WorkflowState,
    stage_name: str,
) -> tuple[bool, str]:
    """兼容旧调用者的字符串入口；门禁命令应使用结构化报告入口。"""
    report = compare_validation_credential_report(project_root, state, stage_name)
    if report.passed:
        stage_state = state.stages.get(stage_name)
        credential = stage_state.validation_credential if stage_state is not None else None
        result_hash = credential.result_hash if credential is not None else ""
        return True, f"第二道门凭据有效：{result_hash}"
    return False, diagnostics_mod.format_diagnostics(report)


def _hash_file_path(full_path: str) -> str:
    digest = hashlib.sha256()
    with open(full_path, "rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


# 计算单个文件的 SHA256 哈希
# 用于 Verification Invalidation：绑定上游内容，检测变化
# 文件不存在时返回 None（还没产出过的 stage）
def compute_file_hash(project_root: str, rel_path: str) -> str | None:
    # 拼出文件的完整路径（项目根 + 相对路径）
    full_path = os.path.join(project_root, rel_path)
    # 文件不存在 → 返回 None
    if not os.path.exists(full_path):
        return None
    return _hash_file_path(full_path)


def compute_file_hashes(
    project_root: str,
    rel_paths: list[str],
) -> dict[str, str | None]:
    """计算一组相对路径的文件哈希，保留当时不存在的文件。"""
    return {
        rel_path: compute_file_hash(project_root, rel_path)
        for rel_path in sorted(set(rel_paths))
    }


def compute_project_file_hashes(
    project_root: str,
    *,
    registered_paths: list[str] | None = None,
) -> dict[str, str]:
    """记录实施阶段可能修改的代码、脚本和配置，用于发现计划外改动。

    不把 IDE 工作区、说明文档等与实现无关的文件算作代码变化。实施计划明确
    列出的其它类型文件由回退清单单独比较，因此不会漏掉计划内的资源文件。
    """
    if registered_paths is None:
        active_paths = _active_registered_paths(project_root)
        if active_paths is not None:
            registered_paths = active_paths
    if registered_paths is not None:
        snapshot = snapshots_mod.collect_snapshot(project_root, registered_paths)
        return {
            item.path: item.content_hash
            for item in snapshot.files
            if item.exists and item.file_type == "file" and item.content_hash
        }

    return compute_complete_implementation_file_hashes(project_root)


def compute_complete_implementation_file_hashes(project_root: str) -> dict[str, str]:
    """扫描完整实施范围，不受活动工作流登记路径收窄。"""

    always_excluded_roots = {
        ".git",
        ".workflow_loop",
        ".venv",
        "node_modules",
        "__pycache__",
        ".pytest_cache",
        "dist",
        "build",
        ".next",
        ".idea",
        ".vscode",
    }
    managed_document_roots = {
        "spec",
        "acceptance",
        "qa",
        "impl",
        "bug",
    }
    excluded_files = {artifact_paths_mod.TRACEABILITY_DOC}
    _, test_entry_path = _project_test_entry(project_root)
    hashes: dict[str, str] = {}
    for root, dirs, files in os.walk(project_root):
        excluded_here = set(always_excluded_roots)
        if os.path.realpath(root) == os.path.realpath(project_root):
            excluded_here.update(managed_document_roots)
        dirs[:] = [directory for directory in dirs if directory not in excluded_here]
        for filename in files:
            relative_path = os.path.relpath(os.path.join(root, filename), project_root)
            normalized = relative_path.replace(os.sep, "/")
            if normalized in excluded_files:
                continue
            if not is_implementation_related_path(normalized, test_entry_path):
                continue
            full_path = os.path.join(project_root, relative_path)
            if os.path.islink(full_path) or not os.path.isfile(full_path):
                continue
            hashes[normalized] = _hash_file_path(full_path)
    return dict(sorted(hashes.items()))


def is_test_related_path(project_root: str, relative_path: str) -> bool:
    """判断文件是否需要在 test_code 前保存真实内容。"""
    normalized = relative_path.replace(os.sep, "/")
    filename = os.path.basename(normalized)
    _, test_entry_path = _project_test_entry(project_root)
    suffix = os.path.splitext(filename)[1].lower()
    return (
        _is_test_path(normalized)
        or _is_standalone_test_config(normalized, test_entry_path)
        or filename in CONFIG_NAMES
        or suffix in CONFIG_SUFFIXES
    )


def compute_test_related_file_hashes(project_root: str) -> dict[str, str]:
    return {
        path: content_hash
        for path, content_hash in compute_project_file_hashes(project_root).items()
        if is_test_related_path(project_root, path)
    }


def _git_changed_paths(project_root: str) -> tuple[list[str] | None, str]:
    """读取 Git 当前提交到工作区的路径差异，包含未跟踪文件。"""

    environment = dict(os.environ)
    for variable in (
        "GIT_DIR",
        "GIT_WORK_TREE",
        "GIT_INDEX_FILE",
        "GIT_OBJECT_DIRECTORY",
        "GIT_ALTERNATE_OBJECT_DIRECTORIES",
        "GIT_COMMON_DIR",
        "GIT_NAMESPACE",
    ):
        environment.pop(variable, None)
    environment["GIT_OPTIONAL_LOCKS"] = "0"

    def run_git(*arguments: str) -> subprocess.CompletedProcess[str] | None:
        try:
            return subprocess.run(
                ["git", *arguments],
                cwd=project_root,
                env=environment,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
                timeout=10,
            )
        except (OSError, subprocess.TimeoutExpired):
            return None

    root = run_git("rev-parse", "--show-toplevel")
    if root is None or root.returncode != 0:
        return None, "当前项目不是可读取的 Git 工作树"
    diff = run_git("diff", "--name-only", "-z", "HEAD", "--")
    untracked = run_git("ls-files", "--others", "--exclude-standard", "-z")
    if (
        diff is None
        or untracked is None
        or diff.returncode != 0
        or untracked.returncode != 0
    ):
        return None, "无法读取 Git 当前提交、暂存区、工作区和未跟踪文件差异"
    paths = sorted(
        {
            path.replace("\\", "/")
            for output in (diff.stdout, untracked.stdout)
            for path in output.split("\0")
            if path
        }
    )
    return paths, "已读取 Git 当前提交、暂存区、工作区和未跟踪文件差异"


def list_actual_test_changes(project_root: str) -> tuple[list[str] | None, str]:
    """读取 Git 当前可见的测试代码、夹具、辅助脚本和测试配置变化。

    该清单用于 QA（测试验证）展示和定向重查，不是测试计划白名单。没有
    可读取的 Git 工作树时返回 ``None``，调用方必须显示限制而不是猜测。
    """

    candidates, detail = _git_changed_paths(project_root)
    if candidates is None:
        return None, detail
    selected: list[str] = []
    project = load_project(project_root)
    referenced_scripts = set()
    if project is not None and isinstance(project.test_entry, dict):
        referenced_scripts = set(test_entry_mod.referenced_project_scripts(project.test_entry))
    for path in sorted(candidates):
        normalized = path.strip().replace("\\", "/")
        if not normalized or normalized.startswith(".workflow_loop/"):
            continue
        filename = os.path.basename(normalized)
        suffix = os.path.splitext(filename)[1].lower()
        if (
            _is_test_path(normalized)
            or _is_standalone_test_config(normalized, _project_test_entry(project_root)[1])
            or normalized in referenced_scripts
            or filename in CONFIG_NAMES
            or suffix in CONFIG_SUFFIXES
        ):
            selected.append(normalized)
    return selected, f"{detail}；已筛出实际测试改动"


def registered_code_design_paths(project_root: str) -> list[str]:
    """读取代码架构表中明确写在“代码位置”列的文件，不扫描项目。"""
    full_path = os.path.join(project_root, artifact_paths_mod.CODE_DESIGN_DOC)
    if not os.path.isfile(full_path):
        return []
    with open(full_path, "r", encoding="utf-8") as stream:
        lines = stream.read().splitlines()
    paths: list[str] = []
    index = 0
    while index < len(lines):
        line = lines[index].strip()
        if not line.startswith("|"):
            index += 1
            continue
        headers = [cell.strip() for cell in line.strip("|").split("|")]
        if "代码位置" not in headers:
            index += 1
            continue
        code_index = headers.index("代码位置")
        index += 1
        while index < len(lines) and lines[index].strip().startswith("|"):
            cells = [cell.strip() for cell in lines[index].strip().strip("|").split("|")]
            index += 1
            if all(re.fullmatch(r"[-:]+", cell) for cell in cells):
                continue
            if len(cells) != len(headers):
                raise ValueError("代码架构设计的代码位置表列数与表头不一致")
            for reference in re.findall(r"`([^`]+)`", cells[code_index]):
                candidate = re.split(r"::|#L?\d+|:\d+$", reference.strip(), maxsplit=1)[0]
                if not candidate or candidate.startswith("-"):
                    continue
                if "/" not in candidate and candidate not in CONFIG_NAMES:
                    continue
                paths.extend(snapshots_mod.normalize_registered_paths(project_root, [candidate]))
        continue
    return sorted(set(paths))


def _active_registered_paths(project_root: str) -> list[str] | None:
    """返回活动轮次明确登记的路径；没有活动轮次时才允许旧式兼容扫描。"""
    state = load_state(project_root)
    if state is None or state.run_status != "active":
        return None
    registered: set[str] = set(registered_code_design_paths(project_root))
    planned = getattr(state.rollback, "planned_paths", None) or []
    if planned:
        registered.update(planned)
    elif state.topics:
        from .rollback import planned_code_paths

        try:
            registered.update(planned_code_paths(project_root, state.topics))
        except FileNotFoundError:
            pass
        except OSError:
            pass
        except ValueError:
            # 实施文档已经存在却无法解析时，不能悄悄回退到全项目扫描。
            if any(
                os.path.exists(os.path.join(project_root, topic_paths(project_root, topic)["impl_doc"]))
                for topic in state.topics
            ):
                raise
    if state.topics:
        from .rollback import recorded_code_paths

        try:
            registered.update(recorded_code_paths(project_root, state.topics))
        except (FileNotFoundError, OSError, ValueError):
            # 实施记录未生成或格式尚未完整时，由实施门禁报告具体问题；
            # 这里不能因读取失败悄悄改用另一套全目录猜测。
            pass
    if state.topics:
        try:
            registered.update(planned_test_source_paths(project_root, state.topics))
        except (FileNotFoundError, OSError, ValueError):
            # 测试计划尚未生成时没有测试登记范围；生成后由对应门禁报告格式错误。
            pass
    project = load_project(project_root)
    if project is not None and isinstance(project.test_entry, dict):
        registered.update(test_entry_mod.referenced_project_scripts(project.test_entry))
    actual_test_paths, _actual_test_detail = list_actual_test_changes(project_root)
    if actual_test_paths is not None:
        registered.update(actual_test_paths)
    return snapshots_mod.normalize_registered_paths(project_root, registered)


def compute_registered_file_snapshot(
    project_root: str,
    *,
    scope: str = "all",
) -> dict[str, object]:
    """保存登记路径的逐文件事实；scope 为 product/test/all。"""
    if scope not in {"product", "test", "all"}:
        raise ValueError(f"未知快照范围：{scope}")
    paths = _active_registered_paths(project_root) or []
    _, test_entry_path = _project_test_entry(project_root)
    if scope != "all":
        selected: list[str] = []
        for path in paths:
            is_test = _is_test_path(path) or _is_standalone_test_config(path, test_entry_path)
            filename = os.path.basename(path)
            suffix = os.path.splitext(filename)[1].lower()
            shared_config = filename in CONFIG_NAMES or suffix in CONFIG_SUFFIXES
            if (
                (scope == "test" and (is_test or shared_config))
                or (scope == "product" and (not is_test or shared_config))
            ):
                selected.append(path)
        paths = selected
    return snapshots_mod.collect_snapshot(project_root, paths).to_dict()


def compute_complete_implementation_file_snapshot(
    project_root: str,
    *,
    scope: str = "all",
) -> dict[str, object]:
    """保存完整实施范围的逐文件事实；只用于 impl 的入场和回退基线。"""
    if scope not in {"product", "test", "all"}:
        raise ValueError(f"未知快照范围：{scope}")
    paths = list(compute_complete_implementation_file_hashes(project_root))
    _, test_entry_path = _project_test_entry(project_root)
    if scope != "all":
        selected: list[str] = []
        for path in paths:
            filename = os.path.basename(path)
            suffix = os.path.splitext(filename)[1].lower()
            is_test = _is_test_path(path) or _is_standalone_test_config(
                path,
                test_entry_path,
            )
            shared_config = filename in CONFIG_NAMES or suffix in CONFIG_SUFFIXES
            if (
                (scope == "test" and (is_test or shared_config))
                or (scope == "product" and (not is_test or shared_config))
            ):
                selected.append(path)
        paths = selected
    return snapshots_mod.collect_snapshot(project_root, paths).to_dict()


def compare_registered_file_snapshot(
    project_root: str,
    baseline: object,
    *,
    scope: str,
) -> dict[str, list[str]]:
    """比较当前登记文件与已保存逐文件基线。"""
    current = snapshots_mod.snapshot_from_dict(
        compute_registered_file_snapshot(project_root, scope=scope)
    )
    if baseline is None:
        return snapshots_mod.compare_snapshots(None, current)
    previous = snapshots_mod.snapshot_from_dict(baseline)
    return snapshots_mod.compare_snapshots(previous, current)


def compare_complete_implementation_file_snapshot(
    project_root: str,
    baseline: object,
    *,
    scope: str,
) -> dict[str, list[str]]:
    """比较完整实施范围，包含基线后新增、删除和修改的文件。"""
    current = snapshots_mod.snapshot_from_dict(
        compute_complete_implementation_file_snapshot(project_root, scope=scope)
    )
    if baseline is None:
        return snapshots_mod.compare_snapshots(None, current)
    previous = snapshots_mod.snapshot_from_dict(baseline)
    return snapshots_mod.compare_snapshots(previous, current)


def format_registered_differences(differences: dict[str, list[str]]) -> str:
    """把逐文件差异变成稳定、可直接显示的中文证据。"""
    labels = {
        "added": "新增",
        "modified": "修改",
        "deleted": "删除",
        "type_changed": "类型变化",
        "not_checked": "未检查（缺少逐文件基线）",
    }
    parts = [
        f"{labels[key]}={sorted(differences.get(key, []))}"
        for key in ("added", "modified", "deleted", "type_changed", "not_checked")
        if differences.get(key)
    ]
    return "；".join(parts) if parts else "登记文件无变化"


def compute_document_snapshot(project_root: str, paths: list[str]) -> dict[str, object]:
    """保存一组明确登记的正式文档事实，不扫描目录。"""
    return snapshots_mod.collect_snapshot(project_root, paths).to_dict()


def _normalized_topic_index_content(
    project_root: str,
    relative_path: str,
    result_column_name: str,
    replacement: str,
) -> str | None:
    """屏蔽索引中由下游阶段回填的结果列，其余单元格仍参与绑定。"""
    full_path = os.path.join(project_root, relative_path)
    if not os.path.isfile(full_path):
        return None
    with open(full_path, "r", encoding="utf-8") as stream:
        lines = stream.read().splitlines(keepends=True)

    normalized: list[str] = []
    result_column: tuple[int, int] | None = None
    for line in lines:
        stripped = line.strip()
        cells = None
        if stripped.startswith("|") and stripped.endswith("|"):
            cells = [cell.strip() for cell in stripped.strip("|").split("|")]

        if (
            cells is not None
            and cells[:3] == ["展示顺序", "验收主题", "前置主题"]
            and result_column_name in cells
        ):
            result_column = (cells.index(result_column_name), len(cells))
            normalized.append(line)
            continue

        if result_column is None or cells is None:
            if cells is None:
                result_column = None
            normalized.append(line)
            continue

        column_index, column_count = result_column
        if len(cells) != column_count:
            result_column = None
            normalized.append(line)
            continue
        if all(re.fullmatch(r"[-:]+", cell) for cell in cells):
            normalized.append(line)
            continue

        cells[column_index] = replacement
        line_ending = line[len(line.rstrip("\r\n")) :]
        normalized.append("| " + " | ".join(cells) + " |" + line_ending)
    return "".join(normalized)


def _normalized_test_plan_index_content(project_root: str) -> str | None:
    """只屏蔽测试执行阶段才会更新的“测试结果”列。"""
    return _normalized_topic_index_content(
        project_root,
        artifact_paths_mod.QA_INDEX_DOC,
        "测试结果",
        "<下游测试结果>",
    )


def _normalized_acceptance_plan_index_content(project_root: str) -> str | None:
    """只屏蔽主题验收阶段才会更新的“主题验收结果”列。"""
    return _normalized_topic_index_content(
        project_root,
        artifact_paths_mod.ACCEPTANCE_INDEX_DOC,
        "主题验收结果",
        "<下游主题验收结果>",
    )


def compute_test_plan_document_snapshot(
    project_root: str,
    topics: str | list[str] | None,
) -> dict[str, object]:
    """保存测试计划事实，但不把下游测试结果链接当成计划内容。"""
    topic_list = normalize_topics(topics)
    paths = [
        artifact_paths_mod.QA_INDEX_DOC,
        *[topic_paths(project_root, topic)["test_plan"] for topic in topic_list],
    ]
    snapshot = snapshots_mod.collect_snapshot(project_root, paths)
    normalized_index = _normalized_test_plan_index_content(project_root)
    facts = []
    for fact in snapshot.files:
        if (
            fact.path == artifact_paths_mod.QA_INDEX_DOC
            and fact.exists
            and fact.file_type == "file"
            and normalized_index is not None
        ):
            facts.append(
                snapshots_mod.FileFact(
                    path=fact.path,
                    exists=True,
                    file_type="file",
                    content_hash=hash_text(normalized_index),
                )
            )
        else:
            facts.append(fact)
    return snapshots_mod.Snapshot(tuple(facts)).to_dict()


def compute_acceptance_plan_document_snapshot(
    project_root: str,
    topics: str | list[str] | None,
) -> dict[str, object]:
    """保存验收计划事实，但不把下游主题验收结果链接当成计划内容。"""
    topic_list = normalize_topics(topics)
    paths = [
        artifact_paths_mod.ACCEPTANCE_INDEX_DOC,
        *[topic_paths(project_root, topic)["acceptance_plan"] for topic in topic_list],
    ]
    snapshot = snapshots_mod.collect_snapshot(project_root, paths)
    normalized_index = _normalized_acceptance_plan_index_content(project_root)
    facts = []
    for fact in snapshot.files:
        if (
            fact.path == artifact_paths_mod.ACCEPTANCE_INDEX_DOC
            and fact.exists
            and fact.file_type == "file"
            and normalized_index is not None
        ):
            facts.append(
                snapshots_mod.FileFact(
                    path=fact.path,
                    exists=True,
                    file_type="file",
                    content_hash=hash_text(normalized_index),
                )
            )
        else:
            facts.append(fact)
    return snapshots_mod.Snapshot(tuple(facts)).to_dict()


def _compare_test_plan_document_snapshot(
    project_root: str,
    baseline: object,
    topics: str | list[str] | None,
) -> dict[str, list[str]]:
    """用与测试计划哈希相同的规则生成逐文件诊断。"""
    if isinstance(baseline, dict) and isinstance(baseline.get("files"), list):
        previous = snapshots_mod.snapshot_from_dict(baseline)
        current = snapshots_mod.snapshot_from_dict(
            compute_test_plan_document_snapshot(project_root, topics)
        )
        return snapshots_mod.compare_snapshots(previous, current)
    paths = [
        artifact_paths_mod.QA_INDEX_DOC,
        *[topic_paths(project_root, topic)["test_plan"] for topic in normalize_topics(topics)],
    ]
    return _compare_recorded_snapshot(project_root, baseline, paths)


def _compare_acceptance_plan_document_snapshot(
    project_root: str,
    baseline: object,
    topics: str | list[str] | None,
) -> dict[str, list[str]]:
    """用与验收计划哈希相同的规则生成逐文件诊断。"""
    if isinstance(baseline, dict) and isinstance(baseline.get("files"), list):
        previous = snapshots_mod.snapshot_from_dict(baseline)
        current = snapshots_mod.snapshot_from_dict(
            compute_acceptance_plan_document_snapshot(project_root, topics)
        )
        return snapshots_mod.compare_snapshots(previous, current)
    topic_list = normalize_topics(topics)
    paths = [
        artifact_paths_mod.ACCEPTANCE_INDEX_DOC,
        *[topic_paths(project_root, topic)["acceptance_plan"] for topic in topic_list],
    ]
    return _compare_recorded_snapshot(project_root, baseline, paths)


def _compare_recorded_snapshot(
    project_root: str,
    baseline: object,
    current_paths: list[str],
) -> dict[str, list[str]]:
    """比较新逐文件快照，并兼容旧版的“路径到哈希”记录。"""
    if isinstance(baseline, dict) and isinstance(baseline.get("files"), list):
        previous = snapshots_mod.snapshot_from_dict(baseline)
        current = snapshots_mod.collect_snapshot(project_root, current_paths)
        return snapshots_mod.compare_snapshots(previous, current)
    if isinstance(baseline, dict) and all(isinstance(path, str) for path in baseline):
        current = compute_file_hashes(project_root, current_paths)
        result = {
            "added": [],
            "modified": [],
            "deleted": [],
            "type_changed": [],
            "not_checked": [],
        }
        for path in sorted(set(baseline) | set(current)):
            before = baseline.get(path)
            after = current.get(path)
            if path not in baseline or (before is None and after is not None):
                result["added"].append(path)
            elif path not in current or (before is not None and after is None):
                result["deleted"].append(path)
            elif before != after:
                result["modified"].append(path)
        return result
    current = snapshots_mod.collect_snapshot(project_root, current_paths)
    return snapshots_mod.compare_snapshots(None, current)


# 读取 产品总说明.md 中真实链接的功能文档路径
# 产品设计整体哈希以这里返回的文件为准，不扫描目录里的废弃功能文档
# 已移除历史功能文档只要不再被链接，就不参与当前哈希
def get_linked_product_design_paths(project_root: str) -> list[str]:
    product_rel = artifact_paths_mod.PRODUCT_OVERVIEW_DOC
    product_path = os.path.join(project_root, product_rel)
    paths = [product_rel]
    if not os.path.exists(product_path):
        return paths

    with open(product_path, "r", encoding="utf-8") as f:
        content = f.read()

    for filename in PRODUCT_FEATURE_LINK_RE.findall(content):
        paths.append(os.path.join("spec", filename))
    return sorted(set(paths))


# 对一组文档计算稳定的整体 SHA256
# 路径也参与哈希，所以新增、删除或替换链接都会改变结果
def compute_document_set_hash(project_root: str, rel_paths: list[str]) -> str:
    parts = []
    for rel_path in sorted(set(rel_paths)):
        file_hash = compute_file_hash(project_root, rel_path)
        parts.append(f"{rel_path}:{file_hash or '<missing>'}")
    return hashlib.sha256("\n".join(parts).encode("utf-8")).hexdigest()


def normalize_topics(topics: str | list[str] | None) -> list[str]:
    """兼容旧版单主题参数，并统一返回主题列表。"""
    if topics is None:
        return []
    if isinstance(topics, str):
        return [topics] if topics else []
    return [topic for topic in topics if topic]


# 计算产品总说明及其功能清单链接文档的整体哈希
def compute_product_design_hash(project_root: str) -> tuple[str | None, list[str]]:
    paths = get_linked_product_design_paths(project_root)
    if compute_file_hash(project_root, artifact_paths_mod.PRODUCT_OVERVIEW_DOC) is None:
        return (None, paths)
    return (compute_document_set_hash(project_root, paths), paths)


# 计算代码设计文档哈希
def compute_code_design_hash(project_root: str) -> str | None:
    return compute_file_hash(project_root, artifact_paths_mod.CODE_DESIGN_DOC)


# 代码文件后缀；文档、状态和日志不属于代码快照。
CODE_SUFFIXES = {
    ".c", ".cc", ".cpp", ".cxx", ".h", ".hh", ".hpp", ".hxx",
    ".py", ".pyi", ".ts", ".tsx", ".js", ".jsx", ".vue", ".svelte",
    ".go", ".rs", ".java", ".kt", ".kts", ".swift", ".ets",
    ".rb", ".php", ".cs", ".fs", ".fsx", ".m", ".mm", ".qml",
    ".sh", ".bash", ".zsh", ".ps1", ".bat", ".cmd",
}
CONFIG_NAMES = {
    "pyproject.toml", "uv.lock", "package.json", "package-lock.json", "yarn.lock",
    "pnpm-lock.yaml", "Cargo.toml", "Cargo.lock", "go.mod", "go.sum",
    "CMakeLists.txt", "CMakePresets.json", "Makefile", "justfile",
    "setup.py", "setup.cfg", "requirements.txt",
    "pom.xml", "build.gradle", "build.gradle.kts", "settings.gradle",
    "settings.gradle.kts", "Gemfile", "Gemfile.lock", "composer.json",
    "composer.lock",
}
CONFIG_SUFFIXES = {".pro", ".pri", ".cmake", ".yml", ".yaml"}
EXCLUDED_CODE_DIRS = {
    ".git", ".workflow_loop", "__pycache__", ".venv", "node_modules",
    ".pytest_cache", "dist", "build",
}


STANDALONE_TEST_CONFIG_NAMES = {
    "pytest.ini", "tox.ini", ".coveragerc", "conftest.py",
    "requirements-test.txt", "requirements-dev.txt", "dev-requirements.txt",
}
TEST_CONFIG_PREFIXES = (
    "jest.config.", "vitest.config.", "playwright.config.", "cypress.config.",
    "karma.conf.",
)


def _is_test_path(relative_path: str) -> bool:
    """判断相对路径是否属于测试代码。"""
    parts = [part.lower() for part in relative_path.replace(os.sep, "/").split("/")]
    filename = parts[-1].lower()
    stem = os.path.splitext(filename)[0]
    test_directories = {
        "tests", "test", "__tests__", "testdata", "test_data",
        "integration_tests", "e2e",
    }
    if any(part in test_directories for part in parts[:-1]):
        return True
    if stem.endswith(("_test", "_spec", ".test", ".spec")):
        return True
    return "src" not in parts[:-1] and filename.startswith(("test_", "tst_"))


def _stable_payload(value) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)


def _split_pyproject_config(full_path: str) -> tuple[str, str]:
    """把 pyproject.toml 的测试专用配置和产品配置分开。"""
    with open(full_path, "rb") as stream:
        data = tomllib.load(stream)
    product_data = copy.deepcopy(data)
    test_data: dict = {}

    tool_data = data.get("tool", {})
    selected_tools = {
        key: value
        for key, value in tool_data.items()
        if key in {"pytest", "coverage", "tox"}
    }
    if selected_tools:
        test_data["tool"] = selected_tools
        product_tool = product_data.get("tool", {})
        for key in selected_tools:
            product_tool.pop(key, None)
        if not product_tool:
            product_data.pop("tool", None)

    optional_dependencies = data.get("project", {}).get("optional-dependencies", {})
    selected_dependencies = {
        key: value
        for key, value in optional_dependencies.items()
        if key.lower() in {"dev", "test", "tests"}
    }
    if selected_dependencies:
        test_data.setdefault("project", {})["optional-dependencies"] = selected_dependencies
        product_optional = (
            product_data.get("project", {}).get("optional-dependencies", {})
        )
        for key in selected_dependencies:
            product_optional.pop(key, None)
        if not product_optional:
            product_data.get("project", {}).pop("optional-dependencies", None)

    dependency_groups = data.get("dependency-groups", {})
    selected_groups = {
        key: value
        for key, value in dependency_groups.items()
        if key.lower() in {"dev", "test", "tests"}
    }
    if selected_groups:
        test_data["dependency-groups"] = selected_groups
        product_groups = product_data.get("dependency-groups", {})
        for key in selected_groups:
            product_groups.pop(key, None)
        if not product_groups:
            product_data.pop("dependency-groups", None)

    return _stable_payload(test_data), _stable_payload(product_data)


def _split_package_json_config(full_path: str) -> tuple[str, str]:
    """把 package.json 中的测试脚本、测试工具配置和测试依赖分开。"""
    with open(full_path, "r", encoding="utf-8") as stream:
        data = json.load(stream)
    product_data = copy.deepcopy(data)
    test_data: dict = {}

    scripts = data.get("scripts", {})
    selected_scripts = {
        key: value
        for key, value in scripts.items()
        if key == "test" or key.startswith("test:")
    }
    if selected_scripts:
        test_data["scripts"] = selected_scripts
        product_scripts = product_data.get("scripts", {})
        for key in selected_scripts:
            product_scripts.pop(key, None)
        if not product_scripts:
            product_data.pop("scripts", None)

    for key in ("jest", "vitest", "playwright", "cypress"):
        if key in data:
            test_data[key] = data[key]
            product_data.pop(key, None)

    dev_dependencies = data.get("devDependencies", {})
    selected_dev_dependencies = {
        key: value
        for key, value in dev_dependencies.items()
        if any(
            token in key.lower()
            for token in (
                "test", "jest", "vitest", "mocha", "chai", "sinon", "ava", "tap",
                "playwright", "cypress", "testing-library", "nyc", "coverage",
            )
        )
    }
    if selected_dev_dependencies:
        test_data["devDependencies"] = selected_dev_dependencies
        product_dev_dependencies = product_data.get("devDependencies", {})
        for key in selected_dev_dependencies:
            product_dev_dependencies.pop(key, None)
        if not product_dev_dependencies:
            product_data.pop("devDependencies", None)

    return _stable_payload(test_data), _stable_payload(product_data)


def _split_setup_cfg(full_path: str) -> tuple[str, str]:
    parser = configparser.ConfigParser()
    parser.read(full_path, encoding="utf-8")
    test_sections = {
        section: dict(parser[section])
        for section in parser.sections()
        if section.startswith(("tool:pytest", "coverage:", "tox:"))
    }
    product_sections = {
        section: dict(parser[section])
        for section in parser.sections()
        if section not in test_sections
    }
    return _stable_payload(test_sections), _stable_payload(product_sections)


def _project_test_entry(project_root: str) -> tuple[str, str | None]:
    """返回 (稳定编码后的入口配置, 入口脚本相对路径)。

    入口配置是操作系统到参数数组的完整映射，稳定编码进测试代码快照；
    入口脚本路径用于识别测试相关文件（脚本内容变化 → 测试快照变化）。
    """
    project = load_project(project_root)
    raw_config = project.test_entry if project is not None else {}
    if isinstance(raw_config, str):
        raw_config = {"default": [raw_config]} if raw_config.strip() else {}
    if not isinstance(raw_config, dict):
        raw_config = {}
    encoded = json.dumps(raw_config, ensure_ascii=False, sort_keys=True)

    # 在任一平台参数中找项目内脚本路径（含 / 或常见脚本后缀的参数）
    entry_path = None
    for argv in raw_config.values():
        if not isinstance(argv, list):
            continue
        for part in argv:
            if not isinstance(part, str) or part.startswith("-"):
                continue
            if "/" in part or "\\" in part or part.endswith(
                (".sh", ".bash", ".zsh", ".py", ".js", ".ts", ".ps1", ".bat", ".cmd")
            ):
                entry_path = part.replace("\\", "/")
                break
        if entry_path:
            break
    if entry_path is not None:
        entry_path = os.path.normpath(entry_path).replace(os.sep, "/")
        if os.path.isabs(entry_path):
            try:
                relative_entry = os.path.relpath(entry_path, project_root)
            except ValueError:
                relative_entry = entry_path
            if relative_entry != ".." and not relative_entry.startswith(f"..{os.sep}"):
                entry_path = relative_entry.replace(os.sep, "/")
    return encoded, entry_path


def _is_standalone_test_config(relative_path: str, test_entry_path: str | None) -> bool:
    normalized = relative_path.replace(os.sep, "/")
    filename = os.path.basename(normalized).lower()
    return (
        normalized == test_entry_path
        or filename in STANDALONE_TEST_CONFIG_NAMES
        or filename.startswith(TEST_CONFIG_PREFIXES)
    )


def is_implementation_related_path(
    relative_path: str,
    test_entry_path: str | None = None,
) -> bool:
    """判断路径是否属于实施代码、脚本、测试或项目配置。"""
    normalized = relative_path.replace(os.sep, "/")
    filename = os.path.basename(normalized)
    suffix = os.path.splitext(filename)[1].lower()
    return (
        _is_test_path(normalized)
        or _is_standalone_test_config(normalized, test_entry_path)
        or suffix in CODE_SUFFIXES
        or filename in CONFIG_NAMES
        or suffix in CONFIG_SUFFIXES
    )


def _snapshot_parts_registered(
    project_root: str,
    registered_paths: list[str],
    test_entry_path: str | None,
    test_parts: list[str],
    product_parts: list[str],
) -> tuple[list[str], list[str]]:
    """按登记路径生成快照输入；此函数不调用 os.walk。"""
    for relative_path in sorted(set(registered_paths)):
        full_path = os.path.join(project_root, *relative_path.split("/"))
        if os.path.islink(full_path) or not os.path.isfile(full_path):
            continue
        filename = os.path.basename(relative_path)
        suffix = os.path.splitext(filename)[1].lower()
        is_test_path = _is_test_path(relative_path)
        is_test_config = _is_standalone_test_config(relative_path, test_entry_path)
        if not (is_test_path or is_test_config or suffix in CODE_SUFFIXES or filename in CONFIG_NAMES or suffix in CONFIG_SUFFIXES):
            continue
        raw_hash = _hash_file_path(full_path)
        if relative_path == "pyproject.toml":
            try:
                test_payload, product_payload = _split_pyproject_config(full_path)
            except (OSError, tomllib.TOMLDecodeError):
                test_parts.append(f"{relative_path}#test-fallback:{raw_hash}")
                product_parts.append(f"{relative_path}#product-fallback:{raw_hash}")
            else:
                test_parts.append(f"{relative_path}#test:{hashlib.sha256(test_payload.encode('utf-8')).hexdigest()}")
                product_parts.append(f"{relative_path}#product:{hashlib.sha256(product_payload.encode('utf-8')).hexdigest()}")
            continue
        if relative_path == "package.json":
            try:
                test_payload, product_payload = _split_package_json_config(full_path)
            except (OSError, json.JSONDecodeError):
                test_parts.append(f"{relative_path}#test-fallback:{raw_hash}")
                product_parts.append(f"{relative_path}#product-fallback:{raw_hash}")
            else:
                test_parts.append(f"{relative_path}#test:{hashlib.sha256(test_payload.encode('utf-8')).hexdigest()}")
                product_parts.append(f"{relative_path}#product:{hashlib.sha256(product_payload.encode('utf-8')).hexdigest()}")
            continue
        if relative_path == "setup.cfg":
            try:
                test_payload, product_payload = _split_setup_cfg(full_path)
            except (OSError, configparser.Error):
                test_parts.append(f"{relative_path}#test-fallback:{raw_hash}")
                product_parts.append(f"{relative_path}#product-fallback:{raw_hash}")
            else:
                test_parts.append(f"{relative_path}#test:{hashlib.sha256(test_payload.encode('utf-8')).hexdigest()}")
                product_parts.append(f"{relative_path}#product:{hashlib.sha256(product_payload.encode('utf-8')).hexdigest()}")
            continue
        is_shared_config = filename in CONFIG_NAMES or suffix in CONFIG_SUFFIXES
        if is_shared_config and not (is_test_path or is_test_config):
            test_parts.append(f"{relative_path}#test-config:{raw_hash}")
            product_parts.append(f"{relative_path}#product-config:{raw_hash}")
        else:
            target = test_parts if is_test_path or is_test_config else product_parts
            target.append(f"{relative_path}:{raw_hash}")
    return sorted(test_parts), sorted(product_parts)


def _snapshot_parts(project_root: str) -> tuple[list[str], list[str]]:
    """返回测试部分和产品部分的稳定哈希输入。"""
    test_parts: list[str] = []
    product_parts: list[str] = []
    test_entry, test_entry_path = _project_test_entry(project_root)
    test_parts.append(f".workflow_loop/project.json#test_entry:{hashlib.sha256(test_entry.encode('utf-8')).hexdigest()}")

    registered_paths = _active_registered_paths(project_root)
    if registered_paths is not None:
        return _snapshot_parts_registered(
            project_root,
            registered_paths,
            test_entry_path,
            test_parts,
            product_parts,
        )

    for root, dirs, files in os.walk(project_root):
        dirs[:] = [directory for directory in dirs if directory not in EXCLUDED_CODE_DIRS and directory != ".next"]
        for filename in files:
            relative_path = os.path.relpath(os.path.join(root, filename), project_root)
            is_test_path = _is_test_path(relative_path)
            is_test_config = _is_standalone_test_config(relative_path, test_entry_path)
            suffix = os.path.splitext(filename)[1].lower()
            is_project_config = filename in CONFIG_NAMES or suffix in CONFIG_SUFFIXES
            if (
                not is_test_path
                and not is_test_config
                and suffix not in CODE_SUFFIXES
                and not is_project_config
            ):
                continue
            full_path = os.path.join(project_root, relative_path)
            try:
                raw_hash = _hash_file_path(full_path)
            except OSError:
                continue

            if relative_path == "pyproject.toml":
                try:
                    test_payload, product_payload = _split_pyproject_config(full_path)
                except (OSError, tomllib.TOMLDecodeError):
                    test_parts.append(f"{relative_path}#test-fallback:{raw_hash}")
                    product_parts.append(f"{relative_path}#product-fallback:{raw_hash}")
                else:
                    test_parts.append(
                        f"{relative_path}#test:{hashlib.sha256(test_payload.encode('utf-8')).hexdigest()}"
                    )
                    product_parts.append(
                        f"{relative_path}#product:{hashlib.sha256(product_payload.encode('utf-8')).hexdigest()}"
                    )
                continue
            if relative_path == "package.json":
                try:
                    test_payload, product_payload = _split_package_json_config(full_path)
                except (OSError, json.JSONDecodeError):
                    test_parts.append(f"{relative_path}#test-fallback:{raw_hash}")
                    product_parts.append(f"{relative_path}#product-fallback:{raw_hash}")
                else:
                    test_parts.append(
                        f"{relative_path}#test:{hashlib.sha256(test_payload.encode('utf-8')).hexdigest()}"
                    )
                    product_parts.append(
                        f"{relative_path}#product:{hashlib.sha256(product_payload.encode('utf-8')).hexdigest()}"
                    )
                continue
            if relative_path == "setup.cfg":
                try:
                    test_payload, product_payload = _split_setup_cfg(full_path)
                except (OSError, configparser.Error):
                    test_parts.append(f"{relative_path}#test-fallback:{raw_hash}")
                    product_parts.append(f"{relative_path}#product-fallback:{raw_hash}")
                else:
                    test_parts.append(
                        f"{relative_path}#test:{hashlib.sha256(test_payload.encode('utf-8')).hexdigest()}"
                    )
                    product_parts.append(
                        f"{relative_path}#product:{hashlib.sha256(product_payload.encode('utf-8')).hexdigest()}"
                    )
                continue

            target = test_parts if is_test_path or is_test_config else product_parts
            target.append(f"{relative_path}:{raw_hash}")
    return sorted(test_parts), sorted(product_parts)


def _compute_code_snapshot_hash(project_root: str, *, test_only: bool | None) -> str:
    """按范围计算代码快照：全部、仅测试或排除测试。"""
    test_parts, product_parts = _snapshot_parts(project_root)
    if test_only is True:
        parts = test_parts
    elif test_only is False:
        parts = product_parts
    else:
        parts = [*test_parts, *product_parts]
    return hashlib.sha256("\n".join(parts).encode("utf-8")).hexdigest()


# 计算项目全部代码的快照哈希（impl_hash 和全量测试基线使用）
def compute_code_snapshot_hash(project_root: str) -> str:
    return _compute_code_snapshot_hash(project_root, test_only=None)


# 计算测试代码快照哈希（test_code 阶段确认是否真的写了测试代码）
def compute_test_code_snapshot_hash(project_root: str) -> str:
    return _compute_code_snapshot_hash(project_root, test_only=True)


# 计算排除测试代码后的产品代码快照哈希（阻止 test_code 阶段修改产品代码）
def compute_non_test_code_snapshot_hash(project_root: str) -> str:
    return _compute_code_snapshot_hash(project_root, test_only=False)


# 计算实施阶段使用的实施综合哈希（impl_hash）
# 包含两部分：impl/ 下全部实施记录内容哈希 + 非测试代码快照哈希
# test_code 阶段后续修改测试代码，不应让已经确认的实施结果失效。
def _indexes_generated(project_root: str) -> bool:
    """主题关系表已填时，三类索引由程序生成，不参与文档失效绑定。"""
    from . import records as records_mod
    from . import state as state_mod

    state = state_mod.load_state(project_root)
    if state is None:
        return False
    relative = records_mod.table_relative_path(
        project_root, state.workflow_id, "topic_relations", ""
    )
    if not records_mod.table_exists(project_root, relative):
        return False
    try:
        table = records_mod.load_table(os.path.join(project_root, relative))
    except Exception:
        return False
    return bool(table.get("主题关系"))


def _table_document_hash(
    project_root: str,
    workflow_id: str,
    kind: str,
    topic_list: list[str],
) -> str | None:
    """表启用时返回工作记录表内容的绑定哈希；未启用返回 None。

    表是机器事实的唯一真本：按表生成的正式文档随表确定性再生，不参与失效绑定。
    绑定只覆盖 AI 填写的内容，剔除程序专用键（生成文档哈希、生成文档路径）——
    程序重新生成文档或回补下游链接会改动这两个键，但表内容没变，
    不得因此误判上游变化并连锁失效（R7/R11）。
    """
    from . import records as records_mod

    paths = []
    for topic in topic_list or [""]:
        relative = records_mod.table_relative_path(project_root, workflow_id, kind, topic)
        if records_mod.table_exists(project_root, relative):
            paths.append(relative)
    if not paths:
        return None
    if kind in {"acceptance_plan"}:
        relations = records_mod.table_relative_path(project_root, workflow_id, "topic_relations", "")
        if records_mod.table_exists(project_root, relations):
            paths.append(relations)
    digest = hashlib.sha256()
    for relative in sorted(set(paths)):
        full = os.path.join(project_root, *relative.split("/"))
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        try:
            table = records_mod.load_table(full)
        except records_mod.RecordsError:
            # 表解析失败时退回原始字节，坏表也必须让失效检查看见变化
            with open(full, "rb") as stream:
                for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                    digest.update(chunk)
            digest.update(b"\0")
            continue
        content = {
            key: value
            for key, value in table.items()
            if key not in (records_mod.DOC_HASH_KEY, records_mod.GENERATED_DOC_PATH_KEY)
        }
        digest.update(
            json.dumps(content, ensure_ascii=False, sort_keys=True).encode("utf-8")
        )
        digest.update(b"\0")
    return digest.hexdigest()


def compute_impl_hash(project_root: str, topics: str | list[str] | None = None) -> str:
    # 只绑定当前工作流明确登记的实施索引和主题记录，历史记录和目录内其它文件
    # 不得因为文件名后缀相同而影响当前实施状态。
    topic_list = normalize_topics(topics)
    parts = []
    state = load_state(project_root)
    if topic_list:
        table_hash = None
        if state is not None:
            table_hash = _table_document_hash(project_root, state.workflow_id, "impl_record", topic_list)
        if table_hash is not None:
            parts.append(f"impl_tables:{table_hash}")
        else:
            impl_paths = [
                topic_paths(project_root, topic)["impl_doc"] for topic in topic_list
            ]
            if not _indexes_generated(project_root):
                impl_paths.insert(0, artifact_paths_mod.IMPL_INDEX_DOC)
            parts.append(f"impl_docs:{compute_document_set_hash(project_root, impl_paths)}")
    # 只加入非测试代码快照，测试代码由 test_code 阶段单独校验。
    parts.append(f"code_snapshot:{compute_non_test_code_snapshot_hash(project_root)}")
    # 合并所有部分算最终 SHA256
    return hashlib.sha256("\n".join(parts).encode("utf-8")).hexdigest()


# 计算测试计划文件 qa/<主题文件标识>_测试计划.md 的 SHA256
# 在 gate test_plan --confirmed 时记录；变化时使主题执行及其后续结果失效
def compute_test_plan_hash(project_root: str, topics: str | list[str] | None) -> str | None:
    topic_list = normalize_topics(topics)
    if not topic_list:
        return None
    state = load_state(project_root)
    if state is not None:
        table_hash = _table_document_hash(project_root, state.workflow_id, "test_plan", topic_list)
        if table_hash is not None:
            return table_hash
    snapshot = compute_test_plan_document_snapshot(project_root, topic_list)
    return str(snapshot["aggregate_hash"])


# 计算验收计划文件和验收主题索引的 SHA256
# 在 gate acceptance_plan --confirmed 时记录
# acceptance_plan 或主题关系变化时把 test_plan 和后续阶段退回待检查
def compute_acceptance_plan_hash(project_root: str, topics: str | list[str] | None) -> str | None:
    topic_list = normalize_topics(topics)
    if not topic_list:
        return None
    state = load_state(project_root)
    if state is not None:
        table_hash = _table_document_hash(project_root, state.workflow_id, "acceptance_plan", topic_list)
        if table_hash is not None:
            return table_hash
    snapshot = compute_acceptance_plan_document_snapshot(project_root, topic_list)
    return str(snapshot["aggregate_hash"])


# 计算测试结果文件和 QA 机器任务记录的绑定摘要。
# 在 qa 确认时记录；结果文档或机器记录变化时可指向不同的恢复步骤。
def test_tasks_payload(
    state: WorkflowState | None,
    topics: str | list[str] | None,
) -> dict:
    if state is None:
        return {}
    topic_list = normalize_topics(topics)
    stage = state.stages.get("qa") or state.stages.get("test_execution")
    if stage is None:
        return {}
    selected = topic_list or list(stage.test_tasks)
    return {
        topic: {
            test_id: asdict(task)
            for test_id, task in sorted(stage.test_tasks.get(topic, {}).items())
        }
        for topic in selected
        if topic in stage.test_tasks
    }


def compute_test_result_hash(
    project_root: str,
    topics: str | list[str] | None,
    state: WorkflowState | None = None,
) -> str | None:
    topic_list = normalize_topics(topics)
    if not topic_list:
        return None
    current_state = state if state is not None else load_state(project_root)
    table_hash = None
    if current_state is not None:
        table_hash = _table_document_hash(project_root, current_state.workflow_id, "test_result", topic_list)
    if table_hash is not None:
        document_hash = table_hash
    else:
        paths = [
            topic_paths(project_root, topic)["test_result"]
            for topic in automated_topics(project_root, topic_list)
        ]
        document_hash = (
            hashlib.sha256(b"<no-automated-test-results>").hexdigest()
            if not paths
            else compute_document_set_hash(project_root, paths)
        )
    task_hash = _canonical_hash(test_tasks_payload(current_state, topic_list))
    return hashlib.sha256(
        f"documents:{document_hash}\ntasks:{task_hash}".encode("utf-8")
    ).hexdigest()


# 计算主题验收结果文件 acceptance/<主题文件标识>_验收结果.md 的 SHA256
# 在 gate topic_acceptance --confirmed 时记录；变化时使最终回归及后续阶段失效
def compute_acceptance_result_hash(
    project_root: str,
    topics: str | list[str] | None,
    state: WorkflowState | None = None,
) -> str | None:
    topic_list = normalize_topics(topics)
    if not topic_list:
        return None
    current_state = state if state is not None else load_state(project_root)
    table_hash = None
    if current_state is not None:
        table_hash = _table_document_hash(project_root, current_state.workflow_id, "acceptance_result", topic_list)
    if table_hash is not None:
        document_hash = table_hash
    else:
        paths = [topic_paths(project_root, topic)["acceptance_result"] for topic in topic_list]
        document_hash = compute_document_set_hash(project_root, paths)
    current_state = state if state is not None else load_state(project_root)
    records = (
        acceptance_records_mod.acceptance_records_payload(current_state, topic_list)
        if current_state is not None
        else {}
    )
    payload = json.dumps(records, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(
        f"documents:{document_hash}\nrecords:{payload}".encode("utf-8")
    ).hexdigest()


def compute_regression_test_result_hash(project_root: str) -> str | None:
    state = load_state(project_root)
    if state is None:
        return None
    payload = json.dumps(state.regression_test.__dict__, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


# 清零单个 stage 的所有门禁状态（3 道闸全清，状态回 pending）
# 用于 Verification Invalidation：上游变化时清零下游
def clear_stage_gates(stage: StageState) -> None:
    # 重置 3 道闸为全新 GateState（全 False）
    stage.gate = GateState()
    # stage 状态回到 pending（需要重新走 7 步模式）
    stage.status = "pending"
    # 下游失效后，旧产物基线和 impl 代码基线也不能继续复用。
    stage.artifact_produced_at = None
    stage.artifact_baseline_captured_at = None
    stage.artifact_baseline_hashes = {}
    stage.code_baseline_hash = None
    stage.test_code_baseline_hash = None
    stage.non_test_code_baseline_hash = None
    stage.existing_code_accepted_hash = None
    stage.existing_test_code_accepted_hash = None
    stage.plan_confirmed_hash = None
    stage.internal_step = ""
    stage.internal_step_hash = None
    stage.scope_confirmed_hash = None
    stage.result_hash = None
    stage.reuse_decision_hash = None
    stage.validation_credential = None


def set_recovery_context(
    state: WorkflowState,
    source_stage: str,
    affected_stages: list[str],
    reason: str,
) -> None:
    """保存退回原因，让后续命令能解释当前阶段是复核还是重做。"""
    state.recovery = RecoveryContext(
        source_stage=source_stage,
        reason=reason,
        affected_stages=list(affected_stages),
        created_at=now_iso(),
    )


def clear_completed_material_recovery(state: WorkflowState) -> bool:
    """引发恢复的阶段重新确认完成后，清除当前提示，历史留在 Journal。"""
    recovery = state.recovery
    if not recovery.source_stage or not recovery.reason:
        return False
    source_state = state.stages.get(recovery.source_stage)
    if source_state is None or source_state.status != "done":
        return False
    state.recovery = RecoveryContext()
    return True


def recovery_stage_action(state: WorkflowState, stage_name: str) -> str | None:
    """返回当前恢复阶段的具体动作，避免把复核误说成重新开发。"""
    recovery = state.recovery
    if not recovery.source_stage or stage_name not in recovery.affected_stages:
        return None

    if recovery.reason and "流程模板或规范" in recovery.reason:
        return (
            "重新阅读更新后的流程材料，并按新规则核对当前产出；"
            "只有新规则使现有产出不合格时才修改"
        )

    if stage_name in {"spec", "reproduce", "code_design", "revise_code_design", "spike"}:
        return "重新核对上游事实和设计；只有内容确实不一致时才修改文档"
    if stage_name in {"acceptance_plan", "test_plan"}:
        return "重新核对上游文档和当前计划；已有内容仍正确时不需要为了门禁重写"
    if stage_name == "impl":
        return (
            "重新核对实施计划、实施记录和现有代码是否符合最新上游计划；"
            "一致时确认既有代码，不一致时才修改代码"
        )
    if stage_name == "qa":
        qa_state = state.stages.get("qa")
        step = qa_state.internal_step if qa_state is not None else "scope"
        if step == "scope":
            return "重新确认受影响主题的测试范围和通过标准；保留无影响主题的结果"
        if step == "test_code":
            return "保留已确认测试范围，只重新核对受影响的测试代码和配置"
        if step == "result":
            return "保留当前机器执行记录，只重新生成受影响的测试结果"
        return "保留测试范围和测试代码，只重新执行受影响的测试任务"
    if stage_name == "test_code":
        return (
            "重新核对测试计划与现有测试代码的对应关系；一致时确认既有测试代码，"
            "不一致时才修改测试代码"
        )
    if stage_name == "test_execution":
        return "旧测试结果不能继续使用，重新登记并执行需要测试的主题"
    if stage_name == "topic_acceptance":
        return "使用新的主题测试结果重新逐条验收；不能直接沿用旧验收结果"
    if stage_name == "regression_test":
        return "重新执行全量回归；旧回归状态不能代表当前代码"
    if stage_name == "overall_acceptance":
        return "根据最新主题验收和全量回归结果重新做整体验收"
    if stage_name == "update_code_design":
        return "根据重新确认后的真实代码和验收结果更新详细代码设计"
    return "重新核对当前阶段产出是否仍符合上游结果"


def recovery_summary(state: WorkflowState) -> str | None:
    """返回一行可直接显示给用户的恢复原因。"""
    recovery = state.recovery
    if not recovery.source_stage or not recovery.reason:
        return None
    return f"{recovery.source_stage} 相关内容需要重新处理：{recovery.reason}"


def reset_stages_and_move_current(state: WorkflowState, stage_names: list[str]) -> None:
    """清零指定阶段，并把当前阶段退回到路径中最早的受影响阶段。"""
    affected = []
    for stage_name in stage_names:
        if stage_name in state.stages:
            clear_stage_gates(state.stages[stage_name])
            affected.append(stage_name)

    if not affected:
        return

    order = {stage_name: index for index, stage_name in enumerate(state.stage_path)}
    earliest = min(affected, key=lambda stage_name: order.get(stage_name, len(order)))
    state.current_stage = earliest
    state.stages[earliest].status = "in_progress"


def _invalidate_test_execution_outputs(
    project_root: str,
    state: WorkflowState,
    topics: list[str],
    test_items: list[tuple[str, str]] | None = None,
) -> None:
    """上游内容变化时，清掉不能继续使用的主题测试状态和结果文件。"""
    stage_state = state.stages.get("qa") or state.stages.get("test_execution")
    if stage_state is not None:
        if test_items is None:
            for topic in topics:
                stage_state.test_tasks.pop(topic, None)
        else:
            for topic, test_id in test_items:
                topic_tasks = stage_state.test_tasks.get(topic)
                if topic_tasks is None:
                    continue
                topic_tasks.pop(test_id, None)
                if not topic_tasks:
                    stage_state.test_tasks.pop(topic, None)
    for topic in topics:
        paths = topic_paths(project_root, topic)
        for kind in ("test_result", "acceptance_result"):
            result_path = os.path.join(project_root, paths[kind])
            if os.path.isfile(result_path):
                os.remove(result_path)
    acceptance_records_mod.clear_topic_records(project_root, state, topics)
    state.regression_test = RegressionTestState()


@dataclass(frozen=True)
class InvalidationInspection:
    """一次只读失效检查得到的完整事实。"""

    source_stage: str | None = None
    affected_stages: tuple[str, ...] = ()
    affected_topics: tuple[str, ...] = ()
    affected_test_items: tuple[tuple[str, str], ...] = ()
    affected_description: str = ""
    reason: str = ""
    diagnostics: tuple[diagnostics_mod.Diagnostic, ...] = ()
    findings: tuple["InvalidationFinding", ...] = ()
    blocked: bool = False

    @property
    def changed(self) -> bool:
        return bool(self.findings)


@dataclass(frozen=True)
class InvalidationFinding:
    """一个可靠比较得到的独立变化事实。"""

    source_stage: str
    expected_hash: str
    actual_hash: str | None
    affected_topics: tuple[str, ...]
    affected_test_items: tuple[tuple[str, str], ...]
    reason: str
    diagnostics: tuple[diagnostics_mod.Diagnostic, ...]
    details: tuple[tuple[str, dict[str, list[str]]], ...] = ()
    recovery_step: str = ""
    result_documents_only: bool = False
    machine_records_changed: bool = False


_INVALIDATION_ORDER = (
    ("acceptance_plan", "acceptance_plan_hash"),
    ("impl", "impl_hash"),
    ("test_plan", "test_plan_hash"),
    ("test_code", "test_code_hash"),
    ("test_execution", "test_result_hash"),
    ("topic_acceptance", "acceptance_result_hash"),
    ("regression_test", "regression_test_result_hash"),
)

_LEGACY_INVALIDATION_AFFECTED = {
    "acceptance_plan": (
        "acceptance_plan", "impl", "test_plan", "test_code", "test_execution",
        "topic_acceptance", "regression_test", "overall_acceptance", "update_code_design",
    ),
    "impl": (
        "impl", "test_plan", "test_code", "test_execution", "topic_acceptance",
        "regression_test", "overall_acceptance", "update_code_design",
    ),
    "test_plan": (
        "test_plan", "test_code", "test_execution", "topic_acceptance",
        "regression_test", "overall_acceptance", "update_code_design",
    ),
    "test_code": (
        "test_code", "test_execution", "topic_acceptance", "regression_test",
        "overall_acceptance", "update_code_design",
    ),
    "test_execution": (
        "topic_acceptance", "regression_test", "overall_acceptance", "update_code_design",
    ),
    "topic_acceptance": ("regression_test", "overall_acceptance", "update_code_design"),
    "regression_test": ("regression_test", "overall_acceptance", "update_code_design"),
}

_CURRENT_INVALIDATION_AFFECTED = {
    "acceptance_plan": (
        "acceptance_plan", "impl", "qa", "topic_acceptance", "regression_test",
        "overall_acceptance", "update_code_design",
    ),
    "impl": (
        "impl", "qa", "topic_acceptance", "regression_test", "overall_acceptance",
        "update_code_design",
    ),
    "test_plan": (
        "qa", "topic_acceptance", "regression_test", "overall_acceptance",
        "update_code_design",
    ),
    "test_code": (
        "qa", "topic_acceptance", "regression_test", "overall_acceptance",
        "update_code_design",
    ),
    "test_execution": (
        "qa", "topic_acceptance", "regression_test", "overall_acceptance",
        "update_code_design",
    ),
    "topic_acceptance": ("regression_test", "overall_acceptance", "update_code_design"),
    "regression_test": ("regression_test", "overall_acceptance", "update_code_design"),
}


def _invalidation_affected_stages(
    state: WorkflowState,
    source_stage: str,
) -> tuple[str, ...]:
    table = (
        _CURRENT_INVALIDATION_AFFECTED
        if "qa" in state.stage_path
        else _LEGACY_INVALIDATION_AFFECTED
    )
    return tuple(stage for stage in table[source_stage] if stage in state.stages)

_INVALIDATION_DESCRIPTIONS = {
    "acceptance_plan": "acceptance_plan 及全部后续阶段",
    "impl": "impl 及全部后续阶段",
    "test_plan": "qa 测试范围及全部后续阶段（保留 impl）",
    "test_code": "qa 测试代码及全部后续阶段",
    "test_execution": "qa 测试执行或结果及全部后续阶段",
    "topic_acceptance": "regression_test、overall_acceptance 和 update_code_design",
    "regression_test": "regression_test、overall_acceptance 和 update_code_design",
}


def _change_diagnostics(
    *,
    source_stage: str,
    scope_name: str,
    differences: dict[str, list[str]],
    parent_check_id: str,
) -> list[diagnostics_mod.Diagnostic]:
    labels = {
        "added": "新增或进入登记范围",
        "modified": "内容修改",
        "deleted": "删除或移出登记范围",
        "type_changed": "文件类型变化",
    }
    diagnostics: list[diagnostics_mod.Diagnostic] = []
    for kind in ("added", "modified", "deleted", "type_changed"):
        for path in sorted(differences.get(kind, [])):
            diagnostics.append(
                diagnostics_mod.Diagnostic(
                    kind="error",
                    check_id=f"invalidation.{source_stage}.{scope_name}.{kind}:{path}",
                    location=path,
                    expected=f"与 {source_stage} 确认时登记的{scope_name}逐文件事实一致",
                    actual=labels[kind],
                    evidence=f"逐文件快照比较结果：{kind}={path}",
                    impact=f"{_INVALIDATION_DESCRIPTIONS[source_stage]}不能继续沿用",
                    next_action=f"核对 {path} 的真实变化，并在 {source_stage} 阶段更新或恢复对应内容",
                )
            )
    for path in sorted(differences.get("not_checked", [])):
        diagnostics.append(
            diagnostics_mod.Diagnostic(
                kind="not_checked",
                check_id=f"invalidation.{source_stage}.{scope_name}.not_checked:{path}",
                location=path,
                expected=f"存在 {source_stage} 确认时保存的{scope_name}逐文件基线",
                actual="未检查：旧状态没有该路径的逐文件基线",
                evidence="只有聚合哈希发生变化，无法从旧状态还原该路径修改前事实",
                impact="不能精确断言该路径属于新增、修改、删除还是类型变化",
                next_action=f"返回 {source_stage} 重新确认并保存新的逐文件基线",
                depends_on=parent_check_id,
            )
        )
    return diagnostics


_CHANGE_KINDS = ("added", "modified", "deleted", "type_changed")


def _changed_paths(*differences: dict[str, list[str]]) -> set[str]:
    """汇总逐文件差异中的真实变化路径，不丢失任一变化类型。"""
    return {
        path
        for difference in differences
        for kind in _CHANGE_KINDS
        for path in difference.get(kind, [])
    }


def _topic_owned_paths(
    project_root: str,
    topics: list[str],
    source_stage: str,
) -> dict[str, set[str]] | None:
    """返回路径到主题的归属；计划无法解析时返回 None，调用方按整轮处理。"""
    ownership: dict[str, set[str]] = {}

    def register(topic: str, paths: list[str]) -> None:
        for path in paths:
            normalized = path.replace(os.sep, "/")
            ownership.setdefault(normalized, set()).add(topic)

    try:
        for topic in topics:
            paths = topic_paths(project_root, topic)
            if source_stage == "acceptance_plan":
                register(topic, [paths["acceptance_plan"]])
            elif source_stage == "impl":
                # rollback（回退模块）会反向引用本模块，只能在运行检查时局部导入。
                from .rollback import planned_code_paths

                register(topic, [paths["impl_doc"]])
                try:
                    register(topic, planned_code_paths(project_root, [topic]))
                except (FileNotFoundError, OSError, ValueError):
                    pass
                try:
                    from .rollback import recorded_code_paths

                    register(topic, recorded_code_paths(project_root, [topic]))
                except (FileNotFoundError, OSError, ValueError):
                    pass
            elif source_stage == "test_plan":
                register(topic, [paths["test_plan"]])
            elif source_stage == "test_code":
                try:
                    register(topic, planned_test_source_paths(project_root, [topic]))
                except (FileNotFoundError, OSError, ValueError):
                    pass
                try:
                    from .test_mapping import collect_all_workflow_test_markers

                    for marker in collect_all_workflow_test_markers(project_root):
                        if marker.topic == topic:
                            register(topic, [marker.path])
                except (FileNotFoundError, OSError, ValueError):
                    pass
            elif source_stage == "test_execution":
                register(topic, [paths["test_result"]])
            elif source_stage == "topic_acceptance":
                register(topic, [paths["acceptance_result"]])
    except (FileNotFoundError, OSError, ValueError):
        return None
    return ownership


def _affected_topics_from_changes(
    project_root: str,
    topics: list[str],
    source_stage: str,
    *differences: dict[str, list[str]],
) -> tuple[str, ...] | None:
    """由逐文件变化反推直接受影响主题；证据不足时不猜测。"""
    ordered_topics = tuple(dict.fromkeys(topics))
    if not ordered_topics:
        return ()
    if source_stage == "regression_test":
        return ordered_topics

    # 旧状态没有逐文件基线时，无法证明具体是哪个主题变化。
    if any(difference.get("not_checked") for difference in differences):
        return None
    changed_paths = _changed_paths(*differences)
    if not changed_paths:
        # 有完整逐文件基线且比较结果为空，表示该来源本身没有主题变化。
        # 调用方还可能把机器记录等结构化变化并入同一失效事实，因此这里
        # 必须返回空主题集合，而不能把“零差异”误判为“没有可定位基线”。
        return ()

    global_paths = {
        "acceptance_plan": {artifact_paths_mod.ACCEPTANCE_INDEX_DOC},
        "impl": {artifact_paths_mod.IMPL_INDEX_DOC},
        "test_plan": {artifact_paths_mod.QA_INDEX_DOC},
    }.get(source_stage, set())
    if changed_paths & global_paths:
        return ordered_topics

    ownership = _topic_owned_paths(project_root, list(ordered_topics), source_stage)
    if ownership is None:
        return None
    affected: set[str] = set()
    for path in changed_paths:
        owners = ownership.get(path.replace(os.sep, "/"))
        if not owners:
            return None
        affected.update(owners)
    return tuple(topic for topic in ordered_topics if topic in affected)


def _normalized_test_item_mapping(
    value: object,
) -> dict[str, set[tuple[str, str]]] | None:
    """读取 JSON 往返后的测试文件到测试项映射。"""

    if not isinstance(value, dict):
        return None
    normalized: dict[str, set[tuple[str, str]]] = {}
    for raw_path, raw_items in value.items():
        if not isinstance(raw_path, str) or not isinstance(raw_items, (list, tuple)):
            return None
        items: set[tuple[str, str]] = set()
        for raw_item in raw_items:
            if (
                not isinstance(raw_item, (list, tuple))
                or len(raw_item) != 2
                or not all(isinstance(part, str) and part for part in raw_item)
            ):
                return None
            items.add((raw_item[0], raw_item[1]))
        normalized[raw_path.replace(os.sep, "/")] = items
    return normalized


def _affected_test_items_from_changes(
    project_root: str,
    topics: list[str],
    differences: dict[str, list[str]],
    baseline_mapping: object,
) -> tuple[tuple[str, str], ...] | None:
    """把测试代码变化定位到 TC；无直接标识的路径按共享支持文件处理。"""

    baseline = _normalized_test_item_mapping(baseline_mapping)
    if baseline is None:
        return None
    try:
        current = {
            path: set(items)
            for path, items in test_item_path_mapping(project_root, topics).items()
        }
        ordered_items = [
            (item.topic, item.test_id)
            for item in automated_test_items(project_root, topics)
        ]
    except (OSError, ValueError):
        return None
    changed_paths = _changed_paths(differences)
    if not changed_paths:
        return ()
    affected: set[tuple[str, str]] = set()
    all_items = set(ordered_items)
    for path in changed_paths:
        normalized = path.replace(os.sep, "/")
        direct = baseline.get(normalized, set()) | current.get(normalized, set())
        affected.update(direct or all_items)
    return tuple(item for item in ordered_items if item in affected)


def _test_item_change_diagnostics(
    affected_items: tuple[tuple[str, str], ...],
    differences: dict[str, list[str]],
) -> list[diagnostics_mod.Diagnostic]:
    changed_paths = sorted(_changed_paths(differences))
    return [
        diagnostics_mod.Diagnostic(
            kind="error",
            check_id=f"invalidation.test_code.test_item:{topic}:{test_id}",
            location=f".workflow_loop/state.json#stages.qa.test_tasks.{topic}.{test_id}",
            expected="测试项机器记录绑定的测试代码和配置未变化",
            actual=f"{topic} / {test_id} 受到测试代码变化影响",
            evidence=f"变化路径={changed_paths}",
            impact="只使该测试项的旧机器记录失效，同主题其它测试项记录保留",
            next_action=f"重新登记并执行 {topic} / {test_id}",
            depends_on="invalidation.test_code.binding",
        )
        for topic, test_id in affected_items
    ]


def _dependent_not_checked(
    state: WorkflowState,
    source_stage: str,
    parent_check_id: str,
) -> list[diagnostics_mod.Diagnostic]:
    """最上游已经失效时，明确列出本次没有继续判断的下游绑定。"""
    source_index = [name for name, _ in _INVALIDATION_ORDER].index(source_stage)
    diagnostics: list[diagnostics_mod.Diagnostic] = []
    for stage_name, field_name in _INVALIDATION_ORDER[source_index + 1 :]:
        if getattr(state.verification, field_name) is None:
            continue
        diagnostics.append(
            diagnostics_mod.Diagnostic(
                kind="not_checked",
                check_id=f"invalidation.{stage_name}.not_checked",
                location=f".workflow_loop/state.json#verification.{field_name}",
                expected=f"在有效的上游结果上检查 {stage_name} 绑定是否变化",
                actual=f"未检查：更上游的 {source_stage} 已经失效",
                evidence=f"前置检查 {parent_check_id} 已确认变化",
                impact=f"{stage_name} 的旧结果随上游一起失效，单独比较没有判定意义",
                next_action=f"先完成并确认 {source_stage}，再按流程重新检查 {stage_name}",
                depends_on=parent_check_id,
            )
        )
    return diagnostics


def _make_invalidation_inspection(
    state: WorkflowState,
    *,
    source_stage: str,
    expected_hash: str,
    actual_hash: str | None,
    reason: str,
    exact_diagnostics: list[diagnostics_mod.Diagnostic],
    affected_topics: tuple[str, ...] | None,
) -> InvalidationInspection:
    field_name = dict(_INVALIDATION_ORDER)[source_stage]
    parent_check_id = f"invalidation.{source_stage}.binding"
    diagnostics = [
        diagnostics_mod.Diagnostic(
            kind="error",
            check_id=parent_check_id,
            location=f".workflow_loop/state.json#verification.{field_name}",
            expected=f"当前 {source_stage} 绑定哈希等于确认值 {expected_hash}",
            actual=f"当前绑定哈希为 {actual_hash}",
            evidence=f"saved={expected_hash}; current={actual_hash}",
            impact=f"{_INVALIDATION_DESCRIPTIONS[source_stage]}的旧确认不能继续使用",
            next_action=f"先核对下面列出的具体变化，再返回 {source_stage} 处理",
        ),
        *exact_diagnostics,
        *_dependent_not_checked(state, source_stage, parent_check_id),
    ]
    if affected_topics is None:
        diagnostics.append(
            diagnostics_mod.Diagnostic(
                kind="not_checked",
                check_id=f"invalidation.{source_stage}.affected_topics.not_checked",
                location=".workflow_loop/state.json#meta.registered_snapshots",
                expected="存在足以定位直接受影响主题的逐文件基线和路径归属",
                actual="未检查：当前事实只能证明绑定变化，不能可靠证明应删除哪些主题结果",
                evidence="逐文件基线缺失、没有具体变化路径或路径无法归属到单一主题",
                impact="为避免误删，程序不会自动应用本次失效清理",
                next_action=f"先返回 {source_stage} 重建可定位基线，或由用户明确直接受影响主题",
                depends_on=parent_check_id,
            )
        )
    return InvalidationInspection(
        source_stage=source_stage,
        affected_stages=_invalidation_affected_stages(state, source_stage),
        affected_topics=affected_topics or (),
        affected_description=_INVALIDATION_DESCRIPTIONS[source_stage],
        reason=reason,
        diagnostics=tuple(diagnostics),
        blocked=affected_topics is None,
    )




def _current_test_entry_config(project_root: str) -> dict:
    project = load_project(project_root)
    raw = project.test_entry if project is not None else {}
    if isinstance(raw, str):
        return {"default": [raw]} if raw.strip() else {}
    return copy.deepcopy(raw) if isinstance(raw, dict) else {}


def _payload_changed_topics(
    baseline: object,
    current: dict,
    topics: list[str],
) -> tuple[str, ...] | None:
    """比较按主题保存的状态事实；无基线时不猜测影响范围。"""
    if not isinstance(baseline, dict):
        return None
    return tuple(
        topic
        for topic in topics
        if baseline.get(topic, {}) != current.get(topic, {})
    )


def _state_change_diagnostics(
    *,
    source_stage: str,
    scope_name: str,
    location: str,
    changed_topics: tuple[str, ...],
    parent_check_id: str,
) -> list[diagnostics_mod.Diagnostic]:
    return [
        diagnostics_mod.Diagnostic(
            kind="error",
            check_id=f"invalidation.{source_stage}.{scope_name}:{topic}",
            location=f"{location}.{topic}",
            expected=f"与 {source_stage} 确认时保存的{scope_name}一致",
            actual=f"主题“{topic}”的{scope_name}已变化",
            evidence=f"结构化状态逐主题比较：{topic}",
            impact=f"主题“{topic}”的{_INVALIDATION_DESCRIPTIONS[source_stage]}不能继续沿用",
            next_action=f"只重新处理主题“{topic}”中受影响的{scope_name}",
            depends_on=parent_check_id,
        )
        for topic in changed_topics
    ]


def inspect_invalidation(state: WorkflowState, project_root: str) -> InvalidationInspection:
    """先完成全部可靠只读比较，再生成一份精确失效计划。"""
    topics = list(dict.fromkeys(state.topics or ([state.topic] if state.topic else [])))
    stored = state.meta.get("registered_snapshots", {})
    if not isinstance(stored, dict):
        stored = {}
    findings: list[InvalidationFinding] = []
    blocked: list[tuple[str, str, tuple[diagnostics_mod.Diagnostic, ...]]] = []

    def record_change(
        *,
        source_stage: str,
        expected_hash: str,
        actual_hash: str | None,
        reason: str,
        affected_topics: tuple[str, ...] | None,
        detail_differences: list[tuple[str, dict[str, list[str]]]],
        affected_test_items: tuple[tuple[str, str], ...] = (),
        extra_diagnostics: list[diagnostics_mod.Diagnostic] | None = None,
        recovery_step: str = "",
        result_documents_only: bool = False,
        machine_records_changed: bool = False,
    ) -> None:
        field_name = dict(_INVALIDATION_ORDER)[source_stage]
        parent = f"invalidation.{source_stage}.binding"
        diagnostics: list[diagnostics_mod.Diagnostic] = [
            diagnostics_mod.Diagnostic(
                kind="error",
                check_id=parent,
                location=f".workflow_loop/state.json#verification.{field_name}",
                expected=f"当前 {source_stage} 绑定哈希等于确认值 {expected_hash}",
                actual=f"当前绑定哈希为 {actual_hash}",
                evidence=f"saved={expected_hash}; current={actual_hash}",
                impact=f"{_INVALIDATION_DESCRIPTIONS[source_stage]}的旧确认不能继续使用",
                next_action="先核对本次一次列出的全部变化，再一次应用失效计划",
            )
        ]
        for scope_name, differences in detail_differences:
            diagnostics.extend(
                _change_diagnostics(
                    source_stage=source_stage,
                    scope_name=scope_name,
                    differences=differences,
                    parent_check_id=parent,
                )
            )
        diagnostics.extend(extra_diagnostics or [])
        if affected_topics is None:
            diagnostics.append(
                diagnostics_mod.Diagnostic(
                    kind="not_checked",
                    check_id=f"invalidation.{source_stage}.affected_topics.not_checked",
                    location=".workflow_loop/state.json#meta.registered_snapshots",
                    expected="存在能定位直接受影响主题的逐文件或结构化状态基线",
                    actual="未检查：只能证明整体绑定变化，不能可靠证明删除哪些主题结果",
                    evidence="基线缺失、没有具体变化路径，或路径无法归属到主题",
                    impact="程序本次不执行删文件或清主题记录的破坏性操作",
                    next_action=f"先在 {source_stage} 重建可定位基线，或让用户明确直接受影响主题",
                    depends_on=parent,
                )
            )
            blocked.append((source_stage, reason, tuple(diagnostics)))
            return
        findings.append(
            InvalidationFinding(
                source_stage=source_stage,
                expected_hash=expected_hash,
                actual_hash=actual_hash,
                affected_topics=affected_topics,
                affected_test_items=affected_test_items,
                reason=reason,
                diagnostics=tuple(diagnostics),
                details=tuple(detail_differences),
                recovery_step=recovery_step,
                result_documents_only=result_documents_only,
                machine_records_changed=machine_records_changed,
            )
        )

    expected = state.verification.acceptance_plan_hash
    if expected is not None:
        current_topics = list_acceptance_index_topics(project_root, state.workflow_id)
        current = compute_acceptance_plan_hash(project_root, current_topics)
        if current != expected:
            differences = _compare_acceptance_plan_document_snapshot(
                project_root,
                stored.get("acceptance_plan_documents"),
                current_topics,
            )
            record_change(
                source_stage="acceptance_plan",
                expected_hash=expected,
                actual_hash=current,
                reason=(
                    "验收主题或验收条件已经改变："
                    f"{format_registered_differences(differences)}"
                ),
                affected_topics=_affected_topics_from_changes(
                    project_root, topics, "acceptance_plan", differences
                ),
                detail_differences=[("验收计划文档", differences)],
            )

    expected = state.verification.impl_hash
    if expected is not None:
        current = compute_impl_hash(project_root, topics)
        if current != expected:
            try:
                impl_snapshot = stored.get("impl_actual") or stored.get("impl")
                if isinstance(impl_snapshot, dict) and isinstance(
                    impl_snapshot.get("files"), list
                ):
                    code_differences = compare_complete_implementation_file_snapshot(
                        project_root,
                        impl_snapshot,
                        scope="product",
                    )
                else:
                    code_differences = compare_registered_file_snapshot(
                        project_root, impl_snapshot, scope="product"
                    )
            except ValueError:
                code_differences = {
                    "added": [], "modified": [], "deleted": [], "type_changed": [],
                    "not_checked": _active_registered_paths(project_root) or [],
                }
            document_paths = [
                artifact_paths_mod.IMPL_INDEX_DOC,
                *[topic_paths(project_root, topic)["impl_doc"] for topic in topics],
            ]
            document_differences = _compare_recorded_snapshot(
                project_root, stored.get("impl_documents"), document_paths
            )
            affected = _affected_topics_from_changes(
                project_root, topics, "impl", code_differences, document_differences
            )
            record_change(
                source_stage="impl",
                expected_hash=expected,
                actual_hash=current,
                reason=(
                    "实施绑定内容变化。核心代码："
                    f"{format_registered_differences(code_differences)}；实施文档："
                    f"{format_registered_differences(document_differences)}"
                ),
                affected_topics=affected,
                detail_differences=[
                    ("核心代码", code_differences),
                    ("实施文档", document_differences),
                ],
            )

    expected = state.verification.test_plan_hash
    if expected is not None:
        current = compute_test_plan_hash(project_root, topics)
        if current != expected:
            differences = _compare_test_plan_document_snapshot(
                project_root, stored.get("test_plan_documents"), topics
            )
            record_change(
                source_stage="test_plan",
                expected_hash=expected,
                actual_hash=current,
                reason=(
                    "测试范围或测试计划已经改变："
                    f"{format_registered_differences(differences)}"
                ),
                affected_topics=_affected_topics_from_changes(
                    project_root, topics, "test_plan", differences
                ),
                detail_differences=[("测试计划文档", differences)],
                recovery_step="scope",
            )

    expected = state.verification.test_code_hash
    if expected is not None:
        current = compute_test_code_snapshot_hash(project_root)
        if current != expected:
            try:
                test_snapshot = stored.get("test_code_actual") or stored.get("test_code")
                if isinstance(test_snapshot, dict) and isinstance(
                    test_snapshot.get("files"), list
                ):
                    differences = compare_complete_implementation_file_snapshot(
                        project_root,
                        test_snapshot,
                        scope="test",
                    )
                else:
                    differences = compare_registered_file_snapshot(
                        project_root, test_snapshot, scope="test"
                    )
            except ValueError:
                differences = {
                    "added": [], "modified": [], "deleted": [], "type_changed": [],
                    "not_checked": _active_registered_paths(project_root) or [],
                }
            entry_known = "test_entry_config" in stored
            current_entry = _current_test_entry_config(project_root)
            entry_changed = entry_known and stored.get("test_entry_config") != current_entry
            if entry_changed:
                try:
                    affected_items = tuple(
                        (item.topic, item.test_id)
                        for item in automated_test_items(project_root, topics)
                    )
                except (OSError, ValueError):
                    affected_items = None
            else:
                affected_items = _affected_test_items_from_changes(
                    project_root,
                    topics,
                    differences,
                    stored.get("test_item_paths"),
                )
                if affected_items is None and "test_item_paths" not in stored:
                    # 旧状态没有逐文件到 TC 的映射，只能保守影响当前主题全部自动化测试项。
                    affected_items = tuple(
                        (item.topic, item.test_id)
                        for item in automated_test_items(project_root, topics)
                    )
            affected = (
                tuple(
                    topic
                    for topic in topics
                    if affected_items is not None
                    and any(item_topic == topic for item_topic, _test_id in affected_items)
                )
                if affected_items is not None
                else None
            )
            extra: list[diagnostics_mod.Diagnostic] = []
            parent = "invalidation.test_code.binding"
            if entry_changed:
                extra.append(
                    diagnostics_mod.Diagnostic(
                        kind="error",
                        check_id="invalidation.test_code.test_entry",
                        location=".workflow_loop/project.json#test_entry",
                        expected="项目统一测试入口与 QA 确认时一致",
                        actual="统一测试入口已变化",
                        evidence=(
                            f"saved={stored.get('test_entry_config')!r}; current={current_entry!r}"
                        ),
                        impact="所有主题的旧测试机器记录都不能代表当前入口",
                        next_action="在 qa 的测试代码步骤重新核对全部主题",
                        depends_on=parent,
                    )
                )
            if affected_items is not None:
                extra.extend(_test_item_change_diagnostics(affected_items, differences))
            if not entry_known:
                affected = None
                affected_items = None
                extra.append(
                    diagnostics_mod.Diagnostic(
                        kind="not_checked",
                        check_id="invalidation.test_code.test_entry.not_checked",
                        location=".workflow_loop/state.json#meta.registered_snapshots.test_entry_config",
                        expected="存在 QA 确认时的统一测试入口基线",
                        actual="未检查：旧状态没有该基线",
                        evidence="test_code_hash 包含入口配置，但旧快照未单独保存",
                        impact="不能排除公共入口同时变化",
                        next_action="重建测试代码和统一入口基线",
                        depends_on=parent,
                    )
                )
            record_change(
                source_stage="test_code",
                expected_hash=expected,
                actual_hash=current,
                reason=(
                    "登记的测试文件、测试配置或统一测试入口已改变："
                    f"{format_registered_differences(differences)}"
                ),
                affected_topics=affected,
                affected_test_items=affected_items or (),
                detail_differences=[("测试代码", differences)],
                extra_diagnostics=extra,
                recovery_step="test_code",
            )

    expected = state.verification.test_result_hash
    if expected is not None:
        current = compute_test_result_hash(project_root, topics, state=state)
        if current != expected:
            result_paths = [
                topic_paths(project_root, topic)["test_result"]
                for topic in automated_topics(project_root, topics)
            ]
            document_differences = _compare_recorded_snapshot(
                project_root, stored.get("test_result_documents"), result_paths
            )
            document_topics = _affected_topics_from_changes(
                project_root, topics, "test_execution", document_differences
            )
            current_tasks = test_tasks_payload(state, topics)
            task_topics = _payload_changed_topics(
                stored.get("test_task_records"), current_tasks, topics
            )
            if task_topics is None or document_topics is None:
                affected = None
            else:
                changed = set(document_topics) | set(task_topics)
                affected = tuple(topic for topic in topics if topic in changed)
                if not affected:
                    affected = None
            parent = "invalidation.test_execution.binding"
            extra = (
                _state_change_diagnostics(
                    source_stage="test_execution",
                    scope_name="测试机器记录",
                    location=".workflow_loop/state.json#stages.qa.test_tasks",
                    changed_topics=task_topics,
                    parent_check_id=parent,
                )
                if task_topics is not None
                else [
                    diagnostics_mod.Diagnostic(
                        kind="not_checked",
                        check_id="invalidation.test_execution.machine_records.not_checked",
                        location=".workflow_loop/state.json#meta.registered_snapshots.test_task_records",
                        expected="存在 QA 确认时的测试机器记录基线",
                        actual="未检查：旧状态没有该基线",
                        evidence="结果绑定包含机器记录，但旧快照未单独保存",
                        impact="不能区分结果文档整理错误和机器记录失效",
                        next_action="重建 QA 机器记录基线",
                        depends_on=parent,
                    )
                ]
            )
            machine_changed = bool(task_topics)
            documents_changed = bool(_changed_paths(document_differences))
            record_change(
                source_stage="test_execution",
                expected_hash=expected,
                actual_hash=current,
                reason=(
                    "主题测试结果或机器记录已改变："
                    f"{format_registered_differences(document_differences)}"
                ),
                affected_topics=affected,
                detail_differences=[("测试结果文档", document_differences)],
                extra_diagnostics=extra,
                recovery_step="execution" if machine_changed else "result",
                result_documents_only=documents_changed and not machine_changed,
                machine_records_changed=machine_changed,
            )

    expected = state.verification.acceptance_result_hash
    if expected is not None:
        current = compute_acceptance_result_hash(project_root, topics, state=state)
        if current != expected:
            result_paths = [
                topic_paths(project_root, topic)["acceptance_result"] for topic in topics
            ]
            document_differences = _compare_recorded_snapshot(
                project_root, stored.get("acceptance_result_documents"), result_paths
            )
            document_topics = _affected_topics_from_changes(
                project_root, topics, "topic_acceptance", document_differences
            )
            current_records = acceptance_records_mod.acceptance_records_payload(state, topics)
            record_topics = _payload_changed_topics(
                stored.get("acceptance_records"), current_records, topics
            )
            if record_topics is None or document_topics is None:
                affected = None
            else:
                changed = set(document_topics) | set(record_topics)
                affected = tuple(topic for topic in topics if topic in changed) or None
            parent = "invalidation.topic_acceptance.binding"
            extra = (
                _state_change_diagnostics(
                    source_stage="topic_acceptance",
                    scope_name="验收机器记录",
                    location=".workflow_loop/state.json#stages.topic_acceptance.acceptance_records",
                    changed_topics=record_topics,
                    parent_check_id=parent,
                )
                if record_topics is not None
                else []
            )
            record_change(
                source_stage="topic_acceptance",
                expected_hash=expected,
                actual_hash=current,
                reason=(
                    "主题验收结果或验收机器记录已改变："
                    f"{format_registered_differences(document_differences)}"
                ),
                affected_topics=affected,
                detail_differences=[("验收结果文档", document_differences)],
                extra_diagnostics=extra,
            )

    expected = state.verification.regression_test_result_hash
    if expected is not None:
        payload = json.dumps(state.regression_test.__dict__, ensure_ascii=False, sort_keys=True)
        current = hashlib.sha256(payload.encode("utf-8")).hexdigest()
        code_changed = (
            state.regression_test.code_snapshot_hash
            != compute_code_snapshot_hash(project_root)
        )
        if current != expected or code_changed:
            if code_changed:
                try:
                    differences = compare_registered_file_snapshot(
                        project_root, stored.get("regression_test"), scope="all"
                    )
                except ValueError:
                    differences = {
                        "added": [], "modified": [], "deleted": [], "type_changed": [],
                        "not_checked": _active_registered_paths(project_root) or [],
                    }
                affected = _affected_topics_from_changes(
                    project_root, topics, "regression_test", differences
                )
                details = [("回归绑定代码", differences)]
                reason = (
                    "全量回归后登记文件发生变化："
                    f"{format_registered_differences(differences)}"
                )
            else:
                affected = tuple(topics)
                details = []
                reason = "全量回归机器状态已经改变"
            record_change(
                source_stage="regression_test",
                expected_hash=expected,
                actual_hash=current,
                reason=reason,
                affected_topics=affected,
                detail_differences=details,
            )

    if not findings and not blocked:
        return InvalidationInspection()

    order = {name: index for index, (name, _field) in enumerate(_INVALIDATION_ORDER)}
    source_candidates = (
        [finding.source_stage for finding in findings]
        if findings
        else [source for source, _reason, _diagnostics in blocked]
    )
    source_stage = min(source_candidates, key=lambda name: order[name])
    all_diagnostics = [
        diagnostic
        for finding in findings
        for diagnostic in finding.diagnostics
    ] + [
        diagnostic
        for _source, _reason, diagnostics in blocked
        for diagnostic in diagnostics
    ]
    affected_stage_set = {
        stage_name
        for finding in findings
        for stage_name in _invalidation_affected_stages(state, finding.source_stage)
    }
    affected_stages = tuple(
        stage_name for stage_name in state.stage_path if stage_name in affected_stage_set
    )
    affected_topic_set = {
        topic for finding in findings for topic in finding.affected_topics
    }
    affected_topics = tuple(topic for topic in topics if topic in affected_topic_set)
    affected_test_items = tuple(
        item
        for finding in findings
        for item in finding.affected_test_items
    )
    reasons = [finding.reason for finding in findings] + [
        reason for _source, reason, _diagnostics in blocked
    ]
    descriptions = list(
        dict.fromkeys(
            _INVALIDATION_DESCRIPTIONS[finding.source_stage] for finding in findings
        )
    )
    if blocked:
        descriptions.append("存在无法定位主题的变化，本次不自动清理")
    return InvalidationInspection(
        source_stage=source_stage,
        affected_stages=affected_stages,
        affected_topics=affected_topics,
        affected_test_items=tuple(dict.fromkeys(affected_test_items)),
        affected_description="；".join(descriptions),
        reason="；".join(reasons),
        diagnostics=tuple(all_diagnostics),
        findings=tuple(findings),
        blocked=bool(blocked),
    )




def _qa_recovery_step(findings: tuple[InvalidationFinding, ...]) -> str:
    priorities = {"scope": 0, "test_code": 1, "execution": 2, "result": 3}
    steps: list[str] = []
    for finding in findings:
        if finding.source_stage in {"acceptance_plan", "impl", "test_plan"}:
            steps.append("scope")
        elif finding.source_stage == "test_code":
            steps.append("test_code")
        elif finding.source_stage == "test_execution":
            steps.append(finding.recovery_step or "execution")
    return min(steps, key=lambda step: priorities[step]) if steps else "scope"


def _reset_qa_stage_for_invalidation(stage: StageState, step: str) -> None:
    """只清掉 QA 中真实失效的内部步骤，保留更上游的确认。"""
    stage.status = "pending"
    stage.gate.code_validated = False
    stage.gate.user_confirmed = False
    stage.validation_credential = None
    stage.result_hash = None
    stage.internal_step_hash = None
    stage.internal_step = step
    if step == "scope":
        stage.gate.discussion_complete = False
        stage.scope_confirmed_hash = None
        stage.test_code_baseline_hash = None
        stage.non_test_code_baseline_hash = None
        stage.existing_test_code_accepted_hash = None
        stage.reuse_decision_hash = None
    else:
        stage.gate.discussion_complete = bool(stage.scope_confirmed_hash)
        if step == "test_code":
            stage.test_code_baseline_hash = None
            stage.non_test_code_baseline_hash = None
            stage.existing_test_code_accepted_hash = None
            stage.reuse_decision_hash = None


_HASHES_CLEARED_BY_SOURCE = {
    "acceptance_plan": (
        "acceptance_plan_hash", "impl_hash", "test_plan_hash", "test_code_hash",
        "test_result_hash", "acceptance_result_hash", "regression_test_result_hash",
    ),
    "impl": (
        "impl_hash", "test_plan_hash", "test_code_hash", "test_result_hash",
        "acceptance_result_hash", "regression_test_result_hash",
    ),
    "test_plan": (
        "test_plan_hash", "test_code_hash", "test_result_hash",
        "acceptance_result_hash", "regression_test_result_hash",
    ),
    "test_code": (
        "test_code_hash", "test_result_hash", "acceptance_result_hash",
        "regression_test_result_hash",
    ),
    "test_execution": (
        "test_result_hash", "acceptance_result_hash", "regression_test_result_hash",
    ),
    "topic_acceptance": ("acceptance_result_hash", "regression_test_result_hash"),
    "regression_test": ("regression_test_result_hash",),
}


def _remove_topic_result_files(
    project_root: str,
    topics: list[str],
    *kinds: str,
) -> None:
    for topic in topics:
        paths = topic_paths(project_root, topic)
        for kind in kinds:
            result_path = os.path.join(project_root, paths[kind])
            if os.path.isfile(result_path):
                os.remove(result_path)


def apply_invalidation(
    state: WorkflowState,
    project_root: str,
    inspection: InvalidationInspection,
) -> list[tuple[str, str]]:
    """完成所有只读比较后，按每个变化源的直接证据一次应用。"""
    if not inspection.findings or inspection.source_stage is None:
        return []

    source_order = {
        source_stage: index
        for index, (source_stage, _field_name) in enumerate(_INVALIDATION_ORDER)
    }
    applied_source = min(
        (finding.source_stage for finding in inspection.findings),
        key=lambda source_stage: source_order[source_stage],
    )
    applied_reason = "；".join(finding.reason for finding in inspection.findings)

    affected_stage_set = set(inspection.affected_stages)
    qa_step = _qa_recovery_step(inspection.findings)
    for stage_name in inspection.affected_stages:
        stage = state.stages.get(stage_name)
        if stage is None:
            continue
        if stage_name == "qa":
            _reset_qa_stage_for_invalidation(stage, qa_step)
        else:
            clear_stage_gates(stage)

    ordered_affected_stages = [
        stage_name
        for stage_name in state.stage_path
        if stage_name in affected_stage_set
    ]
    if ordered_affected_stages:
        state.current_stage = ordered_affected_stages[0]
        state.stages[state.current_stage].status = "in_progress"

    for finding in inspection.findings:
        for field_name in _HASHES_CLEARED_BY_SOURCE[finding.source_stage]:
            setattr(state.verification, field_name, None)

    traceability_exists = os.path.isfile(
        os.path.join(project_root, artifact_paths_mod.TRACEABILITY_DOC)
    )
    regression_invalidated = False
    for finding in inspection.findings:
        source = finding.source_stage
        topics = list(finding.affected_topics)
        if traceability_exists:
            traceability_mod.reset_topics_for_return(
                project_root,
                state.workflow_id,
                topics,
                source,
            )

        if source in {"acceptance_plan", "impl", "test_plan", "test_code"}:
            if source == "test_code" and finding.affected_test_items:
                _invalidate_test_execution_outputs(
                    project_root,
                    state,
                    topics,
                    list(finding.affected_test_items),
                )
            else:
                _invalidate_test_execution_outputs(project_root, state, topics)
            regression_invalidated = True
        elif source == "test_execution":
            qa_state = state.stages.get("qa") or state.stages.get("test_execution")
            if finding.machine_records_changed and qa_state is not None:
                for topic in topics:
                    qa_state.test_tasks.pop(topic, None)
            _remove_topic_result_files(
                project_root,
                topics,
                "test_result",
                "acceptance_result",
            )
            acceptance_records_mod.clear_topic_records(project_root, state, topics)
            state.regression_test = RegressionTestState()
            regression_invalidated = True
        elif source == "topic_acceptance":
            _remove_topic_result_files(project_root, topics, "acceptance_result")
            acceptance_records_mod.clear_topic_records(project_root, state, topics)
            state.regression_test = RegressionTestState()
            regression_invalidated = True
        elif source == "regression_test":
            state.regression_test = RegressionTestState()
            regression_invalidated = True

    if regression_invalidated and traceability_exists:
        traceability_mod.reset_topics_for_return(
            project_root,
            state.workflow_id,
            list(state.topics or ([state.topic] if state.topic else [])),
            "regression_test",
        )

    set_recovery_context(
        state,
        applied_source,
        ordered_affected_stages,
        applied_reason,
    )
    state.recovery.affected_topics = list(inspection.affected_topics)
    return [
        (finding.source_stage, _INVALIDATION_DESCRIPTIONS[finding.source_stage])
        for finding in inspection.findings
    ]


# 兼容原调用：先只读检查，再一次应用。需要展示完整诊断的命令层应分别调用
# inspect_invalidation（检查失效）和 apply_invalidation（应用失效）。
def check_invalidation(state: WorkflowState, project_root: str) -> list[tuple[str, str]]:
    inspection = inspect_invalidation(state, project_root)
    return apply_invalidation(state, project_root, inspection)
