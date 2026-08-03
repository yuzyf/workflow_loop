"""最终全量回归的执行。

本模块只保留最终全量回归职责：使用项目按平台登记的参数数组入口，
通过共同的受控进程执行器真实执行一次，并把完整机器事实写入状态。
修改前全量测试基线已经删除；实施前没有任何全量测试执行路径。
"""

from __future__ import annotations

import hashlib

from . import process_runner as process_runner_mod
from . import test_entry as test_entry_mod
from .project import load_project
from .state import RegressionTestState, WorkflowState
from .verification import compute_code_snapshot_hash


TEST_TIMEOUT_SECONDS = 30 * 60


def regression_record_id(
    started_at: str | None,
    finished_at: str | None,
    exit_code: int | None,
    output_sha256: str | None,
    command: list[str],
) -> str:
    """根据最终回归机器事实计算稳定记录编号。"""
    payload = (
        f"{started_at}|{finished_at}|{exit_code}|"
        f"{output_sha256}|{' '.join(command)}"
    )
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()[:8]
    compact_time = (started_at or "").replace(":", "").replace("-", "")
    return f"REG-{compact_time}-{digest}"


def resolve_regression_entry(project_root: str) -> tuple[list[str] | None, str]:
    """按当前操作系统选择项目全量测试入口；返回 (参数数组, 说明)。"""
    project = load_project(project_root)
    raw_config = project.test_entry if project is not None else None
    if not isinstance(raw_config, dict):
        return None, "项目测试入口配置无效"
    errors = test_entry_mod.validate_entry_config(raw_config)
    if errors:
        return None, "项目测试入口配置不合法：" + "；".join(errors)
    argv = test_entry_mod.select_entry(raw_config)
    if not argv:
        return None, (
            f"当前操作系统（{test_entry_mod.current_platform_key()}）没有可用的"
            "项目全量测试入口；请先在测试计划阶段登记入口配置"
        )
    return argv, f"使用入口 {argv}"


def run_final_regression(project_root: str, workflow_state: WorkflowState) -> tuple[bool, str]:
    """在最新完整代码上执行一次项目全量入口，写入完整机器事实。"""

    current_snapshot = compute_code_snapshot_hash(project_root)
    argv, entry_detail = resolve_regression_entry(project_root)
    if argv is None:
        workflow_state.regression_test = RegressionTestState(
            status="unavailable",
            timeout_seconds=TEST_TIMEOUT_SECONDS,
            output_tail=entry_detail,
            code_snapshot_hash=current_snapshot,
        )
        return False, f"最终全量回归无法执行: {entry_detail}"

    result = process_runner_mod.run_process(
        process_runner_mod.ProcessRequest(
            argv=argv,
            cwd=project_root,
            timeout_seconds=TEST_TIMEOUT_SECONDS,
        )
    )
    state = RegressionTestState(
        entry=argv,
        command=result.argv,
        cwd="",
        timeout_seconds=TEST_TIMEOUT_SECONDS,
        started_at=result.started_at,
        finished_at=result.finished_at,
        duration_seconds=result.duration_seconds,
        status=result.status,
        exit_code=result.exit_code,
        code_snapshot_hash=current_snapshot,
        output_tail=result.output_tail,
        output_sha256=result.output_sha256,
        output_bytes=result.output_bytes,
        platform=result.platform,
        executable=result.executable,
    )
    state.record_id = regression_record_id(
        result.started_at,
        result.finished_at,
        result.exit_code,
        result.output_sha256,
        result.argv,
    )
    workflow_state.regression_test = state

    if result.status == "passed":
        return True, f"最终全量测试通过: {argv}；退出码 0；机器记录 {state.record_id}"
    return False, (
        f"最终全量测试未通过: {argv}；状态 {result.status}；"
        f"退出码 {result.exit_code if result.exit_code is not None else '无'}；"
        f"输出摘要: {result.output_tail[-800:]}"
    )


def regression_journal_fields(workflow_state: WorkflowState) -> dict:
    """返回最终回归状态，供 journal 记录。"""

    result = workflow_state.regression_test
    return {
        "entry": result.entry,
        "command": result.command,
        "cwd": result.cwd,
        "timeout_seconds": result.timeout_seconds,
        "started_at": result.started_at,
        "finished_at": result.finished_at,
        "duration_seconds": result.duration_seconds,
        "status": result.status,
        "exit_code": result.exit_code,
        "code_snapshot_hash": result.code_snapshot_hash,
        "record_id": result.record_id,
        "output_sha256": result.output_sha256,
        "output_bytes": result.output_bytes,
        "platform": result.platform,
        "executable": result.executable,
        "output_tail": result.output_tail,
    }
