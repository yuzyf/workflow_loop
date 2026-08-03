import sys

import workflow_loop.test_runner as test_runner
from workflow_loop.process_runner import ProcessResult
from workflow_loop.project import create_project, register_test_entry
from workflow_loop.state import WorkflowState


TOPIC = "主题验收_全量回归和最终同步完成后正式收工"


def _state() -> WorkflowState:
    return WorkflowState(workflow_id="wf", intent="product_change", run_status="active")


def _entry_for_current_platform() -> dict[str, list[str]]:
    return {
        "windows" if sys.platform.startswith("win") else (
            "darwin" if sys.platform == "darwin" else "linux"
        ): [sys.executable, "-m", "pytest", "-q"]
    }


def _result(status: str = "passed", exit_code: int | None = 0) -> ProcessResult:
    return ProcessResult(
        status=status,
        exit_code=exit_code,
        started_at="2026-08-03T01:00:00+00:00",
        finished_at="2026-08-03T01:00:01+00:00",
        duration_seconds=1.0,
        output_tail="result output",
        output_sha256="a" * 64,
        output_bytes=13,
        platform=sys.platform,
        executable=sys.executable,
        argv=[sys.executable, "-m", "pytest", "-q"],
        cwd="/tmp/project",
    )


def test_final_regression_requires_current_platform_entry(tmp_path):
    """Workflow-Test
    主题：主题验收、全量回归和最终同步完成后正式收工
    测试项：TC-03 最新完整代码执行项目全量测试
    验收条件：AC-03 最终回归在最新完整代码上执行
    测试方式：自动化测试
    测试层级：模块测试
    测试目标：没有当前系统全量入口时明确阻止最终回归
    测试入口：tests/test_test_runner.py::test_final_regression_requires_current_platform_entry
    代码入口：workflow_loop.test_runner.resolve_regression_entry
    """
    create_project(str(tmp_path))

    entry, detail = test_runner.resolve_regression_entry(str(tmp_path))

    assert entry is None
    assert "没有可用的项目全量测试入口" in detail


def test_final_regression_runs_registered_entry_and_records_machine_facts(
    tmp_path, monkeypatch
):
    """Workflow-Test
    主题：主题验收、全量回归和最终同步完成后正式收工
    测试项：TC-03 最新完整代码执行项目全量测试
    验收条件：AC-03 最终回归在最新完整代码上执行
    测试方式：自动化测试
    测试层级：集成测试
    测试目标：最终回归执行当前系统入口并保存代码哈希和进程机器事实
    测试入口：tests/test_test_runner.py::test_final_regression_runs_registered_entry_and_records_machine_facts
    代码入口：workflow_loop.test_runner.run_final_regression
    """
    create_project(str(tmp_path))
    entry = _entry_for_current_platform()
    register_test_entry(str(tmp_path), entry)
    calls = []

    def fake_run(request):
        calls.append(request)
        result = _result()
        result.cwd = request.cwd
        result.argv = list(request.argv)
        return result

    monkeypatch.setattr(test_runner.process_runner_mod, "run_process", fake_run)
    state = _state()

    ok, detail = test_runner.run_final_regression(str(tmp_path), state)

    assert ok is True
    assert len(calls) == 1
    assert calls[0].argv == next(iter(entry.values()))
    assert calls[0].cwd == str(tmp_path)
    assert state.regression_test.status == "passed"
    assert state.regression_test.code_snapshot_hash
    assert state.regression_test.output_sha256 == "a" * 64
    assert state.regression_test.record_id.startswith("REG-")
    assert "机器记录" in detail


def test_failed_final_regression_replaces_previous_success(tmp_path, monkeypatch):
    """Workflow-Test
    主题：主题验收、全量回归和最终同步完成后正式收工
    测试项：TC-03 最新完整代码执行项目全量测试
    验收条件：AC-03 最终回归在最新完整代码上执行
    测试方式：自动化测试
    测试层级：模块测试
    测试目标：最新一次非零退出覆盖旧成功记录并阻止后续验收
    测试入口：tests/test_test_runner.py::test_failed_final_regression_replaces_previous_success
    代码入口：workflow_loop.test_runner.run_final_regression
    """
    create_project(str(tmp_path))
    register_test_entry(str(tmp_path), _entry_for_current_platform())
    state = _state()
    state.regression_test.status = "passed"
    monkeypatch.setattr(
        test_runner.process_runner_mod,
        "run_process",
        lambda _request: _result("failed", 2),
    )

    ok, detail = test_runner.run_final_regression(str(tmp_path), state)

    assert ok is False
    assert state.regression_test.status == "failed"
    assert state.regression_test.exit_code == 2
    assert "未通过" in detail


def test_regression_confirmation_can_reuse_same_machine_record(tmp_path, monkeypatch):
    """Workflow-Test
    主题：主题验收、全量回归和最终同步完成后正式收工
    测试项：TC-04 最终回归三道门只运行一次测试
    验收条件：AC-04 最终回归三道门不重复运行测试
    测试方式：自动化测试
    测试层级：模块测试
    测试目标：最终回归状态能完整序列化供确认门复核而无需再次启动入口
    测试入口：tests/test_test_runner.py::test_regression_confirmation_can_reuse_same_machine_record
    代码入口：workflow_loop.test_runner.regression_journal_fields
    """
    create_project(str(tmp_path))
    register_test_entry(str(tmp_path), _entry_for_current_platform())
    count = 0

    def fake_run(_request):
        nonlocal count
        count += 1
        return _result()

    monkeypatch.setattr(test_runner.process_runner_mod, "run_process", fake_run)
    state = _state()

    assert test_runner.run_final_regression(str(tmp_path), state)[0] is True
    journal = test_runner.regression_journal_fields(state)
    repeated_journal = test_runner.regression_journal_fields(state)

    assert count == 1
    assert repeated_journal == journal
    assert journal["record_id"] == state.regression_test.record_id
    assert journal["status"] == "passed"


def test_modification_before_regression_baseline_api_is_absent():
    """Workflow-Test
    主题：验收测试和实施计划按同一主题完整追踪
    测试项：TC-05 项目专属全量入口按系统保存且不执行修改前回归
    验收条件：AC-05 全量测试入口属于当前项目
    测试方式：自动化测试
    测试层级：单元测试
    测试目标：测试计划和实施阶段不存在修改前全量回归调用入口
    测试入口：tests/test_test_runner.py::test_modification_before_regression_baseline_api_is_absent
    代码入口：workflow_loop.test_runner
    """
    assert not hasattr(test_runner, "ensure_test_baseline")
