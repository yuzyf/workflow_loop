"""项目统一测试入口的执行和修改前基线记录。"""

from __future__ import annotations

import os
import re
import shlex
import subprocess
from dataclasses import dataclass

from .project import DEFAULT_TEST_ENTRY, load_project
from .state import TestBaselineState, WorkflowState, now_iso
from .verification import compute_code_snapshot_hash


# 没有项目级配置时使用的全量测试入口
TEST_ENTRY_PATH = DEFAULT_TEST_ENTRY
TEST_TIMEOUT_SECONDS = 30 * 60
OUTPUT_TAIL_LIMIT = 4000
TEST_FILE_RE = re.compile(
    r"(^test_.*\.(py|js|ts|tsx)$|.*(_test|\.test|\.spec)\.(py|js|ts|tsx|go|rs)$)"
)


@dataclass(frozen=True)
class TestBaselineResult:
    """一次执行或复用修改前全量测试基线的结果。"""

    passed: bool
    ran: bool
    reused: bool
    detail: str


def _as_text(value) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return str(value)


def _output_tail(stdout: str, stderr: str) -> str:
    combined = "\n".join(part for part in (stdout, stderr) if part)
    if len(combined) <= OUTPUT_TAIL_LIMIT:
        return combined
    return combined[-OUTPUT_TAIL_LIMIT:]


def _has_existing_tests(project_root: str) -> bool:
    """判断项目是否已有可以作为修改前基线的测试文件。"""
    excluded_dirs = {
        ".git", ".workflow_loop", ".venv", "node_modules", "__pycache__",
        ".pytest_cache", "dist", "build",
    }
    for root, dirs, files in os.walk(project_root):
        dirs[:] = [directory for directory in dirs if directory not in excluded_dirs]
        for filename in files:
            relative_path = os.path.relpath(os.path.join(root, filename), project_root)
            parent_dirs = set(relative_path.split(os.sep)[:-1])
            if "tests" in parent_dirs or "test" in parent_dirs:
                return True
            if TEST_FILE_RE.match(filename):
                return True
    return False


def _result_detail(baseline: TestBaselineState, *, reused: bool) -> str:
    entry = baseline.entry or TEST_ENTRY_PATH
    command = baseline.command or f"./{TEST_ENTRY_PATH}"
    prefix = "复用修改前全量测试结果" if reused else "修改前全量测试完成"
    if baseline.status == "passed":
        return (
            f"{prefix}: {entry}；命令 {command}；退出码 0；"
            f"结束时间 {baseline.finished_at}"
        )
    if baseline.status == "unavailable":
        return f"修改前全量测试无法执行: {entry}；{baseline.output_tail}"
    if baseline.status == "not_applicable":
        return f"暂无修改前测试基线: {baseline.output_tail}"
    return (
        f"修改前全量测试失败: {entry}；命令 {command}；"
        f"退出码 {baseline.exit_code if baseline.exit_code is not None else '无'}；"
        f"结束时间 {baseline.finished_at}；输出摘要: {baseline.output_tail}"
    )


def ensure_test_baseline(
    project_root: str,
    workflow_state: WorkflowState,
) -> TestBaselineResult:
    """执行或复用当前代码状态对应的修改前全量测试。"""

    current_snapshot = compute_code_snapshot_hash(project_root)
    project = load_project(project_root)
    test_entry = (project.test_entry if project is not None else DEFAULT_TEST_ENTRY).strip()
    if not test_entry:
        test_entry = DEFAULT_TEST_ENTRY
    baseline = workflow_state.test_baseline

    # 只有通过且代码快照未变时才能复用；失败结果每次重试，便于处理临时环境问题。
    if (
        baseline.status in {"passed", "not_applicable"}
        and baseline.code_snapshot_hash == current_snapshot
        and baseline.entry == test_entry
    ):
        return TestBaselineResult(
            passed=True,
            ran=False,
            reused=True,
            detail=_result_detail(baseline, reused=True),
        )

    try:
        command_parts = shlex.split(test_entry)
    except ValueError as exc:
        command_parts = []
        parse_error = f"统一测试入口配置无法解析: {exc}"
    else:
        parse_error = ""
    started_at = now_iso()
    entry_path = (
        os.path.join(project_root, command_parts[0])
        if command_parts and "/" in command_parts[0]
        else None
    )
    if (
        test_entry == DEFAULT_TEST_ENTRY
        and entry_path is not None
        and not os.path.exists(entry_path)
        and not _has_existing_tests(project_root)
    ):
        baseline = TestBaselineState(
            entry=test_entry,
            command=test_entry,
            started_at=None,
            finished_at=now_iso(),
            status="not_applicable",
            code_snapshot_hash=current_snapshot,
            output_tail="当前项目没有已有测试，暂无可建立的修改前测试基线",
        )
        workflow_state.test_baseline = baseline
        return TestBaselineResult(True, False, False, _result_detail(baseline, reused=False))
    if parse_error:
        baseline = TestBaselineState(
            entry=test_entry,
            command=test_entry,
            started_at=started_at,
            finished_at=now_iso(),
            status="unavailable",
            code_snapshot_hash=current_snapshot,
            output_tail=parse_error,
        )
        workflow_state.test_baseline = baseline
        return TestBaselineResult(False, True, False, _result_detail(baseline, reused=False))

    if not command_parts:
        baseline = TestBaselineState(
            entry=test_entry,
            command=test_entry,
            started_at=started_at,
            finished_at=now_iso(),
            status="unavailable",
            code_snapshot_hash=current_snapshot,
            output_tail="统一测试入口为空",
        )
        workflow_state.test_baseline = baseline
        return TestBaselineResult(False, True, False, _result_detail(baseline, reused=False))

    if entry_path is not None and not os.path.isfile(entry_path):
        baseline = TestBaselineState(
            entry=test_entry,
            command=test_entry,
            started_at=started_at,
            finished_at=now_iso(),
            status="unavailable",
            code_snapshot_hash=current_snapshot,
            output_tail=f"找不到统一测试入口: {command_parts[0]}",
        )
        workflow_state.test_baseline = baseline
        return TestBaselineResult(False, True, False, _result_detail(baseline, reused=False))

    if entry_path is not None and not os.access(entry_path, os.X_OK):
        baseline = TestBaselineState(
            entry=test_entry,
            command=test_entry,
            started_at=started_at,
            finished_at=now_iso(),
            status="unavailable",
            code_snapshot_hash=current_snapshot,
            output_tail=f"统一测试入口没有执行权限: {command_parts[0]}",
        )
        workflow_state.test_baseline = baseline
        return TestBaselineResult(False, True, False, _result_detail(baseline, reused=False))

    try:
        completed = subprocess.run(
            command_parts,
            cwd=project_root,
            capture_output=True,
            text=True,
            timeout=TEST_TIMEOUT_SECONDS,
            check=False,
        )
        status = "passed" if completed.returncode == 0 else "failed"
        exit_code = completed.returncode
        output_tail = _output_tail(completed.stdout, completed.stderr)
    except subprocess.TimeoutExpired as exc:
        status = "failed"
        exit_code = None
        output_tail = _output_tail(_as_text(exc.stdout), _as_text(exc.stderr))
        output_tail = (
            f"运行超过 {TEST_TIMEOUT_SECONDS} 秒，已终止。\n{output_tail}"
        ).strip()
    except OSError as exc:
        status = "unavailable"
        exit_code = None
        output_tail = f"启动统一测试入口失败: {exc}"

    baseline = TestBaselineState(
        entry=test_entry,
        command=test_entry,
        started_at=started_at,
        finished_at=now_iso(),
        status=status,
        exit_code=exit_code,
        code_snapshot_hash=compute_code_snapshot_hash(project_root),
        output_tail=output_tail,
    )
    workflow_state.test_baseline = baseline
    return TestBaselineResult(
        passed=status == "passed",
        ran=True,
        reused=False,
        detail=_result_detail(baseline, reused=False),
    )


def baseline_journal_fields(workflow_state: WorkflowState) -> dict:
    """返回适合写入 journal.jsonl 的基线字段。"""

    baseline = workflow_state.test_baseline
    return {
        "entry": baseline.entry,
        "command": baseline.command,
        "started_at": baseline.started_at,
        "finished_at": baseline.finished_at,
        "status": baseline.status,
        "exit_code": baseline.exit_code,
        "code_snapshot_hash": baseline.code_snapshot_hash,
        "output_tail": baseline.output_tail,
    }
