"""本轮集成测试共用的隔离项目与真实执行证据。"""

import sys

from workflow_loop import acceptance_records, project, records, test_execution, test_runner
from workflow_loop import state as state_mod
from workflow_loop.path_composer import build_stage_path
from test_workflow_guidance import _save, _write


ENTRY = "tests/test_app.py::test_upload"


def filled_table(root, state, kind, topic=""):
    relative = records.create_or_complete_table(str(root), state.workflow_id, kind, topic)
    path = root / relative
    table = records.load_table(str(path))
    schema = records._schema(kind, state.table_format_version)
    values = {
        "验收条件编号": "AC-01", "验收条件名称": "上传返回真实结果",
        "对应验收条件": "AC-01", "测试项编号": "TC-01",
        "直白测试名称": "上传返回真实结果", "前置测试项": "无",
        "测试方式": "自动化测试", "产品入口": "调用上传入口",
        "代码入口": "src/app.py::upload", "测试入口": ENTRY,
        "准备数据": "隔离临时项目中存在真实上传函数和测试文件。",
        "执行动作": "运行测试并实际调用上传函数检查返回值。",
        "观察位置": "上传返回值和本次结构化测试报告。",
        "预期结果": "上传函数返回 ok，结构化报告无失败、错误或跳过。",
        "不通过表现": "上传返回值错误，或者报告含失败、错误或跳过。",
        "证据要求": "保存真实测试进程的结构化报告与零退出码。",
        "命令参数数组": [sys.executable, "-m", "pytest", "-q", ENTRY],
        "正式目标名称": ENTRY, "报告适配器": "pytest-junitxml",
        "工作目录": "", "超时秒数": 60,
        "顺序": "1", "实施顺序": "1", "对应计划步骤": "1", "前置步骤": "无",
        "文件": "src/app.py", "代码位置（最终文件）": "L1-L2",
        "是否需要继续修改": "否",
        "产品设计依据": "[上传规则](../spec/功能_上传文件.md#r-1)",
        "执行结论": "passed", "机器记录编号": "",
    }
    for key, definition in schema["row_lists"].items():
        table[key] = [{column: values.get(column, f"{column}按临时项目的真实输入与输出逐项核对。")
                       for column in definition["columns"]}]
    for key in schema["narrative"]:
        table[key] = [f"{key}依据本测试临时项目的实际状态，不代表真实用户操作。"]
    for key in records._NARRATIVE_ALLOW_NO_CONTENT.get(kind, set()):
        if key in schema["narrative"]:
            table[key] = ["暂无"]
    _save(path, table)
    return path, table


def prepared_project(root, topics, *, workflow_id="repair-evidence", version="3", intent="product_change"):
    root.mkdir(parents=True, exist_ok=True)
    if project.load_project(str(root)) is None:
        project.create_project(str(root))
    project_state = project.load_project(str(root))
    project_state.project_design_initialized = True
    project.save_project(str(root), project_state)
    stages = build_stage_path(intent, str(root))
    state = state_mod.WorkflowState(
        workflow_id=workflow_id, intent=intent, topics=list(topics),
        table_format_version=version, stage_path_version=2,
        current_stage="acceptance_plan", stage_path=[stage.name() for stage in stages],
        stages={stage.name(): state_mod.StageState(artifact_paths=stage.artifact_paths())
                for stage in stages},
    )
    state_mod.save_state(str(root), state)
    _write(root / "src/app.py", "def upload():\n    return 'ok'\n")
    _write(root / "tests/test_app.py",
           "from src.app import upload\n\n\ndef test_upload():\n    assert upload() == 'ok'\n")
    if not (root / "spec/产品总说明.md").exists():
        _write(root / "spec/产品总说明.md", "# 产品\n\n[上传文件](./功能_上传文件.md)\n")
    _write(root / "spec/功能_上传文件.md", '# 上传文件\n\n<a id="r-1"></a>\n上传返回实际结果。\n')
    records.ensure_stage_tables(str(root), state)
    for topic in topics:
        filled_table(root, state, "acceptance_plan", topic)
    relation = records.table_relative_path(str(root), workflow_id, "topic_relations", "")
    table = records.load_table(str(root / relation))
    table["主题关系"] = [{"验收主题": topic, "前置主题": "无"} for topic in topics]
    _save(root / relation, table)
    problems, _ = records.sync_stage_tables(str(root), state)
    assert not problems, problems
    state.current_stage = "impl"
    state_mod.save_state(str(root), state)
    for topic in topics:
        filled_table(root, state, "impl_record", topic)
    problems, _ = records.sync_stage_tables(str(root), state)
    assert not problems, problems

    state.current_stage = "qa"
    state.stages["qa"].status = "in_progress"
    state.stages["qa"].gate.discussion_complete = True
    state_mod.save_state(str(root), state)
    for topic in topics:
        filled_table(root, state, "test_plan", topic)
    problems, _ = records.sync_documents(str(root), workflow_id, "test_plan", list(topics))
    assert not problems, problems
    records.regenerate_workflow_indexes(str(root), workflow_id)
    return state


def run_project_evidence(root, state):
    for topic in state.topics:
        test_execution.prepare_task(
            str(root), state, topic, "TC-01",
            [sys.executable, "-m", "pytest", "-q", ENTRY],
            report_adapter="pytest-junitxml",
        )
    state_mod.save_state(str(root), state)
    attempts = test_execution.run_prepared_tasks(str(root), state, parallelism=1)
    assert len(attempts) == len(state.topics)
    assert all(attempt.status == "passed" for attempt in attempts), attempts
    for topic in state.topics:
        filled_table(root, state, "test_result", topic)
    problems, _ = records.sync_stage_tables(str(root), state)
    assert not problems, problems
    state.current_stage = "topic_acceptance"
    created = acceptance_records.ensure_automated_records(str(root), state)
    assert len(created) == len(state.topics)
    for topic in state.topics:
        assert acceptance_records.topic_records_complete(str(root), state, topic)
        record = state.stages["topic_acceptance"].acceptance_records[topic]["AC-01"]
        path, table = filled_table(root, state, "acceptance_result", topic)
        key = records.topic_file_key(str(root), topic)
        table["验收结果"][0].update({
            "验收方式": "自动化测试", "验收结论": "passed",
            "自动化依据": f"[主题测试结果](../qa/{key}_测试结果.md#tc-01)",
            "机器测试记录编号": "、".join(record.test_record_ids),
            "用户实际回答": "不适用", "人工确认": "不适用",
            "实际观察结果": record.actual_result, "证据": record.evidence,
            "验收记录编号": "",
        })
        _save(path, table)
    problems, _ = records.sync_stage_tables(str(root), state)
    assert not problems, problems
    for topic in state.topics:
        key = records.topic_file_key(str(root), topic)
        record = state.stages["topic_acceptance"].acceptance_records[topic]["AC-01"]
        document = root / f"acceptance/{key}_验收结果.md"
        assert f"- 验收记录编号：{record.record_id}" in document.read_text(encoding="utf-8")
        table_path = root / records.table_relative_path(str(root), state.workflow_id, "acceptance_result", topic)
        assert records.load_table(str(table_path))["验收结果"][0]["验收记录编号"] == record.record_id
    project.register_test_entry(str(root), {"default": [sys.executable, "-m", "pytest", "-q", "tests/test_app.py"]})
    state.current_stage = "regression_test"
    state_mod.save_state(str(root), state)
    passed, detail = test_runner.run_final_regression(str(root), state)
    assert passed, detail
    for stage in state.stages.values():
        stage.status = "done"
        stage.gate = state_mod.GateState(True, True, True)
    state.current_stage = "update_code_design"
    state.stages["update_code_design"].status = "in_progress"
    state.stages["update_code_design"].gate = state_mod.GateState(True, False, False)
    state_mod.save_state(str(root), state)
    return state
