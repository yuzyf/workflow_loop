"""混合主题测试结果文档的生成到校验正向闭环测试。

背景：两个缺陷（汇总被人工项拖成"未完成"、第 3 节口径不一致）的共同根因
是生成器与校验器对"人工验收项怎么表达"各写各的判断。本文件建立正向闭环：
生成器产出的文档喂给校验器必须通过；负向用例证明校验器仍拒绝错误文档。
"""

import json
import sys
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from workflow_loop import artifact_validation as av
from workflow_loop import records as records_mod
from workflow_loop import state as state_mod
from workflow_loop import test_mapping as test_mapping_mod

TOPIC = "混合主题闭环测试"


def _write_state(root: Path, workflow_id: str) -> None:
    state = {
        "workflow_id": workflow_id,
        "intent": "bugfix",
        "current_stage": "qa",
        "topics": [TOPIC],
        "stages": {},
    }
    wf_dir = root / ".workflow_loop"
    wf_dir.mkdir(parents=True, exist_ok=True)
    (wf_dir / "state.json").write_text(
        json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def _write_plan_table(root: Path, workflow_id: str, rows: list[dict]) -> None:
    rec_dir = root / ".workflow_loop" / "records" / workflow_id
    rec_dir.mkdir(parents=True, exist_ok=True)
    plan = {
        "表版本": "4",
        "工作流编号": workflow_id,
        "验收主题": TOPIC,
        "测试项": rows,
        "填写说明": {},
    }
    (rec_dir / f"test_plan_{TOPIC}.json").write_text(
        json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def _build_task() -> object:
    """构造一个满足严格成功判定的登记任务与当前机器记录。"""

    record = state_mod.TestExecutionRecord(
        record_id=None,
        command=["python", "-m", "pytest", "-q"],
        cwd="",
        exit_code=0,
        status="passed",
        started_at="2026-09-10T00:00:00+00:00",
        finished_at="2026-09-10T00:00:01+00:00",
        duration_seconds=1.0,
        executed_count=1,
        skipped_count=0,
        failed_count=0,
        error_count=0,
        test_entries=["tests/test_x.py::test_a"],
        matched_test_entries=["tests/test_x.py::test_a"],
        code_snapshot_hash="a" * 64,
        test_code_hash="b" * 64,
        timeout_seconds=600,
        output_tail="ok",
        output_sha256="c" * 64,
        output_bytes=100,
        platform="darwin",
        executable="/usr/bin/python3",
        report_adapter="pytest-junitxml",
        report_hash="d" * 64,
        report_size=200,
    )
    record.record_id = state_mod.compute_test_execution_record_id(
        record, TOPIC, "TC-01"
    )
    task = type("T", (), {})()
    task.status = "passed"
    task.current_record = record
    task.command = ["python", "-m", "pytest", "-q"]
    task.test_entries = ["tests/test_x.py::test_a"]
    task.cwd = ""
    task.timeout_seconds = 600
    task.report_adapter = "pytest-junitxml"
    task.report_path = ".workflow_loop/test_reports/fake.xml"
    return task


def _mixed_result_table() -> dict:
    return {
        "工作流编号": "wf-mixed",
        "验收主题": TOPIC,
        "测试结果": [
            {
                "测试项编号": "TC-01",
                "执行结论": "passed",
                "机器记录编号": "RUN-x1",
                "实际结果说明": "自动化项通过",
            },
            {
                "测试项编号": "TC-02",
                "执行结论": "",
                "机器记录编号": "",
                "实际结果说明": "人工验收项",
            },
        ],
        "结果说明": [],
        "执行说明": [],
        "人工验收交接": ["人工项对象与检查方法"],
        "未通过或阻塞": [],
    }


def _mixed_plan_rows() -> list[dict]:
    return [
        {
            "测试项编号": "TC-01",
            "测试方式": "自动化测试",
            "直白测试名称": "自动一",
            "对应验收条件": "AC-01",
            "测试入口": "tests/test_x.py::test_a",
        },
        {
            "测试项编号": "TC-02",
            "测试方式": "人工验收",
            "直白测试名称": "人工一",
            "对应验收条件": "AC-02",
            "测试入口": "",
        },
    ]


def test_mixed_topic_generator_to_validator_closed_loop(tmp_path: Path) -> None:
    """AC-01/AC-02/AC-04：混合主题生成器产出喂校验器，正向闭环通过。

Workflow-Test
主题：混合主题测试结果文档正确生成并通过门禁
测试项：TC-01 混合主题生成到校验正向闭环
验收条件：AC-01 混合主题汇总结果正确
测试方式：自动化测试
测试层级：单元测试
产品入口：workflow gate qa 的测试结果生成与校验
测试入口：tests/test_mixed_topic_test_result.py::test_mixed_topic_generator_to_validator_closed_loop
代码入口：src/workflow_loop/records.py::_generate_test_result_document_v2
准备数据：临时项目内构造混合主题：state.json、测试计划表（1 自动化项 TC-01 加 1 人工项 TC-02）、测试结果表、登记任务与完整机器记录
执行动作：生成器生成测试结果文档后由真实校验器校验第 3 节覆盖与汇总字段
关键断言：自动化测试结果为通过、人工验收状态为待主题验收、人工项小节含测试方式人工验收且不含未执行、校验器判定通过
预期证据：pytest junitxml 报告与退出码 0
    """
    workflow_id = "wf-mixed"
    _write_state(tmp_path, workflow_id)
    _write_plan_table(tmp_path, workflow_id, _mixed_plan_rows())
    task = _build_task()

    doc = records_mod._generate_test_result_document_v2(
        TOPIC,
        _mixed_result_table(),
        {"TC-01": task},
        {"测试项": _mixed_plan_rows()},
        str(tmp_path),
    )
    # AC-01：汇总只算自动化项，人工项不拖"未完成"
    assert "- 自动化测试结果：通过" in doc
    assert "- 人工验收状态：待主题验收" in doc
    # AC-02：人工项小节标注人工验收，不写"未执行"
    tc02 = doc.split("### TC-02")[1].split("### ")[0] if "### TC-02" in doc else ""
    assert "测试方式：人工验收" in tc02
    assert "自动化测试结果：未执行" not in tc02

    qa_dir = tmp_path / "qa"
    qa_dir.mkdir(exist_ok=True)
    (qa_dir / f"{TOPIC}_测试结果.md").write_text(doc, encoding="utf-8")

    items = test_mapping_mod.parse_test_plan_items(str(tmp_path), TOPIC)
    auto_items = [i for i in items if i.requires_test_code]
    assert [i.test_id for i in auto_items] == ["TC-01"]
    ok, detail = av._validate_topic_test_execution_result(
        str(tmp_path), workflow_id, TOPIC, auto_items, {"TC-01": task}
    )
    assert ok, detail


def test_pure_automated_topic_unchanged(tmp_path: Path) -> None:
    """AC-03：纯自动化主题字段与小节构成不受修复影响。

Workflow-Test
主题：混合主题测试结果文档正确生成并通过门禁
测试项：TC-02 纯自动化主题输出不变
验收条件：AC-03 纯自动化主题不受影响
测试方式：自动化测试
测试层级：单元测试
产品入口：workflow gate qa 的测试结果生成
测试入口：tests/test_mixed_topic_test_result.py::test_pure_automated_topic_unchanged
代码入口：src/workflow_loop/records.py::_generate_test_result_document_v2
准备数据：临时项目内构造纯自动化主题：测试计划表只含 1 个自动化项，无人工项
执行动作：生成器生成纯自动化主题的测试结果文档
关键断言：自动化测试结果为通过、人工验收状态为无需人工验收、第 3 节只有 TC-01 小节且无 TC-02 小节
预期证据：pytest junitxml 报告与退出码 0
    """
    workflow_id = "wf-pure"
    _write_state(tmp_path, workflow_id)
    rows = [
        {
            "测试项编号": "TC-01",
            "测试方式": "自动化测试",
            "直白测试名称": "自动一",
            "对应验收条件": "AC-01",
            "测试入口": "tests/test_x.py::test_a",
        }
    ]
    _write_plan_table(tmp_path, workflow_id, rows)
    task = _build_task()
    table = {
        "工作流编号": workflow_id,
        "验收主题": TOPIC,
        "测试结果": [
            {
                "测试项编号": "TC-01",
                "执行结论": "passed",
                "机器记录编号": "RUN-x1",
                "实际结果说明": "自动化项通过",
            }
        ],
        "结果说明": [],
        "执行说明": [],
        "人工验收交接": [],
        "未通过或阻塞": [],
    }
    doc = records_mod._generate_test_result_document_v2(
        TOPIC, table, {"TC-01": task}, {"测试项": rows}, str(tmp_path)
    )
    assert "- 自动化测试结果：通过" in doc
    assert "- 人工验收状态：无需人工验收" in doc
    assert "### TC-01：" in doc
    assert "### TC-02" not in doc


def test_validator_still_rejects_missing_automated_section(tmp_path: Path) -> None:
    """AC-04 负向：校验器仍拒绝自动化项覆盖缺失的文档。

Workflow-Test
主题：混合主题测试结果文档正确生成并通过门禁
测试项：TC-03 负向用例校验器仍拒绝缺自动化项文档
验收条件：AC-04 生成到校验正向闭环
测试方式：自动化测试
测试层级：单元测试
产品入口：workflow gate qa 的测试结果校验
测试入口：tests/test_mixed_topic_test_result.py::test_validator_still_rejects_missing_automated_section
代码入口：src/workflow_loop/artifact_validation.py::_validate_topic_test_execution_result
准备数据：临时项目内构造混合主题计划，但文档第 3 节删掉自动化项 TC-01 的小节
执行动作：真实校验器校验被破坏的文档
关键断言：校验器报"必须正好覆盖"并不通过
预期证据：pytest junitxml 报告与退出码 0
    """
    workflow_id = "wf-neg"
    _write_state(tmp_path, workflow_id)
    _write_plan_table(tmp_path, workflow_id, _mixed_plan_rows())
    task = _build_task()

    doc = records_mod._generate_test_result_document_v2(
        TOPIC,
        _mixed_result_table(),
        {"TC-01": task},
        {"测试项": _mixed_plan_rows()},
        str(tmp_path),
    )
    # 破坏：删除自动化项 TC-01 的第 3 节小节（保留人工项 TC-02 小节）
    lines = doc.splitlines(keepends=True)
    out = []
    skipping = False
    for line in lines:
        if line.startswith("### TC-01："):
            skipping = True
            continue
        if skipping and line.startswith("### "):
            skipping = False
        if not skipping:
            out.append(line)
    broken = "".join(out)

    qa_dir = tmp_path / "qa"
    qa_dir.mkdir(exist_ok=True)
    (qa_dir / f"{TOPIC}_测试结果.md").write_text(broken, encoding="utf-8")

    items = test_mapping_mod.parse_test_plan_items(str(tmp_path), TOPIC)
    auto_items = [i for i in items if i.requires_test_code]
    ok, detail = av._validate_topic_test_execution_result(
        str(tmp_path), workflow_id, TOPIC, auto_items, {"TC-01": task}
    )
    assert not ok
    assert "必须正好覆盖" in detail

def test_mixed_topic_section3_manual_item_presentation(tmp_path: Path) -> None:
    """AC-02：第 3 节人工项小节呈现与校验器口径一致。

Workflow-Test
主题：混合主题测试结果文档正确生成并通过门禁
测试项：TC-05 第三节人工项小节口径一致
验收条件：AC-02 第三节口径两端一致
测试方式：自动化测试
测试层级：单元测试
产品入口：workflow gate qa 的测试结果生成与校验
测试入口：tests/test_mixed_topic_test_result.py::test_mixed_topic_section3_manual_item_presentation
代码入口：src/workflow_loop/records.py::_generate_test_result_document_v2
准备数据：临时项目内构造混合主题：state.json、测试计划表（1 自动化项 TC-01 加 1 人工项 TC-02）、测试结果表、登记任务与完整机器记录
执行动作：生成器生成测试结果文档后检查第 3 节小节构成与校验器第 3 节覆盖检查的口径
关键断言：第 3 节自动化项每个一节且带机器事实、人工项小节标注测试方式人工验收并指向第 4 节且不出现自动化测试结果未执行、门禁不报必须正好覆盖
预期证据：pytest junitxml 报告与退出码 0
    """
    workflow_id = "wf-mixed"
    _write_state(tmp_path, workflow_id)
    _write_plan_table(tmp_path, workflow_id, _mixed_plan_rows())
    task = _build_task()

    doc = records_mod._generate_test_result_document_v2(
        TOPIC,
        _mixed_result_table(),
        {"TC-01": task},
        {"测试项": _mixed_plan_rows()},
        str(tmp_path),
    )
    # 第 3 节边界
    section3 = doc.split("## 3. 测试项结果")[1].split("## 4.")[0]
    # 自动化项小节带机器事实
    tc01 = section3.split("### TC-01")[1].split("### TC-02")[0]
    assert "机器记录编号" in tc01
    assert "- 自动化测试结果：通过" in tc01
    # 人工项小节：标注人工验收、指向第 4 节、不写未执行
    tc02 = section3.split("### TC-02")[1]
    assert "测试方式：人工验收" in tc02
    assert "自动化测试结果：未执行" not in tc02
    assert "第 4 节人工验收交接" in tc02
    # 校验器口径：自动化小节正好覆盖自动化项，人工小节合法
    items = test_mapping_mod.parse_test_plan_items(str(tmp_path), TOPIC)
    auto_items = [i for i in items if i.requires_test_code]
    qa_dir = tmp_path / "qa"
    qa_dir.mkdir(exist_ok=True)
    (qa_dir / f"{TOPIC}_测试结果.md").write_text(doc, encoding="utf-8")
    ok, detail = av._validate_topic_test_execution_result(
        str(tmp_path), workflow_id, TOPIC, auto_items, {"TC-01": task}
    )
    assert ok, detail
    assert "必须正好覆盖" not in detail
