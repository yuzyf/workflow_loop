"""测试结果表三列机器采集与代码符号索引测试。

主题一：三列回填（更新已有行、追加缺失行、叙述保留、无任务降级、重跑刷新）。
主题二：符号索引（解析、相近建议、引用核对、非 Python 与不存在文件、文字提取）。
"""
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import pytest

from workflow_loop import code_symbols
from workflow_loop import machine_collect


# ══ 主题一：test_result_columns 与 _fill_machine_record_ids ══


class _Record:
    def __init__(self, record_id):
        self.record_id = record_id


class _Task:
    def __init__(self, status, record_id):
        self.status = status
        self.current_record = _Record(record_id) if record_id else None


class _StageState:
    def __init__(self, tasks):
        self.test_tasks = tasks


TOPIC = "主题甲"


class _State:
    def __init__(self, tasks, current_stage="qa"):
        self.workflow_id = "wf-1"
        self.current_stage = current_stage
        by_topic = {TOPIC: tasks}
        self.stages = {
            "qa": _StageState(by_topic),
            "test_execution": _StageState(by_topic),
        }


def test_result_columns_values():
    tasks = {
        "TC-02": _Task("passed", "RUN-2"),
        "TC-01": _Task("passed", "RUN-1"),
        "TC-03": _Task("pending", None),
    }
    rows = machine_collect.test_result_columns(".", _State(tasks), "主题甲")
    assert rows == [
        {"测试项编号": "TC-01", "执行结论": "passed", "机器记录编号": "RUN-1"},
        {"测试项编号": "TC-02", "执行结论": "passed", "机器记录编号": "RUN-2"},
        {"测试项编号": "TC-03", "执行结论": "pending", "机器记录编号": ""},
    ]


def test_fill_machine_record_ids_updates_and_appends(tmp_path):
    from workflow_loop import records as records_mod

    table = {
        "测试结果": [
            {
                "测试项编号": "TC-01",
                "执行结论": "passed",
                "机器记录编号": "RUN-OLD",
                "实际结果说明": "AI 填写的叙述保留",
            }
        ]
    }
    tasks = {
        "TC-01": _Task("passed", "RUN-NEW"),
        "TC-02": _Task("passed", "RUN-2"),
    }
    problems = records_mod._fill_machine_record_ids(
        str(tmp_path), _State(tasks), "主题甲", table
    )
    rows = table["测试结果"]
    assert len(rows) == 2
    assert rows[0]["机器记录编号"] == "RUN-NEW"
    assert rows[0]["执行结论"] == "passed"
    assert rows[0]["实际结果说明"] == "AI 填写的叙述保留"
    assert rows[1]["测试项编号"] == "TC-02"
    assert rows[1]["机器记录编号"] == "RUN-2"
    assert not problems  # 全部有当前记录


def test_fill_machine_record_ids_pending_reports(tmp_path):
    from workflow_loop import records as records_mod

    table = {"测试结果": []}
    tasks = {"TC-01": _Task("pending", None)}
    problems = records_mod._fill_machine_record_ids(
        str(tmp_path), _State(tasks), "主题甲", table
    )
    # 无当前记录：行仍写入（结论 pending），并提示待执行
    assert table["测试结果"][0]["执行结论"] == "pending"
    assert table["测试结果"][0]["机器记录编号"] == ""
    assert len(problems) == 1
    assert "还没有当前成功机器记录" in problems[0][1]


def test_fill_machine_record_ids_no_tasks_safe(tmp_path):
    from workflow_loop import records as records_mod

    table = {"测试结果": []}
    problems = records_mod._fill_machine_record_ids(
        str(tmp_path), _State({}), "主题甲", table
    )
    assert table["测试结果"] == []
    assert problems == []  # 无任务安全降级，空表守卫另行报未填


def test_fill_machine_record_ids_idempotent(tmp_path):
    from workflow_loop import records as records_mod

    table = {"测试结果": []}
    tasks = {"TC-01": _Task("passed", "RUN-1")}
    state = _State(tasks)
    records_mod._fill_machine_record_ids(str(tmp_path), state, "主题甲", table)
    first = json.dumps(table, ensure_ascii=False)
    records_mod._fill_machine_record_ids(str(tmp_path), state, "主题甲", table)
    second = json.dumps(table, ensure_ascii=False)
    assert first == second  # 重复执行幂等，不重复追加


# ══ 主题二：code_symbols ══


def _write_source(tmp_path, relative, content):
    full = tmp_path / relative
    full.parent.mkdir(parents=True, exist_ok=True)
    full.write_text(content, encoding="utf-8")


def test_symbol_index_parses_functions_classes_methods(tmp_path):
    _write_source(
        tmp_path,
        "src/pkg/mod.py",
        "def top_func():\n    pass\n\n\nclass Widget:\n"
        "    def method_a(self):\n        pass\n\n"
        "    async def method_b(self):\n        pass\n",
    )
    index, failures = code_symbols.build_symbol_index(str(tmp_path))
    assert failures == []
    symbols = index["src/pkg/mod.py"]
    assert {"top_func", "Widget", "Widget.method_a", "Widget.method_b"} <= symbols


def test_symbol_index_skips_broken_file(tmp_path):
    _write_source(tmp_path, "src/pkg/good.py", "def fine():\n    pass\n")
    _write_source(tmp_path, "src/pkg/broken.py", "def broken(:\n")
    index, failures = code_symbols.build_symbol_index(str(tmp_path))
    assert "src/pkg/broken.py" in failures
    assert "fine" in index["src/pkg/good.py"]
    assert "src/pkg/broken.py" not in index


def test_check_reference_branches(tmp_path):
    _write_source(
        tmp_path,
        "src/pkg/mod.py",
        "def collect_diff_facts():\n    pass\n\nclass Machine:\n    def run(self):\n        pass\n",
    )
    _write_source(tmp_path, "scripts/run.sh", "echo hi\n")
    index, _ = code_symbols.build_symbol_index(str(tmp_path))
    ok, _ = code_symbols.check_reference(
        str(tmp_path), index, "src/pkg/mod.py", "collect_diff_facts"
    )
    assert ok
    ok, _ = code_symbols.check_reference(
        str(tmp_path), index, "src/pkg/mod.py", "Machine.run"
    )
    assert ok
    # 错误符号给相近建议
    ok, detail = code_symbols.check_reference(
        str(tmp_path), index, "src/pkg/mod.py", "collect_diff"
    )
    assert not ok and "collect_diff_facts" in detail
    # 非 Python 只查存在
    ok, detail = code_symbols.check_reference(
        str(tmp_path), index, "scripts/run.sh", "anything"
    )
    assert ok and "存在性核对" in detail
    # 不存在文件
    ok, detail = code_symbols.check_reference(
        str(tmp_path), index, "src/pkg/nope.py", "f"
    )
    assert not ok and "文件不存在" in detail


def test_extract_references_from_text():
    text = (
        "依据 `src/workflow_loop/cli.py::cmd_collect` 和 "
        "src/workflow_loop/records.py::sync_stage_tables 与 "
        "`tests/test_x.py::test_y`（tests/test_dup.py::test_y 重复一次）；"
        "scripts/a.sh::not_python 不计入"
    )
    refs = code_symbols.extract_file_symbol_references(text)
    assert ("src/workflow_loop/cli.py", "cmd_collect") in refs
    assert ("src/workflow_loop/records.py", "sync_stage_tables") in refs
    assert ("tests/test_x.py", "test_y") in refs
    assert ("tests/test_dup.py", "test_y") in refs  # 不同文件是独立引用
    assert len(refs) == 4  # scripts/ 不计入


def test_check_architecture_change_references_integration(tmp_path):
    from workflow_loop import records as records_mod

    _write_source(
        tmp_path, "src/pkg/mod.py", "def real_func():\n    pass\n"
    )
    table = {
        "正文变更": [
            {
                "章节": "4.6 实施、测试与验收层",
                "原文": "旧事实",
                "新文": "新事实见 `src/pkg/mod.py::real_func`",
                "依据": "src/pkg/mod.py::real_func 与 src/pkg/missing.py::gone",
            }
        ]
    }
    problems = records_mod._check_architecture_change_references(str(tmp_path), table)
    # real_func 通过（新文与依据各提取一次但去重）；missing.py 报文件不存在
    assert len(problems) == 1
    assert "src/pkg/missing.py" in problems[0][1]
    assert "正文变更第 1 行" in problems[0][1]
