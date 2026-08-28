"""当前工作流新增契约的正式测试入口。"""

from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
import sys

import pytest

from workflow_loop import cli as cli_mod
from workflow_loop.state import GateState, StageState, WorkflowState


_LOADED_TEST_MODULES = {}


def _test_module(stem: str):
    """按文件名加载既有测试模块，复用其中已经验证过的真实场景。"""
    if stem in _LOADED_TEST_MODULES:
        return _LOADED_TEST_MODULES[stem]
    path = Path(__file__).with_name(f"{stem}.py")
    module_name = f"_current_workflow_contract_{stem}"
    spec = spec_from_file_location(module_name, path)
    assert spec is not None and spec.loader is not None
    module = module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    _LOADED_TEST_MODULES[stem] = module
    return module


def _run(stem: str, function_name: str, *args) -> None:
    getattr(_test_module(stem), function_name)(*args)


def _case(tmp_path: Path, name: str) -> Path:
    path = tmp_path / name
    path.mkdir(parents=True)
    return path


def test_actual_change_gate_process_is_shown_once_per_stage(tmp_path):
    """Workflow-Test
    主题：代码门禁按实际改动验证并展示过程
    测试项：TC-01 实施和测试首次材料只展示一次完整过程
    验收条件：AC-01 首次进入实施完整展示实际改动门禁过程
    测试方式：自动化测试 + 人工验收
    测试层级：模块测试
    产品入口：`workflow discuss`
    测试入口：`tests/test_current_workflow_contracts.py::test_actual_change_gate_process_is_shown_once_per_stage`
    代码入口：`src/workflow_loop/cli.py::cmd_discuss`
    准备数据：分别建立首次进入和已经完成讨论的 `impl`、`qa` 状态，并准备可读取的阶段材料
    执行动作：对四种状态分别执行材料加载命令
    关键断言：`impl` 与 `qa` 首次输出各包含五步门禁含义，后续加载不重复整段说明；人工验收确认文字无需猜测
    预期证据：保存 pytest JUnit XML、四次标准输出和状态前后比较结果
    """
    impl_state = WorkflowState(
        workflow_id="tc01",
        intent="product_change",
        current_stage="impl",
        stages={"impl": StageState(gate=GateState())},
    )
    impl_state.meta[cli_mod.IMPL_CODE_BASELINE_NOTICE_PENDING_KEY] = {
        "code_snapshot_hash": "hash",
        "recovering": False,
    }
    notice = cli_mod._take_impl_code_baseline_notice(impl_state)
    assert notice is not None
    assert all(f"{index}." in notice for index in range(1, 6))
    assert "额外文件可以直接修改" in notice
    assert cli_mod._take_impl_code_baseline_notice(impl_state) is None

    qa_state = WorkflowState(
        workflow_id="tc01-qa",
        intent="product_change",
        current_stage="qa",
        stages={"qa": StageState(gate=GateState())},
    )
    qa_notice = cli_mod._take_qa_actual_test_gate_notice(qa_state, qa_state.stages["qa"])
    assert qa_notice is not None
    assert all(f"{index}." in qa_notice for index in range(1, 6))
    assert cli_mod._take_qa_actual_test_gate_notice(qa_state, qa_state.stages["qa"]) is None


def test_unplanned_implementation_file_passes_with_complete_evidence(tmp_path, monkeypatch):
    """Workflow-Test
    主题：代码门禁按实际改动验证并展示过程
    测试项：TC-02 计划外实现文件有完整记录时通过
    验收条件：AC-02 计划外实现文件不触发基线返工
    测试方式：自动化测试
    测试层级：集成测试
    产品入口：`workflow gate impl`
    测试入口：`tests/test_current_workflow_contracts.py::test_unplanned_implementation_file_passes_with_complete_evidence`
    代码入口：`src/workflow_loop/rollback.py::validate_actual_implementation_changes_report`
    准备数据：在隔离 Git 项目创建计划文件和一个未列入计划的实现文件，为额外文件写完整实际逻辑、修改理由、AC 和测试证据
    执行动作：修改额外文件并执行实施实际改动校验
    关键断言：额外文件出现在实际改动中且门禁通过；计划中未修改文件不失败；输出不含 `--prepare-code` 或 `--rebaseline`
    预期证据：保存结构化报告、实际路径集合和状态前后字节比较结果
    """
    _run("test_stages", "test_impl_gate_prefers_real_changes_over_existing_code_marker", _case(tmp_path, "tc02"), monkeypatch)


def test_actual_change_gate_reports_each_missing_evidence(tmp_path, monkeypatch):
    """Workflow-Test
    主题：代码门禁按实际改动验证并展示过程
    测试项：TC-03 每个实际文件的缺失证据一次列全
    验收条件：AC-03 代码门禁显示实际改动和缺失证据
    测试方式：自动化测试
    测试层级：模块测试
    产品入口：`workflow gate impl`
    测试入口：`tests/test_current_workflow_contracts.py::test_actual_change_gate_reports_each_missing_evidence`
    代码入口：`src/workflow_loop/rollback.py::validate_actual_implementation_changes_report`
    准备数据：建立多个实际改动文件，分别缺少实施记录、实际逻辑、AC 编号或测试证据，并保留一个完整文件
    执行动作：执行实施实际改动结构化校验
    关键断言：缺失项按文件稳定列出，完整文件不被误报，最终只有补齐证据后重跑当前门禁一个动作
    预期证据：保存全部结构化诊断、排序和报告哈希
    """
    _run("test_commands", "test_impl_gate_replaces_covered_legacy_text_with_structured_file_facts", _case(tmp_path, "tc03"), monkeypatch)


def test_impl_credential_change_rechecks_only_current_gate(tmp_path):
    """Workflow-Test
    主题：代码门禁按实际改动验证并展示过程
    测试项：TC-04 代码变化只使实施第二道门凭据失效
    验收条件：AC-04 代码后续变化只重跑当前代码门禁
    测试方式：自动化测试
    测试层级：集成测试
    产品入口：`workflow gate impl --confirmed`
    测试入口：`tests/test_current_workflow_contracts.py::test_impl_credential_change_rechecks_only_current_gate`
    代码入口：`src/workflow_loop/verification.py::compare_validation_credential_report`
    准备数据：建立已通过实施第二道门的凭据并保持讨论完成，再修改一个实际实现文件
    执行动作：执行实施第三道门凭据比较
    关键断言：旧第二道门凭据失效并要求重跑 `workflow gate impl`，讨论完成和计划确认仍保留
    预期证据：保存凭据差异报告及修改前后状态字段
    """
    _run("test_current_workflow_qa", "test_gate_ac02_credential_binds_only_stage_responsibility", _case(tmp_path, "tc04"))


def test_unavailable_change_or_recovery_scope_is_non_blocking(tmp_path):
    """Workflow-Test
    主题：代码门禁按实际改动验证并展示过程
    测试项：TC-05 无 Git 或恢复依据不足只显示限制
    验收条件：AC-05 改动范围和恢复限制如实展示但不阻塞门禁
    测试方式：自动化测试
    测试层级：模块测试
    产品入口：`workflow gate impl`
    测试入口：`tests/test_current_workflow_contracts.py::test_unavailable_change_or_recovery_scope_is_non_blocking`
    代码入口：`src/workflow_loop/rollback.py::validate_actual_implementation_changes`
    准备数据：分别建立无 Git 工作树和没有回退清单的隔离项目，实施记录和验收关联保持完整
    执行动作：执行实际改动核对和实施阶段校验
    关键断言：明确显示无法自动完整确认或不能自动恢复的范围，且不因该限制失败或要求重设基线
    预期证据：保存返回值、限制原文和结构化报告
    """
    from workflow_loop import rollback
    state = WorkflowState(workflow_id="tc05", intent="product_change", current_stage="impl", topics=[])
    ok, detail = rollback.validate_actual_implementation_changes(str(tmp_path), state)
    assert ok is True
    assert "无法自动完整确认" in detail or "实际改动和实施记录" in detail


def test_unplanned_test_file_does_not_require_baseline(tmp_path):
    """Workflow-Test
    主题：代码门禁按实际改动验证并展示过程
    测试项：TC-06 计划外测试文件可直接关联并继续
    验收条件：AC-06 计划外测试文件不触发测试基线返工
    测试方式：自动化测试
    测试层级：集成测试
    产品入口：`workflow gate qa`
    测试入口：`tests/test_current_workflow_contracts.py::test_unplanned_test_file_does_not_require_baseline`
    代码入口：`src/workflow_loop/stages/stages.py::TestCodeStage._validate_current_test_code`
    准备数据：在隔离 Git 项目新增未列入测试计划的测试文件，写入当前主题、TC 和 AC 的测试追踪标识
    执行动作：读取实际测试改动并执行 QA 测试代码校验
    关键断言：新测试路径被列出并可继续登记执行，不要求测试代码基线，也不清除 QA 范围确认
    预期证据：保存实际测试改动表、标识校验结果和状态比较结果
    """
    _run("test_verification", "test_active_snapshot_ignores_unregistered_build_and_dependency_files", _case(tmp_path, "tc06"))


def test_test_change_invalidates_only_affected_items(tmp_path):
    """Workflow-Test
    主题：代码门禁按实际改动验证并展示过程
    测试项：TC-07 测试变化只使直接受影响测试项失效
    验收条件：AC-07 测试改动后只重查并执行受影响测试项
    测试方式：自动化测试
    测试层级：集成测试
    产品入口：`workflow gate qa`
    测试入口：`tests/test_current_workflow_contracts.py::test_test_change_invalidates_only_affected_items`
    代码入口：`src/workflow_loop/verification.py::inspect_invalidation`
    准备数据：建立两个主题或两个独立测试项的当前机器记录，只修改其中一个测试文件或配置
    执行动作：执行失效检查并应用一次结果
    关键断言：只清除直接受影响测试项并要求重新登记执行；其它记录和 QA 范围确认保留
    预期证据：保存变化路径、受影响项列表及应用前后机器记录
    """
    _run("test_verification", "test_qa_test_code_change_returns_to_test_code_and_keeps_scope", _case(tmp_path, "tc07"))


def test_all_requirement_sources_have_acceptance_coverage(tmp_path):
    """Workflow-Test
    主题：验收计划覆盖完整且每项结果可判定
    测试项：TC-01 全部需求来源都有唯一验收去向
    验收条件：AC-01 本轮全部需求来源和产品行为都有验收入口
    测试方式：自动化测试
    测试层级：集成测试
    产品入口：`workflow gate acceptance_plan`（验收计划程序检查）
    测试入口：`tests/test_current_workflow_contracts.py::test_all_requirement_sources_have_acceptance_coverage`
    代码入口：`src/workflow_loop/artifact_validation.py::validate_downstream_traceability`
    准备数据：在隔离项目写入两项需求来源、两个主题、对应验收计划和九列追踪行，再额外构造一项遗漏来源和一个无来源主题
    执行动作：通过验收计划门禁使用的校验入口读取验收索引、计划和追踪表，并分别检查完整样本与两个缺陷样本
    关键断言：完整样本没有遗漏；缺陷样本同一次结果分别指出遗漏来源和无来源主题，且不能登记验收计划完成
    预期证据：pytest JUnit XML 报告中的原始测试入口、执行数量和零跳过事实，并保留校验错误清单
    """
    _run(
        "test_traceability",
        "test_traceability_validation_reports_all_topic_structure_errors",
        _case(tmp_path, "structure_errors"),
    )
    _run(
        "test_traceability",
        "test_traceability_writes_only_each_acceptance_criterion_test_items",
        _case(tmp_path, "criterion_coverage"),
    )


def test_each_acceptance_condition_has_complete_judgable_fields(tmp_path):
    """Workflow-Test
    主题：验收计划覆盖完整且每项结果可判定
    测试项：TC-02 六项验收字段缺失或含糊都会被一次指出
    验收条件：AC-02 每条验收条件都写明可检查状态和判定边界
    测试方式：自动化测试
    测试层级：模块测试
    产品入口：`workflow gate acceptance_plan`（验收计划程序检查）
    测试入口：`tests/test_current_workflow_contracts.py::test_each_acceptance_condition_has_complete_judgable_fields`
    代码入口：`src/workflow_loop/artifact_validation.py::validate_acceptance_plan_documents`
    准备数据：在隔离项目生成一份完整验收计划，再分别删除开始前状态、触发动作、可检查结果、通过标准、不通过标准和产品依据，并加入“正常”“符合预期”等占位值
    执行动作：调用正式验收计划校验入口检查完整计划和所有缺陷计划
    关键断言：完整计划通过；缺失、占位、无效依据和重复定位编号全部在一次结果中按文件与 AC 编号出现
    预期证据：pytest JUnit XML 报告、精确测试入口、全部缺陷样本数量和逐项错误文本
    """
    _run(
        "test_stages",
        "test_acceptance_plan_requires_complete_judgable_fields",
        _case(tmp_path, "complete_and_missing_result"),
    )
    fields = (
        ("开始前状态", "用户已进入上传界面且目标文件存在。"),
        ("触发动作", "用户选择有效文件并提交。"),
        ("可检查结果", "目标文件被保存，界面显示成功结果。"),
        ("通过标准", "保存后的文件可读取且内容与输入一致。"),
        ("不通过标准", "文件缺失、内容不一致或界面没有成功结果。"),
        ("产品设计依据", "[上传功能](../spec/功能_上传文件.md)，第 4 章 R1。"),
    )
    for index, (label, value) in enumerate(fields):
        _run(
            "test_stages",
            "test_acceptance_plan_rejects_each_missing_or_placeholder_outcome_field",
            _case(tmp_path, f"field_{index}"),
            label,
            value,
        )


def test_complete_research_paths_follow_impl_before_test_plan(tmp_path):
    """Workflow-Test
    主题：验收实施和测试计划统一按新顺序推进
    测试项：TC-01 三类完整轮次都先实施后测试计划
    验收条件：AC-01 新轮次按完整统一顺序推进
    测试方式：自动化测试
    测试层级：命令测试
    产品入口：`workflow start --intent from_scratch`、`workflow start --intent product_change` 和 `workflow start --intent bugfix`
    测试入口：`tests/test_current_workflow_contracts.py::test_complete_research_paths_follow_impl_before_test_plan`
    代码入口：`src/workflow_loop/path_composer.py::build_stage_path`
    准备数据：分别准备从零创建、修改产品和修复缺陷三种意图，并保留无需开发任务作为边界样本
    执行动作：调用阶段路径生成入口取得每种意图的完整阶段数组
    关键断言：三种完整轮次均按验收计划、实施、测试计划、测试代码、测试执行排列；无需开发任务没有研发阶段
    预期证据：pytest JUnit XML 报告、四种意图的实际阶段数组和精确测试入口
    """
    _run(
        "test_commands",
        "test_three_intents_produce_complete_project_specific_paths",
        _case(tmp_path, "complete_paths"),
    )
    _run(
        "test_light_task",
        "test_light_task_route_requires_explicit_start_and_keeps_one_active_run",
        _case(tmp_path, "light_task"),
    )


def test_legacy_stage_order_migrates_once_without_read_side_effects(
    tmp_path,
    monkeypatch,
):
    """Workflow-Test
    主题：验收实施和测试计划统一按新顺序推进
    测试项：TC-02 旧轮次只读零写且首次继续只迁移一次
    验收条件：AC-02 进行中旧轮次只迁移一次并废止实施前测试计划
    测试方式：自动化测试
    测试层级：集成测试
    产品入口：`workflow status` 后执行一条会写状态的继续命令
    测试入口：`tests/test_current_workflow_contracts.py::test_legacy_stage_order_migrates_once_without_read_side_effects`
    代码入口：`src/workflow_loop/cli.py::ensure_stage_path_current`
    准备数据：构造测试计划位于实施前的活动状态，写入已确认验收、旧测试任务、验收记录、回归状态、追踪行和正式结果文件，并保存所有文件原字节
    执行动作：先执行只读状态预览，再执行一次继续入口，再执行第二次继续；另注入状态保存和日志追加失败
    关键断言：只读前后逐字一致；首次继续保留验收和代码、清旧测试及后续并回到实施；第二次零重复迁移；任一写入失败全部恢复
    预期证据：pytest JUnit XML 报告、迁移前后文件哈希、唯一迁移日志和故障恢复比较结果
    """
    _run(
        "test_commands",
        "test_legacy_order_status_preview_is_zero_write",
        _case(tmp_path, "preview"),
    )
    _run(
        "test_commands",
        "test_legacy_order_migration_clears_old_facts_and_is_idempotent",
        _case(tmp_path, "migration"),
    )
    for failed_step in ("save_state", "journal"):
        with monkeypatch.context() as scoped:
            _run(
                "test_commands",
                "test_legacy_order_migration_failure_restores_every_original_byte",
                _case(tmp_path, f"failure_{failed_step}"),
                scoped,
                failed_step,
            )


def test_upstream_invalidation_preserves_only_current_evidence(tmp_path):
    """Workflow-Test
    主题：验收实施和测试计划统一按新顺序推进
    测试项：TC-03 三类上游变化按主题精确失效
    验收条件：AC-03 上游变化只保留仍有当前依据的结果
    测试方式：自动化测试
    测试层级：集成测试
    产品入口：`workflow return` 后执行对应阶段门禁
    测试入口：`tests/test_current_workflow_contracts.py::test_upstream_invalidation_preserves_only_current_evidence`
    代码入口：`src/workflow_loop/verification.py::inspect_invalidation`
    准备数据：构造两个独立主题并确认实施、测试计划、测试执行和验收；分别改变一个主题的验收计划、实施代码或记录、测试计划，再构造共享索引变化；另将 `qa/索引.md` 的测试结果和 `acceptance/索引.md` 的验收结果从待生成路径切换为对应正式链接
    执行动作：对每种输入调用只读失效检查；对真实上游变化应用检查结果并比较状态、哈希、任务、结果文件和追踪列，对两种结果链接转换只比较规范化前后快照与失效结果
    关键断言：验收计划变化清实施及测试；实施变化清测试计划及后续；仅测试计划变化保留实施；独占变化只清所属主题，共享变化才清全部主题；两种结果链接从待生成变为已生成时均不使上游计划失效
    预期证据：pytest JUnit XML 报告、逐文件变化类型、受影响主题列表、应用前后状态快照及两类索引的规范化哈希
    """
    for index, function_name in enumerate(
        (
            "test_invalidation_inspection_lists_exact_changes_before_one_apply",
            "test_impl_invalidation_only_clears_the_topic_that_owns_changed_code",
            "test_shared_test_plan_index_change_affects_all_topics",
            "test_test_plan_change_preserves_confirmed_implementation",
            "test_test_result_link_transition_does_not_invalidate_test_plan",
            "test_acceptance_result_link_transition_does_not_invalidate_acceptance_plan",
            "test_check_invalidation_acceptance_plan_changed",
        )
    ):
        _run("test_verification", function_name, _case(tmp_path, f"case_{index}"))


def test_implementation_plan_actual_and_record_sets_match(tmp_path):
    """Workflow-Test
    主题：实施记录只能记录真实发生的修改
    测试项：TC-01 三组实施文件集合必须完全相等
    验收条件：AC-01 计划范围、真实修改范围和记录范围完全一致
    测试方式：自动化测试
    测试层级：集成测试
    产品入口：`workflow gate impl`（实施完成程序检查）
    测试入口：`tests/test_current_workflow_contracts.py::test_implementation_plan_actual_and_record_sets_match`
    代码入口：`src/workflow_loop/rollback.py::validate_implementation_changes`
    准备数据：在隔离项目保存两文件实施前基线，分别构造计划未改、计划外修改、修改未记录、记录无差异和三组一致五种状态
    执行动作：调用实施真实性校验入口比较计划集合、基线后真实差异集合和实施记录集合
    关键断言：只有三组集合完全相等时通过；四种不一致同一次结果分别显示准确文件；既有代码例外只核对计划、记录和文件存在性
    预期证据：pytest JUnit XML 报告、三组排序路径和四类差异文本
    """
    _run(
        "test_rollback",
        "test_impl_reentry_allows_only_unchanged_confirmed_test_files",
        _case(tmp_path, "matching_sets"),
    )
    _run(
        "test_rollback",
        "test_impl_reentry_ignores_unchanged_unplanned_test_baseline_before_confirmation",
        _case(tmp_path, "unconfirmed_test_code_return"),
    )
    _run(
        "test_rollback",
        "test_planned_actual_and_recorded_implementation_paths_must_match",
        _case(tmp_path, "mismatched_sets"),
    )
    _run(
        "test_rollback",
        "test_existing_implementation_checks_plan_record_and_real_files",
        _case(tmp_path, "existing_code"),
    )


def test_implementation_record_locations_match_final_files(tmp_path):
    """Workflow-Test
    主题：实施记录只能记录真实发生的修改
    测试项：TC-02 每条实施记录都能定位最终事实
    验收条件：AC-02 实施后记录逐项对应最终项目事实
    测试方式：自动化测试
    测试层级：模块测试
    产品入口：`workflow gate impl`（实施完成程序检查）
    测试入口：`tests/test_current_workflow_contracts.py::test_implementation_record_locations_match_final_files`
    代码入口：`src/workflow_loop/rollback.py::recorded_code_paths`
    准备数据：准备包含真实函数、模板标题和删除文件声明的实施记录，再构造不存在位置、占位逻辑、空输出变化、错误 AC 和记录无差异样本
    执行动作：读取实施后记录并核对文件、位置、逻辑、可观察变化和验收编号，再与当前文件和差异集合比较
    关键断言：完整记录返回全部真实路径；所有独立错误一次列出文档行和原值；开发反馈不会被当成正式测试结果
    预期证据：pytest JUnit XML 报告、记录行号、位置命中事实和错误字段清单
    """
    _run(
        "test_rollback",
        "test_existing_implementation_checks_plan_record_and_real_files",
        _case(tmp_path, "valid_record"),
    )
    _run(
        "test_rollback",
        "test_implementation_record_reports_every_invalid_row_fact_at_once",
        _case(tmp_path, "invalid_record"),
    )


def test_impl_gate_blocks_every_detected_mismatch(tmp_path, monkeypatch):
    """Workflow-Test
    主题：实施记录只能记录真实发生的修改
    测试项：TC-03 实施门禁发现任一不一致都停留当前阶段
    验收条件：AC-03 任何实施不一致都会阻止进入测试计划
    测试方式：自动化测试
    测试层级：集成测试
    产品入口：`workflow gate impl`（实施完成程序检查）
    测试入口：`tests/test_current_workflow_contracts.py::test_impl_gate_blocks_every_detected_mismatch`
    代码入口：`src/workflow_loop/stages/stages.py::ImplStage.code_validate`
    准备数据：构造回退清单损坏、计划变化、记录缺项、计划外修改和多个问题并存的实施状态，并保存门禁前状态字节
    执行动作：执行实施阶段代码校验，比较返回诊断、当前阶段、门禁状态和后续阶段
    关键断言：所有可独立确认的问题一次显示；实施保持未确认且当前阶段不变；只有全部修正后才能进入测试计划
    预期证据：pytest JUnit XML 报告、门禁前后状态哈希及完整诊断清单
    """
    with monkeypatch.context() as scoped:
        _run(
            "test_stages",
            "test_impl_gate_prefers_real_changes_over_existing_code_marker",
            _case(tmp_path, "valid_gate"),
            scoped,
        )
    with monkeypatch.context() as scoped:
        _run(
            "test_stages",
            "test_impl_gate_reports_real_change_mismatch_even_with_existing_code_marker",
            _case(tmp_path, "invalid_gate"),
            scoped,
        )


def test_test_plan_rows_bind_real_entries_actions_and_results(tmp_path):
    """Workflow-Test
    主题：正式测试只在真实目标完整执行后通过
    测试项：TC-01 测试计划完整绑定真实实施和入口
    验收条件：AC-01 测试计划在实施完成后写清真实验证办法
    测试方式：自动化测试
    测试层级：模块测试
    产品入口：`workflow gate test_plan`（测试计划程序检查）
    测试入口：`tests/test_current_workflow_contracts.py::test_test_plan_rows_bind_real_entries_actions_and_results`
    代码入口：`src/workflow_loop/artifact_validation.py::validate_test_plan_documents`
    准备数据：构造已确认实施和 13 列完整测试计划，再分别删除产品入口、代码入口、测试入口、准备、动作、观察、预期、失败表现和证据字段，并加入“实施后确认”
    执行动作：调用测试计划正式校验入口检查索引、实施绑定、AC 覆盖和全部测试项字段
    关键断言：完整计划通过；所有缺失和占位字段同一次结果出现；实施未确认或哈希变化时明确阻断且计划不通过
    预期证据：pytest JUnit XML 报告、完整测试项解析结果和全部缺陷字段清单
    """
    mapping = _test_module("test_test_mapping")
    _run(
        "test_test_mapping",
        "test_test_plan_parses_method_primary_criterion_and_direct_dependencies",
        _case(tmp_path, "complete_plan"),
    )
    invalid_relationships = (
        (mapping._row() + "\n" + mapping._row(), "只能对应一条主要验收条件"),
        (
            mapping._row("TC-01", dependency="TC-02")
            + "\n"
            + mapping._row("TC-02", "检查上传状态", "TC-01"),
            "依赖存在循环",
        ),
        (
            mapping._row(method="人工验收")
            + "\n"
            + mapping._row("TC-02", "自动检查上传状态", "TC-01", "自动化测试"),
            "不能依赖人工验收项",
        ),
    )
    for index, (rows, message) in enumerate(invalid_relationships):
        _run(
            "test_test_mapping",
            "test_test_plan_rejects_duplicate_cycle_and_manual_dependency",
            _case(tmp_path, f"invalid_relationship_{index}"),
            rows,
            message,
        )
    base_cells = [cell.strip() for cell in mapping._row().strip().strip("|").split("|")]
    for index in range(4, 13):
        root = _case(tmp_path, f"missing_field_{index}")
        cells = list(base_cells)
        cells[index] = "实施后确认"
        mapping._plan(root, "| " + " | ".join(cells) + " |")
        with pytest.raises(ValueError, match="缺少可执行内容或仍使用占位值"):
            mapping.parse_test_plan_items(str(root), mapping.TOPIC)


def test_test_code_calls_product_entry_and_asserts_observable_result(tmp_path):
    """Workflow-Test
    主题：正式测试只在真实目标完整执行后通过
    测试项：TC-02 测试正文必须调用产品入口并验证其结果
    验收条件：AC-02 测试调用真实产品入口并检查入口产生的结果
    测试方式：自动化测试
    测试层级：模块测试
    产品入口：`workflow gate test_code`（测试代码程序检查）
    测试入口：`tests/test_current_workflow_contracts.py::test_test_code_calls_product_entry_and_asserts_observable_result`
    代码入口：`src/workflow_loop/test_mapping.py::validate_workflow_test_markers`
    准备数据：准备一项完整测试计划和真实产品函数，分别写真实调用测试、空函数、仅 pass、固定常量返回、恒真断言、只设置目标属性后原样断言等测试正文
    执行动作：通过测试代码门禁使用的标识校验读取测试定义范围、正文摘要和哈希，并核对计划中的入口、准备、动作、断言和证据
    关键断言：只有实际调用产品入口并断言入口结果的测试通过；所有空测试和自造结果测试一次列出具体文件、定义与原因
    预期证据：pytest JUnit XML 报告、测试正文 SHA-256、入口调用和关键断言证据
    """
    _run(
        "test_test_mapping",
        "test_python_workflow_marker_binds_readable_names_method_and_entry",
        _case(tmp_path, "real_call"),
    )
    noops = (
        ("", "没有测试代码"),
        ("    pass", "只有 pass 空语句"),
        ("    ...", "只有 Ellipsis（...）空语句"),
        ("    return True", "只返回固定常量"),
        ("    return {'status': 'passed'}", "只返回固定常量"),
        ("    assert True", "只有恒真的字面量断言"),
        ("    assert 'always true'", "只有恒真的字面量断言"),
    )
    for index, (body, reason) in enumerate(noops):
        _run(
            "test_test_mapping",
            "test_python_workflow_marker_rejects_only_obvious_noop_body",
            _case(tmp_path, f"noop_{index}"),
            body,
            reason,
        )
    mapping = _test_module("test_test_mapping")
    self_made_bodies = (
        "    role = 'superadmin'\n    assert role == 'superadmin'",
        (
            "    target = type('Target', (), {})()\n"
            "    target.manually_edited = 1\n"
            "    assert target.manually_edited == 1"
        ),
    )
    unexpected_acceptances = []
    incomplete_rejections = []
    for index, body in enumerate(self_made_bodies):
        self_made_result = _case(tmp_path, f"self_made_result_{index}")
        mapping._plan(self_made_result, mapping._row())
        mapping._write(
            self_made_result / "tests" / "test_upload.py",
            mapping._python_marker(body=body),
        )
        ok, detail = mapping.validate_workflow_test_markers(
            str(self_made_result),
            [mapping.TOPIC],
        )
        if ok:
            unexpected_acceptances.append(f"样本 {index + 1}: {body.strip()}\n{detail}")
        elif "没有验证真实行为" not in detail:
            incomplete_rejections.append(f"样本 {index + 1}: {detail}")
    assert not unexpected_acceptances, "门禁错误放行自造结果：\n" + "\n".join(
        unexpected_acceptances
    )
    assert not incomplete_rejections, "门禁拒绝原因不明确：\n" + "\n".join(
        incomplete_rejections
    )
    for index, body in enumerate(
        (
            "    assert helper_result()",
            "    return helper_result()",
            "    with pytest.raises(ValueError):\n        raise ValueError('expected')",
        )
    ):
        _run(
            "test_test_mapping",
            "test_python_workflow_marker_keeps_nontrivial_helpers_and_expected_errors",
            _case(tmp_path, f"helper_{index}"),
            body,
        )


def test_structured_report_requires_exact_non_skipped_current_targets(
    tmp_path,
    monkeypatch,
):
    """Workflow-Test
    主题：正式测试只在真实目标完整执行后通过
    测试项：TC-03 正式通过同时要求精确目标和零跳过失败错误
    验收条件：AC-03 结构化报告精确证明登记目标在当前代码上完整执行
    测试方式：自动化测试
    测试层级：集成测试
    产品入口：`workflow test prepare` 后执行 `workflow test run`
    测试入口：`tests/test_current_workflow_contracts.py::test_structured_report_requires_exact_non_skipped_current_targets`
    代码入口：`src/workflow_loop/test_execution.py::run_prepared_tasks`
    准备数据：登记一个 pytest 精确入口和受管报告路径，构造真实通过、零执行、跳过、失败、错误、缺目标、多目标、重复目标、旧报告和代码执行中变化样本
    执行动作：运行受控测试进程并解析本次新报告，随后复核任务、机器记录和自动验收记录当前性
    关键断言：仅真实目标集合完全相等、执行数大于零、三类异常数为零、进程成功且代码未变时建立当前成功记录；其余全部清旧成功
    预期证据：pytest JUnit XML 报告本身、报告哈希与大小、精确目标、四项计数、进程退出码和代码身份
    """
    _run(
        "test_test_report",
        "test_vitest_report_recomputes_counts_and_matches_exact_entry",
        _case(tmp_path, "report_success"),
    )
    _run(
        "test_test_report",
        "test_vitest_discovered_but_skipped_is_not_counted_as_executed",
        _case(tmp_path, "report_skipped"),
    )
    for index, (outcome, field) in enumerate(
        (("<failure />", "failed_count"), ("<error />", "error_count"))
    ):
        _run(
            "test_test_report",
            "test_report_recomputes_failure_and_error_from_testcases",
            _case(tmp_path, f"report_outcome_{index}"),
            outcome,
            field,
            1,
        )
    _run(
        "test_test_report",
        "test_pytest_matches_only_dedicated_original_nodeid_property",
        _case(tmp_path, "pytest_exact_target"),
    )
    _run(
        "test_test_report",
        "test_pytest_does_not_guess_target_from_classname_or_name",
        _case(tmp_path, "pytest_missing_target"),
    )
    _run(
        "test_test_execution",
        "test_run_success_writes_current_record_but_not_formal_result",
        _case(tmp_path, "execution_success"),
    )
    _run(
        "test_test_execution",
        "test_failed_rerun_clears_previous_current_success_and_result",
        _case(tmp_path, "execution_failed_rerun"),
    )
    with monkeypatch.context() as scoped:
        _run(
            "test_test_report",
            "test_report_rejects_symlink_outside_path_and_oversize",
            _case(tmp_path, "untrusted_report"),
            scoped,
        )


def test_gate_reports_all_independent_errors_and_unchecked_dependencies(tmp_path):
    """Workflow-Test
    主题：门禁失败一次展示完整可处理原因且快照范围准确
    测试项：TC-01 同一门禁一次报告全部错误和未检查项
    验收条件：AC-01 一次列出全部独立错误并标明未检查依赖
    测试方式：自动化测试
    测试层级：模块测试
    产品入口：`workflow gate impl`（实施阶段第二道门）
    测试入口：`tests/test_current_workflow_contracts.py::test_gate_reports_all_independent_errors_and_unchecked_dependencies`
    代码入口：`src/workflow_loop/diagnostics.py::format_validation_report`
    准备数据：构造两个独立文档错误、一个状态错误和一个依赖前置错误才能执行的带副作用检查，并记录副作用调用次数
    执行动作：原样调用门禁校验入口生成完整报告
    关键断言：三个独立错误各出现一次；依赖检查标为未检查并注明依赖；副作用未执行；状态停留当前阶段
    预期证据：pytest JUnit XML 报告、完整诊断文本和副作用调用次数零
    """
    _run("test_diagnostics", "test_report_lists_all_independent_errors_in_stable_order")
    _run(
        "test_diagnostics",
        "test_report_renders_errors_not_checked_and_one_complete_next_command",
    )
    _run(
        "test_diagnostics",
        "test_cli_failure_adapter_keeps_all_rows_and_marks_dependent_checks",
    )
    _run(
        "test_stages",
        "test_stage_prerequisite_failures_list_all_independent_and_unchecked_items",
        _case(tmp_path, "stage_failures"),
    )


def test_gate_error_points_to_exact_source_and_one_next_command(tmp_path):
    """Workflow-Test
    主题：门禁失败一次展示完整可处理原因且快照范围准确
    测试项：TC-02 错误定位到原值且只给一条可执行命令
    验收条件：AC-02 每项错误能定位到具体内容并给出唯一下一命令
    测试方式：自动化测试
    测试层级：模块测试
    产品入口：`workflow gate update_code_design`（最终代码设计程序检查）
    测试入口：`tests/test_current_workflow_contracts.py::test_gate_error_points_to_exact_source_and_one_next_command`
    代码入口：`src/workflow_loop/artifact_validation.py::validate_final_architecture`
    准备数据：在隔离架构文档同一映射表放入两个不存在的代码位置，并准备正确文件路径作为对照
    执行动作：执行最终代码设计门禁并读取格式化诊断
    关键断言：两个错误同次准确定位；末尾恰好一条完整命令，并写明执行者、自动动作、成功条件和后续阶段
    预期证据：pytest JUnit XML 报告、两项错误原值、唯一下一命令和报告哈希
    """
    _run(
        "test_architecture_validation",
        "test_final_architecture_reports_all_mapping_and_sync_errors_once",
        _case(tmp_path, "architecture_errors"),
    )
    _run(
        "test_diagnostics",
        "test_report_renders_errors_not_checked_and_one_complete_next_command",
    )


def test_repeated_failure_is_stable_and_regression_has_one_command(
    tmp_path,
    monkeypatch,
):
    """Workflow-Test
    主题：门禁失败一次展示完整可处理原因且快照范围准确
    测试项：TC-03 重复诊断稳定且最终回归只有真实入口
    验收条件：AC-03 重复失败不逐次暴露错误，最终回归给出唯一执行方式
    测试方式：自动化测试
    测试层级：集成测试
    产品入口：重复执行失败门禁；最终回归执行 `workflow gate regression_test`
    测试入口：`tests/test_current_workflow_contracts.py::test_repeated_failure_is_stable_and_regression_has_one_command`
    代码入口：`src/workflow_loop/stages/stages.py::RegressionTestStage`
    准备数据：保存一份多错误状态并保持文件字节不变；另登记可观察调用次数的统一全量测试入口
    执行动作：连续两次生成同一失败报告，随后检查最终回归讨论指令并执行最终回归门禁入口
    关键断言：两次错误清单、顺序和哈希相同；失败报告要求先修改；最终回归唯一命令为 `workflow gate regression_test` 且入口只执行一次
    预期证据：pytest JUnit XML 报告、两次报告哈希、统一入口调用次数和最终回归记录
    """
    _run("test_diagnostics", "test_report_lists_all_independent_errors_in_stable_order")
    _run(
        "test_diagnostics",
        "test_regression_instruction_exposes_only_the_real_execution_command",
    )
    with monkeypatch.context() as scoped:
        _run(
            "test_test_runner",
            "test_regression_confirmation_can_reuse_same_machine_record",
            _case(tmp_path, "single_regression_run"),
            scoped,
        )


def test_snapshots_include_only_registered_core_paths_and_exact_diffs(tmp_path):
    """Workflow-Test
    主题：门禁失败一次展示完整可处理原因且快照范围准确
    测试项：TC-04 窄快照忽略生成物并列出四类文件变化
    验收条件：AC-04 只对登记范围做快照并准确列出文件差异
    测试方式：自动化测试
    测试层级：模块测试
    产品入口：实施或测试失效检查使用已登记核心路径
    测试入口：`tests/test_current_workflow_contracts.py::test_snapshots_include_only_registered_core_paths_and_exact_diffs`
    代码入口：`src/workflow_loop/snapshots.py::collect_snapshot`
    准备数据：在隔离项目登记四个核心文件，同时创建 `.next`、`node_modules`、构建目录、缓存和运行文件；随后分别新增、修改、删除和把登记文件改成目录
    执行动作：采集前后快照并比较差异，再只改变范围外目录并重复比较；另传入非法登记目录和缺失基线
    关键断言：只读取登记普通文件；四个登记变化分别标为 added、modified、deleted、type_changed；范围外变化零差异；非法目录拒绝；缺基线标未检查
    预期证据：pytest JUnit XML 报告、登记路径清单、逐文件前后事实和四类差异集合
    """
    _run(
        "test_snapshots",
        "test_snapshot_reads_only_registered_files",
        _case(tmp_path, "registered_only"),
    )
    _run(
        "test_snapshots",
        "test_snapshot_reports_added_modified_deleted_and_type_changed",
        _case(tmp_path, "four_changes"),
    )
    _run(
        "test_snapshots",
        "test_snapshot_without_baseline_marks_every_path_not_checked",
        _case(tmp_path, "missing_baseline"),
    )
    for index, relative_path in enumerate(
        (
            ".next/server/app.js",
            "node_modules/package/index.js",
            "build/generated.py",
            ".pytest_cache/v/cache.json",
        )
    ):
        _run(
            "test_snapshots",
            "test_registered_paths_reject_generated_dependency_and_cache_directories",
            _case(tmp_path, f"invalid_directory_{index}"),
            relative_path,
        )
    _run(
        "test_verification",
        "test_active_snapshot_ignores_unregistered_build_and_dependency_files",
        _case(tmp_path, "active_snapshot"),
    )
