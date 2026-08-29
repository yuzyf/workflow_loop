"""工作记录表功能与出错通道的行为测试。"""
from __future__ import annotations

import json
from pathlib import Path

from workflow_loop import records as records_mod
from workflow_loop import state as state_mod

from test_commands import _install_project, _run


def test_table_create_then_recreate_keeps_filled_content(tmp_path: Path) -> None:
    root = tmp_path / "proj"
    root.mkdir()
    relative = records_mod.create_or_complete_table(str(root), "wf-1", "impl_record", "主题A")
    table_path = root / relative
    assert table_path.is_file()
    table = json.loads(table_path.read_text(encoding="utf-8"))
    assert table["工作流编号"] == "wf-1"
    assert table["验收主题"] == "主题A"
    assert table["代码修改计划"] == []

    table["代码修改计划"] = [
        {"文件": "src/a.py", "计划修改内容": "修复提示", "对应验收条件": "AC-01"}
    ]
    table_path.write_text(json.dumps(table, ensure_ascii=False, indent=2), encoding="utf-8")

    records_mod.create_or_complete_table(str(root), "wf-1", "impl_record", "主题A")
    reloaded = json.loads(table_path.read_text(encoding="utf-8"))
    assert reloaded["代码修改计划"][0]["文件"] == "src/a.py"


def test_validate_reports_category_and_all_problems(tmp_path: Path) -> None:
    table = {
        "表版本": "1",
        "工作流编号": "wf-1",
        "验收主题": "主题A",
        "代码修改计划": [
            {"文件": "src/a.py", "错误列": "x"},
            {"文件": "src/a.py", "计划修改内容": "a", "对应验收条件": "AC-01"},
            {"文件": "src/a.py", "计划修改内容": "b", "对应验收条件": "AC-02"},
        ],
        "实际代码修改": [],
        "实施动作记录": [],
        "实施中问题与处理": [],
        "未完成状态": "状态：无",
    }
    problems = records_mod.validate_table("impl_record", table)
    categories = {category for category, _ in problems}
    assert records_mod.FORMAT_CATEGORY in categories
    assert records_mod.CONTENT_CATEGORY in categories
    joined = "\n".join(message for _category, message in problems)
    assert "栏目与定义不符" in joined
    assert "重复登记" in joined
    # 同一输入重复校验，问题清单和顺序一致
    again = records_mod.validate_table("impl_record", table)
    assert again == problems


def test_generate_impl_doc_and_detect_tamper(tmp_path: Path) -> None:
    root = tmp_path / "proj"
    root.mkdir()
    (root / "impl").mkdir()
    relative = records_mod.create_or_complete_table(str(root), "wf-1", "impl_record", "主题A")
    table_path = root / relative
    table = json.loads(table_path.read_text(encoding="utf-8"))
    table["代码修改计划"] = [
        {"文件": "src/a.py", "计划修改内容": "修复", "对应验收条件": "AC-01"}
    ]
    table["实际代码修改"] = [
        {
            "文件": "src/a.py",
            "代码位置（最终文件）": "L10-L20",
            "实际修改的代码逻辑": "调整状态判断",
            "数据、状态或输出的实际变化": "完成输出不再提示执行完成后的旧命令",
            "修改理由": "修复死路提示",
            "对应验收条件": "AC-01",
            "测试证据": "tests/test_records.py",
        }
    ]
    table["实施动作记录"] = ["修改 src/a.py 并本地核对"]
    table["实施中问题与处理"] = []
    table["未完成状态"] = "状态：无"
    table_path.write_text(json.dumps(table, ensure_ascii=False, indent=2), encoding="utf-8")

    problems, documents = records_mod.sync_stage_tables(
        str(root),
        _state_with_stage("wf-1", "impl"),
    )
    assert problems == [], problems
    doc = root / "impl" / "主题A_实施记录.md"
    assert doc.is_file()
    assert "#### 3.4.1 实际代码修改" in doc.read_text(encoding="utf-8")

    # 手改文档 → 检出且不覆盖
    with doc.open("a", encoding="utf-8") as stream:
        stream.write("手工追加\n")
    problems, _documents = records_mod.sync_stage_tables(
        str(root),
        _state_with_stage("wf-1", "impl"),
    )
    assert any("文档被直接修改" in message for _category, message in problems)
    assert "手工追加" in doc.read_text(encoding="utf-8")


def test_pristine_table_does_not_activate_table_path(tmp_path: Path) -> None:
    root = tmp_path / "proj"
    root.mkdir()
    records_mod.create_or_complete_table(str(root), "wf-1", "impl_record", "主题A")
    assert not records_mod.has_any_table(str(root), "wf-1", "impl", ["主题A"])
    problems, documents = records_mod.sync_stage_tables(
        str(root),
        _state_with_stage("wf-1", "impl"),
    )
    assert problems == [] and documents == []


def test_bad_encoding_table_reports_structured_error(tmp_path: Path) -> None:
    root = tmp_path / "proj"
    root.mkdir()
    table_path = root / ".workflow_loop/records/wf-1/impl_record_主题A.json"
    table_path.parent.mkdir(parents=True)
    table_path.write_bytes("（编码声明）".encode("gbk"))
    try:
        records_mod.load_table(str(table_path))
        raised = False
    except records_mod.RecordsError as exc:
        raised = True
        assert "UTF-8" in str(exc)
    assert raised


def _state_with_stage(workflow_id: str, stage: str) -> state_mod.WorkflowState:
    state = state_mod.WorkflowState(workflow_id=workflow_id, intent="product_change", topics=["主题A"])
    state.current_stage = stage
    state.stages[stage] = state_mod.StageState()
    return state


def test_status_after_completed_does_not_point_to_done(tmp_path: Path) -> None:
    root = tmp_path / "proj"
    root.mkdir()
    _install_project(root)
    _run(["start", "--intent", "light_task"], root)
    _run(["light", "--discuss-done", "--task", "t", "--verification", "v"], root)
    _run(["light", "--confirmed", "--result", "done"], root)
    _run(["done"], root)
    code, out, _err = _run(["status"], root)
    assert code == 0
    assert "调 `workflow done`" not in out
    assert "已经完成" in out


def test_gate_with_non_utf8_document_reports_structured_failure(tmp_path: Path) -> None:
    root = tmp_path / "proj"
    root.mkdir()
    _install_project(root)
    _run(["start", "--intent", "from_scratch"], root)
    _run(["discuss"], root)
    _run(["gate", "spec", "--discuss-done"], root)
    (root / "spec").mkdir(parents=True, exist_ok=True)
    overview = root / "spec" / "产品总说明.md"
    overview.write_text(
        "# 产品总说明\n\n## 7. 产品功能\n\n旧清单\n\n## 8. 相关文档\n\n暂无\n",
        encoding="utf-8",
    )
    (root / "spec" / "功能_一.md").write_bytes("# 【功能】功能一\n".encode("gbk"))
    # R11：填 product_features 表（让 sync 走到 GBK 文件检查）
    _records_dir = root / ".workflow_loop" / "records"
    _wf_dirs = sorted(d for d in _records_dir.iterdir() if d.is_dir())
    _pf_path = _wf_dirs[0] / "product_features_product_features.json"
    _pf = json.loads(_pf_path.read_text(encoding="utf-8"))
    _pf["功能"] = [
        {"功能名称": "功能一", "一句话说明": "功能一说明", "对应场景": "场景", "功能文档路径": "./功能_一.md"}
    ]
    _pf_path.write_text(json.dumps(_pf, ensure_ascii=False, indent=2), encoding="utf-8")
    code, out, _err = _run(["gate", "spec"], root)
    assert "Traceback" not in out
    assert "阶段校验无法完成" in out
    assert "下一步命令" in out


def test_corrupted_state_file_reports_clean_error(tmp_path: Path) -> None:
    root = tmp_path / "proj"
    root.mkdir()
    _install_project(root)
    (root / ".workflow_loop" / "state.json").write_text("{broken", encoding="utf-8")
    code, out, _err = _run(["status"], root)
    assert "Traceback" not in out


def test_regenerate_indexes_from_topic_relations(tmp_path: Path) -> None:
    root = tmp_path / "proj"
    root.mkdir()
    relative = records_mod.create_or_complete_table(str(root), "wf-1", "topic_relations", "")
    table_path = root / relative
    table = json.loads(table_path.read_text(encoding="utf-8"))
    table["主题关系"] = [{"验收主题": "主题A", "前置主题": "无"}]
    table_path.write_text(json.dumps(table, ensure_ascii=False, indent=2), encoding="utf-8")
    paths = records_mod.regenerate_workflow_indexes(str(root), "wf-1")
    assert len(paths) == 3
    acceptance_index = (root / "acceptance" / "索引.md").read_text(encoding="utf-8")
    assert "主题A" in acceptance_index and "wf-1" in acceptance_index
    assert (root / "impl" / "索引.md").is_file()
    assert (root / "qa" / "索引.md").is_file()


def test_product_features_section_rewrite(tmp_path: Path) -> None:
    root = tmp_path / "proj"
    root.mkdir()
    (root / "spec").mkdir()
    overview = root / "spec" / "产品总说明.md"
    overview.write_text(
        "# 产品\n\n## 7. 产品功能\n\n旧清单\n\n## 8. 相关文档\n\n暂无\n",
        encoding="utf-8",
    )
    (root / "spec" / "功能_一次安装.md").write_text("# 【功能】一次安装\n", encoding="utf-8")
    relative = records_mod.create_or_complete_table(str(root), "wf-1", "product_features", "")
    table_path = root / relative
    table = json.loads(table_path.read_text(encoding="utf-8"))
    table["功能"] = [
        {
            "功能名称": "一次安装",
            "一句话说明": "一条命令完成安装",
            "对应场景": "安装场景",
            "功能文档路径": "./功能_一次安装.md",
        }
    ]
    table_path.write_text(json.dumps(table, ensure_ascii=False, indent=2), encoding="utf-8")
    problems, documents = records_mod.sync_stage_tables(
        str(root),
        _state_with_stage("wf-1", "spec"),
    )
    assert problems == [], problems
    content = overview.read_text(encoding="utf-8")
    assert "一次安装" in content and "旧清单" not in content
    # 再同步一次：内容一致，不报手改
    problems, _documents = records_mod.sync_stage_tables(
        str(root),
        _state_with_stage("wf-1", "spec"),
    )
    assert problems == [], problems


def test_spike_bug_design_tables_generate_docs(tmp_path: Path) -> None:
    root = tmp_path / "proj"
    root.mkdir()
    state = state_mod.WorkflowState(
        workflow_id="wf-1", intent="product_change", topics=["主题A"]
    )
    for stage, kind, topic in [
        ("spike", "spike_conclusion", ""),
        ("reproduce", "bug_record", ""),
        ("update_code_design", "design_sync", ""),
    ]:
        relative = records_mod.create_or_complete_table(str(root), "wf-1", kind, topic)
        table_path = root / relative
        table = json.loads(table_path.read_text(encoding="utf-8"))
        schema = records_mod.KIND_SCHEMAS[kind]
        for list_key, definition in schema["row_lists"].items():
            table[list_key] = [{column: f"{column}内容" for column in definition["columns"]}]
        table_path.write_text(json.dumps(table, ensure_ascii=False, indent=2), encoding="utf-8")
        state.current_stage = stage
        state.stages[stage] = state_mod.StageState()
        problems, documents = records_mod.sync_stage_tables(str(root), state)
        assert problems == [], (stage, problems)
    # 三类表都生成了正式文档
    assert (root / ".workflow_loop/records/wf-1/spike_conclusion_spike_conclusion.md").is_file()
    assert (root / ".workflow_loop/records/wf-1/bug_record_bug_record.md").is_file()
    assert (root / ".workflow_loop/records/wf-1/design_sync_design_sync.md").is_file()


def test_acceptance_record_rejects_criterion_not_in_table(tmp_path: Path) -> None:
    root = tmp_path / "proj"
    root.mkdir()
    relative = records_mod.create_or_complete_table(str(root), "wf-1", "acceptance_plan", "主题A")
    table_path = root / relative
    table = json.loads(table_path.read_text(encoding="utf-8"))
    table["验收条件"] = [{
        "验收条件编号": "AC-01",
        "开始前状态": "s", "触发动作": "a", "可检查结果": "r",
        "通过标准": "p", "不通过标准": "f", "产品设计依据": "d",
    }]
    table_path.write_text(json.dumps(table, ensure_ascii=False, indent=2), encoding="utf-8")

    from argparse import Namespace
    from workflow_loop import cli, state as state_mod

    state = state_mod.WorkflowState(workflow_id="wf-1", intent="product_change", topics=["主题A"])
    state.current_stage = "topic_acceptance"
    state.stages["topic_acceptance"] = state_mod.StageState()
    # 表中存在的编号直接放行
    assert cli._reject_criterion_not_in_table(str(root), state, "主题A", "AC-01") is False
    # 表中不存在的编号拒绝
    try:
        cli._reject_criterion_not_in_table(str(root), state, "主题A", "AC-99")
        raised = False
    except SystemExit:
        raised = True
    assert raised


def test_records_lifecycle_abort_deletes_and_clean_preserves(tmp_path: Path) -> None:
    root = tmp_path / "proj"
    root.mkdir()
    records_mod.create_or_complete_table(str(root), "wf-1", "impl_record", "主题A")
    removed = records_mod.delete_workflow_records(str(root), "wf-1")
    assert removed and not (root / ".workflow_loop/records/wf-1").exists()

    # 从零清场只删除 spec/acceptance/qa/impl/bug，不碰旧轮次的工作记录表
    records_mod.create_or_complete_table(str(root), "wf-old", "impl_record", "旧主题")
    from workflow_loop.cli import clean_artifacts

    cleaned = clean_artifacts(str(root))
    assert (root / ".workflow_loop/records/wf-old").exists()
    assert not any("records" in item for item in cleaned)
