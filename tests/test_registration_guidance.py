"""状态给出的登记指引必须与当前模式的真实命令一致。"""

from copy import deepcopy
import re
import shlex
import shutil

from workflow_loop import records, test_execution, verification
from workflow_loop import state as state_mod
from workflow_repair_support import ENTRY, prepared_project
from test_commands import _install_project, _run
from test_workflow_guidance import _save, _write


TOPIC = "上传登记验证"


def _load_materials_and_confirm_scope(root):
    code, output, error = _run(["discuss"], root)
    assert code == 0, (output, error)
    assert "材料清单" in output
    state = state_mod.load_state(str(root))
    state.stages["qa"].gate.discussion_complete = True
    state.stages["qa"].scope_confirmed_hash = verification.compute_test_plan_hash(str(root), state.topics)
    state_mod.save_state(str(root), state)
    return state


def _registration_hint(root):
    code, output, error = _run(["status"], root)
    assert code == 0, (output, error)
    matches = re.findall(r"`(workflow test prepare[^`]+)`", output)
    assert len(matches) == 1, output
    return matches[0]


def test_table_next_step_registers_every_task_first_time(tmp_path):
    """Workflow-Test
    主题：测试登记按表指引首次执行即可成功
    测试项：TC-01 原样执行下一步一次登记全部测试
    验收条件：AC-01 从表指引首次即可登记
    测试方式：自动化测试
    测试层级：集成测试
    产品入口：读取状态输出后原样执行其中的登记命令
    测试入口：tests/test_registration_guidance.py::test_table_next_step_registers_every_task_first_time
    代码入口：src/workflow_loop/cli.py::cmd_test_prepare
    准备数据：测试范围已确认且材料已加载，表中有两个完整自动化测试项，尚未登记任务。
    执行动作：提取状态输出中唯一的测试登记命令原样执行，然后再次登记相同计划。
    关键断言：下一步明确选择从表读取，首次执行退出成功并登记全部缺少项目；阶段规范与程序一致。
    预期证据：当前执行的结构化测试报告中入口精确匹配，执行数大于零，跳过失败错误均为零且退出码为零。
    """
    _install_project(tmp_path)
    state = prepared_project(tmp_path, [TOPIC])
    path = tmp_path / records.table_relative_path(str(tmp_path), state.workflow_id, "test_plan", TOPIC)
    table = records.load_table(str(path))
    second = deepcopy(table["测试项"][0])
    second_entry = "tests/test_app.py::test_upload_again"
    second.update({
        "测试项编号": "TC-02", "直白测试名称": "再次调用上传得到相同返回值",
        "测试入口": second_entry, "正式目标名称": second_entry,
        "命令参数数组": [*second["命令参数数组"][:-1], second_entry],
    })
    table["测试项"].append(second)
    _save(path, table)
    code_path = tmp_path / "tests/test_app.py"
    _write(code_path, code_path.read_text(encoding="utf-8") + "\n\ndef test_upload_again():\n    assert upload() == 'ok'\n")
    assert not records.sync_documents(str(tmp_path), state.workflow_id, "test_plan", [TOPIC])[0]
    _load_materials_and_confirm_scope(tmp_path)
    command = _registration_hint(tmp_path)
    assert command == "workflow test prepare --from-tables"
    arguments = shlex.split(command)[1:]
    code, output, error = _run(arguments, tmp_path)
    assert code == 0, (output, error)
    current = state_mod.load_state(str(tmp_path))
    tasks = current.stages["qa"].test_tasks[TOPIC]
    assert set(tasks) == {"TC-01", "TC-02"}, output
    assert all(task.current_record is None and task.status == "pending" for task in tasks.values())
    attempts = test_execution.run_prepared_tasks(str(tmp_path), current, parallelism=1)
    assert len(attempts) == 2
    assert all(attempt.status == "passed" for attempt in attempts), attempts
    executed = deepcopy(current.stages["qa"].test_tasks[TOPIC])
    code, output, error = _run(arguments, tmp_path)
    assert code == 0, (output, error)
    assert state_mod.load_state(str(tmp_path)).stages["qa"].test_tasks[TOPIC] == executed
    completed = state_mod.load_state(str(tmp_path))
    for field, value in (
        ("命令参数数组", [*second["命令参数数组"], "--disable-warnings"]),
        ("超时秒数", 61),
        ("前置测试项", "TC-01"),
    ):
        changed = records.load_table(str(path))
        changed["测试项"][1] = deepcopy(second)
        changed["测试项"][1][field] = value
        _save(path, changed)
        state_mod.save_state(str(tmp_path), deepcopy(completed))
        assert not records.sync_documents(str(tmp_path), state.workflow_id, "test_plan", [TOPIC])[0]
        _load_materials_and_confirm_scope(tmp_path)
        code, output, error = _run(arguments, tmp_path)
        assert code == 0, (field, output, error)
        updated = state_mod.load_state(str(tmp_path)).stages["qa"].test_tasks[TOPIC]
        assert updated["TC-01"] == executed["TC-01"], field
        assert updated["TC-02"].status == "pending", field
        assert updated["TC-02"].current_record is None, field
        if field == "前置测试项":
            assert updated["TC-02"].dependencies == ["TC-01"]
    for filename in ("test.md", "test_code.md", "test_code_implementation.md", "test_plan.md"):
        text = (tmp_path / ".workflow_loop/Standardized_Repository/qa" / filename).read_text(encoding="utf-8")
        assert "workflow test prepare --from-tables" in text


def test_legacy_registration_keeps_required_parameters(tmp_path):
    """Workflow-Test
    主题：测试登记按表指引首次执行即可成功
    测试项：TC-02 逐条登记仍接受完整参数
    验收条件：AC-02 逐条登记保留完整要求
    测试方式：自动化测试
    测试层级：集成测试
    产品入口：读取旧文档模式指引后逐条登记测试
    测试入口：tests/test_registration_guidance.py::test_legacy_registration_keeps_required_parameters
    代码入口：src/workflow_loop/cli.py::cmd_test_prepare
    准备数据：未启用表模式的测试阶段，已有一个真实自动化测试入口和完整测试计划文档。
    执行动作：核对必需参数说明，使用完整参数登记，再检查缺参数请求的错误。
    关键断言：两种模式的指引与实际登记行为一致，旧参数接口继续可用。
    预期证据：当前执行的结构化测试报告中入口精确匹配，执行数大于零，跳过失败错误均为零且退出码为零。
    """
    _install_project(tmp_path)
    state = prepared_project(tmp_path, [TOPIC])
    path = tmp_path / records.table_relative_path(str(tmp_path), state.workflow_id, "test_plan", TOPIC)
    row = records.load_table(str(path))["测试项"][0]
    labels = [
        "Workflow-Test", f"主题：{TOPIC}",
        f"测试项：TC-01 {row['直白测试名称']}", "验收条件：AC-01 上传返回真实结果",
        "测试方式：自动化测试", "测试层级：集成测试",
        *[f"{key}：{row[key]}" for key in ("产品入口", "测试入口", "准备数据", "执行动作")],
        f"代码入口：`{row['代码入口']}`",
        f"关键断言：{row['预期结果']}", f"预期证据：{row['证据要求']}",
    ]
    marker = "\n".join("    " + line for line in labels)
    source = 'from src.app import upload\n\n\ndef test_upload():\n    """\n' + marker + '\n    """\n    assert upload() == "ok"\n'
    _write(tmp_path / "tests/test_app.py", source)
    shutil.rmtree(tmp_path / ".workflow_loop/records")
    state.table_format_version = ""
    state_mod.save_state(str(tmp_path), state)
    _load_materials_and_confirm_scope(tmp_path)
    command = _registration_hint(tmp_path)
    assert "--from-tables" not in command
    for option in ("--topic", "--tc", "--report-adapter"):
        assert option in command
    arguments = ["test", "prepare", "--topic", TOPIC, "--tc", "TC-01",
                 "--report-adapter", "pytest-junitxml", "--", *row["命令参数数组"]]
    code, output, error = _run(arguments, tmp_path)
    assert code == 0, (output, error)
    current = state_mod.load_state(str(tmp_path))
    task = current.stages["qa"].test_tasks[TOPIC]["TC-01"]
    assert task.test_entries == [ENTRY]
    assert task.current_record is None
    before = deepcopy(task)
    code, output, error = _run(["test", "prepare"], tmp_path)
    assert code == 1, (output, error)
    for option in ("--topic", "--tc", "--report-adapter"):
        assert option in output
    next_step = next(line for line in output.splitlines() if line.startswith("下一步："))
    assert "--from-tables" not in next_step
    assert state_mod.load_state(str(tmp_path)).stages["qa"].test_tasks[TOPIC]["TC-01"] == before
