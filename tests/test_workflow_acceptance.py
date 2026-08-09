from functools import lru_cache
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from types import ModuleType

from workflow_loop.project import is_project_design_initialized
from workflow_loop.state import load_state


@lru_cache(maxsize=None)
def _load_test_module(stem: str) -> ModuleType:
    path = Path(__file__).with_name(f"{stem}.py")
    spec = spec_from_file_location(f"_workflow_acceptance_{stem}", path)
    assert spec is not None and spec.loader is not None
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _case(root: Path, name: str) -> Path:
    path = root / name
    path.mkdir()
    return path


def _prepare_project_design_init_gate(root: Path, command_tests, initialization_tests):
    """建立真实 CLI 门禁样例，并在讨论门后写入初始化产物。"""
    command_tests._install_project(root)
    code, out, err = command_tests._run(["start", "--intent", "product_change"], root)
    assert code == 0, f"start failed: {out} {err}"
    state = load_state(str(root))
    assert state is not None
    assert state.current_stage == "project_design_init"
    assert is_project_design_initialized(str(root)) is False

    code, out, err = command_tests._run(["discuss"], root)
    assert code == 0, f"discuss failed: {out} {err}"
    code, out, err = command_tests._run(
        ["gate", "project_design_init", "--discuss-done"],
        root,
    )
    assert code == 0, f"discussion gate failed: {out} {err}"
    initialization_tests._write_initialization_documents(root, state.workflow_id)
    return state.workflow_id


def test_formal_link_gate_rechecks_navigation_and_lists_all_failures(
    tmp_path,
    monkeypatch,
):
    """Workflow-Test
    主题：正式文档链接可导航且历史坏链接受控修复
    测试项：TC-01 两道门禁重新检查全部正式链接
    验收条件：AC-01 已生成正式文档的本地链接真实可导航
    测试方式：自动化测试
    测试层级：命令测试
    产品入口：`workflow gate acceptance_plan` 和 `workflow gate acceptance_plan --confirmed`
    测试入口：`tests/test_workflow_acceptance.py::test_formal_link_gate_rechecks_navigation_and_lists_all_failures`
    代码入口：`src/workflow_loop/cli.py::validate_stage_output`
    准备数据：建立两个隔离安装项目。有效项目处于 `acceptance_plan`（验收计划）环节，受管文档含 1 个指向现有文件且命中唯一显式定位编号的链接；无效项目含缺失文件、缺失定位、重复定位、项目越界和符号链接共 5 个独立问题，并保存执行前阶段和门禁状态。
    执行动作：有效项目依次执行第二道门禁和用户确认后的第三道门禁；无效项目执行第二道门禁。读取每次命令输出及执行后的工作流状态。
    关键断言：有效项目第二道和第三道门禁都报告链接问题数为 0，第三道门禁后进入下一环节；无效项目一次列出 5 个问题，当前环节仍为 `acceptance_plan`，`code_validated=false` 且 `user_confirmed=false`。
    预期证据：`pytest-junitxml`（pytest 的 JUnit XML 结构化报告）必须精确匹配本测试入口，`executed_count=1`、`skipped_count=0`、`failed_count=0`、`error_count=0`、进程退出码为 0；同时保存两次有效门禁输出、一次无效门禁完整问题清单和执行前后状态字段。
    """
    link_tests = _load_test_module("test_markdown_links")
    command_tests = _load_test_module("test_commands")

    link_tests.test_scan_uses_markdown_structure_and_accepts_unique_explicit_id(
        _case(tmp_path, "valid_link")
    )
    link_tests.test_scan_aggregates_path_file_and_explicit_id_problems(
        _case(tmp_path, "five_invalid_links")
    )
    command_tests.test_three_gates_advance_in_the_required_order(
        _case(tmp_path, "valid_gate_sequence")
    )
    with monkeypatch.context() as isolated_patch:
        command_tests.test_gate_reports_link_and_stage_errors_without_running_regression(
            _case(tmp_path, "invalid_gate"),
            isolated_patch,
        )


def test_future_artifacts_are_pending_plain_paths_until_created(tmp_path):
    """Workflow-Test
    主题：正式文档链接可导航且历史坏链接受控修复
    测试项：TC-02 未来产物只接受待生成普通路径
    验收条件：AC-02 尚未生成的未来产物不形成假链接
    测试方式：自动化测试
    测试层级：模块测试
    产品入口：`workflow gate acceptance_plan` 提交含未来产物位置的验收索引
    测试入口：`tests/test_workflow_acceptance.py::test_future_artifacts_are_pending_plain_paths_until_created`
    代码入口：`src/workflow_loop/topic_relations.py::read_topic_index`
    准备数据：在隔离项目建立真实存在的验收计划，并分别准备 1 个正确索引和 5 个错误索引：可点击的缺失目标、错误固定路径、遗漏“待生成”、把必有验收计划写成待生成、目标已存在仍写待生成。正确索引把尚不存在的验收结果写为反引号普通路径加“待生成”，执行前确认结果文件不存在。
    执行动作：对 6 个样例分别提交索引检查；检查解析结果、完整错误输出和项目文件清单，确认程序没有创建未来结果文档。
    关键断言：正确样例返回固定路径 `./安装_验收结果.md` 且结果文件仍不存在；5 个错误样例全部失败并分别指出原单元格、预期路径或已存在状态；全部样例执行后新增占位结果文件数为 0。
    预期证据：`pytest-junitxml` 必须精确匹配本测试入口，实际执行 1 项且跳过、失败、错误均为 0；保存 6 个样例的解析或错误事实、执行前后文件清单，以及“未来结果文件不存在”的路径检查。
    """
    relation_tests = _load_test_module("test_topic_relations")

    relation_tests.test_topic_index_accepts_exact_pending_future_path(
        _case(tmp_path, "valid_pending_path")
    )
    invalid_values = (
        ("`./错误_验收结果.md`（待生成）", "应指向 ./安装_验收结果.md"),
        ("`./安装_验收结果.md`", "必须是单一真实 Markdown 链接"),
        ("稍后再写", "必须是单一真实 Markdown 链接"),
    )
    for index, (cell, message) in enumerate(invalid_values, start=1):
        relation_tests.test_topic_index_rejects_invalid_future_representation(
            _case(tmp_path, f"invalid_future_{index}"),
            cell,
            message,
        )
    relation_tests.test_topic_index_rejects_pending_required_acceptance_plan(
        _case(tmp_path, "pending_required_plan")
    )
    relation_tests.test_topic_index_rejects_pending_marker_after_target_exists(
        _case(tmp_path, "pending_existing_target")
    )


def test_update_and_confirmed_link_repair_keep_exact_scope(tmp_path):
    """Workflow-Test
    主题：正式文档链接可导航且历史坏链接受控修复
    测试项：TC-03 更新与已确认链接修复范围严格分离
    验收条件：AC-03 历史坏链接只按确认过的准确范围修复
    测试方式：自动化测试 + 人工验收
    测试层级：命令测试
    产品入口：`workflow update` 完成项目更新后单独执行 `workflow repair-links`，用户确认预览，再使用该预览的 64 位哈希执行 `workflow repair-links --apply`
    测试入口：`tests/test_workflow_acceptance.py::test_update_and_confirmed_link_repair_keep_exact_scope`
    代码入口：`src/workflow_loop/cli.py::cmd_repair_links`
    准备数据：建立可离线更新的已安装项目，准备 2 份正式文档：1 个能唯一对应旧标题的标准坏链接和 1 个目标不唯一的手写链接；保存正式文档、项目配置和工作流状态的 SHA-256 内容哈希。另保留一份在预览后修改来源文档的漂移样例。
    执行动作：自动化部分依次执行受控项目更新、只读修复预览、取消后内容核对、使用已经漂移的旧预览哈希尝试应用、重新预览并应用新哈希；人工部分逐项核对预览中的来源、原链接、目标位置、可自动修复项和不可自动修复项后记录确认决定。
    关键断言：项目更新、预览和取消均使正式文档修改数为 0；预览列出 1 个确定修复和 1 个不确定项；漂移后的旧哈希应用失败且整批写入数为 0；新哈希只修改确认清单中的 1 个目标，不确定项原文、项目配置、当前环节和门禁状态不变；人工记录逐项确认预览范围。
    预期证据：`pytest-junitxml` 必须精确匹配本测试入口，实际执行 1 项且跳过、失败、错误均为 0；保存更新前后、取消前后、漂移失败前后的 SHA-256，对应命令完整输出、最终修改清单，以及用户签认的逐项预览记录。
    """
    maintenance_tests = _load_test_module("test_maintenance")
    command_tests = _load_test_module("test_commands")

    maintenance_tests.test_update_overwrites_static_management_and_preserves_runtime_data(
        _case(tmp_path, "update_scope")
    )
    command_tests.test_repair_links_preview_is_zero_write_and_lists_every_unresolved_issue(
        _case(tmp_path, "repair_preview")
    )
    command_tests.test_repair_links_wrong_hash_fails_without_writing(
        _case(tmp_path, "stale_preview")
    )
    command_tests.test_repair_links_matching_hash_applies_only_confirmed_anchor(
        _case(tmp_path, "confirmed_apply")
    )


def test_link_repair_completes_atomically_or_restores_every_original(tmp_path):
    """Workflow-Test
    主题：正式文档链接可导航且历史坏链接受控修复
    测试项：TC-04 整批修复失败或中断后恢复全部原文
    验收条件：AC-04 历史链接修复要么全部成功要么恢复原文
    测试方式：自动化测试
    测试层级：模块测试
    产品入口：使用已确认预览哈希执行 `workflow repair-links --apply`
    测试入口：`tests/test_workflow_acceptance.py::test_link_repair_completes_atomically_or_restores_every_original`
    代码入口：`src/workflow_loop/markdown_links.py::apply_legacy_anchor_repairs`
    准备数据：在三个隔离目录各准备 2 个可确定修复目标并保存 2 个原文 SHA-256：成功样例正常写入，失败样例在替换第 2 个文件时注入写入错误，中断样例在写入第 1 个文件后触发进程中断并保留可恢复事务资料。
    执行动作：三个样例都从当前预览生成确认哈希并执行整批应用；失败样例捕获错误后核对两份文件；中断样例调用恢复入口两次，核对恢复的幂等结果；最后重新扫描链接并检查事务目录。
    关键断言：成功样例修改 2 个目标、扫描问题数为 0 且事务目录不存在；失败样例两份文件哈希都等于执行前值并明确报告“已恢复全部原文”；中断样例首次恢复后两份文件哈希等于执行前值，第二次恢复修改文件数为 0，事务目录不存在。
    预期证据：`pytest-junitxml` 必须精确匹配本测试入口，实际执行 1 项且跳过、失败、错误均为 0；保存三个子场景的预览哈希、两文件执行前后 SHA-256、修复或恢复结果、扫描计数和事务目录存在性。
    """
    link_tests = _load_test_module("test_markdown_links")

    link_tests.test_repair_preview_is_read_only_and_apply_adds_unique_anchor(
        _case(tmp_path, "successful_apply")
    )
    link_tests.test_repair_restores_every_file_when_a_replace_fails(
        _case(tmp_path, "failed_apply")
    )
    link_tests.test_repair_recovers_before_propagating_keyboard_interrupt(
        _case(tmp_path, "interrupted_apply")
    )
    link_tests.test_recover_pending_transaction_restores_original_idempotently(
        _case(tmp_path, "idempotent_recovery")
    )


def test_existing_project_entries_have_one_confirmed_scope_decision(tmp_path):
    """Workflow-Test
    主题：首次接入已有项目时功能完整且产品文档面向用户
    测试项：TC-01 全部真实入口只有一个确认处理结果
    验收条件：AC-01 每个真实入口都有功能归属或明确排除理由
    测试方式：自动化测试 + 人工验收
    测试层级：命令测试
    产品入口：`workflow gate project_design_init` 提交入口清单，用户核对并确认初始化范围
    测试入口：`tests/test_workflow_acceptance.py::test_existing_project_entries_have_one_confirmed_scope_decision`
    代码入口：`src/workflow_loop/stages/stages.py::ProjectDesignInitStage.code_validate`
    准备数据：建立项目设计未初始化的隔离安装项目，真实入口证据包括上传页面、搜索框和已不可达的旧版导出命令共 3 项；正确证据把前两项唯一归入“上传文档”和“搜索文档”，后一项写具体排除理由，3 项均标为已确认。错误副本同时包含未归属入口、无理由排除、重复功能名称和未确认入口，并保存 `project_design_initialized=false`（项目设计尚未初始化）。
    执行动作：自动化部分提交正确和错误两份初始化证据检查，读取一次返回的全部问题及项目状态；人工部分按代码、测试、配置和可安全运行入口的调查证据逐项核对 3 项清单，并记录对整份入口归属、排除理由和功能名称的确认。
    关键断言：正确清单恰有 3 个入口、2 个唯一功能归属、1 个带具体理由的排除项、0 个未决入口和 2 个不重复功能名称；错误副本一次报告 4 类问题且初始化状态仍为 `false`；人工记录确认调查到的入口与清单逐项相等。
    预期证据：`pytest-junitxml` 必须精确匹配本测试入口，`executed_count=1`、`skipped_count=0`、`failed_count=0`、`error_count=0`、进程退出码为 0；同时保存 3 项入口的调查证据、正确计数、4 类错误完整输出、状态值和用户整表确认记录。
    """
    initialization_tests = _load_test_module("test_project_design_init")
    command_tests = _load_test_module("test_commands")

    valid_root = _case(tmp_path, "confirmed_scope")
    _prepare_project_design_init_gate(valid_root, command_tests, initialization_tests)
    code, out, err = command_tests._run(["gate", "project_design_init"], valid_root)
    assert code == 0, err
    assert "project_design_init 代码校验通过" in out
    assert is_project_design_initialized(str(valid_root)) is False

    invalid_root = _case(tmp_path, "invalid_scope")
    _prepare_project_design_init_gate(invalid_root, command_tests, initialization_tests)
    evidence = invalid_root / "spec" / "项目设计初始化证据.md"
    content = evidence.read_text(encoding="utf-8")
    content = content.replace(
        "| 搜索框 | 用户操作入口 | `src/search.py` | 搜索文档 | 暂无 | 已确认 |",
        "| 搜索框 | 用户操作入口 | `src/search.py` | 暂无 | 暂无 | 未确认 |",
    )
    content = content.replace(
        "| 搜索文档 | 输入关键词并得到匹配结果 | 搜索框 | 已确认 |",
        "| 上传文档 | 输入关键词并得到匹配结果 | 搜索框 | 未确认 |",
    )
    content = content.replace(
        "| `spec/功能_搜索文档.md` | 搜索文档 | 已生成 |\n",
        "",
    )
    evidence.write_text(content, encoding="utf-8")

    _, out, _ = command_tests._run(["gate", "project_design_init"], invalid_root)
    assert "project_design_init 代码校验失败" in out
    assert "搜索框" in out
    assert "重复" in out
    assert "产出文件清单" in out
    assert is_project_design_initialized(str(invalid_root)) is False
    invalid_state = load_state(str(invalid_root))
    assert invalid_state is not None
    assert invalid_state.current_stage == "project_design_init"
    assert invalid_state.stages["project_design_init"].gate.code_validated is False


def test_initialization_outputs_match_one_feature_baseline_before_completion(tmp_path):
    """Workflow-Test
    主题：首次接入已有项目时功能完整且产品文档面向用户
    测试项：TC-02 四类产物匹配唯一功能基准后才完成初始化
    验收条件：AC-02 四类初始化产物使用完全相同的功能集合
    测试方式：自动化测试
    测试层级：命令测试
    产品入口：`workflow gate project_design_init` 和用户确认后的 `workflow gate project_design_init --confirmed`
    测试入口：`tests/test_workflow_acceptance.py::test_initialization_outputs_match_one_feature_baseline_before_completion`
    代码入口：`src/workflow_loop/stages/stages.py::ProjectDesignInitStage.code_validate`
    准备数据：建立含“上传文档”“搜索文档”两个已确认功能的隔离项目；产品总说明、2 份功能文档、代码架构 2 个完整功能段、初始化证据功能清单均使用这两个名称，产出清单含产品总说明、2 份功能文档、代码架构和初始化证据共 5 个路径。另准备分别缺功能、多功能、名称不一致、重复架构段、漏产出和缺代码过程字段的错误副本，所有副本初始状态为 `project_design_initialized=false`。
    执行动作：正确样例先执行程序门禁，核对用户确认前状态仍为 `false`，再执行确认门禁；各错误副本分别执行程序门禁并读取全部集合差异、产出差异和代码过程错误。
    关键断言：正确样例四个功能集合均精确等于 `['上传文档', '搜索文档']`，每个名称出现 1 次，产出路径数为 5，每个架构段 6 类过程信息齐全；第二道门禁后状态仍为 `false`，确认门禁后才变为 `true`。全部错误副本门禁失败并保持 `false`，输出指出具体来源、缺少项、多出项、重复项或缺失字段。
    预期证据：`pytest-junitxml` 必须精确匹配本测试入口，实际执行 1 项且跳过、失败、错误均为 0；保存四类集合、5 项路径、各错误副本的完整差异、两道门禁输出及确认前后初始化状态。
    """
    initialization_tests = _load_test_module("test_project_design_init")
    command_tests = _load_test_module("test_commands")

    root = _case(tmp_path, "matching_feature_sets")
    _prepare_project_design_init_gate(root, command_tests, initialization_tests)

    code, out, err = command_tests._run(["gate", "project_design_init"], root)
    assert code == 0, err
    assert "project_design_init 代码校验通过" in out
    state = load_state(str(root))
    assert state is not None
    assert state.stages["project_design_init"].gate.code_validated is True
    assert is_project_design_initialized(str(root)) is False

    code, out, err = command_tests._run(
        ["gate", "project_design_init", "--confirmed"],
        root,
    )
    assert code == 0, f"confirmation gate failed: {out} {err}"
    assert "project_design_init 完成" in out
    assert is_project_design_initialized(str(root)) is True
    state = load_state(str(root))
    assert state is not None
    assert state.stages["project_design_init"].gate.user_confirmed is True
    assert state.current_stage == "spec"

    initialization_tests.test_initialization_reports_all_independent_scope_and_output_errors(
        _case(tmp_path, "mismatched_feature_sets")
    )
