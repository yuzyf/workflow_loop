from pathlib import Path

import pytest

from workflow_loop import acceptance_records as records_mod
from workflow_loop.state import (
    AcceptanceCriterionRecord,
    GateState,
    StageState,
    TestExecutionRecord as ExecutionRecord,
    TestTaskState as ExecutionTask,
    WorkflowState,
    save_state,
)


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _test_task(record_id: str = "RUN-1") -> ExecutionTask:
    return ExecutionTask(
        test_entries=["tests/test_upload.py::test_upload"],
        command=["pytest", "tests/test_upload.py::test_upload", "--junitxml=report.xml"],
        report_adapter="pytest-junitxml",
        report_path=".workflow_loop/test_reports/upload.xml",
        status="passed",
        current_record=ExecutionRecord(
            test_entries=["tests/test_upload.py::test_upload"],
            command=["pytest", "tests/test_upload.py::test_upload", "--junitxml=report.xml"],
            status="passed",
            exit_code=0,
            record_id=record_id,
            code_snapshot_hash="code",
            test_code_hash="tests",
            report_adapter="pytest-junitxml",
            report_hash="a" * 64,
            report_size=1024,
            executed_count=1,
            skipped_count=0,
            failed_count=0,
            error_count=0,
            matched_test_entries=["tests/test_upload.py::test_upload"],
        ),
    )


def _setup(
    tmp_path: Path,
    method: str = "自动化测试",
    execution_stage: str = "qa",
) -> WorkflowState:
    topic = "上传文件"
    _write(
        tmp_path / "src" / "upload.py",
        "def upload_file():\n    return 'saved'\n",
    )
    _write(
        tmp_path / "acceptance" / "索引.md",
        """# 验收主题索引

## test

| 展示顺序 | 验收主题 | 前置主题 | 验收计划 | 主题验收结果 |
|---|---|---|---|---|
| 1 | 上传文件 | 无 | [验收计划](./上传文件_验收计划.md) | `./上传文件_验收结果.md`（待生成） |
""",
    )
    _write(
        tmp_path / "qa" / "上传文件_测试计划.md",
        f"""# 测试计划

## 1. 验收条件覆盖

| 验收条件链接 | 测试项 | 前置测试项 | 测试方式 | 产品入口 | 代码入口 | 测试入口 | 准备数据 | 执行动作 | 观察位置 | 预期结果 | 不通过表现 | 证据要求 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| [AC-01：上传完成](../acceptance/上传文件_验收计划.md#ac-01) | <a id=\"tc-01\"></a>[TC-01 验证上传完成](#tc-01) | 无 | {method} | 上传命令 | `src/upload.py::upload_file` | `tests/test_upload.py::test_upload` | 创建隔离临时目录 | 调用上传入口写入文件 | 临时目录中的目标文件 | 目标文件存在且内容正确 | 文件缺失或内容错误 | 结构化报告和目标文件内容 |
""",
    )
    state = WorkflowState(
        workflow_id="test",
        intent="from_scratch",
        current_stage="topic_acceptance",
        topics=[topic],
        stages={
            execution_stage: StageState(
                test_tasks={topic: {"TC-01": _test_task()}}
            ),
            "topic_acceptance": StageState(),
        },
    )
    state.verification.acceptance_plan_hash = "acceptance-plan"
    state.verification.impl_hash = "impl"
    state.verification.test_result_hash = "test-result"
    save_state(str(tmp_path), state)
    return state


def test_automated_acceptance_record_is_created_from_current_test(tmp_path):
    """Workflow-Test
    主题：主题验收、全量回归和最终同步完成后正式收工
    测试项：TC-01 自动化证据复用和人工验收记录
    验收条件：AC-01 主题验收使用当前有效证据
    测试方式：自动化测试 + 人工验收
    测试层级：集成测试
    测试目标：纯自动化条件直接复用当前通过记录并绑定精确机器记录编号
    测试入口：tests/test_acceptance_records.py::test_automated_acceptance_record_is_created_from_current_test
    代码入口：workflow_loop.acceptance_records.ensure_automated_records
    """
    state = _setup(tmp_path)

    created = records_mod.ensure_automated_records(str(tmp_path), state)

    assert len(created) == 1
    record = state.stages["topic_acceptance"].acceptance_records["上传文件"]["AC-01"]
    assert record.method == "自动化测试"
    assert records_mod.record_is_current(record, state)
    assert record.user_answer is None
    assert record.test_record_ids == ["RUN-1"]


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("report_hash", None),
        ("executed_count", 0),
        ("skipped_count", 1),
        ("matched_test_entries", ["tests/test_upload.py::other_test"]),
        ("code_snapshot_hash", None),
    ],
)
def test_automated_acceptance_rejects_incomplete_or_invalid_machine_facts(
    tmp_path,
    field,
    value,
):
    state = _setup(tmp_path)
    task = state.stages["qa"].test_tasks["上传文件"]["TC-01"]
    assert task.current_record is not None
    setattr(task.current_record, field, value)

    created = records_mod.ensure_automated_records(str(tmp_path), state)

    assert created == []
    assert state.stages["topic_acceptance"].acceptance_records.get("上传文件", {}) == {}


def test_current_qa_tasks_drive_automated_and_mixed_acceptance_with_legacy_fallback(
    tmp_path,
):
    """Workflow-Test
    主题：完整研发流程按最少用户环节推进并兼容旧轮次
    测试项：TC-05 当前 QA 机器记录可建立并复核验收记录
    验收条件：AC-01 新轮次只生成精简后的完整研发路径
    测试方式：自动化测试
    测试层级：集成测试
    产品入口：`workflow gate topic_acceptance` 和 `workflow acceptance record`
    测试入口：`tests/test_acceptance_records.py::test_current_qa_tasks_drive_automated_and_mixed_acceptance_with_legacy_fallback`
    代码入口：`src/workflow_loop/acceptance_records.py::ensure_automated_records`
    准备数据：分别构造只有 `qa`（测试验证）任务、只有旧 `test_execution`（测试执行）任务、两种状态并存，以及 `qa` 存在但没有有效任务的隔离工作流；混合验收样本同时准备用户原话
    执行动作：建立纯自动验收记录、复核记录当前性，并为混合验收记录用户结果
    关键断言：只有 `qa` 时可建立并复核精确机器编号；只有旧状态时仍可兼容；两者并存时必须使用 `qa`；`qa` 存在但无有效任务时不得改用旧成功记录；混合记录保留用户原话和当前机器编号
    预期证据：pytest JUnit XML 报告精确命中本入口，并保存四种阶段组合的记录建立与当前性结果、机器记录编号和混合验收字段
    """
    current_state = _setup(tmp_path / "current")
    current_records = records_mod.ensure_automated_records(
        str(tmp_path / "current"),
        current_state,
    )
    assert len(current_records) == 1
    current_record = current_records[0]
    assert current_record.test_record_ids == ["RUN-1"]
    assert records_mod.record_is_current(current_record, current_state)

    legacy_state = _setup(tmp_path / "legacy", execution_stage="test_execution")
    legacy_records = records_mod.ensure_automated_records(
        str(tmp_path / "legacy"),
        legacy_state,
    )
    assert len(legacy_records) == 1
    assert legacy_records[0].test_record_ids == ["RUN-1"]
    assert records_mod.record_is_current(legacy_records[0], legacy_state)

    preferred_state = _setup(tmp_path / "preferred")
    preferred_state.stages["qa"].test_tasks["上传文件"]["TC-01"] = _test_task(
        "RUN-QA"
    )
    preferred_state.stages["test_execution"] = StageState(
        test_tasks={"上传文件": {"TC-01": _test_task("RUN-LEGACY")}}
    )
    preferred_records = records_mod.ensure_automated_records(
        str(tmp_path / "preferred"),
        preferred_state,
    )
    assert preferred_records[0].test_record_ids == ["RUN-QA"]
    assert records_mod.record_is_current(preferred_records[0], preferred_state)

    rejected_state = _setup(tmp_path / "rejected")
    rejected_state.stages["qa"] = StageState()
    rejected_state.stages["test_execution"] = StageState(
        test_tasks={"上传文件": {"TC-01": _test_task("RUN-LEGACY")}}
    )
    assert records_mod.ensure_automated_records(
        str(tmp_path / "rejected"),
        rejected_state,
    ) == []

    mixed_state = _setup(tmp_path / "mixed", method="自动化测试 + 人工验收")
    mixed_record = records_mod.record_user_result(
        str(tmp_path / "mixed"),
        mixed_state,
        topic="上传文件",
        criterion_id="AC-01",
        result="passed",
        actual_result="用户看到文件已经上传",
        user_answer="确认通过",
        evidence="用户原话：确认通过",
    )
    assert mixed_record.user_answer == "确认通过"
    assert mixed_record.actual_result == "用户看到文件已经上传"
    assert mixed_record.evidence == "用户原话：确认通过"
    assert mixed_record.test_record_ids == ["RUN-1"]
    assert records_mod.record_is_current(mixed_record, mixed_state)


def test_manual_acceptance_record_requires_user_observation_and_answer(tmp_path):
    """Workflow-Test
    主题：主题验收、全量回归和最终同步完成后正式收工
    测试项：TC-01 自动化证据复用和人工验收记录
    验收条件：AC-01 主题验收使用当前有效证据
    测试方式：自动化测试 + 人工验收
    测试层级：集成测试
    测试目标：人工条件必须保存用户实际观察和明确回答而不能由程序代答
    测试入口：tests/test_acceptance_records.py::test_manual_acceptance_record_requires_user_observation_and_answer
    代码入口：workflow_loop.acceptance_records.record_user_result
    """
    state = _setup(tmp_path, method="人工验收")

    with pytest.raises(ValueError, match="实际观察到的结果"):
        records_mod.record_user_result(
            str(tmp_path),
            state,
            topic="上传文件",
            criterion_id="AC-01",
            result="passed",
            actual_result="",
            user_answer="通过",
            evidence="",
        )

    record = records_mod.record_user_result(
        str(tmp_path),
        state,
        topic="上传文件",
        criterion_id="AC-01",
        result="passed",
        actual_result="用户看到上传完成提示",
        user_answer="通过",
        evidence="用户实际观察到上传完成提示",
    )
    assert record.user_answer == "通过"
    assert record.evidence == "用户实际观察到上传完成提示"
    assert records_mod.topic_records_complete(str(tmp_path), state, "上传文件")


def test_failed_acceptance_clears_current_topic_record_and_result_file(tmp_path):
    """Workflow-Test
    主题：主题验收、全量回归和最终同步完成后正式收工
    测试项：TC-02 主题必须全部条件通过
    验收条件：AC-02 主题只能完整通过
    测试方式：自动化测试
    测试层级：集成测试
    测试目标：任一条件失败时整个主题的当前通过记录和正式结果立即失效
    测试入口：tests/test_acceptance_records.py::test_failed_acceptance_clears_current_topic_record_and_result_file
    代码入口：workflow_loop.acceptance_records.record_user_result
    """
    state = _setup(tmp_path, method="人工验收")
    records_mod.record_user_result(
        str(tmp_path),
        state,
        topic="上传文件",
        criterion_id="AC-01",
        result="passed",
        actual_result="用户看到上传完成提示",
        user_answer="通过",
        evidence="观察记录",
    )
    result_file = tmp_path / "acceptance" / "上传文件_验收结果.md"
    _write(result_file, "旧结果")
    index_file = tmp_path / "acceptance" / "索引.md"
    index_file.write_text(
        index_file.read_text(encoding="utf-8").replace(
            "`./上传文件_验收结果.md`（待生成）",
            "[验收结果](./上传文件_验收结果.md)",
        ),
        encoding="utf-8",
    )

    records_mod.record_user_result(
        str(tmp_path),
        state,
        topic="上传文件",
        criterion_id="AC-01",
        result="failed",
        actual_result="用户看到错误提示",
        user_answer="未通过",
        evidence="观察记录",
    )

    assert "上传文件" not in state.stages["topic_acceptance"].acceptance_records
    assert not result_file.exists()


def test_unaffected_topic_record_survives_global_hash_reset(tmp_path):
    """Workflow-Test
    主题：返回上游或整轮作废后状态与项目内容正确恢复
    测试项：TC-03 只使直接受影响主题结果失效
    验收条件：AC-03 只清除真实受影响的结果
    测试方式：自动化测试
    测试层级：单元测试
    测试目标：全局哈希变化本身不能连带清除没有被返回操作选中的独立主题
    测试入口：tests/test_acceptance_records.py::test_unaffected_topic_record_survives_global_hash_reset
    代码入口：workflow_loop.acceptance_records.record_is_current
    """
    state = _setup(tmp_path, method="人工验收")
    state.topics = ["上传文件", "查看状态"]
    state.stages["topic_acceptance"].acceptance_records["查看状态"] = {
        "AC-01": AcceptanceCriterionRecord(
            topic="查看状态",
            criterion_id="AC-01",
            method="人工验收",
            result="passed",
            actual_result="用户看到状态",
            user_answer="通过",
            evidence="观察记录",
            confirmed_at="2026-07-29T00:00:00+00:00",
            acceptance_plan_hash="old-plan",
            impl_hash="old-impl",
            test_result_hash="old-test",
        )
    }
    other = state.stages["topic_acceptance"].acceptance_records["查看状态"]["AC-01"]
    other.record_id = records_mod.compute_record_id(other)
    state.verification.acceptance_plan_hash = "new-plan"
    state.verification.impl_hash = "new-impl"
    state.verification.test_result_hash = "new-test"

    assert records_mod.record_is_current(other, state)
