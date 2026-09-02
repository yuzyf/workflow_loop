"""计划路径非法时门禁一次说清而不是抛异常（AC-01..AC-04）。

覆盖：计划路径问题进问题清单、与其它问题一次列全、判定口径不变、
现有捕获该失败的调用方行为不变。
"""

import json
from pathlib import Path

from workflow_loop import diagnostics as diagnostics_mod
from workflow_loop import project as project_mod
from workflow_loop import records as records_mod
from workflow_loop import rollback as rollback_mod
from workflow_loop import state as state_mod
from workflow_loop import verification as verification_mod


WORKFLOW_ID = "2026-09-02-1012-bugfix"
TOPIC = "样例主题"
PROCESS_DOC = ".workflow_loop/Standardized_Repository/qa/test_plan.md"
REAL_CODE = "src/workflow_loop/cli.py"


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _project(tmp_path: Path, *, plan_file: str, recorded_file: str = REAL_CODE) -> Path:
    root = tmp_path / "proj"
    root.mkdir()
    project_mod.create_project(str(root))
    state_mod.save_state(str(root), state_mod.WorkflowState(
        workflow_id=WORKFLOW_ID, intent="bugfix", run_status="active", current_stage="impl",
        topics=[TOPIC], stage_path=["impl"],
        stages={"impl": state_mod.StageState(status="in_progress")},
        table_format_version="2",
    ))
    records_mod.create_or_complete_table(str(root), WORKFLOW_ID, "impl_record", TOPIC)
    relative = records_mod.table_relative_path(str(root), WORKFLOW_ID, "impl_record", TOPIC)
    full = root / relative
    table = json.loads(full.read_text(encoding="utf-8"))
    table["实施依据"] = [{
        "依据类型": "验收条件", "依据编号": "JU-01",
        "具体内容": "门禁失败必须一次列出全部可以独立确认的问题。",
        "文档位置": "acceptance/索引.md",
    }]
    table["代码修改计划"] = [{
        "顺序": "1", "文件": plan_file, "类、函数或配置项": "整份文件",
        "当前逻辑": "计划路径解析失败时只抛异常，丢掉定位字段。",
        "计划修改内容": "改为携带完整诊断，让门禁一次列全问题。",
        "数据、状态或输出变化": "问题清单里出现带位置和改法的条目。",
        "对应验收条件": "AC-01", "前置步骤": "无",
    }]
    table["开发检查计划"] = [{
        "检查命令或方法": ".venv/bin/python -m pytest tests/test_gate_plan_path_diagnostics.py",
        "检查范围": "本主题四条验收条件对应测试",
        "预期观察结果": "全部用例通过，没有跳过项，也没有失败计数",
    }]
    table["实施动作记录"] = [{
        "实施顺序": "1", "对应计划步骤": "1", "文件": REAL_CODE,
        "代码位置（最终文件）": "L1-L2", "实际执行的动作": "把计划路径诊断并入实施门禁报告。",
        "当步反馈": "问题清单里出现该条目且字段齐全。", "状态": "已完成",
    }]
    table["实际代码修改"] = [{
        "文件": recorded_file, "代码位置（最终文件）": "L1-L2",
        "实际修改的代码逻辑": "把计划路径诊断并入实施门禁的结构化报告。",
        "数据、状态或输出的实际变化": "第二道门一次报出计划路径问题和实际改动问题。",
        "修改理由": "门禁必须一次列出全部可以独立确认的问题。",
        "对应验收条件": "AC-01", "测试证据": "tests/test_gate_plan_path_diagnostics.py",
    }]
    table["开发检查记录"] = [{
        "检查命令或方法": ".venv/bin/python -m pytest tests/test_gate_plan_path_diagnostics.py",
        "检查范围": "本主题四条验收条件对应测试",
        "实际反馈": "本文件全部用例通过，没有跳过项。", "是否需要继续修改": "否",
    }]
    table["预期产品结果"] = ["计划路径写错时门禁在一次输出里给出位置和改法。"]
    table["未决问题"] = ["暂无"]
    _write(full, json.dumps(table, ensure_ascii=False, indent=2))
    return root


# ─── AC-01：计划路径问题进问题清单 ───


def test_planned_path_problem_carries_full_diagnostic(tmp_path):
    """Workflow-Test
    主题：计划路径非法时门禁一次说清而不是抛异常
    测试项：TC-01 计划路径问题带完整诊断
    验收条件：AC-01 计划路径问题进问题清单
    测试方式：自动化测试
    测试层级：模块测试
    产品入口：workflow gate impl 第二道门
    测试入口：tests/test_gate_plan_path_diagnostics.py::test_planned_path_problem_carries_full_diagnostic
    代码入口：src/workflow_loop/rollback.py::planned_code_paths
    准备数据：隔离项目的实施记录表把工作流过程文档路径填在代码修改计划的文件列
    执行动作：取本主题的计划路径集合
    关键断言：失败以携带诊断的专用异常给出，每条诊断的位置、预期、实际、证据、影响和下一动作齐全
    预期证据：pytest 结构化 junit 报告 1 条通过且退出码 0
    """
    root = _project(tmp_path, plan_file=PROCESS_DOC)

    try:
        rollback_mod.planned_code_paths(str(root), [TOPIC])
    except rollback_mod.PlannedPathError as error:
        carried = error.diagnostics
    else:
        raise AssertionError("非法计划路径必须被判为错误")

    assert len(carried) == 1
    item = carried[0]
    assert item.kind == "error"
    assert item.check_id == "impl.implementation_plan.path_invalid"
    assert "文件" in item.location and "impl_record" in item.location
    for field in (item.expected, item.actual, item.evidence, item.impact, item.next_action):
        assert field.strip()


def test_gate_report_lists_planned_path_problem(tmp_path):
    """Workflow-Test
    主题：计划路径非法时门禁一次说清而不是抛异常
    测试项：TC-02 第二道门报告含计划路径问题
    验收条件：AC-01 计划路径问题进问题清单
    测试方式：自动化测试
    测试层级：模块测试
    产品入口：workflow gate impl 第二道门
    测试入口：tests/test_gate_plan_path_diagnostics.py::test_gate_report_lists_planned_path_problem
    代码入口：src/workflow_loop/rollback.py::validate_actual_implementation_changes_report
    准备数据：隔离项目的实施记录表把工作流过程文档路径填在代码修改计划的文件列
    执行动作：生成实施门禁的结构化报告
    关键断言：报告里出现该条计划路径错误，渲染文本含位置和下一动作，且没有以异常形式中断
    预期证据：pytest 结构化 junit 报告 1 条通过且退出码 0
    """
    root = _project(tmp_path, plan_file=PROCESS_DOC)
    state = state_mod.load_state(str(root))

    report = rollback_mod.validate_actual_implementation_changes_report(str(root), state)

    ids = [item.check_id for item in report.diagnostics]
    assert "impl.implementation_plan.path_invalid" in ids
    rendered = report.render()
    assert "“文件”列" in rendered
    assert "下一动作" in rendered


def test_command_layer_renders_carried_diagnostics(tmp_path):
    """Workflow-Test
    主题：计划路径非法时门禁一次说清而不是抛异常
    测试项：TC-03 兜底处理按诊断渲染
    验收条件：AC-01 计划路径问题进问题清单
    测试方式：自动化测试
    测试层级：单元测试
    产品入口：workflow 命令的未预期失败兜底输出
    测试入口：tests/test_gate_plan_path_diagnostics.py::test_command_layer_renders_carried_diagnostics
    代码入口：src/workflow_loop/rollback.py::PlannedPathError
    准备数据：构造一条带七个字段的诊断并放进专用异常
    执行动作：按命令层的做法取出异常携带的诊断并渲染
    关键断言：渲染结果逐项包含位置、预期、实际、证据、影响和下一动作
    预期证据：pytest 结构化 junit 报告 1 条通过且退出码 0
    """
    diagnostic = diagnostics_mod.Diagnostic(
        kind="error", check_id="impl.implementation_plan.path_invalid",
        location="表文件:1，“文件”列", expected="项目内相对路径",
        actual="填的是工作流过程文档", evidence="该路径位于流程目录下",
        impact="计划范围不完整", next_action="改成实际修改文件的项目内相对路径",
    )
    error = rollback_mod.PlannedPathError([diagnostic])

    carried = getattr(error, "diagnostics", None)
    assert carried
    rendered = diagnostics_mod.ValidationReport(
        stage="impl", gate="命令执行中断", diagnostics=list(carried)
    ).render()

    for text in ("表文件:1", "项目内相对路径", "工作流过程文档", "流程目录", "改成实际修改文件"):
        assert text in rendered


# ─── AC-02：与其它问题一次列全 ───


def test_planned_and_actual_problems_reported_together(tmp_path):
    """Workflow-Test
    主题：计划路径非法时门禁一次说清而不是抛异常
    测试项：TC-04 两类问题一次列全
    验收条件：AC-02 与其它问题一次列全
    测试方式：自动化测试
    测试层级：模块测试
    产品入口：workflow gate impl 第二道门
    测试入口：tests/test_gate_plan_path_diagnostics.py::test_planned_and_actual_problems_reported_together
    代码入口：src/workflow_loop/rollback.py::validate_actual_implementation_changes_report
    准备数据：同一份实施记录表里计划行和实际改动行各填一个工作流过程文档路径
    执行动作：生成一次实施门禁的结构化报告
    关键断言：同一次报告里同时出现计划一侧和实际改动一侧的路径问题
    预期证据：pytest 结构化 junit 报告 1 条通过且退出码 0
    """
    root = _project(tmp_path, plan_file=PROCESS_DOC, recorded_file=PROCESS_DOC)
    state = state_mod.load_state(str(root))

    report = rollback_mod.validate_actual_implementation_changes_report(str(root), state)

    ids = {item.check_id for item in report.diagnostics}
    assert "impl.implementation_plan.path_invalid" in ids
    assert "impl.implementation_record.path_invalid" in ids


# ─── AC-03：判定本身不变 ───


def test_legal_plan_path_still_returns_without_diagnostic(tmp_path):
    """Workflow-Test
    主题：计划路径非法时门禁一次说清而不是抛异常
    测试项：TC-05 合法计划路径仍正常返回
    验收条件：AC-03 判定本身不变
    测试方式：自动化测试
    测试层级：模块测试
    产品入口：workflow gate impl 第二道门
    测试入口：tests/test_gate_plan_path_diagnostics.py::test_legal_plan_path_still_returns_without_diagnostic
    代码入口：src/workflow_loop/rollback.py::planned_code_paths
    准备数据：隔离项目的实施记录表把项目内真实源码路径填在代码修改计划的文件列
    执行动作：取本主题的计划路径集合，并生成一次实施门禁报告
    关键断言：正常返回该路径，报告里没有计划路径类错误
    预期证据：pytest 结构化 junit 报告 1 条通过且退出码 0
    """
    root = _project(tmp_path, plan_file=REAL_CODE)
    state = state_mod.load_state(str(root))

    assert rollback_mod.planned_code_paths(str(root), [TOPIC]) == [REAL_CODE]

    report = rollback_mod.validate_actual_implementation_changes_report(str(root), state)
    assert "impl.implementation_plan.path_invalid" not in {
        item.check_id for item in report.diagnostics
    }


def test_illegal_plan_path_is_still_rejected(tmp_path):
    """Workflow-Test
    主题：计划路径非法时门禁一次说清而不是抛异常
    测试项：TC-06 非法计划路径仍被拦下
    验收条件：AC-03 判定本身不变
    测试方式：自动化测试
    测试层级：模块测试
    产品入口：workflow gate impl 第二道门
    测试入口：tests/test_gate_plan_path_diagnostics.py::test_illegal_plan_path_is_still_rejected
    代码入口：src/workflow_loop/rollback.py::planned_code_paths
    准备数据：隔离项目的实施记录表把工作流过程文档路径填在代码修改计划的文件列
    执行动作：取本主题的计划路径集合
    关键断言：仍被判为错误，且失败类型仍可被原有的通用异常捕获方式接住
    预期证据：pytest 结构化 junit 报告 1 条通过且退出码 0
    """
    root = _project(tmp_path, plan_file=PROCESS_DOC)

    try:
        rollback_mod.planned_code_paths(str(root), [TOPIC])
    except ValueError as error:
        assert isinstance(error, rollback_mod.PlannedPathError)
        assert PROCESS_DOC in str(error)
    else:
        raise AssertionError("非法计划路径必须继续被判为错误")


# ─── AC-04：现有调用方行为不变 ───


def test_existing_callers_keep_swallowing_the_failure(tmp_path):
    """Workflow-Test
    主题：计划路径非法时门禁一次说清而不是抛异常
    测试项：TC-07 现有捕获方行为不变
    验收条件：AC-04 现有调用方行为不变
    测试方式：自动化测试
    测试层级：模块测试
    产品入口：workflow gate impl 第二道门读取阶段责任文件
    测试入口：tests/test_gate_plan_path_diagnostics.py::test_existing_callers_keep_swallowing_the_failure
    代码入口：src/workflow_loop/verification.py::stage_responsibility_paths
    准备数据：隔离项目的计划路径非法且实施记录文档已经生成
    执行动作：调用阶段责任文件清单和既有实现路径校验两处入口
    关键断言：两处都不把异常抛给调用方，也不返回全项目扫描结果
    预期证据：pytest 结构化 junit 报告 1 条通过且退出码 0
    """
    root = _project(tmp_path, plan_file=PROCESS_DOC)
    state = state_mod.load_state(str(root))
    _write(root / f"impl/{TOPIC}_实施记录.md", f"# 【实施】{TOPIC}\n")

    paths = verification_mod.stage_responsibility_paths(str(root), state, "impl")
    assert isinstance(paths, list)
    assert PROCESS_DOC not in paths

    ok, detail = rollback_mod.validate_existing_implementation_paths(str(root), state)
    assert isinstance(ok, bool)
    assert isinstance(detail, str)
