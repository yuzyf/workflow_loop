"""主题验收的结构化记录和当前有效性检查。"""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import asdict

from . import artifact_paths as artifact_paths_mod
from . import state as state_mod
from .test_mapping import TestPlanItem, parse_test_plan_items
from .topic import topic_paths
from .topic_relations import read_topic_index


ACCEPTANCE_METHODS = {"自动化测试", "人工验收", "自动化测试 + 人工验收"}
RESULT_CHOICES = {"passed", "failed", "blocked"}


def compute_record_id(record: state_mod.AcceptanceCriterionRecord) -> str:
    payload = asdict(record)
    payload["record_id"] = None
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _criterion_groups(project_root: str, topic: str) -> dict[str, list[TestPlanItem]]:
    groups: dict[str, list[TestPlanItem]] = {}
    for item in parse_test_plan_items(project_root, topic):
        groups.setdefault(item.criterion_id, []).append(item)
    return groups


def criterion_methods(project_root: str, topic: str) -> dict[str, str]:
    """按一条 AC 的全部测试项归并最终验收方式。"""
    methods: dict[str, str] = {}
    for criterion_id, items in _criterion_groups(project_root, topic).items():
        item_methods = {item.test_method for item in items}
        if item_methods == {"自动化测试"}:
            method = "自动化测试"
        elif item_methods == {"人工验收"}:
            method = "人工验收"
        else:
            method = "自动化测试 + 人工验收"
        methods[criterion_id] = method
    return methods


def criterion_names(project_root: str, topic: str) -> dict[str, str]:
    return {
        criterion_id: items[0].criterion_name
        for criterion_id, items in _criterion_groups(project_root, topic).items()
    }


def automated_test_ids(project_root: str, topic: str, criterion_id: str) -> list[str]:
    return [
        item.test_id
        for item in _criterion_groups(project_root, topic).get(criterion_id, [])
        if item.requires_test_code
    ]


def record_is_current(
    record: state_mod.AcceptanceCriterionRecord,
    wf_state: state_mod.WorkflowState,
) -> bool:
    """判断当前主题记录是否仍被程序保留为有效。

    上游全局哈希只用于发现变化和触发清理，不能直接拿来让所有主题一起失效。
    用户只退回一个主题时，程序已经清理该主题及其依赖主题；没有被清理的独立
    主题应继续保留当前验收记录。

    自动化或混合记录还必须逐项指向当前任务的精确机器记录编号；
    执行记录被替换后，旧验收记录不能继续通过。旧记录缺少编号时同样失效。
    """
    if record.result != "passed" or record.record_id != compute_record_id(record):
        return False
    if record.method in ("自动化测试", "自动化测试 + 人工验收") and record.test_ids:
        tasks = wf_state.stages.get(
            "test_execution",
            state_mod.StageState(),
        ).test_tasks.get(record.topic, {})
        current_ids: list[str] = []
        for test_id in record.test_ids:
            task = tasks.get(test_id)
            if (
                task is None
                or task.current_record is None
                or task.current_record.status != "passed"
                or not task.current_record.record_id
            ):
                return False
            current_ids.append(task.current_record.record_id)
        if not record.test_record_ids:
            return False
        if sorted(current_ids) != sorted(record.test_record_ids):
            return False
    return True


def _automated_items_are_current(
    wf_state: state_mod.WorkflowState,
    topic: str,
    test_ids: list[str],
) -> tuple[bool, str, list[str]]:
    """核对每个测试项当前机器记录有效，并返回精确记录编号列表。"""
    stage_state = wf_state.stages.get("test_execution")
    if stage_state is None:
        return False, "缺少 test_execution（测试执行阶段）状态", []
    tasks = stage_state.test_tasks.get(topic, {})
    record_ids: list[str] = []
    for test_id in test_ids:
        task = tasks.get(test_id)
        if task is None or task.status != "passed" or task.current_record is None:
            return False, f"{topic} / {test_id} 没有当前有效的通过记录", []
        record = task.current_record
        if record.status != "passed" or record.exit_code != 0:
            return False, f"{topic} / {test_id} 当前测试记录不是通过状态", []
        if not record.record_id:
            return False, f"{topic} / {test_id} 的执行记录缺少机器记录编号，必须重新执行", []
        record_ids.append(record.record_id)
    return True, "", record_ids


def _topic_relations(project_root: str, wf_state: state_mod.WorkflowState):
    return read_topic_index(
        project_root,
        artifact_paths_mod.ACCEPTANCE_INDEX_DOC,
        wf_state.workflow_id,
        ["展示顺序", "验收主题", "前置主题", "验收计划", "主题验收结果"],
    )


def topic_records_complete(
    project_root: str,
    wf_state: state_mod.WorkflowState,
    topic: str,
) -> bool:
    methods = criterion_methods(project_root, topic)
    records = wf_state.stages.get(
        "topic_acceptance",
        state_mod.StageState(),
    ).acceptance_records.get(topic, {})
    return bool(methods) and set(records) == set(methods) and all(
        records[criterion_id].method == method
        and record_is_current(records[criterion_id], wf_state)
        for criterion_id, method in methods.items()
    )


def incomplete_prerequisites(
    project_root: str,
    wf_state: state_mod.WorkflowState,
    topic: str,
) -> list[str]:
    relations = {relation.topic: relation for relation in _topic_relations(project_root, wf_state)}
    relation = relations.get(topic)
    if relation is None:
        return [f"验收索引缺少主题：{topic}"]
    return [
        prerequisite
        for prerequisite in relation.prerequisites
        if not topic_records_complete(project_root, wf_state, prerequisite)
    ]


def ensure_automated_records(
    project_root: str,
    wf_state: state_mod.WorkflowState,
) -> list[state_mod.AcceptanceCriterionRecord]:
    """为纯自动化 AC 建立当前有效记录，不替代人工验收。"""
    stage_state = wf_state.stages.get("topic_acceptance")
    if stage_state is None:
        return []
    created: list[state_mod.AcceptanceCriterionRecord] = []
    for relation in _topic_relations(project_root, wf_state):
        if incomplete_prerequisites(project_root, wf_state, relation.topic):
            continue
        methods = criterion_methods(project_root, relation.topic)
        topic_records = stage_state.acceptance_records.setdefault(relation.topic, {})
        for criterion_id, method in methods.items():
            if method != "自动化测试":
                continue
            existing = topic_records.get(criterion_id)
            if existing is not None and record_is_current(existing, wf_state):
                continue
            test_ids = automated_test_ids(project_root, relation.topic, criterion_id)
            current, detail, machine_record_ids = _automated_items_are_current(
                wf_state,
                relation.topic,
                test_ids,
            )
            if not current:
                continue
            record = state_mod.AcceptanceCriterionRecord(
                topic=relation.topic,
                criterion_id=criterion_id,
                method=method,
                result="passed",
                actual_result=f"对应自动化测试项均有当前有效通过记录：{', '.join(test_ids)}",
                user_answer=None,
                evidence=topic_paths(project_root, relation.topic)["test_result"],
                confirmed_at=state_mod.now_iso(),
                acceptance_plan_hash=wf_state.verification.acceptance_plan_hash,
                impl_hash=wf_state.verification.impl_hash,
                test_result_hash=wf_state.verification.test_result_hash,
                test_ids=test_ids,
                test_record_ids=machine_record_ids,
            )
            record.record_id = compute_record_id(record)
            topic_records[criterion_id] = record
            created.append(record)
    return created


def record_user_result(
    project_root: str,
    wf_state: state_mod.WorkflowState,
    *,
    topic: str,
    criterion_id: str,
    result: str,
    actual_result: str,
    user_answer: str,
    evidence: str,
) -> state_mod.AcceptanceCriterionRecord:
    if result not in RESULT_CHOICES:
        raise ValueError(f"验收结果必须是 {sorted(RESULT_CHOICES)}")
    if topic not in wf_state.topics:
        raise ValueError(f"主题不属于当前工作流：{topic}")
    methods = criterion_methods(project_root, topic)
    method = methods.get(criterion_id)
    if method is None:
        raise ValueError(f"{topic} 没有验收条件 {criterion_id}")
    if method == "自动化测试":
        raise ValueError(f"{topic} / {criterion_id} 是纯自动化条件，不需要用户重复确认")
    prerequisites = incomplete_prerequisites(project_root, wf_state, topic)
    if prerequisites:
        raise ValueError(f"前置主题尚未验收通过：{prerequisites}")
    test_ids = automated_test_ids(project_root, topic, criterion_id)
    machine_record_ids: list[str] = []
    if method == "自动化测试 + 人工验收":
        current, detail, machine_record_ids = _automated_items_are_current(
            wf_state,
            topic,
            test_ids,
        )
        if not current:
            raise ValueError(detail)
    if not actual_result.strip():
        raise ValueError("必须记录用户实际观察到的结果")
    if not user_answer.strip():
        raise ValueError("必须记录用户实际回答")

    record = state_mod.AcceptanceCriterionRecord(
        topic=topic,
        criterion_id=criterion_id,
        method=method,
        result=result,
        actual_result=actual_result.strip(),
        user_answer=user_answer.strip(),
        evidence=evidence.strip() or actual_result.strip(),
        confirmed_at=state_mod.now_iso(),
        acceptance_plan_hash=wf_state.verification.acceptance_plan_hash,
        impl_hash=wf_state.verification.impl_hash,
        test_result_hash=wf_state.verification.test_result_hash,
        test_ids=test_ids,
        test_record_ids=machine_record_ids,
    )
    record.record_id = compute_record_id(record)
    stage_state = wf_state.stages["topic_acceptance"]
    if result == "passed":
        stage_state.acceptance_records.setdefault(topic, {})[criterion_id] = record
    else:
        stage_state.acceptance_records.pop(topic, None)
        result_path = os.path.join(
            project_root,
            topic_paths(project_root, topic)["acceptance_result"],
        )
        if os.path.isfile(result_path):
            os.remove(result_path)
    return record


def clear_topic_records(
    project_root: str,
    wf_state: state_mod.WorkflowState,
    topics: list[str],
) -> None:
    stage_state = wf_state.stages.get("topic_acceptance")
    if stage_state is not None:
        for topic in topics:
            stage_state.acceptance_records.pop(topic, None)
    for topic in topics:
        result_path = os.path.join(
            project_root,
            topic_paths(project_root, topic)["acceptance_result"],
        )
        if os.path.isfile(result_path):
            os.remove(result_path)


def acceptance_records_payload(
    wf_state: state_mod.WorkflowState,
    topics: list[str],
) -> dict:
    stage_state = wf_state.stages.get("topic_acceptance")
    records = stage_state.acceptance_records if stage_state is not None else {}
    return {
        topic: {
            criterion_id: asdict(record)
            for criterion_id, record in sorted(records.get(topic, {}).items())
        }
        for topic in topics
    }


def acceptance_progress(
    project_root: str,
    wf_state: state_mod.WorkflowState,
) -> list[str]:
    lines: list[str] = []
    stage_state = wf_state.stages.get("topic_acceptance", state_mod.StageState())
    for topic in wf_state.topics:
        methods = criterion_methods(project_root, topic)
        records = stage_state.acceptance_records.get(topic, {})
        remaining = [
            criterion_id
            for criterion_id in methods
            if criterion_id not in records or not record_is_current(records[criterion_id], wf_state)
        ]
        if remaining:
            lines.append(f"{topic}: 待验收 {remaining}")
        else:
            lines.append(f"{topic}: 验收条件已全部通过，待生成或复核主题结果文件")
    return lines
