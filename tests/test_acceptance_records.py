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


def _setup(tmp_path: Path, method: str = "自动化测试") -> WorkflowState:
    topic = "上传文件"
    _write(
        tmp_path / "acceptance" / "索引.md",
        """# 验收主题索引

## test

| 展示顺序 | 验收主题 | 前置主题 | 验收计划 | 主题验收结果 |
|---|---|---|---|---|
| 1 | 上传文件 | 无 | [验收计划](./上传文件_验收计划.md) | [验收结果](./上传文件_验收结果.md) |
""",
    )
    _write(
        tmp_path / "qa" / "上传文件_测试计划.md",
        f"""# 测试计划

## 1. 验收条件覆盖

| 验收条件链接 | 测试项 | 前置测试项 | 测试方式 | 验证方向 | 预期观察结果 | 证据要求 |
|---|---|---|---|---|---|---|
| [AC-01：上传完成](../acceptance/上传文件_验收计划.md#ac-01) | <a id=\"tc-01\"></a>[TC-01 验证上传完成](#tc-01) | 无 | {method} | 检查上传 | 观察到上传完成 | 记录结果 |
""",
    )
    state = WorkflowState(
        workflow_id="test",
        intent="from_scratch",
        current_stage="topic_acceptance",
        topics=[topic],
        stages={
            "test_execution": StageState(
                test_tasks={
                    topic: {
                        "TC-01": ExecutionTask(
                            status="passed",
                            current_record=ExecutionRecord(
                                status="passed",
                                exit_code=0,
                                record_id="RUN-1",
                            ),
                        )
                    }
                }
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
