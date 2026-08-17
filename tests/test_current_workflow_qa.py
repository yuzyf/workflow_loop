"""当前精简研发流程的正式 QA 测试入口。"""

from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
import sys


_LOADED_TEST_MODULES = {}


def _test_module(stem: str):
    """按文件名加载既有测试模块，复用已经覆盖真实产品行为的场景。"""
    if stem in _LOADED_TEST_MODULES:
        return _LOADED_TEST_MODULES[stem]
    path = Path(__file__).with_name(f"{stem}.py")
    module_name = f"_current_workflow_qa_{stem}"
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


def test_flow_ac01_new_runs_use_condensed_stage_path(tmp_path):
    """Workflow-Test
    主题：完整研发流程按最少用户环节推进并兼容旧轮次
    测试项：TC-01 三类新轮次只生成精简研发主干
    验收条件：AC-01 新轮次只生成精简后的完整研发路径
    测试方式：自动化测试
    测试层级：集成测试
    产品入口：`workflow start --intent from_scratch`、`workflow start --intent product_change`、`workflow start --intent bugfix`
    测试入口：`tests/test_current_workflow_qa.py::test_flow_ac01_new_runs_use_condensed_stage_path`
    代码入口：`src/workflow_loop/path_composer.py::build_stage_path`
    准备数据：建立五个隔离安装项目，覆盖从零创建、修改产品未初始化或已初始化、修复缺陷未初始化或已初始化
    执行动作：分别启动轮次并读取程序保存的阶段路径
    关键断言：统一尾段精确为 `acceptance_plan -> impl -> qa -> topic_acceptance -> regression_test -> overall_acceptance -> update_code_design`，适用前置正确，五个旧阶段均不存在
    预期证据：pytest JUnit XML 报告精确命中本入口，并保存五组实际阶段数组和零跳过、失败、错误事实
    """
    _run(
        "test_commands",
        "test_three_intents_produce_complete_project_specific_paths",
        _case(tmp_path, "command_paths"),
    )
    for index, function_name in enumerate(
        (
            "test_from_scratch_path",
            "test_product_change_with_uninitialized",
            "test_product_change_with_initialized",
            "test_bugfix_with_uninitialized",
            "test_bugfix_with_initialized",
        )
    ):
        _run(
            "test_path_composer",
            function_name,
            _case(tmp_path, f"path_{index}"),
        )


def test_flow_ac02_from_scratch_design_lives_in_impl_plan(tmp_path):
    """Workflow-Test
    主题：完整研发流程按最少用户环节推进并兼容旧轮次
    测试项：TC-02 从零最低实现设计只进入代码计划
    验收条件：AC-02 从零创建的最低限度实现设计只进入代码计划
    测试方式：自动化测试
    测试层级：集成测试
    产品入口：从零轮次进入 `impl` 后执行 `workflow gate impl --discuss-done`
    测试入口：`tests/test_current_workflow_qa.py::test_flow_ac02_from_scratch_design_lives_in_impl_plan`
    代码入口：`src/workflow_loop/stages/stages.py::ImplStage.discussion_validate`
    准备数据：建立已确认产品设计和验收计划、正式代码未变化的从零轮次；实施记录填写项目入口、模块职责、共享状态、依赖和测试入口；保存代码架构文档原字节
    执行动作：确认代码计划并检查阶段路径、实施记录和长期代码架构文档
    关键断言：五类决定全部位于代码计划；没有独立代码设计阶段；正式代码和长期代码架构文档未提前变化
    预期证据：pytest JUnit XML、五类字段提取结果、阶段数组、正式代码和架构文档前后哈希
    """
    _run(
        "test_path_composer",
        "test_from_scratch_path",
        _case(tmp_path, "from_scratch_path"),
    )
    _run(
        "test_stages",
        "test_impl_discussion_requires_every_topic_plan_and_no_unresolved_question",
        _case(tmp_path, "impl_discussion"),
    )


def test_flow_ac03_legacy_runs_migrate_once_and_preserve_current_evidence(
    tmp_path,
    monkeypatch,
):
    """Workflow-Test
    主题：完整研发流程按最少用户环节推进并兼容旧轮次
    测试项：TC-03 旧轮次逐项迁移且重复继续零变化
    验收条件：AC-03 旧进行中轮次逐项迁移且重复继续结果不变
    测试方式：自动化测试
    测试层级：集成测试
    产品入口：`workflow status` 只读预览后执行 `workflow discuss` 触发首次可写迁移
    测试入口：`tests/test_current_workflow_qa.py::test_flow_ac03_legacy_runs_migrate_once_and_preserve_current_evidence`
    代码入口：`src/workflow_loop/cli.py::ensure_stage_path_current`
    准备数据：分别建立旧测试已失效和旧测试仍有当前依据的样本，并保存状态、日志、追踪表和结果文件原字节
    执行动作：先预览，再迁移两次；另分别注入状态保存和日志追加失败
    关键断言：预览零写；首次只清失效事实并保留有效事实；第二次零变化；失败时恢复全部原字节
    预期证据：pytest JUnit XML、迁移前后哈希、保留与失效事实清单、唯一迁移日志和故障恢复比较
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


def test_flow_ac04_design_initialized_only_after_confirmed_real_architecture(tmp_path):
    """Workflow-Test
    主题：完整研发流程按最少用户环节推进并兼容旧轮次
    测试项：TC-04 初始化标记只在真实架构确认后设置
    验收条件：AC-04 项目设计初始化标记只在真实架构形成后设置
    测试方式：自动化测试
    测试层级：集成测试
    产品入口：`workflow gate project_design_init --confirmed`；从零轮次执行 `workflow gate update_code_design --confirmed`
    测试入口：`tests/test_current_workflow_qa.py::test_flow_ac04_design_initialized_only_after_confirmed_real_architecture`
    代码入口：`src/workflow_loop/cli.py::cmd_gate`
    准备数据：准备未初始化已有项目、未完成最终同步的从零项目和已有有效标记的旧项目
    执行动作：分别执行程序校验门和用户确认门，并迁移已有标记样本
    关键断言：已有项目只在初始化确认后置真；从零项目只在最终代码设计同步确认后置真；旧有效标记迁移后仍为真
    预期证据：pytest JUnit XML、各门禁前后标记值、阶段值和旧标记迁移前后值
    """
    _run(
        "test_workflow_acceptance",
        "test_initialization_outputs_match_one_feature_baseline_before_completion",
        _case(tmp_path, "existing_project"),
    )
    _run(
        "test_project",
        "test_project_json_cross_run_persistence",
        _case(tmp_path, "persistent_marker"),
    )


def test_flow_ac01_acceptance_result_uses_current_record_id_field(
    tmp_path,
    monkeypatch,
):
    """Workflow-Test
    主题：完整研发流程按最少用户环节推进并兼容旧轮次
    测试项：TC-06 主题验收结果只接受当前验收记录编号字段
    验收条件：AC-01 新轮次只生成精简后的完整研发路径
    测试方式：自动化测试
    测试层级：集成测试
    产品入口：`workflow gate topic_acceptance`
    测试入口：`tests/test_current_workflow_qa.py::test_flow_ac01_acceptance_result_uses_current_record_id_field`
    代码入口：`src/workflow_loop/stages/stages.py::TopicAcceptanceStage.code_validate`
    准备数据：建立已完成当前机器验收记录的主题验收状态，并分别准备四份验收结果：`验收记录编号` 与状态一致、删除该字段、写入错误编号、只写旧字段 `程序记录`
    执行动作：逐份调用主题验收阶段的正式代码校验；仅隔离与本字段无关的测试结果和追踪表前置检查，不替换验收结果字段校验
    关键断言：当前字段与状态一致时通过；缺字段时明确报告缺少 `验收记录编号`；编号错误时报告 `验收记录编号不一致`；只写旧字段时仍按缺少当前字段失败
    预期证据：pytest JUnit XML 报告精确命中本入口，并保存四种输入对应的完整校验结果和零跳过、失败、错误事实
    """
    from workflow_loop.stages import stages as stages_mod

    fixture = _test_module("test_acceptance_records")
    root = _case(tmp_path, "acceptance_record_id")
    fixture._write(
        root / "acceptance" / "上传文件_验收计划.md",
        """# 上传文件验收计划

## 4. 验收条件

<a id="ac-01"></a>
### AC-01：上传完成

- 通过标准：文件上传成功。
""",
    )
    state = fixture._setup(root)
    created = fixture.records_mod.ensure_automated_records(str(root), state)
    assert len(created) == 1
    record = created[0]
    fixture.save_state(str(root), state)

    result_path = root / "acceptance" / "上传文件_验收结果.md"
    valid_content = f"""# 【主题验收结果】上传文件

- 工作流编号：test
- 验收主题：上传文件
- 验收结果：通过
- 验收完成时间：{record.confirmed_at}

## 1. 验收依据

- [主题验收计划](./上传文件_验收计划.md)
- [主题测试结果](../qa/上传文件_测试结果.md)
- [实施记录](../impl/上传文件_实施记录.md)
- [需求交付追踪表](../需求交付追踪表.md)

## 2. 验收条件结果

### AC-01：上传完成

- 验收方式：自动化测试
- 验收条件：[AC-01：上传完成](./上传文件_验收计划.md#ac-01)
- 自动化依据：[主题测试结果](../qa/上传文件_测试结果.md)，TC-01
- 机器测试记录编号：RUN-1

#### 人工验收步骤

不适用

- 用户实际回答：不适用
- 人工确认：不适用
- 确认时间：不适用
- 实际结果：{record.actual_result}
- 判定：通过
- 验收证据：{record.evidence}
- 验收记录编号：{record.record_id}

## 3. 上下游文档

- [主题验收计划](./上传文件_验收计划.md)
- [主题测试结果](../qa/上传文件_测试结果.md)
- [实施记录](../impl/上传文件_实施记录.md)
- [需求交付追踪表](../需求交付追踪表.md)
"""

    monkeypatch.setattr(
        stages_mod,
        "validate_test_execution_results",
        lambda *_args: (True, "测试结果前置已隔离"),
    )
    monkeypatch.setattr(
        stages_mod,
        "validate_downstream_traceability",
        lambda *_args: (True, "追踪表前置已隔离"),
    )
    stage = stages_mod.TopicAcceptanceStage()

    fixture._write(result_path, valid_content)
    ok, detail = stage.code_validate(str(root))
    assert ok is True, detail

    fixture._write(
        result_path,
        valid_content.replace(
            f"- 验收记录编号：{record.record_id}\n",
            "",
        ),
    )
    ok, detail = stage.code_validate(str(root))
    assert ok is False
    assert "缺少具体“验收记录编号”" in detail

    fixture._write(
        result_path,
        valid_content.replace(
            f"- 验收记录编号：{record.record_id}",
            "- 验收记录编号：错误编号",
        ),
    )
    ok, detail = stage.code_validate(str(root))
    assert ok is False
    assert "验收记录编号不一致" in detail

    fixture._write(
        result_path,
        valid_content.replace(
            "- 验收记录编号：",
            "- 程序记录：",
        ),
    )
    ok, detail = stage.code_validate(str(root))
    assert ok is False
    assert "缺少具体“验收记录编号”" in detail


def test_impl_ac01_all_plans_confirm_before_product_code_changes(tmp_path):
    """Workflow-Test
    主题：代码实施按计划、实施、结果连续完成并支持复用既有代码
    测试项：TC-01 全部详细代码计划确认前不改正式代码
    验收条件：AC-01 全部代码计划确认前不得修改正式代码
    测试方式：自动化测试
    测试层级：集成测试
    产品入口：`workflow gate impl --discuss-done`
    测试入口：`tests/test_current_workflow_qa.py::test_impl_ac01_all_plans_confirm_before_product_code_changes`
    代码入口：`src/workflow_loop/stages/stages.py::ImplStage.discussion_validate`
    准备数据：建立两个验收主题及对应实施记录；完整样本覆盖文件、位置、现状、目标逻辑、状态或输出、顺序、依赖、共享归属、风险、完成标准、开发检查和复用项，再逐项删除字段；保存正式代码哈希
    执行动作：对完整和缺陷样本执行代码计划确认门
    关键断言：只有全部主题和字段完整、无未决问题且正式代码未变化时通过
    预期证据：pytest JUnit XML、字段缺失矩阵、一次完整诊断和正式代码前后哈希
    """
    _run(
        "test_stages",
        "test_impl_discussion_requires_every_topic_plan_and_no_unresolved_question",
        _case(tmp_path, "discussion"),
    )


def test_impl_ac02_prepare_baseline_then_implement_without_extra_gate(tmp_path):
    """Workflow-Test
    主题：代码实施按计划、实施、结果连续完成并支持复用既有代码
    测试项：TC-02 保存首次基线后连续实施，改法变化先停下
    验收条件：AC-02 回退基线完成后连续实施，计划改变时先停下
    测试方式：自动化测试
    测试层级：集成测试
    产品入口：`workflow gate impl --prepare-code`；计划变化后重新执行 `workflow gate impl --discuss-done`
    测试入口：`tests/test_current_workflow_qa.py::test_impl_ac02_prepare_baseline_then_implement_without_extra_gate`
    代码入口：`src/workflow_loop/rollback.py::prepare_impl`
    准备数据：计划包含一个既有文件和一个新增文件；另准备实施中调整计划、已修改路径和未保存原内容的新路径
    执行动作：准备基线、修改代码、重复准备；改变计划后尝试继续，再重新确认计划
    关键断言：旧文件保存真实原字节，新文件记录原本不存在；首次副本永不覆盖；准备后直接进入代码实施；计划变化未经重新确认不能继续
    预期证据：pytest JUnit XML、清单内容、原副本哈希、内部步骤变化和拒绝诊断
    """
    _run(
        "test_rollback",
        "test_impl_backup_records_existing_and_originally_missing_files",
        _case(tmp_path, "backup"),
    )
    _run(
        "test_rollback",
        "test_adjusted_plan_rejects_path_without_an_original_snapshot",
        _case(tmp_path, "changed_plan"),
    )


def test_impl_ac03_existing_code_reuse_is_bound_and_tests_still_reset(
    tmp_path,
    monkeypatch,
    capsys,
):
    """Workflow-Test
    主题：代码实施按计划、实施、结果连续完成并支持复用既有代码
    测试项：TC-03 既有代码可零修改复用但正式测试仍重做
    验收条件：AC-03 符合计划的现有代码可以直接复用
    测试方式：自动化测试
    测试层级：集成测试
    产品入口：`workflow gate impl --accept-existing-code`
    测试入口：`tests/test_current_workflow_qa.py::test_impl_ac03_existing_code_reuse_is_bound_and_tests_still_reset`
    代码入口：`src/workflow_loop/rollback.py::validate_existing_implementation_paths`
    准备数据：准备零修改且计划、记录、文件一致的样本，基线后有变化的样本，路径或记录无效样本，并预置旧 QA 成功哈希和机器结果
    执行动作：执行既有代码接受命令，随后改变代码；确认实施并进入 QA
    关键断言：合法复用只记录绑定当前代码的哈希，不产生文件差异；代码变化使复用失效；进入 QA 后旧正式测试结果不可沿用
    预期证据：pytest JUnit XML、复用前后文件哈希、复用决定哈希、QA 清零字段和拒绝诊断
    """
    for index, function_name in enumerate(
        (
            "test_accept_existing_code_refuses_post_baseline_changes",
            "test_accept_existing_code_rejects_invalid_scope_without_state_change",
            "test_accept_existing_code_preserves_original_baseline",
        )
    ):
        with monkeypatch.context() as scoped:
            _run(
                "test_commands",
                function_name,
                _case(tmp_path, f"reuse_{index}"),
                scoped,
                capsys,
            )
    _run(
        "test_rollback",
        "test_existing_implementation_checks_plan_record_and_real_files",
        _case(tmp_path, "existing_paths"),
    )


def test_impl_ac04_plan_diff_result_and_baseline_must_match(tmp_path, monkeypatch):
    """Workflow-Test
    主题：代码实施按计划、实施、结果连续完成并支持复用既有代码
    测试项：TC-04 代码结果与计划、真实代码和回退基线一致
    验收条件：AC-04 代码结果与计划、真实代码和回退基线完全一致
    测试方式：自动化测试
    测试层级：集成测试
    产品入口：`workflow gate impl`
    测试入口：`tests/test_current_workflow_qa.py::test_impl_ac04_plan_diff_result_and_baseline_must_match`
    代码入口：`src/workflow_loop/rollback.py::validate_implementation_changes`
    准备数据：建立完全一致样本，以及计划未改、计划外修改、修改未记录、记录无差异、假位置、占位内容、错误 AC 和损坏副本等缺陷样本
    执行动作：执行实施代码结果门禁并比较诊断和状态
    关键断言：三组路径完全相等，记录位置覆盖最终文件真实差异，回退副本完整，未完成内容状态为“无”时才通过
    预期证据：pytest JUnit XML、三组排序路径、完整错误清单和门禁前后状态哈希
    """
    _run(
        "test_rollback",
        "test_planned_actual_and_recorded_implementation_paths_must_match",
        _case(tmp_path, "sets"),
    )
    _run(
        "test_rollback",
        "test_implementation_record_reports_every_invalid_row_fact_at_once",
        _case(tmp_path, "records"),
    )
    for index, function_name in enumerate(
        (
            "test_impl_gate_prefers_real_changes_over_existing_code_marker",
            "test_impl_gate_reports_real_change_mismatch_even_with_existing_code_marker",
        )
    ):
        with monkeypatch.context() as scoped:
            _run(
                "test_stages",
                function_name,
                _case(tmp_path, f"gate_{index}"),
                scoped,
            )


def test_qa_ac01_single_stage_has_only_scope_and_result_confirmations(tmp_path):
    """Workflow-Test
    主题：测试验证一次确认后连续完成并保留真实测试证据
    测试项：TC-01 QA 只在开始和结束确认
    验收条件：AC-01 测试计划、测试代码、执行和结果在一个测试验证环节连续完成
    测试方式：自动化测试
    测试层级：集成测试
    产品入口：依次执行 `workflow gate qa --discuss-done`、`workflow test prepare`、`workflow test run`、`workflow gate qa`、`workflow gate qa --confirmed`
    测试入口：`tests/test_current_workflow_qa.py::test_qa_ac01_single_stage_has_only_scope_and_result_confirmations`
    代码入口：`src/workflow_loop/cli.py::cmd_gate`
    准备数据：建立处于 `qa` 的隔离工作流，含完整测试计划、测试代码和可计数测试进程
    执行动作：按正常 QA 顺序执行全部命令，中间不执行旧测试阶段门禁，最后执行确认门
    关键断言：始终停留单一 `qa` 环节；只在开始范围和结束结果确认；计划与结果分文件；第三道门不重跑测试并进入主题验收
    预期证据：pytest JUnit XML、每步状态快照、命令输出、门禁流水数量、测试进程调用次数和文件清单
    """
    _run(
        "test_path_composer",
        "test_from_scratch_path",
        _case(tmp_path, "single_qa_stage"),
    )
    _run(
        "test_test_execution",
        "test_run_success_writes_current_record_but_not_formal_result",
        _case(tmp_path, "run_once"),
    )
    _run(
        "test_test_execution",
        "test_rerun_keeps_current_success_without_executing_it_twice",
        _case(tmp_path, "no_repeat"),
    )


def test_qa_ac02_reused_test_code_still_gets_current_machine_record(tmp_path):
    """Workflow-Test
    主题：测试验证一次确认后连续完成并保留真实测试证据
    测试项：TC-02 复用既有测试仍生成本轮机器记录
    验收条件：AC-02 符合当前计划的已有测试代码可以复用但必须重新正式执行
    测试方式：自动化测试
    测试层级：集成测试
    产品入口：确认 QA 范围后，不修改符合计划的测试文件，执行 `workflow test prepare` 和 `workflow test run`
    测试入口：`tests/test_current_workflow_qa.py::test_qa_ac02_reused_test_code_still_gets_current_machine_record`
    代码入口：`src/workflow_loop/test_execution.py::run_prepared_tasks`
    准备数据：准备已登记且完整覆盖当前 TC 的既有测试、确认范围哈希和测试文件哈希，并确保没有本轮机器记录
    执行动作：零修改复用测试并正式执行；随后修改测试文件，再检查复用决定和结果有效性
    关键断言：复用时测试文件字节不变，但产生绑定当前代码的新机器记录；测试代码变化后旧复用决定和旧结果失效
    预期证据：pytest JUnit XML、测试文件执行前后哈希、新机器记录编号和时间、精确入口及失效诊断
    """
    _run(
        "test_test_execution",
        "test_run_success_writes_current_record_but_not_formal_result",
        _case(tmp_path, "current_record"),
    )
    _run(
        "test_test_execution",
        "test_failed_rerun_clears_previous_current_success_and_result",
        _case(tmp_path, "changed_test"),
    )
    _run(
        "test_verification",
        "test_qa_test_code_change_returns_to_test_code_and_keeps_scope",
        _case(tmp_path, "invalidation"),
    )


def test_qa_ac03_results_require_current_exact_machine_record(tmp_path, monkeypatch):
    """Workflow-Test
    主题：测试验证一次确认后连续完成并保留真实测试证据
    测试项：TC-03 机器记录精确证明正式测试
    验收条件：AC-03 自动化测试结果只能由当前真实机器记录生成
    测试方式：自动化测试
    测试层级：集成测试
    产品入口：`workflow test prepare`、`workflow test run`、`workflow gate qa`
    测试入口：`tests/test_current_workflow_qa.py::test_qa_ac03_results_require_current_exact_machine_record`
    代码入口：`src/workflow_loop/test_execution.py::run_prepared_tasks`
    准备数据：登记精确 pytest 入口，准备成功、零执行、跳过、失败、错误、旧报告、错目标和已有旧成功记录等样本
    执行动作：对各样本真实执行并解析本次报告，再根据记录生成结果并执行 QA 门禁
    关键断言：只有精确目标、执行数大于零、三类异常数为零、退出码为零且输入未变时形成当前成功结果
    预期证据：pytest JUnit XML 原件及哈希、机器记录、精确目标、四项计数、退出码、产品和测试代码哈希
    """
    _run(
        "test_current_workflow_contracts",
        "test_structured_report_requires_exact_non_skipped_current_targets",
        _case(tmp_path, "structured_report"),
        monkeypatch,
    )


def test_qa_ac04_manual_and_mixed_topics_keep_human_boundary(tmp_path):
    """Workflow-Test
    主题：测试验证一次确认后连续完成并保留真实测试证据
    测试项：TC-04 人工与混合测试不伪造结论
    验收条件：AC-04 纯人工主题不伪造测试结果且混合主题保留人工待验收状态
    测试方式：自动化测试
    测试层级：集成测试
    产品入口：混合主题执行 `workflow test run` 后运行 `workflow gate qa`；纯人工主题直接运行 `workflow gate qa`
    测试入口：`tests/test_current_workflow_qa.py::test_qa_ac04_manual_and_mixed_topics_keep_human_boundary`
    代码入口：`src/workflow_loop/test_mapping.py::automated_topics`
    准备数据：准备一个纯人工主题和一个混合主题；人工计划包含对象、操作、观察及用户问题；仅为混合主题登记自动化任务
    执行动作：执行混合主题自动化部分，整理 QA 文件并运行结束门禁
    关键断言：纯人工主题无命令和结果文件，索引写“无自动化测试项”；混合结果只写机器事实并标记“待主题验收”
    预期证据：pytest JUnit XML、文件清单、QA 索引单元格、任务登记清单和混合结果的机器记录及人工交接字段
    """
    _run(
        "test_traceability",
        "test_traceability_marks_manual_acceptance_per_criterion_in_mixed_topic",
        _case(tmp_path, "mixed_topic"),
    )


def test_gate_ac01_third_gate_reuses_second_gate_credential(tmp_path):
    """Workflow-Test
    主题：门禁凭据复用且只使真实受影响内容失效
    测试项：TC-01 第三道门只比较第二道门凭据
    验收条件：AC-01 第二道门完整校验一次且第三道门只复用有效凭据
    测试方式：自动化测试
    测试层级：集成测试
    产品入口：对同一环节执行 `workflow gate impl`，再执行 `workflow gate impl --confirmed`
    测试入口：`tests/test_current_workflow_qa.py::test_gate_ac01_third_gate_reuses_second_gate_credential`
    代码入口：`src/workflow_loop/verification.py::compare_validation_credential`
    准备数据：准备可通过第二道门的环节，并为完整校验器、测试执行器和穿刺执行器设置调用计数，责任输入保持不变
    执行动作：执行第二道门和第三道门并读取状态、流水和调用计数
    关键断言：完整校验恰好一次并产生一份凭据；第三道门只比较凭据，零测试和零穿刺执行并推进
    预期证据：pytest JUnit XML、调用计数、凭据哈希、两道门输出、流水记录和推进前后状态
    """
    _run(
        "test_commands",
        "test_three_gates_advance_in_the_required_order",
        _case(tmp_path, "three_gates"),
    )


def test_gate_ac02_credential_binds_only_stage_responsibility(tmp_path):
    """Workflow-Test
    主题：门禁凭据复用且只使真实受影响内容失效
    测试项：TC-02 凭据只绑定责任输入
    验收条件：AC-02 校验凭据只绑定当前环节真正负责的输入
    测试方式：自动化测试
    测试层级：集成测试
    产品入口：执行 `workflow gate acceptance_plan` 生成凭据，再执行 `workflow gate acceptance_plan --confirmed` 或凭据复核
    测试入口：`tests/test_current_workflow_qa.py::test_gate_ac02_credential_binds_only_stage_responsibility`
    代码入口：`src/workflow_loop/verification.py::stage_responsibility_paths`
    准备数据：为验收计划环节准备责任文档、正常下游结果链接、未登记文件、缓存和构建输出，并生成当前凭据
    执行动作：分别修改下游字段、范围外文件、责任文件、责任状态和规则版本后复核凭据
    关键断言：下游正常更新及范围外变化不失效；责任文件、责任状态或规则版本变化时拒绝并指出具体项；状态不保存文档全文
    预期证据：pytest JUnit XML、凭据字段清单和哈希、各变化场景的比较结果及具体文件、状态、版本差异
    """
    from workflow_loop import project as project_mod
    from workflow_loop import state as state_mod
    from workflow_loop import verification as verification_mod

    project_mod.create_project(str(tmp_path))
    topic = "凭据边界"
    (tmp_path / "acceptance").mkdir(parents=True, exist_ok=True)
    (tmp_path / "acceptance" / "索引.md").write_text("# 验收索引\n", encoding="utf-8")
    (tmp_path / "acceptance" / f"{topic}_验收计划.md").write_text(
        "# 验收计划\n",
        encoding="utf-8",
    )
    (tmp_path / "需求交付追踪表.md").write_text("# 需求交付追踪表\n", encoding="utf-8")
    state = state_mod.WorkflowState(
        workflow_id="2026-08-11-1200-product_change",
        intent="product_change",
        current_stage="acceptance_plan",
        topics=[topic],
        stage_path=["acceptance_plan"],
        stages={
            "acceptance_plan": state_mod.StageState(
                status="in_progress",
                discussion_material_hash="materials",
            )
        },
    )
    credential = verification_mod.create_validation_credential(
        str(tmp_path),
        state,
        "acceptance_plan",
        "验收计划校验通过",
    )
    state.stages["acceptance_plan"].validation_credential = credential
    (tmp_path / "build").mkdir()
    (tmp_path / "build" / "cache.txt").write_text("ignored\n", encoding="utf-8")
    valid, detail = verification_mod.compare_validation_credential(
        str(tmp_path), state, "acceptance_plan"
    )
    assert valid is True, detail
    (tmp_path / "acceptance" / f"{topic}_验收计划.md").write_text(
        "# 已变化的验收计划\n",
        encoding="utf-8",
    )
    valid, detail = verification_mod.compare_validation_credential(
        str(tmp_path), state, "acceptance_plan"
    )
    assert valid is False
    assert "责任文件修改" in detail


def test_gate_ac03_invalidation_clears_only_directly_affected_results(tmp_path):
    """Workflow-Test
    主题：门禁凭据复用且只使真实受影响内容失效
    测试项：TC-03 变化只失效直接受影响结果
    验收条件：AC-03 失效范围只覆盖有具体证据的直接受影响内容
    测试方式：自动化测试
    测试层级：集成测试
    产品入口：修改一个主题的责任输入后执行 `workflow gate qa`
    测试入口：`tests/test_current_workflow_qa.py::test_gate_ac03_invalidation_clears_only_directly_affected_results`
    代码入口：`src/workflow_loop/verification.py::inspect_invalidation`
    准备数据：构造两个独立主题及共享索引，保存计划、代码、任务、结果、验收和最终全量回归事实
    执行动作：分别改变单主题验收计划、代码、测试计划、测试代码、机器记录、结果整理和公共入口，再执行调查与应用
    关键断言：单主题变化只清所属主题；共享入口才影响全部主题；结果整理错误保留机器记录；真实代码或测试变化使最终全量回归失效
    预期证据：pytest JUnit XML、逐文件差异、受影响主题、应用前后状态、保留和删除清单及最终全量回归状态
    """
    _run(
        "test_current_workflow_contracts",
        "test_upstream_invalidation_preserves_only_current_evidence",
        _case(tmp_path, "invalidation"),
    )


def test_gate_ac04_failure_is_complete_stable_and_has_one_next_action(
    tmp_path,
    monkeypatch,
):
    """Workflow-Test
    主题：门禁凭据复用且只使真实受影响内容失效
    测试项：TC-04 失败一次列全且动作唯一
    验收条件：AC-04 门禁失败一次列全问题并给出唯一下一动作
    测试方式：自动化测试
    测试层级：集成测试
    产品入口：对不变的多错误输入连续两次执行 `workflow gate impl`
    测试入口：`tests/test_current_workflow_qa.py::test_gate_ac04_failure_is_complete_stable_and_has_one_next_action`
    代码入口：`src/workflow_loop/diagnostics.py::format_validation_report`
    准备数据：构造两个独立文件错误、一个状态错误和一个被前置错误阻断的检查，输入字节保持不变
    执行动作：原样执行同一失败门禁两次，不使用管道、截断或重定向
    关键断言：每次一次列出全部独立错误；阻断项标为未检查；两次内容顺序和哈希相同；仅一个完整下一动作和命令
    预期证据：pytest JUnit XML、两次完整输出、报告哈希、问题计数和顺序、命令计数及执行前后状态哈希
    """
    _run(
        "test_current_workflow_contracts",
        "test_gate_reports_all_independent_errors_and_unchecked_dependencies",
        _case(tmp_path, "complete_report"),
    )
    _run(
        "test_current_workflow_contracts",
        "test_repeated_failure_is_stable_and_regression_has_one_command",
        _case(tmp_path, "stable_report"),
        monkeypatch,
    )


def test_spike_ac01_registered_assets_survive_confirmation_done_and_abort(
    tmp_path,
    monkeypatch,
    capsys,
):
    """Workflow-Test
    主题：可复用穿刺资产保留并与验收条件全局追踪
    测试项：TC-01 已登记穿刺资产在确认、收工和作废后保留
    验收条件：AC-01 能产生结论的穿刺代码和最小依赖在结束后保留
    测试方式：自动化测试
    测试层级：集成测试
    产品入口：分别执行 `workflow gate spike --confirmed`、`workflow done` 和 `workflow abort`
    测试入口：`tests/test_current_workflow_qa.py::test_spike_ac01_registered_assets_survive_confirmation_done_and_abort`
    代码入口：`src/workflow_loop/stages/base.py::clean_spike_tmp`
    准备数据：三个隔离项目均准备已登记代码、运行脚本、最小样本和依赖说明，并加入未登记半成品、日志、缓存、纯结果和敏感文件样本
    执行动作：分别完成穿刺确认、正式收工和整轮作废，检查清理结果；另注入作废恢复失败
    关键断言：三条结束路径都保留已登记可重跑资产；只清未登记或不应长期保存内容；恢复失败不提前清理
    预期证据：pytest JUnit XML、三场景目录清单和哈希、冻结清理计划、删除清单、作废状态及失败现场
    """
    _run(
        "test_spike_assets",
        "test_spike_cleanup_removes_only_current_unregistered_entries",
        _case(tmp_path, "cleanup"),
    )
    with monkeypatch.context() as scoped:
        _run(
            "test_spike_assets",
            "test_spike_third_gate_registers_asset_then_cleans_unregistered_content",
            _case(tmp_path, "confirmation"),
            scoped,
        )
    with monkeypatch.context() as scoped:
        _run(
            "test_spike_assets",
            "test_abort_preflight_freezes_spike_plan_and_restore_failure_keeps_contents",
            _case(tmp_path, "abort_failure"),
            scoped,
            capsys,
        )


def test_spike_ac02_assets_bind_only_supported_acceptance_conditions(tmp_path):
    """Workflow-Test
    主题：可复用穿刺资产保留并与验收条件全局追踪
    测试项：TC-02 穿刺资产只绑定实际支撑的 AC
    验收条件：AC-02 可复用穿刺资产只与实际支撑的验收条件关联
    测试方式：自动化测试
    测试层级：集成测试
    产品入口：提交 `需求交付追踪表.md` 后执行 `workflow gate acceptance_plan`
    测试入口：`tests/test_current_workflow_qa.py::test_spike_ac02_assets_bind_only_supported_acceptance_conditions`
    代码入口：`src/workflow_loop/traceability.py::collect_spike_asset_acceptance_links`
    准备数据：准备一项支撑两个 AC 的资产、一个无关 AC、一个未登记路径和整轮跳过穿刺场景
    执行动作：分别提交正确多 AC 关联、漏关联、错误关联、未知资产和跳过却伪造资产的追踪表
    关键断言：正确资产只出现在两个受支持 AC 行并回填两个关联；无关 AC 不关联；跳过场景写固定无资产事实
    预期证据：pytest JUnit XML、逐行追踪内容、返回映射、回填状态及错误场景的主题、AC、路径定位
    """
    _run(
        "test_spike_assets",
        "test_historical_asset_success_from_an_older_run_still_blocks_current_traceability",
        _case(tmp_path, "current_rerun_required"),
    )
    _run(
        "test_spike_assets",
        "test_traceability_allows_historical_reuse_after_skipping_new_spike",
        _case(tmp_path, "skip_and_reuse"),
    )


def test_spike_ac03_current_cleanup_preserves_historical_assets(
    tmp_path,
    monkeypatch,
):
    """Workflow-Test
    主题：可复用穿刺资产保留并与验收条件全局追踪
    测试项：TC-03 当前轮清理不改历史穿刺资产
    验收条件：AC-03 不同工作流的穿刺资产相互隔离且不被覆盖
    测试方式：自动化测试
    测试层级：集成测试
    产品入口：新轮次保存同名穿刺项后执行 `workflow done` 或 `workflow abort`
    测试入口：`tests/test_current_workflow_qa.py::test_spike_ac03_current_cleanup_preserves_historical_assets`
    代码入口：`src/workflow_loop/stages/base.py::plan_spike_tmp_cleanup`
    准备数据：准备历史工作流已登记资产、当前工作流同名已登记资产和当前轮未登记半成品，并记录全部文件哈希
    执行动作：生成并执行当前轮清理计划
    关键断言：清理只删除当前工作流未登记内容；当前已登记和历史资产路径、内容均不变
    预期证据：pytest JUnit XML、清理计划、执行结果、各工作流目录树及执行前后文件哈希
    """
    _run(
        "test_spike_assets",
        "test_spike_cleanup_removes_only_current_unregistered_entries",
        _case(tmp_path, "isolated_cleanup"),
    )
    with monkeypatch.context() as scoped:
        _run(
            "test_spike_assets",
            "test_same_minute_workflow_id_and_historical_assets_are_preserved",
            _case(tmp_path, "same_minute"),
            scoped,
        )


def test_spike_ac04_historical_asset_requires_current_rerun(
    tmp_path,
    monkeypatch,
    capsys,
):
    """Workflow-Test
    主题：可复用穿刺资产保留并与验收条件全局追踪
    测试项：TC-04 历史穿刺只有当前重跑成功才能复用
    验收条件：AC-04 后续复用历史穿刺资产必须在当前环境重新运行
    测试方式：自动化测试
    测试层级：集成测试
    产品入口：先执行 `workflow spike rerun --asset .workflow_loop/spike_tmp/2026-08-10-1000-product_change/interface_probe` 预览，再带当前计划编号、`--confirmed` 和具体结论执行
    测试入口：`tests/test_current_workflow_qa.py::test_spike_ac04_historical_asset_requires_current_rerun`
    代码入口：`src/workflow_loop/spike_reuse.py::historical_asset_success_problems`
    准备数据：准备只有上一轮成功记录的历史资产，并准备本轮成功、缺依赖、非零退出和运行中改写资产目录四种脚本
    执行动作：先验证旧成功不能进入追踪；分别预览并确认执行四种本轮重跑；再次检查追踪资格
    关键断言：只有本轮真实成功且资产未变化时可用；失败或改写目录时标为待修订，历史资产仍存在且旧结论不能沿用
    预期证据：pytest JUnit XML、预览零执行证据、当前进程记录、退出码、输出哈希、资产前后哈希、状态和追踪门禁结果
    """
    _run(
        "test_spike_assets",
        "test_historical_spike_asset_rerun_records_current_success_only_after_execution",
        _case(tmp_path, "success"),
    )
    _run(
        "test_spike_assets",
        "test_historical_spike_asset_failed_rerun_marks_revision_and_preserves_asset",
        _case(tmp_path, "failed"),
    )
    _run(
        "test_spike_assets",
        "test_spike_rerun_marks_asset_blocked_when_command_modifies_asset_directory",
        _case(tmp_path, "modified_asset"),
    )
    with monkeypatch.context() as scoped:
        _run(
            "test_spike_assets",
            "test_spike_rerun_preview_does_not_execute_or_write_state",
            _case(tmp_path, "preview"),
            scoped,
            capsys,
        )
