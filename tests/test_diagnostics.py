import pytest

from workflow_loop.cli import (
    _deduplicate_diagnostics,
    _format_failure_diagnostics,
    current_stage_next_instruction,
)
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


def test_cli_adapter_preserves_structured_facts_and_real_dependencies():
    """Workflow-Test
    主题：所有阶段门禁失败时一次指出全部真实原因和改法
    测试项：TC-01 一次列全错误并标明未检查依赖
    验收条件：AC-01 一次收集全部可独立确定的问题
    测试方式：自动化测试
    测试层级：模块测试
    产品入口：`workflow gate impl --discuss-done` 失败报告
    测试入口：`tests/test_diagnostics.py::test_cli_adapter_preserves_structured_facts_and_real_dependencies`
    代码入口：`src/workflow_loop/cli.py::_format_failure_diagnostics`
    准备数据：建立含一项独立错误、一项依赖该错误的未检查项和一条无效下层命令的结构化诊断报告。
    执行动作：通过门禁命令层格式化该报告，并传入当前门禁唯一有效的下一命令。
    关键断言：独立错误和未检查项各出现一次；未检查项指明真实前置检查；下层事实全部保留；无效下层命令被当前门禁命令替换且只出现一次。
    预期证据：结构化报告需精确匹配该测试入口，实际执行数为 1，跳过数、失败数和错误数均为 0；测试断言需保留检查编号、位置、预期、实际、证据、影响、改法、依赖和唯一命令。
    """
    source_report = ValidationReport(
        stage="impl",
        gate="实施计划解析",
        next_command=NextCommand(
            command="workflow should-not-survive",
            executor="错误的下层执行者",
            side_effects="错误的下层副作用",
            success_condition="错误的下层成功条件",
            next_stage="错误阶段",
        ),
    )
    source_report.add_error(
        check_id="impl.plan.path",
        location="impl/上传文件_实施记录.md 第 83 行，文件列",
        expected="单一项目内相对路径 `src/upload.py`",
        actual="`src/upload.py` 与 `tests/test_upload.py` 写在同一个单元格",
        evidence="实施计划第 83 行的文件单元格包含两个 Markdown 代码路径",
        impact="不能保存每个目标文件的修改前副本",
        next_action="把两个文件拆成两条计划记录，并分别填写真实符号",
    )
    source_report.add_not_checked(
        check_id="impl.rollback.prepare",
        location=".workflow_loop/rollback/",
        expected="每个计划文件都有可验证的首次原内容副本",
        actual="未检查：实施计划路径无法单独解析",
        evidence="前置检查 impl.plan.path 失败",
        impact="不能安全开始代码实施",
        next_action="先修正 impl.plan.path，再保存实施前回退副本",
        depends_on="impl.plan.path",
    )

    rendered = _format_failure_diagnostics(
        stage_name="impl",
        gate_name="讨论完成校验",
        details=source_report,
        command="workflow gate impl --discuss-done",
        side_effects="只核对实施计划和当前状态，不修改产品代码",
        success_condition="实施计划中的每个文件和符号都能单独定位",
        next_stage="impl（代码实施）",
    )

    for expected in (
        "impl.plan.path",
        "impl.rollback.prepare",
        "单一项目内相对路径 `src/upload.py`",
        "实施计划第 83 行的文件单元格包含两个 Markdown 代码路径",
        "把两个文件拆成两条计划记录，并分别填写真实符号",
        "前置检查: impl.plan.path",
    ):
        assert expected in rendered
    assert "impl.prerequisite" not in rendered
    assert "workflow should-not-survive" not in rendered
    assert rendered.count("下一步命令: workflow gate impl --discuss-done") == 1


def test_repeated_failure_report_is_byte_stable_and_exposes_one_next_command():
    """Workflow-Test
    主题：所有阶段门禁失败时一次指出全部真实原因和改法
    测试项：TC-09 重复失败报告全文和哈希稳定且只有一条命令
    验收条件：AC-06 相同输入稳定输出并只给一个有效下一动作
    测试方式：自动化测试
    测试层级：模块测试
    产品入口：`workflow gate regression_test` 的最终失败报告渲染
    测试入口：`tests/test_diagnostics.py::test_repeated_failure_report_is_byte_stable_and_exposes_one_next_command`
    代码入口：`src/workflow_loop/diagnostics.py::format_validation_report`
    准备数据：用相同项目事实建立含两项顺序不同的独立错误、一项依赖错误的未检查项和一条完整下一命令的两份诊断报告。
    执行动作：分别渲染两份报告并计算报告哈希。
    关键断言：两次完整输出逐字一致且哈希一致；错误和未检查项顺序稳定；只出现一次完整下一命令，并明确状态未变时不要原样重试。
    预期证据：结构化报告需精确匹配该测试入口，实际执行数为 1，跳过数、失败数和错误数均为 0；断言需直接比较完整文本、完整哈希和下一命令出现次数。
    """
    first_error = Diagnostic(
        kind="error",
        check_id="regression.entry",
        location=".workflow_loop/project.json 字段 test_entry",
        expected="一个存在的项目内统一测试入口",
        actual="scripts/missing.sh",
        evidence="项目内该路径不存在",
        impact="无法启动最终全量回归",
        next_action="登记存在的统一测试入口",
    )
    second_error = Diagnostic(
        kind="error",
        check_id="regression.record",
        location=".workflow_loop/state.json 字段 regression_test.current_record",
        expected="绑定当前代码的完整机器记录",
        actual="记录绑定旧代码哈希",
        evidence="记录哈希与当前代码哈希不同",
        impact="不能证明当前代码通过最终回归",
        next_action="修复入口后重新执行最终回归",
    )
    not_checked = Diagnostic(
        kind="not_checked",
        check_id="regression.execution",
        location="统一全量测试入口",
        expected="真实执行统一全量测试入口",
        actual="未检查：测试入口无效，不能可靠执行",
        evidence="前置检查 regression.entry 失败",
        impact="不能判断最终回归是否通过",
        next_action="先修复 regression.entry，再执行最终回归",
        depends_on="regression.entry",
    )
    next_command = NextCommand(
        command="workflow gate regression_test",
        executor="AI",
        side_effects="自动执行已登记的统一全量测试入口",
        success_condition="退出码为 0 且机器报告证明所有测试真实执行并通过",
        next_stage="overall_acceptance（整体验收）",
    )
    report_a = ValidationReport(
        stage="regression_test",
        gate="第二道门",
        diagnostics=[second_error, not_checked, first_error],
        next_command=next_command,
    )
    report_b = ValidationReport(
        stage="regression_test",
        gate="第二道门",
        diagnostics=[first_error, second_error, not_checked],
        next_command=next_command,
    )

    rendered_a = format_validation_report(report_a)
    rendered_b = format_validation_report(report_b)

    assert rendered_a == rendered_b
    assert report_a.report_hash == report_b.report_hash
    assert rendered_a.count("下一步命令: workflow gate regression_test") == 1
    assert "状态和内容未变化时不要重复执行同一条失败命令" in rendered_a


def test_deduplicate_keeps_distinct_checks_at_the_same_location():
    """不同规则即使碰巧报在同一位置，也不能在汇总时丢掉其中一项。"""
    first = Diagnostic(
        kind="error",
        check_id="impl.record.location",
        location="impl/上传文件_实施记录.md 第 41 行",
        expected="目标文件内真实函数名",
        actual="组件",
        evidence="目标文件没有名为“组件”的声明",
        impact="无法核对实际修改位置",
        next_action="填写真实函数名",
    )
    second = Diagnostic(
        kind="error",
        check_id="impl.record.acceptance",
        location="impl/上传文件_实施记录.md 第 41 行",
        expected="至少一个存在的 AC 编号",
        actual="组件",
        evidence="同一行的验收条件列没有 AC 编号",
        impact="无法追踪修改对应的验收条件",
        next_action="填写存在的 AC 编号",
    )

    assert _deduplicate_diagnostics([first, second]) == [first, second]


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
