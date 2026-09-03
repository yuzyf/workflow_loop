"""表模式登记入口的形状校验与多入口登记。"""

import json
import os
import sys

import pytest

from workflow_loop import cli
from workflow_loop import records as records_mod
from workflow_loop import test_execution
from workflow_loop import verification
from workflow_loop.project import create_project
from workflow_loop.state import StageState, WorkflowState, load_state, save_state


WORKFLOW_ID = "2026-09-03-0231-bugfix"
TOPIC = "登记测试项时入口填不对当场说清而不是测完才失败"
BARE_TITLE = "验证上传写入与覆盖"
WRITE_ENTRY = "tests/test_upload.py::test_upload_writes_content"
OVERWRITE_ENTRY = "tests/test_upload.py::test_upload_overwrites_existing"


def _build_project(tmp_path) -> WorkflowState:
    """建立一个走表模式、停在测试验证环节的隔离项目，带真实可运行的被测代码。"""
    root = str(tmp_path)
    create_project(root)
    (tmp_path / "src").mkdir(exist_ok=True)
    (tmp_path / "tests").mkdir(exist_ok=True)
    (tmp_path / "qa").mkdir(exist_ok=True)
    (tmp_path / "src" / "upload.py").write_text(
        "from pathlib import Path\n\n\n"
        "def upload_file(target, content):\n"
        "    Path(target).write_text(content, encoding='utf-8')\n",
        encoding="utf-8",
    )
    (tmp_path / "tests" / "test_upload.py").write_text(
        "from src.upload import upload_file\n\n\n"
        "def test_upload_writes_content(tmp_path):\n"
        "    target = tmp_path / 'uploaded.txt'\n"
        "    upload_file(target, 'saved')\n"
        "    assert target.read_text(encoding='utf-8') == 'saved'\n\n\n"
        "def test_upload_overwrites_existing(tmp_path):\n"
        "    target = tmp_path / 'uploaded.txt'\n"
        "    target.write_text('old', encoding='utf-8')\n"
        "    upload_file(target, 'new')\n"
        "    assert target.read_text(encoding='utf-8') == 'new'\n",
        encoding="utf-8",
    )
    (tmp_path / "qa" / "索引.md").write_text(
        f"# 测试计划索引\n\n## {WORKFLOW_ID}\n\n### 主题关系\n\n"
        "| 展示顺序 | 验收主题 | 前置主题 | 验收计划 | 实施记录 | 测试计划 | 测试结果 |\n"
        "|---|---|---|---|---|---|---|\n"
        f"| 1 | {TOPIC} | 无 | [验收计划](../acceptance/{TOPIC}_验收计划.md) "
        f"| [实施记录](../impl/{TOPIC}_实施记录.md) | [测试计划](./{TOPIC}_测试计划.md) "
        f"| `./{TOPIC}_测试结果.md`（待生成） |\n",
        encoding="utf-8",
    )
    state = WorkflowState(
        workflow_id=WORKFLOW_ID,
        intent="bugfix",
        current_stage="qa",
        topics=[TOPIC],
        stages={"qa": StageState(status="in_progress")},
    )
    state.table_format_version = "2"
    state.verification.test_code_hash = verification.compute_test_code_snapshot_hash(root)
    save_state(root, state)
    return state


def _write_plan(tmp_path, official_target, command: list[str]) -> dict:
    """按给定的“正式目标名称”写好测试计划工作记录表，返回表内容。"""
    relative = records_mod.create_or_complete_table(
        str(tmp_path), WORKFLOW_ID, "test_plan", TOPIC
    )
    absolute = os.path.join(str(tmp_path), relative)
    table = records_mod.load_table(absolute)
    table["测试项"] = [{
        "测试项编号": "TC-01",
        "直白测试名称": "验证上传写入与覆盖",
        "前置测试项": "无",
        "测试方式": "自动化测试",
        "产品入口": "上传命令",
        "代码入口": "src/upload.py::upload_file",
        "测试入口": WRITE_ENTRY,
        "准备数据": "创建隔离临时目录并准备待写入内容",
        "执行动作": "调用上传入口把内容写进目标文件",
        "观察位置": "临时目录中的目标文件内容",
        "预期结果": "目标文件存在且内容与写入内容一致",
        "不通过表现": "目标文件缺失或内容与写入内容不同",
        "证据要求": "结构化报告与目标文件实际内容",
        "对应验收条件": "AC-01",
        "命令参数数组": json.dumps(command, ensure_ascii=False),
        "工作目录": "",
        "超时秒数": "600",
        "报告适配器": "pytest-junitxml",
        "正式目标名称": official_target,
    }]
    table["测试范围说明"] = ["本主题只验证上传入口把内容真实写入目标文件这一条行为。"]
    records_mod._atomic_write(absolute, table)
    return records_mod.load_table(absolute)


def _pytest_command(*targets: str) -> list[str]:
    return [sys.executable, "-m", "pytest", *targets, "-q"]


def test_official_target_hint_states_shape_example_and_multi_entry(tmp_path):
    """Workflow-Test
    主题：登记测试项时入口填不对当场说清而不是测完才失败
    测试项：TC-01 两列说明写清怎么填
    验收条件：AC-01 两列说明写清怎么填
    测试方式：自动化测试
    测试层级：模块测试
    产品入口：程序为当前环节生成测试计划工作记录表
    测试入口：tests/test_table_entry_registration.py::test_official_target_hint_states_shape_example_and_multi_entry
    代码入口：src/workflow_loop/records.py::create_or_complete_table
    准备数据：一个隔离临时项目和它的测试验证环节状态
    执行动作：让程序为本主题生成测试计划工作记录表
    关键断言：正式目标名称的说明同时含必须形状、可照抄的例子、多入口的 JSON 数组写法和唯一登记来源四项，测试入口的说明写明它不是登记入口
    预期证据：pytest 结构化 junit 报告 1 条通过且退出码 0
    """
    _build_project(tmp_path)
    relative = records_mod.create_or_complete_table(
        str(tmp_path), WORKFLOW_ID, "test_plan", TOPIC
    )
    hints = records_mod.load_table(os.path.join(str(tmp_path), relative))["填写说明"]["测试项"]

    official = hints["正式目标名称"]
    assert "项目相对路径::报告里的目标名" in official
    assert "tests/test_records.py::test_table_rejects_bad_entry" in official
    assert "JSON 数组" in official
    assert "唯一来源" in official
    assert "不是登记入口" in hints["测试入口"]


def test_prepare_from_tables_rejects_bare_title_without_registering(tmp_path, capsys):
    """Workflow-Test
    主题：登记测试项时入口填不对当场说清而不是测完才失败
    测试项：TC-02 填纯标题当场被拒绝
    验收条件：AC-02 填不对当场被拒绝
    测试方式：自动化测试
    测试层级：命令测试
    产品入口：workflow test prepare --from-tables
    测试入口：tests/test_table_entry_registration.py::test_prepare_from_tables_rejects_bare_title_without_registering
    代码入口：src/workflow_loop/cli.py::_prepare_tasks_from_tables
    准备数据：一张正式目标名称写成纯测试标题的测试计划工作记录表
    执行动作：按表登记该主题的全部测试项
    关键断言：命令以失败退出并写明主题、测试项编号、列名、实际填的值和正确形状，状态文件里没有该测试项的登记任务
    预期证据：pytest 结构化 junit 报告 1 条通过且退出码 0
    """
    state = _build_project(tmp_path)
    _write_plan(tmp_path, BARE_TITLE, _pytest_command(WRITE_ENTRY))

    with pytest.raises(SystemExit) as exit_info:
        cli._prepare_tasks_from_tables(str(tmp_path), state)

    assert exit_info.value.code == 1
    output = capsys.readouterr().out
    assert TOPIC in output
    assert "TC-01" in output
    assert "正式目标名称" in output
    assert BARE_TITLE in output
    assert "项目相对路径::报告里的目标名" in output
    reloaded = load_state(str(tmp_path))
    assert reloaded.stages["qa"].test_tasks == {}


def test_table_gate_reports_bare_title_as_format_problem(tmp_path):
    """Workflow-Test
    主题：登记测试项时入口填不对当场说清而不是测完才失败
    测试项：TC-03 表校验报出同一问题
    验收条件：AC-02 填不对当场被拒绝
    测试方式：自动化测试
    测试层级：模块测试
    产品入口：workflow gate qa 第二道门的表校验
    测试入口：tests/test_table_entry_registration.py::test_table_gate_reports_bare_title_as_format_problem
    代码入口：src/workflow_loop/records.py::validate_table
    准备数据：一张正式目标名称写成纯测试标题的测试计划工作记录表
    执行动作：对这张表执行测试验证环节的表校验
    关键断言：校验结果里有一条格式问题，位置写到行清单名称、行号和列名，并给出正确形状
    预期证据：pytest 结构化 junit 报告 1 条通过且退出码 0
    """
    _build_project(tmp_path)
    table = _write_plan(tmp_path, BARE_TITLE, _pytest_command(WRITE_ENTRY))

    problems = records_mod.validate_table("test_plan", table, "2")

    entry_problems = [
        detail for category, detail in problems
        if category == records_mod.FORMAT_CATEGORY and "正式目标名称" in detail
    ]
    assert len(entry_problems) == 1
    assert "测试项 第 1 行" in entry_problems[0]
    assert "TC-01" in entry_problems[0]
    assert BARE_TITLE in entry_problems[0]
    assert "项目相对路径::报告里的目标名" in entry_problems[0]


def test_two_entries_in_one_cell_register_and_pass(tmp_path):
    """Workflow-Test
    主题：登记测试项时入口填不对当场说清而不是测完才失败
    测试项：TC-04 一格登记两个入口并通过
    验收条件：AC-03 一个测试项能登记多个入口
    测试方式：自动化测试
    测试层级：集成测试
    产品入口：workflow test prepare --from-tables 与 workflow test run
    测试入口：tests/test_table_entry_registration.py::test_two_entries_in_one_cell_register_and_pass
    代码入口：src/workflow_loop/test_execution.py::prepare_task
    准备数据：一个测试项由同文件两个测试函数覆盖，正式目标名称按 JSON 数组写两个入口
    执行动作：按表登记该测试项后真实执行它的命令
    关键断言：登记入口是两条互不相同的入口，执行判定 passed，机器记录的精确匹配入口同样是这两条且实际执行数为 2、跳过失败错误都是 0
    预期证据：pytest 结构化 junit 报告 1 条通过且退出码 0
    """
    state = _build_project(tmp_path)
    command = _pytest_command("tests/test_upload.py")
    _write_plan(
        tmp_path,
        json.dumps([WRITE_ENTRY, OVERWRITE_ENTRY], ensure_ascii=False),
        command,
    )

    task = test_execution.prepare_task(
        str(tmp_path), state, TOPIC, "TC-01", command,
        timeout_seconds=600, cwd=None, report_adapter="pytest-junitxml",
    )
    save_state(str(tmp_path), state)
    attempt = test_execution.run_prepared_tasks(str(tmp_path), state, parallelism=1)[0]
    record = load_state(str(tmp_path)).stages["qa"].test_tasks[TOPIC]["TC-01"].current_record

    assert task.test_entries == sorted([WRITE_ENTRY, OVERWRITE_ENTRY])
    assert attempt.status == "passed"
    assert record is not None
    assert sorted(record.matched_test_entries) == sorted([WRITE_ENTRY, OVERWRITE_ENTRY])
    assert record.executed_count == 2
    assert (record.skipped_count, record.failed_count, record.error_count) == (0, 0, 0)


def test_single_correct_entry_still_registers_and_passes(tmp_path):
    """Workflow-Test
    主题：登记测试项时入口填不对当场说清而不是测完才失败
    测试项：TC-05 填对的表结论不变
    验收条件：AC-04 已经填对的表不受影响
    测试方式：自动化测试
    测试层级：集成测试
    产品入口：workflow test prepare --from-tables 与 workflow test run
    测试入口：tests/test_table_entry_registration.py::test_single_correct_entry_still_registers_and_passes
    代码入口：src/workflow_loop/test_execution.py::prepare_task
    准备数据：一张正式目标名称写成单个项目相对路径加标识的测试计划工作记录表
    执行动作：按表登记该测试项后真实执行它的命令
    关键断言：登记入口仍是原来那一条，执行判定 passed，机器记录的精确匹配入口与登记入口一一对应且实际执行数为 1
    预期证据：pytest 结构化 junit 报告 1 条通过且退出码 0
    """
    state = _build_project(tmp_path)
    command = _pytest_command(WRITE_ENTRY)
    _write_plan(tmp_path, WRITE_ENTRY, command)

    task = test_execution.prepare_task(
        str(tmp_path), state, TOPIC, "TC-01", command,
        timeout_seconds=600, cwd=None, report_adapter="pytest-junitxml",
    )
    save_state(str(tmp_path), state)
    ok, detail = test_execution.validate_prepared_tasks(str(tmp_path), state)
    attempt = test_execution.run_prepared_tasks(str(tmp_path), state, parallelism=1)[0]
    record = load_state(str(tmp_path)).stages["qa"].test_tasks[TOPIC]["TC-01"].current_record

    assert task.test_entries == [WRITE_ENTRY]
    assert ok, detail
    assert attempt.status == "passed"
    assert record is not None
    assert list(record.matched_test_entries) == [WRITE_ENTRY]
    assert record.executed_count == 1
