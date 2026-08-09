"""测试执行阶段的任务登记、依赖调度和安全子进程执行。"""

from __future__ import annotations

import os
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass

from . import artifact_paths as artifact_paths_mod
from . import journal as journal_mod
from . import process_runner as process_runner_mod
from . import state as state_mod
from . import test_mapping
from . import test_report
from . import traceability as traceability_mod
from . import verification
from .project import DEFAULT_TEST_PARALLELISM, load_project
from .state import TestExecutionRecord, TestTaskState, WorkflowState, now_iso
from .topic import topic_file_key, topic_paths
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
    normalized_entry = entry.strip().strip("`").replace("\\", "/")
    path = normalized_entry.split("::", 1)[0]
    candidates = {normalized_entry, path}
    for value in command_values:
        normalized_value = value.replace("\\", "/").rstrip("/")
        if normalized_value in candidates:
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
        result.setdefault(key, []).append(marker.test_entry.strip().strip("`"))
    return result


def _report_relative_path(
    project_root: str,
    workflow_state: WorkflowState,
    topic: str,
    test_id: str,
) -> str:
    """返回程序唯一管理的项目内报告路径。"""
    if not test_id or any(character not in "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_" for character in test_id):
        raise ValueError(f"测试项编号不能用于报告路径: {test_id!r}")
    return "/".join(
        (
            ".workflow_loop",
            "test_reports",
            workflow_state.workflow_id,
            topic_file_key(project_root, topic),
            f"{test_id}.xml",
        )
    )


def _expected_report_command(
    project_root: str,
    task: TestTaskState,
) -> tuple[list[str], list[str]]:
    """拆出基础命令并核对程序追加的报告参数恰好出现一次。"""
    if not task.report_adapter or not task.report_path:
        raise ValueError("缺少结构化报告适配器或程序管理的报告路径")
    absolute_report = os.path.join(project_root, *task.report_path.split("/"))
    if task.report_adapter == "vitest-junit":
        suffix = ["--reporter=junit", f"--outputFile.junit={absolute_report}"]
    elif task.report_adapter == "pytest-junitxml":
        suffix = [
            "-p",
            "workflow_loop.test_report",
            f"--junitxml={absolute_report}",
        ]
    else:
        raise ValueError(f"不支持的结构化报告适配器: {task.report_adapter}")
    if len(task.command) <= len(suffix) or task.command[-len(suffix) :] != suffix:
        raise ValueError("测试命令中的结构化报告参数不是程序生成的唯一固定参数")
    base_command = task.command[: -len(suffix)]
    expected = test_report.append_report_arguments(
        base_command,
        task.report_adapter,
        absolute_report,
    )
    if expected != task.command:
        raise ValueError("测试命令中的结构化报告参数与当前登记不一致")
    return base_command, expected


def _prepare_report_output(project_root: str, report_path: str) -> str:
    """在执行前删除旧报告，拒绝符号链接或越界目录。"""
    normalized = report_path.replace("\\", "/")
    if os.path.isabs(normalized) or normalized.startswith("../") or "/../" in normalized:
        raise ValueError(f"结构化测试报告路径必须在项目内: {report_path}")
    full_path = os.path.abspath(os.path.join(project_root, *normalized.split("/")))
    project_abs = os.path.abspath(project_root)
    try:
        if os.path.commonpath([project_abs, full_path]) != project_abs:
            raise ValueError(f"结构化测试报告路径越出项目: {report_path}")
    except ValueError as exc:
        raise ValueError(f"结构化测试报告路径越出项目: {report_path}") from exc
    current = project_abs
    for component in normalized.split("/")[:-1]:
        current = os.path.join(current, component)
        if os.path.lexists(current) and os.path.islink(current):
            raise ValueError(f"结构化测试报告路径不能经过符号链接: {report_path}")
    os.makedirs(os.path.dirname(full_path), exist_ok=True)
    if os.path.lexists(full_path):
        if os.path.islink(full_path) or not os.path.isfile(full_path):
            raise ValueError(f"旧结构化测试报告不是可删除的普通文件: {report_path}")
        os.remove(full_path)
    return full_path


def prepare_task(
    project_root: str,
    workflow_state: WorkflowState,
    topic: str,
    test_id: str,
    command: list[str],
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
    cwd: str | None = None,
    report_adapter: str | None = None,
) -> TestTaskState:
    """登记一个已经由用户确认过的测试项命令；登记不启动测试。"""
    if report_adapter not in test_report.SUPPORTED_REPORT_ADAPTERS:
        raise ValueError(
            "结构化报告适配器必须是 "
            f"{sorted(test_report.SUPPORTED_REPORT_ADAPTERS)}"
        )
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

    report_path = _report_relative_path(project_root, workflow_state, topic, test_id)
    absolute_report = os.path.join(project_root, *report_path.split("/"))
    try:
        command_with_report = test_report.append_report_arguments(
            list(command),
            report_adapter,
            absolute_report,
        )
    except test_report.TestReportError as exc:
        raise ValueError(str(exc)) from exc

    stage_state = workflow_state.stages.get("test_execution")
    if stage_state is None:
        raise ValueError("当前工作流没有 test_execution 阶段")
    stage_state.test_tasks.setdefault(topic, {})[test_id] = TestTaskState(
        test_entries=sorted(set(entries)),
        command=command_with_report,
        cwd=normalized_cwd,
        dependencies=list(item.dependencies),
        timeout_seconds=timeout_seconds,
        report_adapter=report_adapter,
        report_path=report_path,
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
    errors: list[tuple[str, str, str, str]] = []
    expected: dict[tuple[str, str], test_mapping.TestPlanItem] = {}
    invalid_plan_topics: set[str] = set()
    marker_invalid_topics: dict[str, str] = {}

    # 测试计划是后续登记核对的前置事实。逐主题解析，保证一个主题损坏时，
    # 其他主题及当前已登记任务仍能给出完整、可处理的错误。
    for topic in sorted(workflow_state.topics):
        try:
            items = test_mapping.parse_test_plan_items(project_root, topic)
        except ValueError as exc:
            invalid_plan_topics.add(topic)
            errors.append((topic, "未检查", "测试计划", f"无法解析：{exc}"))
            continue
        for item in items:
            if item.requires_test_code:
                expected[(item.topic, item.test_id)] = item

    actual = {
        (topic, test_id): task
        for topic, tasks in stage_state.test_tasks.items()
        for test_id, task in tasks.items()
    }
    for topic, test_id in sorted(set(expected) - set(actual)):
        errors.append((topic, test_id, "登记任务", "尚未登记测试命令"))
    for topic, test_id in sorted(set(actual) - set(expected)):
        if topic in invalid_plan_topics:
            errors.append(
                (
                    topic,
                    test_id,
                    "登记任务",
                    "未检查：前置测试计划无法解析，无法判断该登记任务是否存在于当前计划",
                )
            )
        else:
            errors.append((topic, test_id, "登记任务", "当前测试计划不存在该测试任务"))

    for topic in sorted(set(workflow_state.topics) - invalid_plan_topics):
        marker_ok, marker_detail = test_mapping.validate_workflow_test_markers(
            project_root,
            [topic],
        )
        if not marker_ok:
            marker_invalid_topics[topic] = marker_detail
            topic_items = [item for item in expected.values() if item.topic == topic]
            if topic_items:
                for item in sorted(topic_items, key=lambda candidate: candidate.test_id):
                    errors.append(
                        (
                            topic,
                            item.test_id,
                            "Workflow-Test 标识",
                            f"未检查：无法核对当前测试入口：{marker_detail}",
                        )
                    )
            else:
                errors.append(
                    (
                        topic,
                        "未检查",
                        "Workflow-Test 标识",
                        f"未检查：无法核对当前测试入口：{marker_detail}",
                    )
                )

    current_entries: dict[tuple[str, str], list[str]] = {}
    valid_marker_topics = sorted(set(workflow_state.topics) - invalid_plan_topics - set(marker_invalid_topics))
    if valid_marker_topics:
        try:
            current_entries = _markers_by_test(project_root, valid_marker_topics)
        except ValueError as exc:
            for item in sorted(expected.values(), key=lambda candidate: (candidate.topic, candidate.test_id)):
                if item.topic in valid_marker_topics:
                    errors.append(
                        (
                            item.topic,
                            item.test_id,
                            "测试入口",
                            f"未检查：无法读取 Workflow-Test 标识：{exc}",
                        )
                    )

    for key, item in sorted(expected.items()):
        if key not in actual:
            # 漏登记已在上面报告；不存在的任务没有命令、目录等事实可继续核对。
            continue
        task = actual[key]
        base_command = list(task.command)
        command_ok, command_detail = validate_command(task.command)
        if not command_ok:
            errors.append((item.topic, item.test_id, "执行命令", command_detail))
        expected_report_path = _report_relative_path(
            project_root,
            workflow_state,
            item.topic,
            item.test_id,
        )
        if task.report_path != expected_report_path:
            errors.append(
                (
                    item.topic,
                    item.test_id,
                    "报告路径",
                    f"必须是程序固定路径 {expected_report_path}，实际是 {task.report_path or '缺少'}",
                )
            )
        if task.report_adapter not in test_report.SUPPORTED_REPORT_ADAPTERS:
            errors.append(
                (
                    item.topic,
                    item.test_id,
                    "报告适配器",
                    f"必须是 {sorted(test_report.SUPPORTED_REPORT_ADAPTERS)}，实际是 {task.report_adapter or '缺少'}",
                )
            )
        else:
            try:
                base_command, _ = _expected_report_command(project_root, task)
            except (ValueError, test_report.TestReportError) as exc:
                errors.append((item.topic, item.test_id, "报告参数", str(exc)))
        if task.timeout_seconds <= 0:
            errors.append((item.topic, item.test_id, "超时时间", "必须大于 0 秒"))
        try:
            normalize_task_cwd(project_root, task.cwd or None)
        except ValueError as exc:
            errors.append((item.topic, item.test_id, "工作目录", str(exc)))
        if tuple(task.dependencies) != item.dependencies:
            errors.append((item.topic, item.test_id, "前置测试项", "登记依赖与当前测试计划不一致"))
        if item.topic in marker_invalid_topics:
            # 入口来源失效只阻断入口比对；命令、目录、超时和依赖仍是独立可判断事实。
            continue
        expected_entries = sorted(set(current_entries.get(key, [])))
        if sorted(set(task.test_entries)) != expected_entries:
            errors.append((item.topic, item.test_id, "测试入口", "登记测试入口与当前测试代码不一致"))
        if not expected_entries:
            errors.append((item.topic, item.test_id, "测试入口", "当前测试代码没有可追踪的测试入口"))
        else:
            entries_ok, entries_detail = validate_command_entries(base_command, expected_entries)
            if not entries_ok:
                errors.append((item.topic, item.test_id, "执行命令", entries_detail))
    if errors:
        return False, _format_prepared_task_errors(errors)
    return True, f"{len(expected)} 个自动化测试项的登记任务与当前计划和测试代码一致"


def _format_prepared_task_errors(
    errors: list[tuple[str, str, str, str]],
) -> str:
    """用稳定顺序输出全部可独立判断的登记问题。"""
    ordered = sorted(set(errors), key=lambda item: (item[0], item[1], item[2], item[3]))
    lines = [f"测试任务登记校验失败（共 {len(ordered)} 项）"]
    for index, (topic, test_id, field, detail) in enumerate(ordered, start=1):
        lines.append(
            f"{index}. 主题：{topic}；测试项：{test_id}；字段：{field}；问题：{detail}"
        )
    return "\n".join(lines)


def _test_process_environment(task: TestTaskState) -> dict[str, str] | None:
    """让被测项目的 pytest 进程能够加载只含标准库的报告属性插件。"""
    if task.report_adapter != "pytest-junitxml":
        return None
    package_parent = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    existing = os.environ.get("PYTHONPATH", "")
    return {
        "PYTHONPATH": os.pathsep.join(
            part for part in (package_parent, existing) if part
        )
    }


def _run_one(
    project_root: str,
    topic: str,
    test_id: str,
    task: TestTaskState,
    code_hash: str,
    test_hash: str,
) -> tuple[
    ExecutionAttempt,
    process_runner_mod.ProcessResult | None,
    test_report.TestReportFacts | None,
]:
    """执行一次登记任务，并同时核对进程、结构化报告、目标和代码状态。"""
    cwd = os.path.join(project_root, task.cwd) if task.cwd else project_root
    try:
        if not task.report_path or not task.report_adapter:
            raise ValueError("缺少结构化报告适配器或程序管理的报告路径")
        _prepare_report_output(project_root, task.report_path)
    except (OSError, ValueError) as exc:
        timestamp = now_iso()
        return (
            ExecutionAttempt(
                topic=topic,
                test_id=test_id,
                status="unavailable",
                command=list(task.command),
                started_at=timestamp,
                finished_at=timestamp,
                duration_seconds=0.0,
                exit_code=None,
                output_tail="",
                error=f"执行前无法准备结构化测试报告：{exc}",
            ),
            None,
            None,
        )
    result = process_runner_mod.run_process(
        process_runner_mod.ProcessRequest(
            argv=list(task.command),
            cwd=cwd,
            timeout_seconds=task.timeout_seconds,
            extra_env=_test_process_environment(task),
        )
    )
    problems: list[str] = []
    if result.status == "timeout":
        problems.append(result.error_message or "测试命令超时")
    elif result.status == "error":
        problems.append(result.error_message or "启动测试命令失败")
    elif result.exit_code != 0:
        problems.append(f"测试进程退出码必须是 0，实际是 {result.exit_code}")

    facts: test_report.TestReportFacts | None = None
    try:
        facts = test_report.parse_test_report(
            project_root,
            task.report_path,
            task.report_adapter,
            task.test_entries,
        )
    except test_report.TestReportError as exc:
        problems.append(f"结构化测试报告无效：{exc}")
    if facts is not None:
        if facts.executed_count <= 0:
            problems.append("结构化测试报告的实际执行数必须大于 0")
        if facts.skipped_count != 0:
            problems.append(f"结构化测试报告存在 {facts.skipped_count} 个跳过用例")
        if facts.failed_count != 0:
            problems.append(f"结构化测试报告存在 {facts.failed_count} 个失败用例")
        if facts.error_count != 0:
            problems.append(f"结构化测试报告存在 {facts.error_count} 个错误用例")
    current_code_hash = verification.compute_non_test_code_snapshot_hash(project_root)
    current_test_hash = verification.compute_test_code_snapshot_hash(project_root)
    if current_code_hash != code_hash:
        problems.append("测试执行期间登记的产品核心代码发生变化，本次结果不能绑定当前实现")
    if current_test_hash != test_hash:
        problems.append("测试执行期间登记的测试代码发生变化，本次结果不能绑定当前测试")

    status = "passed" if not problems else (
        "timeout" if result.status == "timeout" else "unavailable" if result.status == "error" else "failed"
    )
    attempt = ExecutionAttempt(
        topic=topic,
        test_id=test_id,
        status=status,
        command=list(task.command),
        started_at=result.started_at,
        finished_at=result.finished_at,
        duration_seconds=result.duration_seconds,
        exit_code=result.exit_code,
        output_tail=result.output_tail,
        error="；".join(problems) if problems else None,
    )
    return attempt, result, facts


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
    return state_mod.execution_task_has_current_success(task)


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
        ["展示顺序", "验收主题", "前置主题", "验收计划", "实施记录", "测试计划", "测试结果"],
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
            attempt, result, report_facts = _run_one(
                project_root,
                topic,
                test_id,
                task,
                code_hash,
                test_hash,
            )
            attempts.append(attempt)
            if attempt.status == "passed" and result is not None and report_facts is not None:
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
                    report_adapter=report_facts.report_adapter,
                    report_hash=report_facts.report_hash,
                    report_size=report_facts.report_size,
                    executed_count=report_facts.executed_count,
                    skipped_count=report_facts.skipped_count,
                    failed_count=report_facts.failed_count,
                    error_count=report_facts.error_count,
                    matched_test_entries=list(report_facts.matched_test_entries),
                )
                record.record_id = state_mod.compute_test_execution_record_id(
                    record,
                    topic,
                    test_id,
                )
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
        task = topic_tasks[attempt.topic][attempt.test_id]
        record = task.current_record
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
            report_adapter=record.report_adapter if record is not None else task.report_adapter,
            report_path=task.report_path,
            report_hash=record.report_hash if record is not None else None,
            report_size=record.report_size if record is not None else None,
            executed_count=record.executed_count if record is not None else None,
            skipped_count=record.skipped_count if record is not None else None,
            failed_count=record.failed_count if record is not None else None,
            error_count=record.error_count if record is not None else None,
            matched_test_entries=(record.matched_test_entries if record is not None else None),
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
