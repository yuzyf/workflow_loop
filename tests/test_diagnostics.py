import pytest

from workflow_loop.cli import _format_failure_diagnostics, current_stage_next_instruction
from workflow_loop.diagnostics import (
    Diagnostic,
    NextCommand,
    ValidationReport,
    format_validation_report,
    legacy_result,
    report_from_legacy_result,
    stable_sort_diagnostics,
)
from workflow_loop.state import GateState, StageState, WorkflowState


def _next_command() -> NextCommand:
    return NextCommand(
        command="workflow gate update_code_design",
        executor="AI",
        side_effects="只读校验文档，不执行测试，不修改项目文件",
        success_condition="全部架构映射均能定位到项目内真实文件",
        next_stage="completed（已完成）",
    )


def _error(check_id: str, location: str) -> Diagnostic:
    return Diagnostic(
        kind="error",
        check_id=check_id,
        location=location,
        expected="项目内真实相对文件路径和可定位符号",
        actual="中文描述，不是文件路径",
        evidence="项目根下不存在该单元格所写路径",
        impact="功能到代码映射无法核对",
        next_action="填写真实文件路径和符号",
    )


def test_report_lists_all_independent_errors_in_stable_order():
    first = _error(
        "architecture.code_mapping",
        "spec\\代码架构设计.md 第 6.5 节，第 1 张表，第 12 行，代码位置列",
    )
    second = _error(
        "architecture.code_mapping",
        "spec/代码架构设计.md 第 6.5 节，第 1 张表，第 3 行，代码位置列",
    )
    third = _error("architecture.feature_document", "spec/功能_b.md 第 8 行")

    ordered = stable_sort_diagnostics([third, first, second], stage="update_code_design")
    assert ordered == [second, first, third]

    report_a = ValidationReport(
        stage="update_code_design",
        gate="代码校验",
        diagnostics=[third, first, second],
        next_command=_next_command(),
    )
    report_b = ValidationReport(
        stage="update_code_design",
        gate="代码校验",
        diagnostics=[second, third, first],
        next_command=_next_command(),
    )

    assert report_a.passed is False
    assert report_a.to_dict() == report_b.to_dict()
    assert report_a.report_hash == report_b.report_hash


def test_report_renders_errors_not_checked_and_one_complete_next_command():
    report = ValidationReport(
        stage="regression_test",
        gate="第二道门",
        next_command=NextCommand(
            command="workflow gate regression_test",
            executor="AI",
            side_effects="自动执行已登记的统一全量测试入口",
            success_condition="退出码为 0 且机器报告证明所有测试真实执行并通过",
            next_stage="overall_acceptance（整体验收）",
        ),
    )
    report.add_error(
        check_id="regression.entry",
        location=".workflow_loop/project.json 字段 test_entry",
        expected="一个存在的项目内统一测试入口",
        actual="scripts/missing.sh",
        evidence="项目内该路径不存在",
        impact="无法启动最终全量回归",
        next_action="登记存在的统一测试入口",
    )
    report.add_not_checked(
        check_id="regression.execution",
        location=".workflow_loop/state.json 字段 regression_test.current_record",
        expected="本次全量测试的机器执行记录",
        actual="未检查：测试入口无效，不能可靠执行",
        evidence="前置检查 regression.entry 失败",
        impact="不能判断最终回归是否通过",
        next_action="修复 regression.entry 后重新执行本门禁",
        depends_on="regression.entry",
    )

    rendered = format_validation_report(report)

    assert "错误 1 项，未检查 1 项" in rendered
    assert "位置: .workflow_loop/project.json 字段 test_entry" in rendered
    assert "预期: 一个存在的项目内统一测试入口" in rendered
    assert "前置检查: regression.entry" in rendered
    assert rendered.count("下一步命令: workflow gate regression_test") == 1
    assert "自动动作: 自动执行已登记的统一全量测试入口" in rendered
    assert "请按上述每项“下一动作”处理" in rendered
    assert "状态和内容未变化时不要重复执行同一条失败命令" in rendered
    assert report.report_hash in rendered


def test_not_checked_requires_a_named_failed_prerequisite():
    with pytest.raises(ValueError, match="depends_on"):
        Diagnostic(
            kind="not_checked",
            check_id="test.execution",
            location="state.test_record",
            expected="真实执行记录",
            actual="未检查",
            evidence="前置条件不明",
            impact="不能判定测试结果",
            next_action="先修复前置条件",
        )


def test_legacy_tuple_can_be_wrapped_and_returned_without_losing_all_fields():
    report = report_from_legacy_result(
        (False, "文件未产出: spec/功能_a.md"),
        stage="spec",
        gate="代码校验",
        next_command=NextCommand(
            command="workflow gate spec",
            executor="AI",
            side_effects="只读校验正式文档",
            success_condition="全部产品文档存在并通过内容校验",
            next_stage="revise_code_design（设计期代码设计修订）",
        ),
        check_id="spec.artifact_exists",
        location="spec/功能_a.md",
        expected="文件存在",
        impact="产品功能集合不完整",
        next_action="生成缺失的产品功能文档",
    )

    passed, detail = legacy_result(report)

    assert passed is False
    assert "spec.artifact_exists" in detail
    assert "文件未产出: spec/功能_a.md" in detail
    assert "产品功能集合不完整" in detail


def test_successful_report_has_deterministic_hash_and_legacy_success():
    report = ValidationReport(
        stage="spec",
        gate="代码校验",
        next_command=NextCommand(
            command="workflow gate spec --confirmed",
            executor="用户确认后由 AI 执行",
            side_effects="记录用户确认并推进到下一阶段",
            success_condition="确认时文档仍与本次校验内容一致",
            next_stage="revise_code_design（设计期代码设计修订）",
        ),
    )

    assert report.passed is True
    assert legacy_result(report) == (True, "校验通过")
    assert report.report_hash == report.report_hash


def test_cli_failure_adapter_keeps_all_rows_and_marks_dependent_checks():
    rendered = _format_failure_diagnostics(
        stage_name="update_code_design",
        gate_name="代码校验",
        details=(
            "1. spec/代码架构设计.md 第 20 行，代码位置列：不是项目内真实文件\n"
            "2. spec/代码架构设计.md 第 25 行，验证位置列：不是项目内真实文件\n"
            "- 最终同步检查：未检查：前两项代码映射失败"
        ),
        command="workflow gate update_code_design",
        side_effects="只读核对最终架构，不修改文件",
        success_condition="全部功能映射和验证位置可定位",
        next_stage="update_code_design（最终设计同步）",
    )

    assert "第 20 行" in rendered
    assert "第 25 行" in rendered
    assert "错误 2 项，未检查 1 项" in rendered
    assert rendered.count("下一步命令: workflow gate update_code_design") == 1


def test_regression_instruction_exposes_only_the_real_execution_command():
    state = WorkflowState(
        workflow_id="regression-command",
        intent="product_change",
        current_stage="regression_test",
        stage_path=["regression_test", "overall_acceptance"],
        stages={
            "regression_test": StageState(
                status="in_progress",
                gate=GateState(discussion_complete=True),
            ),
            "overall_acceptance": StageState(),
        },
    )

    instruction = current_stage_next_instruction(state)

    assert "workflow gate regression_test" in instruction
    assert "workflow regression" not in instruction
    assert "workflow test run" not in instruction
    assert "自动执行" in instruction
