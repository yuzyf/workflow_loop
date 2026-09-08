"""同轮多个缺陷的独立凭据、旧表兼容及定向退回。"""

from argparse import Namespace
from copy import deepcopy
import json

import pytest

from workflow_loop import artifact_validation, bug_record, cli, records
from workflow_loop import state as state_mod
from workflow_repair_support import prepared_project, run_project_evidence
from test_workflow_guidance import TOPIC, WORKFLOW_ID, _bug_table, _markdown_snapshot, _project, _save, _table, _write


SECOND = "下载结果保持完整"


def _bugs(root, version="3", *, legacy=True):
    state = _project(root, version)
    base, empty = _table(root, "bug_record")
    first, seed = _bug_table(root, version)
    state.topics = [TOPIC, SECOND]
    state_mod.save_state(str(root), state)
    paths = {TOPIC: first}
    if not legacy:
        _save(base, empty)
        relative = records.create_or_complete_table(str(root), WORKFLOW_ID, "bug_record", TOPIC)
        first = root / relative
        _save(first, seed)
        paths[TOPIC] = first
    relative = records.create_or_complete_table(str(root), WORKFLOW_ID, "bug_record", SECOND)
    second = deepcopy(seed)
    second["验收主题"] = SECOND
    second["缺陷信息"][0]["现象"] = "第二份独立事实包含管道符 a|b 和路径 C:\\path"
    _save(root / relative, second)
    paths[SECOND] = root / relative
    return state, paths


def _defect_path(root, topic):
    return root / f"bug/缺陷_{records.bug_file_key(str(root), topic)}.md"


def _receipts(root):
    directory = root / records.records_dir("", WORKFLOW_ID) / ".generated"
    return {path.name: path.read_bytes() for path in directory.glob("*.json")}


def test_independent_bug_documents_and_receipts(tmp_path):
    """Workflow-Test
    主题：同轮多个缺陷各自留证并独立验收
    测试项：TC-01 两份缺陷独立生成和更新
    验收条件：AC-01 独立生成多份缺陷
    测试方式：自动化测试
    测试层级：集成测试
    产品入口：调用缺陷记录表生成与复现校验入口
    测试入口：tests/test_multibug_workflow.py::test_independent_bug_documents_and_receipts
    代码入口：src/workflow_loop/records.py::sync_stage_tables
    准备数据：同轮两份不同主题的完整缺陷表，包含管道符与反斜线事实，并保留独立主题状态。
    执行动作：分别生成两份缺陷，更新其中一份后重复生成，并核对复现校验。
    关键断言：两份都能首次生成且重复生成稳定；没有凭据冲突，未改主题的事实和入口保留。
    预期证据：当前执行的结构化测试报告中入口精确匹配，执行数大于零，跳过失败错误均为零且退出码为零。
    """
    root = tmp_path / "project"
    state, paths = _bugs(root, legacy=False)
    for topic in state.topics:
        problems, _ = records.sync_documents(str(root), WORKFLOW_ID, "bug_record", [topic])
        assert not problems, problems
        table = records.load_table(str(paths[topic]))
        assert (root / table["生成文档路径"]).is_file()
    receipts = _receipts(root)
    assert set(receipts) == {path.name for path in paths.values()} | {"bug_record_bug_record.json"}
    assert json.loads(receipts["bug_record_bug_record.json"])["documents"] == {}
    assert receipts[paths[TOPIC].name] != receipts[paths[SECOND].name]
    original_second = _defect_path(root, SECOND).read_bytes()
    bug_record.record_topic_acceptance_pass(str(root), WORKFLOW_ID, [SECOND])
    accepted_second = _defect_path(root, SECOND).read_bytes()
    assert accepted_second.startswith(original_second.rstrip())
    table = records.load_table(str(paths[TOPIC]))
    table["缺陷信息"][0]["现象"] = "只更新第一主题的真实缺陷现象，不改第二主题。"
    _save(paths[TOPIC], table)
    second_receipt = _receipts(root)[paths[SECOND].name]
    problems, _ = records.sync_documents(str(root), WORKFLOW_ID, "bug_record", [TOPIC])
    assert not problems, problems
    assert _defect_path(root, SECOND).read_bytes() == accepted_second
    assert _receipts(root)[paths[SECOND].name] == second_receipt
    index = (root / "bug/索引.md").read_text(encoding="utf-8")
    assert bug_record.index_entry(index, _defect_path(root, SECOND).name)[1][-1] == "主题验收通过，待全量回归"
    assert bug_record.index_entry(index, _defect_path(root, SECOND).name)[1][1] == "第二份独立事实包含管道符 a|b 和路径 C:\\path"
    assert len([line for line in index.splitlines() if "[缺陷_" in line or "./缺陷_" in line]) == 2
    ok, detail = artifact_validation.validate_reproduce_documents(str(root), [], WORKFLOW_ID)
    assert ok, detail
    assert not records.sync_stage_tables(str(root), state)[0]
    before = _markdown_snapshot(root)
    for _ in range(2):
        assert not records.sync_stage_tables(str(root), state)[0]
        assert _markdown_snapshot(root) == before


def test_legacy_and_invalid_bug_tables_preserve_facts(tmp_path):
    """Workflow-Test
    主题：同轮多个缺陷各自留证并独立验收
    测试项：TC-02 旧表兼容和非法输入零覆盖
    验收条件：AC-02 旧表兼容且错误零覆盖
    测试方式：自动化测试
    测试层级：集成测试
    产品入口：调用多主题建表及阶段按表生成入口
    测试入口：tests/test_multibug_workflow.py::test_legacy_and_invalid_bug_tables_preserve_facts
    代码入口：src/workflow_loop/records.py::sync_stage_tables
    准备数据：冻结版本一至三的已填基础表、空占位表与新增主题表，以及重复、缺表、错误编号和篡改样本。
    执行动作：逐个同步合法旧表和新增表，再分别输入非法身份或手改并比较正式文件。
    关键断言：旧表版本一至三均可继续；有效新表独立处理；重复、缺失、标识冲突和篡改均拒绝且不覆盖正式事实。
    预期证据：当前执行的结构化测试报告中入口精确匹配，执行数大于零，跳过失败错误均为零且退出码为零。
    """
    for version in ("1", "2", "3"):
        root = tmp_path / f"legacy-{version}"
        state, paths = _bugs(root, version)
        problems, _ = records.sync_stage_tables(str(root), state)
        assert not problems, problems
        assert paths[TOPIC].name == "bug_record_bug_record.json"
        assert set(_receipts(root)) == {path.name for path in paths.values()}
        assert records.load_table(str(paths[TOPIC]))["表版本"] == version
        assert not (paths[TOPIC].parent / f"bug_record_{TOPIC}.json").exists()
        before = _markdown_snapshot(root)
        assert not records.sync_stage_tables(str(root), state)[0]
        assert _markdown_snapshot(root) == before

    cases = ("missing", "duplicate", "workflow", "topic", "hash", "path", "json", "manual", "owner", "index")
    for case in cases:
        root = tmp_path / case
        state, paths = _bugs(root)
        assert not records.sync_stage_tables(str(root), state)[0]
        invalid = records.load_table(str(paths[SECOND]))
        if case == "missing":
            paths[SECOND].unlink()
        elif case == "duplicate":
            first = records.load_table(str(paths[TOPIC]))
            _save(paths[TOPIC].parent / f"bug_record_{TOPIC}.json", first)
        elif case == "workflow":
            invalid["工作流编号"] = "other-run"
            _save(paths[SECOND], invalid)
        elif case == "topic":
            invalid["验收主题"] = "与文件名不匹配的主题"
            _save(paths[SECOND], invalid)
        elif case == "hash":
            invalid["生成文档哈希"] = "0" * 64
            _save(paths[SECOND], invalid)
        elif case == "path":
            invalid["生成文档路径"] = "spec/产品总说明.md"
            _save(paths[SECOND], invalid)
        elif case == "json":
            _write(paths[SECOND], "{")
        elif case in {"manual", "owner"}:
            path = _defect_path(root, SECOND)
            content = path.read_text(encoding="utf-8")
            content = (content.replace("第二份独立事实", "手工修改的独立事实") if case == "manual"
                       else content.replace(WORKFLOW_ID, "other-run"))
            _write(path, content)
        else:
            path = root / "bug/索引.md"
            content = path.read_text(encoding="utf-8")
            row = next(line for line in content.splitlines() if _defect_path(root, SECOND).name in line)
            _write(path, content.rstrip() + "\n" + row + "\n")
        valid = records.load_table(str(paths[TOPIC]))
        valid["缺陷信息"][0]["现象"] = "合法主题也有待更新事实，但整批失败时不得提前写入。"
        _save(paths[TOPIC], valid)
        before = _markdown_snapshot(root)
        receipts = _receipts(root)
        problems, documents = records.sync_stage_tables(str(root), state)
        assert problems, case
        assert documents == [], case
        assert _markdown_snapshot(root) == before, case
        assert _receipts(root) == receipts, case

    root = tmp_path / "first-acceptance-plan"
    state = _project(root, stage="acceptance_plan")
    state.intent = "product_change"
    state.topics.append(SECOND)
    state_mod.save_state(str(root), state)
    created = records.ensure_stage_tables(str(root), state)
    assert len(created) == 3
    assert sum("topic_relations_" in path for path in created) == 1
    assert all((root / path).is_file() for path in created)


def test_return_only_invalidates_selected_bug(tmp_path, monkeypatch, capsys):
    """Workflow-Test
    主题：同轮多个缺陷各自留证并独立验收
    测试项：TC-03 退回一个缺陷保留另一个结果
    验收条件：AC-03 退回只清除受影响主题
    测试方式：自动化测试
    测试层级：集成测试
    产品入口：通过返回上游和正式收工命令入口
    测试入口：tests/test_multibug_workflow.py::test_return_only_invalidates_selected_bug
    代码入口：src/workflow_loop/cli.py::cmd_return
    准备数据：同轮两个缺陷都有独立测试及验收记录，追踪关系完整，最终回归已有结果。
    执行动作：指定一个主题退回代码实施，再尝试在未重新完成时收工。
    关键断言：原始复现事实保留，未受影响主题不被清空；任一主题未完成时整轮不能完成。
    预期证据：当前执行的结构化测试报告中入口精确匹配，执行数大于零，跳过失败错误均为零且退出码为零。
    """
    root = tmp_path / "project"
    state, _ = _bugs(root)
    assert not records.sync_stage_tables(str(root), state)[0]
    state = prepared_project(root, state.topics, workflow_id=WORKFLOW_ID, intent="bugfix")
    state = run_project_evidence(root, state)
    table_path = root / records.table_relative_path(str(root), WORKFLOW_ID, "acceptance_result", TOPIC)
    original_table = records.load_table(str(table_path))
    document = root / f"acceptance/{records.topic_file_key(str(root), TOPIC)}_验收结果.md"
    original_document = document.read_bytes()
    for failure in ("missing", "stale", "foreign", "machine"):
        invalid = deepcopy(state)
        invalid.current_stage = "topic_acceptance"
        table = deepcopy(original_table)
        if failure == "missing":
            invalid.stages["topic_acceptance"].acceptance_records[TOPIC].clear()
        elif failure == "stale":
            invalid.stages["qa"].test_tasks[TOPIC]["TC-01"].current_record = None
        elif failure == "foreign":
            invalid.stages["topic_acceptance"].acceptance_records[TOPIC]["AC-01"] = deepcopy(
                invalid.stages["topic_acceptance"].acceptance_records[SECOND]["AC-01"]
            )
        else:
            table["验收结果"][0]["机器测试记录编号"] = "RUN-OTHER"
        _save(table_path, table)
        state_mod.save_state(str(root), invalid)
        assert records.sync_stage_tables(str(root), invalid)[0], failure
        assert records.sync_documents(str(root), WORKFLOW_ID, "acceptance_result", [TOPIC])[0], failure
        assert document.read_bytes() == original_document, failure
    state_mod.save_state(str(root), state)
    original_table["验收结果"][0]["验收记录编号"] = "不可信的手填编号"
    _save(table_path, original_table)
    assert not records.sync_documents(str(root), WORKFLOW_ID, "acceptance_result", [TOPIC])[0]
    assert document.read_bytes() == original_document
    assert records.load_table(str(table_path))["验收结果"][0]["验收记录编号"] == (
        state.stages["topic_acceptance"].acceptance_records[TOPIC]["AC-01"].record_id
    )
    bug_record.record_topic_acceptance_pass(str(root), WORKFLOW_ID, state.topics)
    untouched_key = records.topic_file_key(str(root), SECOND)
    untouched_paths = (
        root / f"qa/{untouched_key}_测试结果.md",
        root / f"acceptance/{untouched_key}_验收结果.md",
        _defect_path(root, SECOND),
    )
    untouched = {path: path.read_bytes() for path in untouched_paths}
    task_before = deepcopy(state.stages["qa"].test_tasks[SECOND])
    acceptance_before = deepcopy(state.stages["topic_acceptance"].acceptance_records[SECOND])
    first_facts = _defect_path(root, TOPIC).read_text(encoding="utf-8").split("### ")[0]
    monkeypatch.chdir(root)
    cli.cmd_return(Namespace(to="impl", topic=[TOPIC], all_topics=False, reason="仅第一主题的实现需要修正"))
    assert "工作流已退回" in capsys.readouterr().out
    current = state_mod.load_state(str(root))
    assert current.current_stage == "impl"
    assert TOPIC not in current.stages["qa"].test_tasks
    assert current.stages["qa"].test_tasks[SECOND] == task_before
    assert TOPIC not in current.stages["topic_acceptance"].acceptance_records
    assert current.stages["topic_acceptance"].acceptance_records[SECOND] == acceptance_before
    assert current.regression_test.record_id is None
    assert not current.stages["overall_acceptance"].gate.user_confirmed
    assert _defect_path(root, TOPIC).read_text(encoding="utf-8").startswith(first_facts.rstrip())
    for path, before in untouched.items():
        assert path.read_bytes() == before, path
    first_key = records.topic_file_key(str(root), TOPIC)
    assert not (root / f"qa/{first_key}_测试结果.md").exists()
    assert not (root / f"acceptance/{first_key}_验收结果.md").exists()
    with pytest.raises(SystemExit) as error:
        cli.cmd_done(Namespace())
    assert error.value.code == 1
    assert "未完成" in capsys.readouterr().out
    assert state_mod.load_state(str(root)).run_status == "active"
