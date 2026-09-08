"""最终同步从记录表与当前机器事实更新正式架构，并保留正文。"""

from copy import deepcopy

from workflow_loop import artifact_validation, records
from workflow_loop import state as state_mod
from workflow_repair_support import filled_table, prepared_project, run_project_evidence
from test_architecture_validation import _write_complete_final_architecture
from test_workflow_guidance import _markdown_snapshot, _save, _write


WORKFLOW_ID = "design-sync-current"
ARCHITECTURE = "spec/代码架构设计.md"


def _final_project(root, version="3"):
    _write_complete_final_architecture(root, "old-run")
    state = prepared_project(root, ["上传文件"], workflow_id=WORKFLOW_ID, version=version)
    state = run_project_evidence(root, state)
    path, table = filled_table(root, state, "design_sync")
    conclusions = {
        "产品设计核对": "一致", "功能文档核对": "一致", "代码实现核对": "一致",
        "功能到代码映射": "完整", "未处理差异": "暂无", "本次同步类型": "架构未变化",
    }
    table["核对项"] = [{"核对项": label, "核对结论": value, "设计影响": "无需修改", "代码影响": "无需修改"}
                     for label, value in conclusions.items()]
    table["同步说明"] = ["核对当前上传入口、真实函数及本测试实际执行的主题测试和最终回归。"]
    _save(path, table)
    records.create_or_complete_table(str(root), WORKFLOW_ID, "architecture_changes", "")
    return state, path


def _changes(root, rows):
    relative = records.table_relative_path(str(root), WORKFLOW_ID, "architecture_changes", "")
    path = root / relative
    table = records.load_table(str(path))
    table["正文变更"] = rows
    _save(path, table)


def _change(**values):
    return {
        "章节": "1. 文档说明", "原文": "已按真实代码更新。",
        "新文": "已核对当前上传入口与真实执行结果。",
        "依据": "src/app.py::upload（上传函数）的真实返回值和本轮机器记录",
        **values,
    }


def test_stage_generates_current_formal_architecture(tmp_path):
    """Workflow-Test
    主题：最终同步按表更新架构并保护正文
    测试项：TC-01 最终同步直接更新正式架构和证据
    验收条件：AC-01 同步正式架构与当前证据
    测试方式：自动化测试
    测试层级：集成测试
    产品入口：调用最终同步阶段按表生成入口
    测试入口：tests/test_design_sync_tables.py::test_stage_generates_current_formal_architecture
    代码入口：src/workflow_loop/records.py::sync_stage_tables
    准备数据：旧轮次正式架构、完整同步表、本轮真实通过的主题测试与最终回归及自动验收记录。
    执行动作：按表同步正式架构并通过原有最终架构校验，核对全部当前机器编号。
    关键断言：程序直接更新正式架构；表、生成文档和最终检查使用一致来源，不混入旧轮次或失效记录。
    预期证据：当前执行的结构化测试报告中入口精确匹配，执行数大于零，跳过失败错误均为零且退出码为零。
    """
    for version in ("2", "3"):
        root = tmp_path / version
        state, table_path = _final_project(root, version)
        before = (root / ARCHITECTURE).read_text(encoding="utf-8")
        problems, paths = records.sync_stage_tables(str(root), state)
        assert not problems, problems
        assert ARCHITECTURE in paths
        content = (root / ARCHITECTURE).read_text(encoding="utf-8")
        assert content.split("## 9.")[0] == before.split("## 9.")[0]
        assert f"工作流编号：{WORKFLOW_ID}" in content
        assert "old-run" not in content and "REG-test-1" not in content
        assert state.regression_test.record_id in content
        for tasks in state.stages["qa"].test_tasks.values():
            for task in tasks.values():
                assert task.current_record.record_id in content
        assert "核对项 | 核对结论 | 设计影响 | 代码影响" in content
        assert records.load_table(str(table_path))["表版本"] == version
        ok, detail = artifact_validation.validate_final_code_design_document(str(root), WORKFLOW_ID)
        assert ok, detail
        snapshot = _markdown_snapshot(root)
        assert not records.sync_stage_tables(str(root), state)[0]
        assert _markdown_snapshot(root) == snapshot


def test_body_changes_preserve_structure_and_repeat(tmp_path):
    """Workflow-Test
    主题：最终同步按表更新架构并保护正文
    测试项：TC-02 精确修改正文且重复生成不变
    验收条件：AC-02 正文按指定事实更新且稳定
    测试方式：自动化测试
    测试层级：集成测试
    产品入口：调用最终同步阶段按表生成入口
    测试入口：tests/test_design_sync_tables.py::test_body_changes_preserve_structure_and_repeat
    代码入口：src/workflow_loop/records.py::sync_stage_tables
    准备数据：正式架构含章节、表格、代码块及锚点，正文变更表只指定一处需要更新的事实。
    执行动作：执行指定事实替换并再次生成，同时核对空变更表保留正文。
    关键断言：每行唯一定位，首次替换准确且重复生成不重复追加或替换；空正文表保留既有正文。
    预期证据：当前执行的结构化测试报告中入口精确匹配，执行数大于零，跳过失败错误均为零且退出码为零。
    """
    root = tmp_path / "project"
    state, _ = _final_project(root)
    path = root / ARCHITECTURE
    initial = path.read_text(encoding="utf-8").replace(
        "已按真实代码更新。", '<a id="kept-anchor"></a>\n\n已按真实代码更新。\n\n```text\n必须保留的代码块\n```'
    )
    _write(path, initial)
    _changes(root, [_change()])
    problems, _ = records.sync_stage_tables(str(root), state)
    assert not problems, problems
    generated = path.read_text(encoding="utf-8")
    assert generated.split("## 9.")[0] == initial.split("## 9.")[0].replace(
        "已按真实代码更新。", "已核对当前上传入口与真实执行结果。"
    )
    assert '<a id="kept-anchor"></a>' in generated
    assert "必须保留的代码块" in generated
    before = _markdown_snapshot(root)
    for _ in range(2):
        assert not records.sync_stage_tables(str(root), state)[0]
        assert _markdown_snapshot(root) == before

    root = tmp_path / "empty-body-changes"
    state, _ = _final_project(root)
    initial = (root / ARCHITECTURE).read_text(encoding="utf-8")
    assert not records.sync_stage_tables(str(root), state)[0]
    assert (root / ARCHITECTURE).read_text(encoding="utf-8").split("## 9.")[0] == initial.split("## 9.")[0]


def test_invalid_evidence_and_conflicts_never_overwrite(tmp_path):
    """Workflow-Test
    主题：最终同步按表更新架构并保护正文
    测试项：TC-03 缺证据和正文冲突都拒绝覆盖
    验收条件：AC-03 缺证据或正文冲突不覆盖
    测试方式：自动化测试
    测试层级：集成测试
    产品入口：调用最终同步阶段按表生成入口
    测试入口：tests/test_design_sync_tables.py::test_invalid_evidence_and_conflicts_never_overwrite
    代码入口：src/workflow_loop/records.py::sync_stage_tables
    准备数据：合法最终同步项目的副本，分别缺少核对结论或当前证据，或存在手改、重复原文和结构冲突。
    执行动作：逐个尝试生成并比较原文，再把可恢复的手改精确写回正文变更表后重新生成。
    关键断言：任何缺项和定位冲突均明确拒绝；手工修改不被覆盖，修正事实后才允许生成。
    预期证据：当前执行的结构化测试报告中入口精确匹配，执行数大于零，跳过失败错误均为零且退出码为零。
    """
    root = tmp_path / "project"
    state, table_path = _final_project(root)
    table = records.load_table(str(table_path))
    original = (root / ARCHITECTURE).read_text(encoding="utf-8")
    cases = ("missing-check", "unresolved", "code-change", "duplicate-check", "unconfirmed",
             "acceptance", "regression", "mapping", "missing-original", "ambiguous",
             "unknown-section", "overlap", "structure", "sync-fields")
    for case in cases:
        candidate = deepcopy(state)
        changed = deepcopy(table)
        content = original
        rows = []
        if case == "missing-check":
            changed["核对项"] = changed["核对项"][1:]
        elif case == "unresolved":
            changed["核对项"][4]["核对结论"] = "仍有未修复差异"
        elif case == "code-change":
            changed["核对项"][2]["代码影响"] = "需要修改"
        elif case == "duplicate-check":
            changed["核对项"].append(deepcopy(changed["核对项"][0]))
        elif case == "unconfirmed":
            candidate.stages["overall_acceptance"].gate.user_confirmed = False
        elif case == "acceptance":
            candidate.stages["topic_acceptance"].acceptance_records.clear()
        elif case == "regression":
            candidate.regression_test.record_id = "REG-obsolete"
        elif case == "mapping":
            content = content.replace("src/app.py::upload", "src/app.py::missing_symbol")
        elif case == "missing-original":
            rows = [_change(原文="正文中没有这个旧事实", 新文="已按真实代码更新。")]
        elif case == "ambiguous":
            content = content.replace("已按真实代码更新。", "已按真实代码更新。已按真实代码更新。")
            rows = [_change()]
        elif case == "unknown-section":
            rows = [_change(章节="不存在的章节")]
        elif case == "overlap":
            rows = [_change(), _change(原文="真实代码", 新文="当前代码")]
        elif case == "structure":
            rows = [_change(新文="## 不应新增的标题")]
        else:
            rows = [_change(章节="9. 最终同步结论", 原文="REG-test-1")]
        _save(table_path, changed)
        _changes(root, rows)
        _write(root / ARCHITECTURE, content)
        state_mod.save_state(str(root), candidate)
        before = _markdown_snapshot(root)
        problems, paths = records.sync_stage_tables(str(root), candidate)
        assert problems, case
        assert paths == [], case
        assert _markdown_snapshot(root) == before, case

    state_mod.save_state(str(root), state)
    _save(table_path, table)
    _changes(root, [_change()])
    _write(root / ARCHITECTURE, original)
    assert not records.sync_stage_tables(str(root), state)[0]
    path = root / ARCHITECTURE
    modified = path.read_text(encoding="utf-8").replace(
        "已核对当前上传入口与真实执行结果。", "用户手工补充的真实说明，必须保留。"
    )
    _write(path, modified)
    before = _markdown_snapshot(root)
    problems, paths = records.sync_stage_tables(str(root), state)
    assert any("直接修改" in message for _, message in problems), problems
    assert paths == []
    assert _markdown_snapshot(root) == before
    _changes(root, [_change(新文="用户手工补充的真实说明，必须保留。")])
    assert not records.sync_stage_tables(str(root), state)[0]
    assert path.read_text(encoding="utf-8") == modified
