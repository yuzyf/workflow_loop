"""退回重走时门禁稳定性的回归测试（AC-01..AC-12）。

覆盖：第二道门先生成后检查、退回回补引用、表模式不要求文档变化、缺陷索引按内容
判定、缺陷文件标识前后一致、缺陷记录锚点与手改保护、表模式不退回文档模式、门禁
日志带轮次编号、安装契约与仓库一致、穿刺资产随仓库保存、包内规范与项目副本一致、
占位判定不误伤且报错定位。
"""

import filecmp
import json
import os
import re
import subprocess
from pathlib import Path

from workflow_loop import artifact_paths as artifact_paths_mod
from workflow_loop import artifact_validation as av_mod
from workflow_loop import bug_record as bug_record_mod
from workflow_loop import installer as installer_mod
from workflow_loop import markdown_links as ml_mod
from workflow_loop import project as project_mod
from workflow_loop import records as records_mod
from workflow_loop import state as state_mod


REPO_ROOT = Path(__file__).resolve().parents[1]
WORKFLOW_ID = "2026-09-02-0752-bugfix"
TOPIC = "样例主题甲"


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _project(tmp_path: Path) -> Path:
    root = tmp_path / "proj"
    root.mkdir()
    project_mod.create_project(str(root))
    return root


def _state(root: Path, stage: str, topics=(TOPIC,), *, frozen: str = "2"):
    names = ["reproduce", "acceptance_plan", "impl", "qa", "topic_acceptance"]
    state = state_mod.WorkflowState(
        workflow_id=WORKFLOW_ID,
        intent="bugfix",
        run_status="active",
        current_stage=stage,
        topics=list(topics),
        stage_path=names,
        stages={
            name: state_mod.StageState(status="in_progress" if name == stage else "pending")
            for name in names
        },
        table_format_version=frozen,
    )
    state_mod.save_state(str(root), state)
    return state


def _fill_impl_table(root: Path, topic: str = TOPIC) -> None:
    records_mod.create_or_complete_table(str(root), WORKFLOW_ID, "impl_record", topic)
    relative = records_mod.table_relative_path(str(root), WORKFLOW_ID, "impl_record", topic)
    full = root / relative
    table = json.loads(full.read_text(encoding="utf-8"))
    table["实施依据"] = [{
        "依据类型": "验收条件", "依据编号": "JU-01",
        "具体内容": "第二道门在同一状态下重复执行必须返回同一份问题清单。",
        "文档位置": "acceptance/索引.md",
    }]
    table["代码修改计划"] = [{
        "顺序": "1", "文件": "src/workflow_loop/cli.py", "类、函数或配置项": "validate_stage_output",
        "当前逻辑": "先执行链接检查，再在阶段校验内部按表生成正式文档。",
        "计划修改内容": "把按表生成提前到链接检查之前执行。",
        "数据、状态或输出变化": "同一输入连续两次执行返回相同的报告哈希。",
        "对应验收条件": "AC-01", "前置步骤": "无",
    }]
    table["开发检查计划"] = [{
        "检查命令或方法": ".venv/bin/python -m pytest tests/test_gate_rework_stability.py",
        "检查范围": "本轮新增的门禁稳定性测试",
        "预期观察结果": "全部用例通过且没有跳过项",
    }]
    table["实施动作记录"] = [{
        "实施顺序": "1", "对应计划步骤": "1", "文件": "src/workflow_loop/cli.py",
        "代码位置（最终文件）": "L2132-L2200", "实际执行的动作": "把按表生成提前到链接检查之前。",
        "当步反馈": "两次执行得到同一个报告哈希。", "状态": "已完成",
    }]
    table["实际代码修改"] = [{
        "文件": "src/workflow_loop/cli.py", "代码位置（最终文件）": "L2132-L2200",
        "实际修改的代码逻辑": "在链接检查之前按当前工作记录表生成正式文档。",
        "数据、状态或输出的实际变化": "同一状态重复执行第二道门不再翻转结论。",
        "修改理由": "满足同状态重复检查结论一致的产品规则。",
        "对应验收条件": "AC-01", "测试证据": "tests/test_gate_rework_stability.py",
    }]
    table["开发检查记录"] = [{
        "检查命令或方法": ".venv/bin/python -m pytest tests/test_gate_rework_stability.py",
        "检查范围": "本轮新增的门禁稳定性测试",
        "实际反馈": "本文件全部用例通过，没有跳过项。", "是否需要继续修改": "否",
    }]
    table["预期产品结果"] = ["退回重走时门禁只报与本次修改真实相关的问题。"]
    table["未决问题"] = ["暂无"]
    _write(full, json.dumps(table, ensure_ascii=False, indent=2))


def _bug_table(root: Path, topic: str = TOPIC) -> Path:
    records_mod.create_or_complete_table(str(root), WORKFLOW_ID, "bug_record", "")
    relative = records_mod.table_relative_path(str(root), WORKFLOW_ID, "bug_record", "")
    full = root / relative
    table = json.loads(full.read_text(encoding="utf-8"))
    table["验收主题"] = topic
    table["缺陷信息"] = [{
        "缺陷编号": "BUG-01",
        "现象": "退回后第二道门报出指向已删除文件的链接失败。",
        "复现步骤": "生成结果文档；执行退回删除它；再执行第二道门。",
        "实际结果": "问题清单里出现目标不是现有普通文件。",
        "期望结果": "退回同时把引用改回待生成，第二道门不报该失败。",
        "根因": "根因说明：删除结果文件的路径不调用回补引用。",
    }]
    table["缺陷说明"] = ["退回删除下游结果文件后，上游文档里由程序写入的链接没有同步回退。"]
    table["真实复现条件"] = ["运行环境：隔离临时项目；真实输入：本轮生成的结果文档与缺陷记录。"]
    table["根因证据"] = ["删除函数与回补函数分别位于两条互不调用的路径上。"]
    table["修复仍存在的不确定性"] = ["暂无"]
    table["修复与验收结果"] = ["本节由后续阶段按实际结果追加。"]
    _write(full, json.dumps(table, ensure_ascii=False, indent=2))
    return full


# ─── AC-01：第二道门先按表生成文档，再执行链接检查 ───


def test_second_gate_generates_documents_before_link_check(tmp_path):
    """Workflow-Test
    主题：退回重走后门禁不再无故反复失败
    测试项：TC-01 第二道门先生成后检查
    验收条件：AC-01 重复执行结论一致
    测试方式：自动化测试
    测试层级：模块测试
    产品入口：workflow gate 环节名 第二道门
    测试入口：tests/test_gate_rework_stability.py::test_second_gate_generates_documents_before_link_check
    代码入口：src/workflow_loop/cli.py::_sync_stage_tables_before_checks
    准备数据：隔离项目生成含真实下游链接的实施记录，再删除被链接的测试结果文档
    执行动作：先调用第二道门的按表生成入口，再执行受管链接检查
    关键断言：生成后文档改回待生成，链接检查一次通过，不需要第二次原样重跑
    预期证据：pytest 结构化 junit 报告 1 条通过且退出码 0
    """
    from workflow_loop import cli as cli_mod

    root = _project(tmp_path)
    state = _state(root, "impl")
    _fill_impl_table(root)
    file_key = artifact_paths_mod.resolve_key_for(project_mod.load_project(str(root)), "topic", TOPIC)
    result_rel = f"qa/{file_key}_测试结果.md"
    for rel in (result_rel, f"acceptance/{file_key}_验收计划.md", f"qa/{file_key}_测试计划.md",
                f"acceptance/{file_key}_验收结果.md", "需求交付追踪表.md"):
        _write(root / rel, f"# {rel}\n")
    records_mod.sync_stage_tables(str(root), state)
    impl_doc = root / f"impl/{file_key}_实施记录.md"
    assert f"](../{result_rel})" in impl_doc.read_text(encoding="utf-8")

    (root / result_rel).unlink()
    cli_mod._sync_stage_tables_before_checks(str(root), state, "impl")

    assert "（待生成）" in impl_doc.read_text(encoding="utf-8")
    passed, _detail = ml_mod.validate_managed_markdown_links(str(root))
    assert passed


# ─── AC-02：退回删除结果文件后回补引用 ───


def test_return_refreshes_references_to_removed_results(tmp_path):
    """Workflow-Test
    主题：退回重走后门禁不再无故反复失败
    测试项：TC-02 退回回补上游引用
    验收条件：AC-02 退回不留坏链接
    测试方式：自动化测试
    测试层级：模块测试
    产品入口：workflow return 退回命令
    测试入口：tests/test_gate_rework_stability.py::test_return_refreshes_references_to_removed_results
    代码入口：src/workflow_loop/records.py::refresh_references_after_removal
    准备数据：隔离项目生成引用测试结果的实施记录，随后删除该测试结果文档
    执行动作：调用删除后回补入口，再执行受管链接检查
    关键断言：实施记录改回待生成，链接检查不再报目标不是现有普通文件
    预期证据：pytest 结构化 junit 报告 1 条通过且退出码 0
    """
    root = _project(tmp_path)
    state = _state(root, "impl")
    _fill_impl_table(root)
    file_key = artifact_paths_mod.resolve_key_for(project_mod.load_project(str(root)), "topic", TOPIC)
    result_rel = f"qa/{file_key}_测试结果.md"
    for rel in (result_rel, f"acceptance/{file_key}_验收计划.md", f"qa/{file_key}_测试计划.md",
                f"acceptance/{file_key}_验收结果.md", "需求交付追踪表.md"):
        _write(root / rel, f"# {rel}\n")
    records_mod.sync_stage_tables(str(root), state)
    (root / result_rel).unlink()

    records_mod.refresh_references_after_removal(str(root), state, [TOPIC])

    impl_doc = (root / f"impl/{file_key}_实施记录.md").read_text(encoding="utf-8")
    assert f"](../{result_rel})" not in impl_doc
    assert "（待生成）" in impl_doc
    passed, detail = ml_mod.validate_managed_markdown_links(str(root))
    assert passed, detail


def test_return_clears_invalidated_bug_result_blocks(tmp_path):
    """Workflow-Test
    主题：退回重走后门禁不再无故反复失败
    测试项：TC-03 退回清除失效缺陷结论块
    验收条件：AC-02 退回不留坏链接
    测试方式：自动化测试
    测试层级：模块测试
    产品入口：workflow return 退回命令
    测试入口：tests/test_gate_rework_stability.py::test_return_clears_invalidated_bug_result_blocks
    代码入口：src/workflow_loop/bug_record.py::reset_status_for_return
    准备数据：隔离项目由程序把主题验收结论块写进缺陷记录第八节
    执行动作：以退回目标为代码实施调用结论块清除入口
    关键断言：结论块和其中指向结果文档的链接都被清除，缺陷索引状态改回根因已确认
    预期证据：pytest 结构化 junit 报告 1 条通过且退出码 0
    """
    root = _project(tmp_path)
    _state(root, "topic_acceptance")
    file_key = artifact_paths_mod.resolve_key_for(project_mod.load_project(str(root)), "topic", TOPIC)
    for rel in (f"qa/{file_key}_测试结果.md", f"acceptance/{file_key}_验收结果.md",
                f"impl/{file_key}_实施记录.md"):
        _write(root / rel, f"# {rel}\n")
    _write(root / "bug/索引.md",
           "# Bug 索引\n\n| Bug 记录 | 现象 | 根因 | 状态 |\n|---|---|---|---|\n"
           f"| [{TOPIC}](./缺陷_{file_key}.md) | 现象 | 根因 | 根因已确认 |\n")
    _write(root / f"bug/缺陷_{file_key}.md",
           f"# 【缺陷】{TOPIC}\n\n- 工作流编号：{WORKFLOW_ID}\n- 复现状态：已复现\n"
           f"- 根因状态：已确认\n- 验收主题：{TOPIC}\n\n## 8. 修复与验收结果\n\n")
    bug_record_mod.record_topic_acceptance_pass(str(root), WORKFLOW_ID, [TOPIC])
    bug_doc = root / f"bug/缺陷_{file_key}.md"
    assert f"(../qa/{file_key}_测试结果.md)" in bug_doc.read_text(encoding="utf-8")

    bug_record_mod.reset_status_for_return(str(root), WORKFLOW_ID, [TOPIC], "impl")

    content = bug_doc.read_text(encoding="utf-8")
    assert "### 主题验收结果" not in content
    assert f"(../qa/{file_key}_测试结果.md)" not in content
    assert "根因已确认" in (root / "bug/索引.md").read_text(encoding="utf-8")


# ─── AC-03：表模式不要求正式文档字节变化 ───


def test_table_mode_accepts_unchanged_generated_document(tmp_path):
    """Workflow-Test
    主题：退回重走后门禁不再无故反复失败
    测试项：TC-04 表模式不要求文档变化
    验收条件：AC-03 不要求制造文档变化
    测试方式：自动化测试
    测试层级：模块测试
    产品入口：workflow gate reproduce 第二道门
    测试入口：tests/test_gate_rework_stability.py::test_table_mode_accepts_unchanged_generated_document
    代码入口：src/workflow_loop/artifact_validation.py::changed_stage_paths
    准备数据：隔离项目冻结表模式并把讨论完成基线设为当前文档内容
    执行动作：不修改任何文件直接判断本阶段产出
    关键断言：判定通过并给出表模式说明，不再报出不能证明本阶段已经生成或修改产物
    预期证据：pytest 结构化 junit 报告 1 条通过且退出码 0
    """
    root = _project(tmp_path)
    state = _state(root, "reproduce", topics=())
    _bug_table(root)
    tracked = ["bug/索引.md", f"bug/缺陷_{TOPIC}.md"]
    for rel in tracked:
        _write(root / rel, f"# {rel}\n")
    state.stages["reproduce"].artifact_baseline_captured_at = state_mod.now_iso()
    state.stages["reproduce"].artifact_baseline_hashes = av_mod.compute_file_hashes(str(root), tracked)
    state_mod.save_state(str(root), state)

    ok, detail, _changed = av_mod.changed_stage_paths(str(root), "reproduce", tracked)

    assert ok, detail
    assert "表模式" in detail
    assert "不能证明本阶段已经生成或修改产物" not in detail


def test_table_mode_change_list_does_not_claim_unchanged_files(tmp_path):
    """Workflow-Test
    主题：退回重走后门禁不再无故反复失败
    测试项：TC-20 表模式不把未变文件报成本阶段改动
    验收条件：AC-03 不要求制造文档变化
    测试方式：自动化测试
    测试层级：模块测试
    产品入口：workflow gate update_code_design 第二道门
    测试入口：tests/test_gate_rework_stability.py::test_table_mode_change_list_does_not_claim_unchanged_files
    代码入口：src/workflow_loop/artifact_validation.py::changed_stage_paths
    准备数据：隔离项目冻结表模式，登记多份产物且全部与讨论完成时逐字节相同
    执行动作：判断本阶段产出并读取返回的变化清单
    关键断言：判定通过但变化清单为空，没有把未改动的文件报成本阶段改动
    预期证据：pytest 结构化 junit 报告 1 条通过且退出码 0
    """
    root = _project(tmp_path)
    state = _state(root, "reproduce", topics=())
    _bug_table(root)
    tracked = ["bug/索引.md", "spec/产品总说明.md", "spec/功能_示例.md"]
    for rel in tracked:
        _write(root / rel, f"# {rel}\n")
    state.stages["reproduce"].artifact_baseline_captured_at = state_mod.now_iso()
    state.stages["reproduce"].artifact_baseline_hashes = av_mod.compute_file_hashes(str(root), tracked)
    state_mod.save_state(str(root), state)

    ok, _detail, changed = av_mod.changed_stage_paths(str(root), "reproduce", tracked)

    assert ok
    assert changed == []


def test_reference_backfill_does_not_recreate_removed_results(tmp_path):
    """Workflow-Test
    主题：退回重走后门禁不再无故反复失败
    测试项：TC-21 回补不重建已删除的结果文档
    验收条件：AC-02 退回不留坏链接
    测试方式：自动化测试
    测试层级：模块测试
    产品入口：workflow return 退回命令
    测试入口：tests/test_gate_rework_stability.py::test_reference_backfill_does_not_recreate_removed_results
    代码入口：src/workflow_loop/records.py::refresh_references_after_removal
    准备数据：隔离项目已生成验收结果文档与对应工作记录表，随后按退回删除该结果文档
    执行动作：调用删除后回补入口
    关键断言：被删除的结果文档没有被重新生成，仍保持删除状态
    预期证据：pytest 结构化 junit 报告 1 条通过且退出码 0
    """
    root = _project(tmp_path)
    state = _state(root, "impl")
    _fill_impl_table(root)
    file_key = artifact_paths_mod.resolve_key_for(project_mod.load_project(str(root)), "topic", TOPIC)
    result_rel = root / f"acceptance/{file_key}_验收结果.md"
    _write(result_rel, f"# 【主题验收结果】{TOPIC}\n")
    records_mod.create_or_complete_table(str(root), WORKFLOW_ID, "acceptance_result", TOPIC)
    relative = records_mod.table_relative_path(str(root), WORKFLOW_ID, "acceptance_result", TOPIC)
    table = json.loads((root / relative).read_text(encoding="utf-8"))
    table["验收结果"] = [{
        "验收条件编号": "AC-01", "验收方式": "自动化测试", "验收结论": "passed",
        "自动化依据": "旧结论", "机器测试记录编号": "RUN-旧", "用户实际回答": "不适用",
        "人工确认": "不适用", "实际观察结果": "上一轮已经作废的验收结论。",
        "证据": "上一轮机器记录。", "验收记录编号": "",
    }]
    table["验收说明"] = ["上一轮的验收说明，退回后应当失效。"]
    _write(root / relative, json.dumps(table, ensure_ascii=False, indent=2))
    result_rel.unlink()

    records_mod.refresh_references_after_removal(str(root), state, [TOPIC])

    assert not result_rel.exists()


def test_document_mode_still_requires_real_change(tmp_path):
    """Workflow-Test
    主题：退回重走后门禁不再无故反复失败
    测试项：TC-05 旧轮次仍要求真实变化
    验收条件：AC-03 不要求制造文档变化
    测试方式：自动化测试
    测试层级：模块测试
    产品入口：workflow gate reproduce 第二道门
    测试入口：tests/test_gate_rework_stability.py::test_document_mode_still_requires_real_change
    代码入口：src/workflow_loop/artifact_validation.py::changed_stage_paths
    准备数据：隔离项目不冻结表模式且本轮没有任何工作记录表
    执行动作：不修改任何文件直接判断本阶段产出
    关键断言：仍返回不通过并保留原有说明，旧轮次行为不变
    预期证据：pytest 结构化 junit 报告 1 条通过且退出码 0
    """
    root = _project(tmp_path)
    state = _state(root, "reproduce", topics=(), frozen="")
    tracked = ["bug/索引.md"]
    _write(root / tracked[0], "# 索引\n")
    state.stages["reproduce"].artifact_baseline_captured_at = state_mod.now_iso()
    state.stages["reproduce"].artifact_baseline_hashes = av_mod.compute_file_hashes(str(root), tracked)
    state_mod.save_state(str(root), state)

    ok, detail, _changed = av_mod.changed_stage_paths(str(root), "reproduce", tracked)

    assert not ok
    assert "不能证明本阶段已经生成或修改产物" in detail


# ─── AC-04：缺陷索引按内容判定 ───


def test_bug_index_is_judged_by_content_not_by_change(tmp_path):
    """Workflow-Test
    主题：退回重走后门禁不再无故反复失败
    测试项：TC-06 缺陷索引按内容判定
    验收条件：AC-04 缺陷索引按内容判定
    测试方式：自动化测试
    测试层级：模块测试
    产品入口：workflow gate reproduce 第二道门
    测试入口：tests/test_gate_rework_stability.py::test_bug_index_is_judged_by_content_not_by_change
    代码入口：src/workflow_loop/artifact_validation.py::validate_reproduce_documents
    准备数据：隔离项目的缺陷索引已经链接本轮缺陷记录且本阶段没有再改过它
    执行动作：把只含缺陷记录的变化清单交给缺陷复现校验
    关键断言：不报索引没有在本阶段更新；索引缺链接时仍报对应失败
    预期证据：pytest 结构化 junit 报告 1 条通过且退出码 0
    """
    root = _project(tmp_path)
    _write(root / "bug/索引.md",
           "# Bug 索引\n\n| Bug 记录 | 现象 | 根因 | 状态 |\n|---|---|---|---|\n"
           "| [样例](./缺陷_样例.md) | 现象 | 根因 | 根因已确认 |\n")
    _write(root / "bug/缺陷_样例.md",
           f"# 【缺陷】样例\n\n- 工作流编号：{WORKFLOW_ID}\n- 复现状态：已复现\n- 根因状态：已确认\n"
           f"- 验收主题：{TOPIC}\n\n## 1. 缺陷现象\n\n现象说明足够具体。\n\n"
           "## 2. 真实复现条件\n\n- 运行环境：隔离临时项目\n- 真实输入：本轮生成的缺陷记录\n\n"
           "## 3. 复现步骤\n\n从真实入口执行一次门禁。\n\n## 4. 实际结果\n\n报出具体失败。\n\n"
           "## 5. 期望结果\n\n按产品设计应当通过。\n\n"
           "## 6. 根因\n\n- 根因说明：判定条件写错\n- 根因位置：某文件某函数\n- 根因证据：真实运行输出\n\n"
           "## 7. 修复仍存在的不确定性\n\n暂无\n")

    ok, detail = av_mod.validate_reproduce_documents(str(root), ["bug/缺陷_样例.md"], WORKFLOW_ID)

    assert ok, detail
    _write(root / "bug/索引.md", "# Bug 索引\n\n| Bug 记录 | 现象 | 根因 | 状态 |\n|---|---|---|---|\n")
    missing_ok, missing_detail = av_mod.validate_reproduce_documents(
        str(root), ["bug/缺陷_样例.md"], WORKFLOW_ID
    )
    assert not missing_ok
    assert "没有链接本次缺陷记录" in missing_detail


# ─── AC-05：缺陷记录生成路径与登记路径一致 ───


def test_same_name_shares_one_file_key_across_categories(tmp_path):
    """Workflow-Test
    主题：退回重走后门禁不再无故反复失败
    测试项：TC-07 同名缺陷与主题共用文件标识
    验收条件：AC-05 缺陷文件名前后一致
    测试方式：自动化测试
    测试层级：模块测试
    产品入口：workflow gate reproduce 第三道门登记文件标识
    测试入口：tests/test_gate_rework_stability.py::test_same_name_shares_one_file_key_across_categories
    代码入口：src/workflow_loop/artifact_paths.py::resolve_file_key
    准备数据：隔离项目对同一个名称先后登记缺陷分类和主题分类
    执行动作：比较两个分类得到的文件标识与生成器实际写出的缺陷记录路径
    关键断言：两个分类共用同一标识，生成路径与登记路径指向同一文件
    预期证据：pytest 结构化 junit 报告 1 条通过且退出码 0
    """
    root = _project(tmp_path)
    project = project_mod.load_project(str(root))
    artifact_paths_mod.register_file_keys(project, "bug", [TOPIC])
    artifact_paths_mod.register_file_keys(project, "topic", [TOPIC])
    project_mod.save_project(str(root), project)

    bug_key = project.artifact_file_keys["bug"][TOPIC]
    topic_key = project.artifact_file_keys["topic"][TOPIC]
    assert bug_key == topic_key
    assert not bug_key.endswith("_2")

    table = json.loads(_bug_table(root).read_text(encoding="utf-8"))
    generated = [rel for rel, _content in records_mod._bug_defect_documents(table, str(root))]
    assert generated[0] == artifact_paths_mod.bug_doc(bug_key)


def test_different_names_still_get_distinct_file_keys(tmp_path):
    """Workflow-Test
    主题：退回重走后门禁不再无故反复失败
    测试项：TC-08 不同名称仍不共用标识
    验收条件：AC-05 缺陷文件名前后一致
    测试方式：自动化测试
    测试层级：模块测试
    产品入口：workflow gate reproduce 第三道门登记文件标识
    测试入口：tests/test_gate_rework_stability.py::test_different_names_still_get_distinct_file_keys
    代码入口：src/workflow_loop/artifact_paths.py::resolve_file_key
    准备数据：隔离项目登记两个只在非法字符上不同、清理后同名的显示名称
    执行动作：连续登记两个名称并读取各自标识
    关键断言：两个不同名称得到不同标识，第二个按原规则追加编号
    预期证据：pytest 结构化 junit 报告 1 条通过且退出码 0
    """
    root = _project(tmp_path)
    project = project_mod.load_project(str(root))
    artifact_paths_mod.register_file_keys(project, "topic", ["同名主题"])
    artifact_paths_mod.register_file_keys(project, "bug", ["同名主题/其它"])
    project_mod.save_project(str(root), project)

    first = project.artifact_file_keys["topic"]["同名主题"]
    second = project.artifact_file_keys["bug"]["同名主题/其它"]
    assert first != second


# ─── AC-06：缺陷记录锚点与手改保护 ───


def test_bug_record_has_section_anchors(tmp_path):
    """Workflow-Test
    主题：退回重走后门禁不再无故反复失败
    测试项：TC-09 缺陷记录八节带锚点
    验收条件：AC-06 缺陷记录有锚点且防手改
    测试方式：自动化测试
    测试层级：模块测试
    产品入口：workflow gate reproduce 第二道门生成缺陷记录
    测试入口：tests/test_gate_rework_stability.py::test_bug_record_has_section_anchors
    代码入口：src/workflow_loop/records.py::_bug_defect_documents
    准备数据：隔离项目填好缺陷记录工作记录表
    执行动作：按表生成缺陷记录内容
    关键断言：八个固定章节标题前各有与编号一致的显式锚点
    预期证据：pytest 结构化 junit 报告 1 条通过且退出码 0
    """
    root = _project(tmp_path)
    table = json.loads(_bug_table(root).read_text(encoding="utf-8"))
    _relative, content = records_mod._bug_defect_documents(table, str(root))[0]

    for index, heading in enumerate(
        ["缺陷现象", "真实复现条件", "复现步骤", "实际结果", "期望结果", "根因",
         "修复仍存在的不确定性", "修复与验收结果"],
        start=1,
    ):
        assert f'<a id="{index}-{heading}"></a>' in content
        assert f"## {index}. {heading}" in content


def test_bug_record_manual_edit_is_reported_not_overwritten(tmp_path):
    """Workflow-Test
    主题：退回重走后门禁不再无故反复失败
    测试项：TC-10 缺陷记录手改被检出并保留
    验收条件：AC-06 缺陷记录有锚点且防手改
    测试方式：自动化测试
    测试层级：模块测试
    产品入口：workflow gate reproduce 第二道门
    测试入口：tests/test_gate_rework_stability.py::test_bug_record_manual_edit_is_reported_not_overwritten
    代码入口：src/workflow_loop/records.py::_write_bug_documents
    准备数据：隔离项目先按表生成缺陷记录，再手工修改其中一段正文
    执行动作：再次执行按表同步
    关键断言：报告文档被直接修改，手改内容仍在磁盘上
    预期证据：pytest 结构化 junit 报告 1 条通过且退出码 0
    """
    root = _project(tmp_path)
    state = _state(root, "reproduce", topics=())
    _bug_table(root)
    records_mod.sync_stage_tables(str(root), state)
    file_key = records_mod.bug_file_key(str(root), TOPIC)
    bug_doc = root / f"bug/缺陷_{file_key}.md"
    edited = bug_doc.read_text(encoding="utf-8").replace("现象说明", "现象说明") + "\n手工补充的一句话。\n"
    bug_doc.write_text(edited, encoding="utf-8")

    problems, _documents = records_mod.sync_stage_tables(str(root), state)

    assert any("文档被直接修改" in message for _category, message in problems), problems
    assert "手工补充的一句话。" in bug_doc.read_text(encoding="utf-8")


def test_bug_record_keeps_stage_result_blocks_on_regeneration(tmp_path):
    """Workflow-Test
    主题：退回重走后门禁不再无故反复失败
    测试项：TC-11 重新生成保留阶段结论块
    验收条件：AC-06 缺陷记录有锚点且防手改
    测试方式：自动化测试
    测试层级：模块测试
    产品入口：workflow gate reproduce 第二道门
    测试入口：tests/test_gate_rework_stability.py::test_bug_record_keeps_stage_result_blocks_on_regeneration
    代码入口：src/workflow_loop/records.py::_existing_bug_result_blocks
    准备数据：隔离项目生成缺陷记录后由程序追加主题验收结论块
    执行动作：再次执行按表同步
    关键断言：结论块原样保留，且不被误报为手改
    预期证据：pytest 结构化 junit 报告 1 条通过且退出码 0
    """
    root = _project(tmp_path)
    state = _state(root, "reproduce", topics=())
    _bug_table(root)
    records_mod.sync_stage_tables(str(root), state)
    file_key = records_mod.bug_file_key(str(root), TOPIC)
    for rel in (f"qa/{file_key}_测试结果.md", f"acceptance/{file_key}_验收结果.md",
                f"impl/{file_key}_实施记录.md"):
        _write(root / rel, f"# {rel}\n")
    bug_record_mod.record_topic_acceptance_pass(str(root), WORKFLOW_ID, [TOPIC])

    problems, _documents = records_mod.sync_stage_tables(str(root), state)

    content = (root / f"bug/缺陷_{file_key}.md").read_text(encoding="utf-8")
    assert "### 主题验收结果" in content
    assert not [message for _category, message in problems if "文档被直接修改" in message]


# ─── AC-07：表模式判定看开工冻结标记 ───


def test_table_mode_is_decided_by_frozen_marker(tmp_path):
    """Workflow-Test
    主题：退回重走后门禁不再无故反复失败
    测试项：TC-12 表模式判定读开工标记
    验收条件：AC-07 表模式不退回文档模式
    测试方式：自动化测试
    测试层级：模块测试
    产品入口：workflow gate qa 第二道门
    测试入口：tests/test_gate_rework_stability.py::test_table_mode_is_decided_by_frozen_marker
    代码入口：src/workflow_loop/records.py::workflow_uses_tables
    准备数据：隔离项目冻结表版本但一张表都不建
    执行动作：分别在冻结与未冻结两种状态下判定是否走表模式
    关键断言：冻结即表模式，与磁盘上有没有表无关；未冻结且无表时才是旧轮次
    预期证据：pytest 结构化 junit 报告 1 条通过且退出码 0
    """
    root = _project(tmp_path)
    frozen = _state(root, "qa")
    assert records_mod.workflow_uses_tables(frozen, str(root))

    legacy = _state(root, "qa", frozen="")
    assert not records_mod.workflow_uses_tables(legacy, str(root))


def test_missing_or_broken_table_reports_error_instead_of_document_mode(tmp_path):
    """Workflow-Test
    主题：退回重走后门禁不再无故反复失败
    测试项：TC-13 缺表与坏表报具体错误
    验收条件：AC-07 表模式不退回文档模式
    测试方式：自动化测试
    测试层级：模块测试
    产品入口：workflow gate qa 第二道门
    测试入口：tests/test_gate_rework_stability.py::test_missing_or_broken_table_reports_error_instead_of_document_mode
    代码入口：src/workflow_loop/artifact_validation.py::validate_test_plan_documents
    准备数据：隔离项目冻结表模式，一个主题缺测试计划表，另一个主题的表写成非法结构
    执行动作：执行测试计划校验
    关键断言：分别点名缺表主题和无法解析的表，不出现文档模式的章节缺失类失败
    预期证据：pytest 结构化 junit 报告 1 条通过且退出码 0
    """
    root = _project(tmp_path)
    _state(root, "qa", topics=(TOPIC, "样例主题乙"))
    broken = records_mod.table_relative_path(str(root), WORKFLOW_ID, "test_plan", "样例主题乙")
    _write(root / broken, "{ 这不是合法 JSON")

    ok, detail = av_mod.validate_test_plan_documents(str(root), WORKFLOW_ID, [TOPIC, "样例主题乙"])

    assert not ok
    assert "缺少测试计划工作记录表" in detail
    assert "无法解析" in detail
    assert "索引.md 不存在" not in detail


# ─── AC-08：门禁日志带轮次编号 ───


def test_gate_validation_journal_entry_records_workflow_id(tmp_path):
    """Workflow-Test
    主题：退回重走后门禁不再无故反复失败
    测试项：TC-14 门禁日志带轮次编号
    验收条件：AC-08 门禁日志带轮次编号
    测试方式：自动化测试
    测试层级：模块测试
    产品入口：workflow gate 环节名 第二道门
    测试入口：tests/test_gate_rework_stability.py::test_gate_validation_journal_entry_records_workflow_id
    代码入口：src/workflow_loop/cli.py::cmd_gate
    准备数据：读取命令编排源码中写门禁校验日志的两处调用
    执行动作：检查两处调用是否传入当前轮次编号
    关键断言：通过与失败两个分支都写入 workflow_id
    预期证据：pytest 结构化 junit 报告 1 条通过且退出码 0
    """
    source = (REPO_ROOT / "src/workflow_loop/cli.py").read_text(encoding="utf-8")
    calls = re.findall(
        r'journal_mod\.append_entry\(\s*\n\s*project_root,\s*\n\s*"门禁代码校验",\s*\n'
        r'\s*"workflow\.py",\s*\n\s*(workflow_id=[^\n]*)\n',
        source,
    )
    assert len(calls) == 2, calls
    assert all("wf_state.workflow_id" in call for call in calls)


# ─── AC-09：安装契约与仓库契约一致 ───


def test_installed_contract_matches_repository_contract(tmp_path):
    """Workflow-Test
    主题：退回重走后门禁不再无故反复失败
    测试项：TC-15 安装契约与仓库一致
    验收条件：AC-09 安装契约与仓库一致
    测试方式：自动化测试
    测试层级：模块测试
    产品入口：项目安装写入 AGENTS.md
    测试入口：tests/test_gate_rework_stability.py::test_installed_contract_matches_repository_contract
    代码入口：src/workflow_loop/installer.py::AGENTS_MD_CONTENT
    准备数据：读取仓库根契约与安装器常量
    执行动作：逐字节比较两份内容并检查四节标题
    关键断言：两份完全相同且四节齐全
    预期证据：pytest 结构化 junit 报告 1 条通过且退出码 0
    """
    repository = (REPO_ROOT / "AGENTS.md").read_text(encoding="utf-8")

    assert repository == installer_mod.AGENTS_MD_CONTENT
    for section in ("## workflow 入口", "## 无需开发任务", "## 工作记录表", "## 表达要求"):
        assert section in repository


# ─── AC-10：登记穿刺资产随仓库保存 ───


def test_registered_spike_assets_are_not_ignored(tmp_path):
    """Workflow-Test
    主题：退回重走后门禁不再无故反复失败
    测试项：TC-16 穿刺资产随仓库保存
    验收条件：AC-10 登记穿刺资产随仓库保存
    测试方式：自动化测试
    测试层级：集成测试
    产品入口：仓库版本控制忽略规则
    测试入口：tests/test_gate_rework_stability.py::test_registered_spike_assets_are_not_ignored
    代码入口：.gitignore 穿刺临时目录忽略规则
    准备数据：取本仓库中一条已登记的穿刺资产路径与同目录的缓存和纯输出路径
    执行动作：对三类路径分别执行 git check-ignore
    关键断言：登记代码不被忽略，缓存目录和纯输出目录仍被忽略
    预期证据：pytest 结构化 junit 报告 1 条通过且退出码 0
    """
    def ignored(relative: str) -> bool:
        result = subprocess.run(
            ["git", "check-ignore", "-q", relative],
            cwd=REPO_ROOT, capture_output=True, text=True,
        )
        return result.returncode == 0

    base = ".workflow_loop/spike_tmp/某轮次/某穿刺项"
    assert not ignored(f"{base}/prototype.py")
    assert ignored(f"{base}/__pycache__/prototype.pyc")
    assert ignored(f"{base}/out/结果.json")


# ─── AC-11：包内规范与项目副本一致 ───


def test_packaged_standards_match_project_copies(tmp_path):
    """Workflow-Test
    主题：退回重走后门禁不再无故反复失败
    测试项：TC-17 包内规范与项目副本一致
    验收条件：AC-11 包内规范与项目副本一致
    测试方式：自动化测试
    测试层级：集成测试
    产品入口：workflow update 覆盖模板与规范
    测试入口：tests/test_gate_rework_stability.py::test_packaged_standards_match_project_copies
    代码入口：src/workflow_loop/data/Standardized_Repository
    准备数据：取本仓库包内两套资源目录与项目运行副本目录
    执行动作：逐文件比较内容并检查被正式文档链接的锚点
    关键断言：同名文件全部相同，被链接的锚点存在于包内源文件
    预期证据：pytest 结构化 junit 报告 1 条通过且退出码 0
    """
    for base in ("Standardized_Repository", "Template_Repository"):
        packaged = REPO_ROOT / "src/workflow_loop/data" / base
        project_copy = REPO_ROOT / ".workflow_loop" / base
        differences: list[str] = []

        def walk(comparison, prefix=""):
            differences.extend(os.path.join(prefix, name) for name in comparison.diff_files)
            differences.extend(os.path.join(prefix, name) for name in comparison.left_only)
            differences.extend(os.path.join(prefix, name) for name in comparison.right_only)
            for name, sub in comparison.subdirs.items():
                walk(sub, os.path.join(prefix, name))

        walk(filecmp.dircmp(str(packaged), str(project_copy)))
        assert not differences, f"{base} 两侧不一致: {differences}"

    lifecycle = (
        REPO_ROOT
        / "src/workflow_loop/data/Standardized_Repository/global/workflow_lifecycle.md"
    ).read_text(encoding="utf-8")
    assert '<a id="文档链接要求"></a>' in lifecycle


# ─── AC-12：占位判定不误伤且报错定位 ───


def test_angle_bracket_inside_real_content_is_not_placeholder(tmp_path):
    """Workflow-Test
    主题：退回重走后门禁不再无故反复失败
    测试项：TC-18 含小于号的实质内容不判空
    验收条件：AC-12 占位判定不误伤且报错定位
    测试方式：自动化测试
    测试层级：模块测试
    产品入口：workflow gate 环节名 第二道门的章节内容检查
    测试入口：tests/test_gate_rework_stability.py::test_angle_bracket_inside_real_content_is_not_placeholder
    代码入口：src/workflow_loop/artifact_validation.py::_no_real_text_reason
    准备数据：准备三段值，分别是含小于号的实质内容、整段模板占位写法和空值
    执行动作：逐段判断是否算已填写并读取判定原因
    关键断言：实质内容判为已填写；整段占位和空值判为未填写并给出不同原因
    预期证据：pytest 结构化 junit 报告 1 条通过且退出码 0
    """
    real = "- 生成器写出 bug/缺陷_<标识>.md，与登记路径不一致。\n- 上游用 <a id=\"6-根因\"></a> 链接该节。"
    assert av_mod._no_real_text_reason(real) is None

    placeholder = "<用户在什么操作中看到了什么问题。>"
    reason = av_mod._no_real_text_reason(placeholder)
    assert reason is not None
    assert "模板占位写法" in reason
    assert "用户在什么操作" in reason

    assert av_mod._no_real_text_reason("") == "内容为空"


def test_section_failure_message_locates_the_matched_value(tmp_path):
    """Workflow-Test
    主题：退回重走后门禁不再无故反复失败
    测试项：TC-19 报错写明原因和命中值
    验收条件：AC-12 占位判定不误伤且报错定位
    测试方式：自动化测试
    测试层级：模块测试
    产品入口：workflow gate reproduce 第二道门
    测试入口：tests/test_gate_rework_stability.py::test_section_failure_message_locates_the_matched_value
    代码入口：src/workflow_loop/artifact_validation.py::validate_reproduce_documents
    准备数据：隔离项目的缺陷记录里有一节整段仍是模板占位写法
    执行动作：执行缺陷复现校验
    关键断言：失败文字同时包含文件名、章节名和命中的占位内容
    预期证据：pytest 结构化 junit 报告 1 条通过且退出码 0
    """
    root = _project(tmp_path)
    _write(root / "bug/索引.md",
           "# Bug 索引\n\n| Bug 记录 | 现象 | 根因 | 状态 |\n|---|---|---|---|\n"
           "| [样例](./缺陷_样例.md) | 现象 | 根因 | 根因已确认 |\n")
    _write(root / "bug/缺陷_样例.md",
           f"# 【缺陷】样例\n\n- 工作流编号：{WORKFLOW_ID}\n- 复现状态：已复现\n- 根因状态：已确认\n"
           f"- 验收主题：{TOPIC}\n\n## 1. 缺陷现象\n\n<用户在什么操作中看到了什么问题。>\n\n"
           "## 2. 真实复现条件\n\n- 运行环境：隔离临时项目\n- 真实输入：本轮生成的缺陷记录\n\n"
           "## 3. 复现步骤\n\n从真实入口执行一次门禁。\n\n## 4. 实际结果\n\n报出具体失败。\n\n"
           "## 5. 期望结果\n\n按产品设计应当通过。\n\n"
           "## 6. 根因\n\n- 根因说明：判定条件写错\n- 根因位置：某文件某函数\n- 根因证据：真实运行输出\n\n"
           "## 7. 修复仍存在的不确定性\n\n暂无\n")

    ok, detail = av_mod.validate_reproduce_documents(str(root), ["bug/缺陷_样例.md"], WORKFLOW_ID)

    assert not ok
    assert "缺陷_样例.md" in detail
    assert "1. 缺陷现象" in detail
    assert "模板占位写法" in detail
    assert "用户在什么操作" in detail
