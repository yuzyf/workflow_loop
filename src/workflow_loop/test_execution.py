"""测试执行阶段的任务登记、依赖调度和安全子进程执行。"""

from __future__ import annotations

import hashlib
import os
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass

from . import artifact_paths as artifact_paths_mod
from . import journal as journal_mod
from . import process_runner as process_runner_mod
from . import state as state_mod
from . import test_mapping
from . import traceability as traceability_mod
from . import verification
from .project import DEFAULT_TEST_PARALLELISM, load_project
from .state import TestExecutionRecord, TestTaskState, WorkflowState, now_iso
from .topic import topic_paths
from .topic_relations import read_topic_index


FORBIDDEN_SHELL_TOKENS = ("|", "&&", ";", ">", "<", "$(", "`")
INLINE_CODE_FLAGS = {"-c", "-e", "--eval", "--evaluate"}
DEFAULT_TIMEOUT_SECONDS = 600
SAFE_ENVIRONMENT_KEYS = {
    "CI",
    "GITHUB_ACTIONS",
    "PYTHON_VERSION",
    "NODE_ENV",
}


@dataclass(frozen=True)
class ExecutionAttempt:
    topic: str
    test_id: str
    status: str
    command: list[str]
    started_at: str
    finished_at: str
    duration_seconds: float
    exit_code: int | None
    output_tail: str
    error: str | None = None


def normalize_task_cwd(project_root: str, cwd: str | None) -> str:
    """校验并规范化项目内工作目录；返回相对项目根的路径（空串表示项目根）。"""
    if not cwd or cwd in (".", "./"):
        return ""
    candidate = cwd
    if not os.path.isabs(candidate):
        candidate = os.path.join(project_root, candidate)
    project_real = os.path.realpath(project_root)
    candidate_real = os.path.realpath(candidate)
    if os.path.commonpath([project_real, candidate_real]) != project_real:
        raise ValueError(f"测试工作目录必须在项目内: {cwd}")
    if not os.path.isdir(candidate_real):
        raise ValueError(f"测试工作目录不存在: {cwd}")
    relative = os.path.relpath(candidate_real, project_real)
    return "" if relative == "." else relative.replace(os.sep, "/")


def validate_command(argv: list[str]) -> tuple[bool, str]:
    """检查命令是否能以 shell=False 安全执行。"""
    if not argv:
        return False, "测试命令不能为空"
    for token in argv:
        if not isinstance(token, str) or not token.strip():
            return False, "测试命令参数必须是非空字符串"
        if any(operator in token for operator in FORBIDDEN_SHELL_TOKENS):
            return False, "测试命令不能包含管道、重定向、命令串联或命令替换"
    return True, ""


def _command_value_tokens(command: list[str]) -> set[str]:
    values = set(command)
    for token in command:
        if "=" in token:
            values.add(token.split("=", 1)[1])
    return values


def _entry_is_selected(entry: str, command_values: set[str]) -> bool:
    normalized_entry = entry.replace("\\", "/")
    parts = normalized_entry.split("::")
    path = parts[0]
    symbol = parts[-1] if len(parts) > 1 else ""
    candidates = {normalized_entry, path}
    if symbol:
        candidates.add(symbol)
    for value in command_values:
        normalized_value = value.replace("\\", "/").rstrip("/")
        if normalized_value in candidates:
            return True
        if normalized_value and path.startswith(normalized_value + "/"):
            return True
    return False


def validate_command_entries(command: list[str], entries: list[str]) -> tuple[bool, str]:
    """确认登记命令确实选择了当前 TC 的测试入口，而不是任意成功命令。"""
    if any(flag in command for flag in INLINE_CODE_FLAGS):
        return False, "测试命令不能使用 -c、-e 或 --eval 执行临时代码，必须运行真实测试入口"
    command_values = _command_value_tokens(command)
    missing = [entry for entry in entries if not _entry_is_selected(entry, command_values)]
    if missing:
        return False, f"测试命令没有明确选择当前测试入口: {missing}"
    return True, ""


def safe_environment() -> dict[str, str]:
    """只记录少量不含密钥的环境事实，避免把整个环境写进 state.json。"""
    return {
        "platform": sys.platform,
        "python": sys.version.split()[0],
        **{
            key: os.environ[key]
            for key in sorted(SAFE_ENVIRONMENT_KEYS)
            if os.environ.get(key)
        },
    }


def _markers_by_test(project_root: str, topics: list[str]) -> dict[tuple[str, str], list[str]]:
    markers = test_mapping.collect_workflow_test_markers(project_root, topics)
    result: dict[tuple[str, str], list[str]] = {}
    for marker in markers:
        key = (marker.topic, marker.test_id)
        result.setdefault(key, []).append(marker.test_entry)
    return result


def prepare_task(
    project_root: str,
    workflow_state: WorkflowState,
    topic: str,
    test_id: str,
    command: list[str],
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
    cwd: str | None = None,
) -> TestTaskState:
    """登记一个已经由用户确认过的测试项命令；登记不启动测试。"""
    valid, detail = validate_command(command)
    if not valid:
        raise ValueError(detail)
    if timeout_seconds <= 0:
        raise ValueError("测试超时时间必须大于 0 秒")
    if topic not in workflow_state.topics:
        raise ValueError(f"主题不属于当前工作流: {topic}")
    normalized_cwd = normalize_task_cwd(project_root, cwd)

    items = test_mapping.parse_test_plan_items(project_root, topic)
    item = next((candidate for candidate in items if candidate.test_id == test_id), None)
    if item is None:
        raise ValueError(f"{topic} 的测试计划没有 {test_id}")
    if not item.requires_test_code:
        raise ValueError(f"{topic} / {test_id} 不是自动化或混合测试项，不需要登记自动化命令")

    marker_ok, marker_detail = test_mapping.validate_workflow_test_markers(
        project_root,
        [topic],
    )
    if not marker_ok:
        raise ValueError(marker_detail)
    entries = _markers_by_test(project_root, [topic]).get((topic, test_id), [])
    if not entries:
        raise ValueError(f"{topic} / {test_id} 没有可追踪的测试入口")
    entries_ok, entries_detail = validate_command_entries(command, entries)
    if not entries_ok:
        raise ValueError(f"{topic} / {test_id}: {entries_detail}")

    stage_state = workflow_state.stages.get("test_execution")
    if stage_state is None:
        raise ValueError("当前工作流没有 test_execution 阶段")
    stage_state.test_tasks.setdefault(topic, {})[test_id] = TestTaskState(
        test_entries=sorted(set(entries)),
        command=list(command),
        cwd=normalized_cwd,
        dependencies=list(item.dependencies),
        timeout_seconds=timeout_seconds,
        status="pending",
        prepared_at=now_iso(),
        last_error=None,
        current_record=None,
    )
    return stage_state.test_tasks[topic][test_id]


def missing_prepared_tasks(
    project_root: str,
    workflow_state: WorkflowState,
) -> list[str]:
    """返回所有需要自动执行但尚未登记命令的主题/测试项。"""
    missing: list[str] = []
    for item in test_mapping.automated_test_items(project_root, workflow_state.topics):
        task = workflow_state.stages.get("test_execution", state_mod.StageState()).test_tasks.get(
            item.topic,
            {},
        ).get(item.test_id)
        if task is None:
            missing.append(f"{item.topic} / {item.test_id}")
    return missing


def validate_prepared_tasks(
    project_root: str,
    workflow_state: WorkflowState,
) -> tuple[bool, str]:
    """核对登记任务与当前测试计划、依赖和 Workflow-Test 入口完全一致。"""
    stage_state = workflow_state.stages.get("test_execution")
    if stage_state is None:
        return False, "当前工作流没有 test_execution 阶段"
    try:
        expected_items = test_mapping.automated_test_items(
            project_root,
            workflow_state.topics,
        )
        marker_ok, marker_detail = test_mapping.validate_workflow_test_markers(
            project_root,
            workflow_state.topics,
        )
    except ValueError as exc:
        return False, str(exc)
    if not marker_ok:
        return False, marker_detail

    expected = {(item.topic, item.test_id): item for item in expected_items}
    actual = {
        (topic, test_id): task
        for topic, tasks in stage_state.test_tasks.items()
        for test_id, task in tasks.items()
    }
    missing = sorted(set(expected) - set(actual))
    extra = sorted(set(actual) - set(expected))
    if missing:
        return False, f"尚未登记测试命令: {[f'{topic} / {test_id}' for topic, test_id in missing]}"
    if extra:
        return False, f"登记了当前测试计划不存在的测试任务: {extra}"

    current_entries = _markers_by_test(project_root, workflow_state.topics)
    for key, item in expected.items():
        task = actual[key]
        command_ok, command_detail = validate_command(task.command)
        if not command_ok:
            return False, f"{item.topic} / {item.test_id}: {command_detail}"
        if task.timeout_seconds <= 0:
            return False, f"{item.topic} / {item.test_id} 的超时时间必须大于 0 秒"
        try:
            normalize_task_cwd(project_root, task.cwd or None)
        except ValueError as exc:
            return False, f"{item.topic} / {item.test_id}: {exc}"
        if tuple(task.dependencies) != item.dependencies:
            return False, f"{item.topic} / {item.test_id} 的登记依赖与当前测试计划不一致"
        expected_entries = sorted(set(current_entries.get(key, [])))
        if sorted(set(task.test_entries)) != expected_entries:
            return False, f"{item.topic} / {item.test_id} 的登记测试入口与当前测试代码不一致"
        entries_ok, entries_detail = validate_command_entries(task.command, expected_entries)
        if not entries_ok:
            return False, f"{item.topic} / {item.test_id}: {entries_detail}"
    return True, f"{len(expected)} 个自动化测试项的登记任务与当前计划和测试代码一致"


def _record_id_for(attempt_result: process_runner_mod.ProcessResult, topic: str, test_id: str) -> str:
    """测试机器记录编号：可从结果文档逐字段回查状态快照。"""
    payload = (
        f"{topic}|{test_id}|{attempt_result.started_at}|{attempt_result.finished_at}|"
        f"{attempt_result.exit_code}|{attempt_result.output_sha256}"
    )
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()[:8]
    compact_time = (attempt_result.started_at or "").replace(":", "").replace("-", "")
    return f"RUN-{compact_time}-{digest}"


def _run_one(
    project_root: str,
    topic: str,
    test_id: str,
    task: TestTaskState,
    code_hash: str,
    test_hash: str,
) -> tuple[ExecutionAttempt, process_runner_mod.ProcessResult]:
    """通过共同受控执行器运行一个测试项，返回尝试摘要和完整机器事实。"""
    cwd = os.path.join(project_root, task.cwd) if task.cwd else project_root
    result = process_runner_mod.run_process(
        process_runner_mod.ProcessRequest(
            argv=list(task.command),
            cwd=cwd,
            timeout_seconds=task.timeout_seconds,
        )
    )
    if result.status == "passed":
        error = None
    elif result.status == "timeout":
        error = result.error_message
    elif result.status == "error":
        error = result.error_message or "启动测试命令失败"
    else:
        error = f"退出码为 {result.exit_code}"
    attempt = ExecutionAttempt(
        topic=topic,
        test_id=test_id,
        status=result.status if result.status != "error" else "unavailable",
        command=list(task.command),
        started_at=result.started_at,
        finished_at=result.finished_at,
        duration_seconds=result.duration_seconds,
        exit_code=result.exit_code,
        output_tail=result.output_tail,
        error=error,
    )
    return attempt, result


def _topic_execution_order(
    project_root: str,
    topic: str,
    tasks: dict[str, TestTaskState],
) -> list[str]:
    items = {item.test_id: item for item in test_mapping.parse_test_plan_items(project_root, topic)}
    ordered: list[str] = []
    visited: set[str] = set()

    def visit(test_id: str) -> None:
        if test_id in visited:
            return
        for dependency in items[test_id].dependencies:
            if dependency in tasks:
                visit(dependency)
        visited.add(test_id)
        ordered.append(test_id)

    for test_id in tasks:
        visit(test_id)
    return ordered


def _has_current_success(task: TestTaskState) -> bool:
    """判断任务是否已有可继续使用的当前成功记录。"""
    record = task.current_record
    return (
        task.status == "passed"
        and record is not None
        and record.status == "passed"
        and record.exit_code == 0
        and record.command == task.command
        and set(record.test_entries) == set(task.test_entries)
        and bool(record.code_snapshot_hash)
        and bool(record.test_code_hash)
    )


def _topic_prerequisites(
    project_root: str,
    workflow_state: WorkflowState,
    topics: set[str],
) -> tuple[list[str], dict[str, tuple[str, ...]]]:
    """读取 qa/索引.md 的主题顺序，只保留本阶段有自动化任务的前置主题。"""
    relations = read_topic_index(
        project_root,
        artifact_paths_mod.QA_INDEX_DOC,
        workflow_state.workflow_id,
        ["展示顺序", "验收主题", "前置主题", "验收计划", "测试计划", "测试结果"],
        {"测试结果": {"无自动化测试项"}},
    )
    ordered_topics = [relation.topic for relation in relations if relation.topic in topics]
    missing = sorted(topics - set(ordered_topics))
    if missing:
        raise ValueError(f"{artifact_paths_mod.QA_INDEX_DOC} 缺少需要执行自动化测试的主题: {missing}")
    prerequisites = {
        relation.topic: tuple(
            prerequisite
            for prerequisite in relation.prerequisites
            if prerequisite in topics
        )
        for relation in relations
        if relation.topic in topics
    }
    return ordered_topics, prerequisites


def run_prepared_tasks(
    project_root: str,
    workflow_state: WorkflowState,
    parallelism: int | None = None,
) -> list[ExecutionAttempt]:
    """按主题并行、主题内按 TC 依赖顺序执行已登记任务。"""
    stage_state = workflow_state.stages.get("test_execution")
    if stage_state is None:
        raise ValueError("当前工作流没有 test_execution 阶段")
    tasks_ok, tasks_detail = validate_prepared_tasks(project_root, workflow_state)
    if not tasks_ok:
        raise ValueError(tasks_detail)

    project = load_project(project_root)
    max_workers = parallelism or (
        project.test_parallelism if project is not None else DEFAULT_TEST_PARALLELISM
    )
    max_workers = max(1, int(max_workers))
    code_hash = verification.compute_non_test_code_snapshot_hash(project_root)
    test_hash = verification.compute_test_code_snapshot_hash(project_root)
    topic_tasks = {
        topic: tasks
        for topic, tasks in stage_state.test_tasks.items()
        if tasks
    }
    ordered_topics, topic_prerequisites = _topic_prerequisites(
        project_root,
        workflow_state,
        set(topic_tasks),
    )
    topics_to_run = [
        topic
        for topic in ordered_topics
        if any(not _has_current_success(task) for task in topic_tasks[topic].values())
    ]

    # 本主题要重新执行时，旧的正式结果已经不能代表本次代码状态。
    if topics_to_run:
        trace_detail = traceability_mod.reset_topic_test_results(
            project_root,
            workflow_state.workflow_id,
            topics_to_run,
        )
        journal_mod.append_entry(
            project_root,
            "主题测试追踪状态重置",
            "workflow.py",
            workflow_id=workflow_state.workflow_id,
            topics=topics_to_run,
            detail=trace_detail,
        )
    for topic in topics_to_run:
        result_path = os.path.join(project_root, topic_paths(project_root, topic)["test_result"])
        if os.path.exists(result_path):
            os.remove(result_path)
            journal_mod.append_entry(
                project_root,
                "主题测试结果失效",
                "workflow.py",
                workflow_id=workflow_state.workflow_id,
                topic=topic,
                reason="主题测试重新执行，旧结果不再代表当前代码",
            )

    def run_topic(topic: str) -> list[ExecutionAttempt]:
        attempts: list[ExecutionAttempt] = []
        tasks = topic_tasks[topic]
        for test_id in _topic_execution_order(project_root, topic, tasks):
            task = tasks[test_id]
            if _has_current_success(task):
                continue
            if any(
                not _has_current_success(tasks[dependency])
                for dependency in task.dependencies
                if dependency in tasks
            ):
                task.status = "blocked"
                task.current_record = None
                task.last_error = "前置测试项没有通过，本测试项未执行"
                attempts.append(
                    ExecutionAttempt(
                        topic=topic,
                        test_id=test_id,
                        status="blocked",
                        command=list(task.command),
                        started_at=now_iso(),
                        finished_at=now_iso(),
                        duration_seconds=0.0,
                        exit_code=None,
                        output_tail="",
                        error=task.last_error,
                    )
                )
                continue
            attempt, result = _run_one(project_root, topic, test_id, task, code_hash, test_hash)
            attempts.append(attempt)
            if attempt.status == "passed":
                task.status = "passed"
                task.last_error = None
                record = TestExecutionRecord(
                    test_entries=list(task.test_entries),
                    command=list(task.command),
                    cwd=task.cwd,
                    timeout_seconds=task.timeout_seconds,
                    started_at=attempt.started_at,
                    finished_at=attempt.finished_at,
                    duration_seconds=attempt.duration_seconds,
                    exit_code=attempt.exit_code,
                    status="passed",
                    environment=safe_environment(),
                    code_snapshot_hash=code_hash,
                    test_code_hash=test_hash,
                    output_tail=result.output_tail,
                    output_sha256=result.output_sha256,
                    output_bytes=result.output_bytes,
                    platform=result.platform,
                    executable=result.executable,
                )
                record.record_id = _record_id_for(result, topic, test_id)
                task.current_record = record
            else:
                # 失败、超时或无法启动立即清除当前测试项旧成功
                task.status = "needs_action"
                task.last_error = attempt.error or "测试没有通过"
                task.current_record = None
        return attempts

    all_attempts: list[ExecutionAttempt] = []
    completed_topics = {
        topic
        for topic, tasks in topic_tasks.items()
        if all(_has_current_success(task) for task in tasks.values())
    }
    failed_topics: set[str] = set()
    remaining = set(topics_to_run)

    while remaining:
        blocked_topics = [
            topic
            for topic in ordered_topics
            if topic in remaining
            and any(
                prerequisite in failed_topics
                for prerequisite in topic_prerequisites.get(topic, ())
            )
        ]
        for topic in blocked_topics:
            for test_id in _topic_execution_order(project_root, topic, topic_tasks[topic]):
                task = topic_tasks[topic][test_id]
                if _has_current_success(task):
                    continue
                task.status = "blocked"
                task.current_record = None
                task.last_error = "前置主题的自动化测试没有通过，本主题未执行"
                all_attempts.append(
                    ExecutionAttempt(
                        topic=topic,
                        test_id=test_id,
                        status="blocked",
                        command=list(task.command),
                        started_at=now_iso(),
                        finished_at=now_iso(),
                        duration_seconds=0.0,
                        exit_code=None,
                        output_tail="",
                        error=task.last_error,
                    )
                )
            remaining.remove(topic)
            failed_topics.add(topic)

        ready_topics = [
            topic
            for topic in ordered_topics
            if topic in remaining
            and all(
                prerequisite in completed_topics
                for prerequisite in topic_prerequisites.get(topic, ())
            )
        ]
        if not ready_topics:
            # 失败会逐层阻塞后置主题；先重新计算，不把正常传播误报为非法依赖。
            if blocked_topics:
                continue
            if remaining:
                raise ValueError(
                    f"主题依赖无法继续执行，请检查 {artifact_paths_mod.QA_INDEX_DOC}: "
                    f"{sorted(remaining)}"
                )
            break

        with ThreadPoolExecutor(max_workers=min(max_workers, len(ready_topics))) as executor:
            futures = {executor.submit(run_topic, topic): topic for topic in ready_topics}
            for future in as_completed(futures):
                topic = futures[future]
                attempts = future.result()
                all_attempts.extend(attempts)
                if all(_has_current_success(task) for task in topic_tasks[topic].values()):
                    completed_topics.add(topic)
                else:
                    failed_topics.add(topic)
                remaining.remove(topic)

    # 并发执行只运行子进程；state 统一在这里保存，避免多个线程同时写 state.json。
    for attempt in sorted(all_attempts, key=lambda item: (item.topic, item.test_id)):
        journal_mod.append_entry(
            project_root,
            "测试项执行",
            "workflow.py",
            workflow_id=workflow_state.workflow_id,
            topic=attempt.topic,
            test_id=attempt.test_id,
            status=attempt.status,
            command=attempt.command,
            started_at=attempt.started_at,
            finished_at=attempt.finished_at,
            duration_seconds=attempt.duration_seconds,
            exit_code=attempt.exit_code,
            error=attempt.error,
        )
    state_mod.save_state(project_root, workflow_state)
    return sorted(all_attempts, key=lambda item: (item.topic, item.test_id))


def summarize_attempts(attempts: list[ExecutionAttempt]) -> str:
    if not attempts:
        return "本次没有执行测试命令：当前没有自动化测试项，或全部测试项已有当前成功记录"
    passed = sum(attempt.status == "passed" for attempt in attempts)
    failed = [attempt for attempt in attempts if attempt.status != "passed"]
    detail = f"本次执行 {len(attempts)} 个测试项，{passed} 个通过"
    if failed:
        detail += "；未通过或未执行：" + ", ".join(
            f"{attempt.topic}/{attempt.test_id}（{attempt.status}）"
            for attempt in failed
        )
    return detail
