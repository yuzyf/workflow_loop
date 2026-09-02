"""退回重走路径的回归测试（BUG-01..08）。

覆盖：验收计划主题合并（死锁修复）、追踪表按主题/按 AC 补行、scaffold/表同步
主题源、同一 Run 重进 impl 的入场基线继承、复用既有实现说明豁免、
同 Run 重走 reproduce 确认的注册幂等边界。
"""

import json
from pathlib import Path

import pytest

from workflow_loop import project as project_mod
from workflow_loop import records as records_mod
from workflow_loop import rollback as rollback_mod
from workflow_loop import state as state_mod
from workflow_loop import topic as topic_mod
from workflow_loop import traceability as traceability_mod
from workflow_loop.traceability import (
    SPIKE_RECHECK_TEXT,
    SPIKE_SKIPPED_TEXT,
)


WORKFLOW_ID = "2026-09-01-1500-bugfix"
TOPIC_A = "旧主题甲"
TOPIC_B = "旧主题乙"
TOPIC_NEW = "退回后新增主题"


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _install_project(root: Path) -> None:
    project_mod.create_project(str(root))


def _save_state(root: Path, state: state_mod.WorkflowState) -> None:
    state_mod.save_state(str(root), state)


def _acceptance_plan_state(root: Path, topics: list[str], intent: str = "product_change"):
    state = state_mod.WorkflowState(
        workflow_id=WORKFLOW_ID,
        intent=intent,
        run_status="active",
        current_stage="acceptance_plan",
        topics=list(topics),
        stage_path=["acceptance_plan", "impl"],
        stages={"acceptance_plan": state_mod.StageState(status="in_progress")},
    )
    _save_state(root, state)
    return state


def _acceptance_index(root: Path, topics: list[str]) -> None:
    rows = "\n".join(
        f"| {i + 1} | {t} | 无 | [验收计划](./{t}_验收计划.md) | `./{t}_验收结果.md`（待生成） |"
        for i, t in enumerate(topics)
    )
    for t in topics:
        _write(root / "acceptance" / f"{t}_验收计划.md", f"# 【验收主题】{t}\n")
    _write(
        root / "acceptance" / "索引.md",
        f"""# 验收主题索引

## {WORKFLOW_ID}

### 主题关系

| 展示顺序 | 验收主题 | 前置主题 | 验收计划 | 主题验收结果 |
|---|---|---|---|---|
{rows}
""",
    )


def _register_topics(root: Path, topics: list[str]) -> None:
    project_mod.register_topics(str(root), topics)


def _plan_table(root: Path, topic: str, ac_ids: list[str]) -> Path:
    records_mod.create_or_complete_table(str(root), WORKFLOW_ID, "acceptance_plan", topic)
    relative = records_mod.table_relative_path(str(root), WORKFLOW_ID, "acceptance_plan", topic)
    full = root / relative
    table = json.loads(full.read_text(encoding="utf-8"))
    table["验收条件"] = [
        {
            "验收条件编号": ac,
            "验收条件名称": f"{ac} 回归条件",
            "开始前状态": "一个退回后的工作流状态存在且索引包含该主题。",
            "触发动作": f"AI 执行 workflow gate acceptance_plan 校验 {ac}。",
            "可检查结果": f"门禁报告列出 {ac} 的校验结论。",
            "通过标准": f"{ac} 的一次真实执行得到明确通过结论。",
            "不通过标准": f"{ac} 报错、跳过或结论缺失。",
            "产品设计依据": f"缺陷记录第 6 节根因（{ac} 对应缺陷）。",
        }
        for ac in ac_ids
    ]
    full.write_text(json.dumps(table, ensure_ascii=False, indent=2), encoding="utf-8")
    return full


# ─── BUG-01：第二道门校验集接纳索引新主题 ───


def test_acceptance_topics_merges_index_new_topic_for_non_bugfix(tmp_path):
    """Workflow-Test
    主题：退回验收计划后新增主题能走通门禁与追踪表
    测试项：TC-01 退回后索引新主题进入校验集
    验收条件：AC-01 第二道门放行含新主题校验集
    测试方式：自动化测试
    测试层级：模块测试
    产品入口：workflow gate acceptance_plan 第二道门
    测试入口：tests/test_return_rework_flow.py::test_acceptance_topics_merges_index_new_topic_for_non_bugfix
    代码入口：src/workflow_loop/topic.py::acceptance_topics
    准备数据：隔离项目登记 2 个旧主题，acceptance/索引.md 追加 1 个未使用过的新主题
    执行动作：以 product_change 意图调用 acceptance_topics 取验收计划环节主题集
    关键断言：返回值为旧主题并上新主题且包含退回后新增主题
    预期证据：pytest 结构化 junit 报告 1 条通过且退出码 0
    """
    root = tmp_path
    _install_project(root)
    _register_topics(root, [TOPIC_A, TOPIC_B])
    _acceptance_plan_state(root, [TOPIC_A, TOPIC_B])
    _acceptance_index(root, [TOPIC_A, TOPIC_B, TOPIC_NEW])

    topics = topic_mod.acceptance_topics(str(root), "product_change", "acceptance_plan")

    assert topics == [TOPIC_A, TOPIC_B, TOPIC_NEW]


def test_acceptance_topics_rejects_cross_run_duplicate(tmp_path):
    """Workflow-Test
    主题：退回验收计划后新增主题能走通门禁与追踪表
    测试项：TC-02 他轮已用主题不进入候选
    验收条件：AC-05 首轮仍从索引取全部主题
    测试方式：自动化测试
    测试层级：模块测试
    产品入口：workflow gate acceptance_plan 第二道门
    测试入口：tests/test_return_rework_flow.py::test_acceptance_topics_rejects_cross_run_duplicate
    代码入口：src/workflow_loop/topic.py::acceptance_topics
    准备数据：项目主题历史已含另一轮注册过的同名主题
    执行动作：调用 acceptance_topics 取校验集
    关键断言：校验集不包含历史已用主题名
    预期证据：pytest 结构化 junit 报告 1 条通过且退出码 0
    """
    root = tmp_path
    _install_project(root)
    _register_topics(root, [TOPIC_A, TOPIC_NEW])  # 新主题名已被历史占用
    _acceptance_plan_state(root, [TOPIC_A, TOPIC_B])
    _acceptance_index(root, [TOPIC_A, TOPIC_B, TOPIC_NEW])

    topics = topic_mod.acceptance_topics(str(root), "product_change", "acceptance_plan")

    assert TOPIC_NEW not in topics


def test_acceptance_topics_bugfix_uses_state_only(tmp_path):
    """Workflow-Test
    主题：退回验收计划后新增主题能走通门禁与追踪表
    测试项：TC-03 bugfix 意图只取 state 主题不混入索引候选
    验收条件：AC-04 复核旧轮次行为保持不变
    测试方式：自动化测试
    测试层级：模块测试
    产品入口：workflow gate acceptance_plan 第二道门
    测试入口：tests/test_return_rework_flow.py::test_acceptance_topics_bugfix_uses_state_only
    代码入口：src/workflow_loop/topic.py::acceptance_topics
    准备数据：bugfix 轮 state.topics 含 1 个主题且索引比 state 多 1 个主题
    执行动作：以 bugfix 意图调用 acceptance_topics
    关键断言：返回值恰为 state.topics
    预期证据：pytest 结构化 junit 报告 1 条通过且退出码 0
    """
    root = tmp_path
    _install_project(root)
    _register_topics(root, [TOPIC_A, TOPIC_NEW])
    _acceptance_plan_state(root, [TOPIC_A], intent="bugfix")
    _acceptance_index(root, [TOPIC_A, TOPIC_NEW])

    topics = topic_mod.acceptance_topics(str(root), "bugfix", "acceptance_plan")

    assert topics == [TOPIC_A]


# ─── BUG-02/07/08：追踪表按主题与按 AC 自动补行、穿刺列回补 ───


def _trace_table_with_section(root: Path, rows: list[str]) -> None:
    body = "\n".join(rows)
    _write(
        root / "需求交付追踪表.md",
        f"""# 需求交付追踪表

## {WORKFLOW_ID}

### 交付链路

| {" | ".join(traceability_mod.TRACEABILITY_HEADERS)} |
|{"---|" * len(traceability_mod.TRACEABILITY_HEADERS)}
{body}
""",
    )


def _topic_row(topic: str, ac: str, spike_cell: str = SPIKE_SKIPPED_TEXT) -> str:
    cells = {
        "需求来源与设计依据": "[缺陷复现记录](./bug/缺陷_x.md)",
        "验收主题": f"[{topic}](./acceptance/{topic}_验收计划.md)",
        "验收条件": f"{ac}：一次真实执行得到明确通过结论。",
        "穿刺结论与可复用内容": spike_cell,
        "测试项": "待制定",
        "实施计划与任务": "待制定",
        "实施记录与代码": "待执行",
        "测试结果": "待执行",
        "验收结果": "待执行",
        "更新后的代码设计": "待更新",
    }
    return "| " + " | ".join(cells[h] for h in traceability_mod.TRACEABILITY_HEADERS) + " |"


def test_ensure_workflow_section_appends_new_topic_rows(tmp_path):
    """Workflow-Test
    主题：退回验收计划后新增主题能走通门禁与追踪表
    测试项：TC-04 章节存在时缺主题行自动补行
    验收条件：AC-02 追踪表按初值为新主题补行
    测试方式：自动化测试
    测试层级：模块测试
    产品入口：workflow gate acceptance_plan 第二道门
    测试入口：tests/test_return_rework_flow.py::test_ensure_workflow_section_appends_new_topic_rows
    代码入口：src/workflow_loop/traceability.py::ensure_workflow_section
    准备数据：追踪表当前章节只有旧主题行且新主题验收计划表已建
    执行动作：调用 ensure_workflow_section 执行补行
    关键断言：返回 True 且表内出现新主题计划链接并保留旧行
    预期证据：pytest 结构化 junit 报告 1 条通过且退出码 0
    """
    root = tmp_path
    _install_project(root)
    _register_topics(root, [TOPIC_A])
    _acceptance_plan_state(root, [TOPIC_A, TOPIC_NEW])
    _plan_table(root, TOPIC_NEW, ["AC-01"])
    _trace_table_with_section(root, [_topic_row(TOPIC_A, "AC-01")])

    changed = traceability_mod.ensure_workflow_section(str(root), WORKFLOW_ID, [TOPIC_A, TOPIC_NEW])

    content = (root / "需求交付追踪表.md").read_text(encoding="utf-8")
    assert changed is True
    assert f"[{TOPIC_NEW}](./acceptance/{TOPIC_NEW}_验收计划.md)" in content
    assert f"{TOPIC_A}_验收计划" in content  # 旧行不被删除


def test_ensure_workflow_section_appends_missing_ac_rows_for_existing_topic(tmp_path):
    """Workflow-Test
    主题：退回验收计划后新增主题能走通门禁与追踪表
    测试项：TC-05 已有主题新增 AC 时按 AC 补行
    验收条件：AC-02 追踪表按初值为新主题补行
    测试方式：自动化测试
    测试层级：模块测试
    产品入口：workflow gate acceptance_plan 第二道门
    测试入口：tests/test_return_rework_flow.py::test_ensure_workflow_section_appends_missing_ac_rows_for_existing_topic
    代码入口：src/workflow_loop/traceability.py::ensure_workflow_section
    准备数据：主题已有 AC-01 一行且验收计划表新增 AC-02 与 AC-03
    执行动作：调用 ensure_workflow_section
    关键断言：出现 AC-02 与 AC-03 行且 AC-01 原行逐字符不变
    预期证据：pytest 结构化 junit 报告 1 条通过且退出码 0
    """
    root = tmp_path
    _install_project(root)
    _register_topics(root, [TOPIC_A])
    _acceptance_plan_state(root, [TOPIC_A])
    old_row = _topic_row(TOPIC_A, "AC-01")
    _plan_table(root, TOPIC_A, ["AC-01", "AC-02", "AC-03"])
    _trace_table_with_section(root, [old_row])

    changed = traceability_mod.ensure_workflow_section(str(root), WORKFLOW_ID, [TOPIC_A])

    content = (root / "需求交付追踪表.md").read_text(encoding="utf-8")
    lines = [line for line in content.splitlines() if line.startswith("| ")]
    topic_lines = [line for line in lines if TOPIC_A in line]
    assert changed is True
    assert any("AC-02" in line for line in topic_lines)
    assert any("AC-03" in line for line in topic_lines)
    assert old_row in content  # 已有 AC 行逐字符不变


def test_append_rows_use_recheck_text_when_spike_not_skipped(tmp_path):
    """Workflow-Test
    主题：退回验收计划后新增主题能走通门禁与追踪表
    测试项：TC-06 未跳过穿刺时补行写待复核文本
    验收条件：AC-02 追踪表按初值为新主题补行
    测试方式：自动化测试
    测试层级：模块测试
    产品入口：workflow gate acceptance_plan 第二道门
    测试入口：tests/test_return_rework_flow.py::test_append_rows_use_recheck_text_when_spike_not_skipped
    代码入口：src/workflow_loop/traceability.py::ensure_workflow_section
    准备数据：当前轮 state.spike_skipped 为 False 且主题有一行待复核文本旧行
    执行动作：调用 ensure_workflow_section 补 AC-02 行
    关键断言：AC-02 新行穿刺列为待重新确认；已登记资产保留
    预期证据：pytest 结构化 junit 报告 1 条通过且退出码 0
    """
    root = tmp_path
    _install_project(root)
    _register_topics(root, [TOPIC_A])
    state = _acceptance_plan_state(root, [TOPIC_A])
    state.spike_skipped = False
    _save_state(root, state)
    _plan_table(root, TOPIC_A, ["AC-01", "AC-02"])
    _trace_table_with_section(root, [_topic_row(TOPIC_A, "AC-01", spike_cell=SPIKE_RECHECK_TEXT)])

    traceability_mod.ensure_workflow_section(str(root), WORKFLOW_ID, [TOPIC_A])

    content = (root / "需求交付追踪表.md").read_text(encoding="utf-8")
    new_lines = [line for line in content.splitlines() if "AC-02" in line]
    assert new_lines and SPIKE_RECHECK_TEXT in new_lines[0]


def test_resolve_spike_recheck_for_skip_rewrites_only_recheck_rows(tmp_path):
    """Workflow-Test
    主题：退回验收计划后新增主题能走通门禁与追踪表
    测试项：TC-07 skip 回补穿刺列只改待复核行
    验收条件：AC-02 追踪表按初值为新主题补行
    测试方式：自动化测试
    测试层级：模块测试
    产品入口：workflow gate spike --skip
    测试入口：tests/test_return_rework_flow.py::test_resolve_spike_recheck_for_skip_rewrites_only_recheck_rows
    代码入口：src/workflow_loop/traceability.py::resolve_spike_recheck_for_skip
    准备数据：当前章节含待复核文本、跳过文本和引用资产三行
    执行动作：调用 resolve_spike_recheck_for_skip
    关键断言：仅待复核行改为跳过文本且返回说明计数 1 行
    预期证据：pytest 结构化 junit 报告 1 条通过且退出码 0
    """
    root = tmp_path
    _install_project(root)
    _acceptance_plan_state(root, [TOPIC_A])
    asset_row = _topic_row(TOPIC_A, "AC-03", spike_cell=".workflow_loop/spike_tmp/wf/x 引用历史资产")
    _trace_table_with_section(
        root,
        [
            _topic_row(TOPIC_A, "AC-01", spike_cell=SPIKE_RECHECK_TEXT),
            _topic_row(TOPIC_A, "AC-02", spike_cell=SPIKE_SKIPPED_TEXT),
            asset_row,
        ],
    )

    detail = traceability_mod.resolve_spike_recheck_for_skip(str(root), WORKFLOW_ID)

    content = (root / "需求交付追踪表.md").read_text(encoding="utf-8")
    ac1 = [line for line in content.splitlines() if "AC-01" in line][0]
    ac2 = [line for line in content.splitlines() if "AC-02" in line][0]
    ac3 = [line for line in content.splitlines() if "AC-03" in line][0]
    assert "穿刺列 1 行为跳过文本" in detail
    assert SPIKE_SKIPPED_TEXT in ac1
    assert SPIKE_RECHECK_TEXT not in ac1
    assert SPIKE_SKIPPED_TEXT in ac2  # 未受影响
    assert "spike_tmp" in ac3  # 引用资产行不动


def test_resolve_spike_recheck_for_skip_missing_section_is_safe(tmp_path):
    """Workflow-Test
    主题：退回验收计划后新增主题能走通门禁与追踪表
    测试项：TC-08 追踪表无当前章节时回补直接返回
    验收条件：AC-02 追踪表按初值为新主题补行
    测试方式：自动化测试
    测试层级：模块测试
    产品入口：workflow gate spike --skip
    测试入口：tests/test_return_rework_flow.py::test_resolve_spike_recheck_for_skip_missing_section_is_safe
    代码入口：src/workflow_loop/traceability.py::resolve_spike_recheck_for_skip
    准备数据：追踪表只有其他轮次章节
    执行动作：调用 resolve_spike_recheck_for_skip
    关键断言：返回无需回补说明且不抛异常
    预期证据：pytest 结构化 junit 报告 1 条通过且退出码 0
    """
    root = tmp_path
    _install_project(root)
    _write(root / "需求交付追踪表.md", "# 需求交付追踪表\n\n## 其他轮次\n")
    detail = traceability_mod.resolve_spike_recheck_for_skip(str(root), WORKFLOW_ID)
    assert "无需回补" in detail


# ─── BUG-03：表生成主题源接纳索引新主题 ───


def test_ensure_stage_tables_creates_table_for_index_new_topic(tmp_path):
    """Workflow-Test
    主题：退回验收计划后新增主题能走通门禁与追踪表
    测试项：TC-09 表生成创建新主题验收计划表
    验收条件：AC-03 scaffold 为新主题建记录表
    测试方式：自动化测试
    测试层级：模块测试
    产品入口：workflow discuss 与 workflow scaffold
    测试入口：tests/test_return_rework_flow.py::test_ensure_stage_tables_creates_table_for_index_new_topic
    代码入口：src/workflow_loop/records.py::ensure_stage_tables
    准备数据：state.topics 为 2 个旧主题且索引含 1 个新主题
    执行动作：调用 ensure_stage_tables
    关键断言：返回值包含新主题 acceptance_plan 表路径且文件存在
    预期证据：pytest 结构化 junit 报告 1 条通过且退出码 0
    """
    root = tmp_path
    _install_project(root)
    _register_topics(root, [TOPIC_A, TOPIC_B])
    state = _acceptance_plan_state(root, [TOPIC_A, TOPIC_B])
    _acceptance_index(root, [TOPIC_A, TOPIC_B, TOPIC_NEW])

    created = records_mod.ensure_stage_tables(str(root), state)

    assert any(TOPIC_NEW in path for path in created), created
    assert records_mod.table_exists(
        str(root),
        records_mod.table_relative_path(str(root), WORKFLOW_ID, "acceptance_plan", TOPIC_NEW),
    )


# ─── BUG-04：同一 Run 重进 impl 继承首次入场基线 ───


def _impl_state(root: Path) -> state_mod.WorkflowState:
    state = state_mod.WorkflowState(
        workflow_id="run-two-impl",
        intent="product_change",
        run_status="active",
        current_stage="impl",
        topics=["旧主题甲"],
        stage_path=["impl"],
        stages={"impl": state_mod.StageState(status="in_progress")},
    )
    _save_state(root, state)
    _write(root / "src" / "demo" / "core.py", "def f():\n    return 1\n")
    return state


def test_second_impl_entry_inherits_first_frozen_baseline(tmp_path):
    """Workflow-Test
    主题：退回验收计划后新增主题能走通门禁与追踪表
    测试项：TC-10 第二次入场沿用首次入场基线
    验收条件：AC-06 同一 Run 重进实施环节沿用首次入场基线
    测试方式：自动化测试
    测试层级：模块测试
    产品入口：workflow gate impl --discuss-done
    测试入口：tests/test_return_rework_flow.py::test_second_impl_entry_inherits_first_frozen_baseline
    代码入口：src/workflow_loop/cli.py::_freeze_impl_code_baseline
    准备数据：第一次入场冻结基线后改文件并用 clear_stage_gates 模拟退回
    执行动作：第二次入场冻结并计算入场 diff
    关键断言：哈希与完整快照与首次一致且第一次实施改动仍在 diff 中
    预期证据：pytest 结构化 junit 报告 1 条通过且退出码 0
    """
    from workflow_loop import cli as cli_mod
    from workflow_loop import verification as verification_mod

    root = tmp_path
    _install_project(root)
    state = _impl_state(root)

    assert cli_mod.ensure_impl_recovery_baseline(str(root), state) is True
    first_hash = state.stages["impl"].code_baseline_hash
    first_complete = state.meta[rollback_mod.IMPL_COMPLETE_BASELINE_SNAPSHOT_KEY]

    # 第一次实施改动
    _write(root / "src" / "demo" / "core.py", "def f():\n    return 2\n")
    changed_first, _ = rollback_mod.actual_implementation_paths_since_entry(str(root), state)
    assert "src/demo/core.py" in changed_first

    # 退回：clear_stage_gates 清空入场哈希与快照
    verification_mod.clear_stage_gates(state.stages["impl"])
    state.meta[rollback_mod.IMPL_COMPLETE_BASELINE_SNAPSHOT_KEY] = {"aggregate_hash": "stale"}
    state.meta[rollback_mod.IMPL_CODE_BASELINE_SNAPSHOT_KEY] = {"aggregate_hash": "stale"}
    _save_state(root, state)
    state = state_mod.load_state(str(root))

    assert cli_mod.ensure_impl_recovery_baseline(str(root), state) is True
    assert state.stages["impl"].code_baseline_hash == first_hash
    assert (
        state.meta[rollback_mod.IMPL_COMPLETE_BASELINE_SNAPSHOT_KEY]
        == first_complete
    )
    changed_second, _ = rollback_mod.actual_implementation_paths_since_entry(str(root), state)
    assert "src/demo/core.py" in changed_second


def test_first_impl_entry_writes_entry_anchor(tmp_path):
    """Workflow-Test
    主题：退回验收计划后新增主题能走通门禁与追踪表
    测试项：TC-11 首次冻结写入入场锚点
    验收条件：AC-06 同一 Run 重进实施环节沿用首次入场基线
    测试方式：自动化测试
    测试层级：模块测试
    产品入口：workflow gate impl --discuss-done
    测试入口：tests/test_return_rework_flow.py::test_first_impl_entry_writes_entry_anchor
    代码入口：src/workflow_loop/cli.py::ensure_impl_recovery_baseline
    准备数据：新一轮第一次进入 impl
    执行动作：调用 ensure_impl_recovery_baseline
    关键断言：meta 的 impl_entry_baseline 哈希等于 stage 基线且含两快照与 workflow_id
    预期证据：pytest 结构化 junit 报告 1 条通过且退出码 0
    """
    from workflow_loop import cli as cli_mod

    root = tmp_path
    _install_project(root)
    state = _impl_state(root)
    cli_mod.ensure_impl_recovery_baseline(str(root), state)
    entry = state.meta.get(rollback_mod.IMPL_ENTRY_BASELINE_META_KEY)
    assert isinstance(entry, dict)
    assert entry["code_baseline_hash"] == state.stages["impl"].code_baseline_hash
    assert isinstance(entry["complete_snapshot"], dict)
    assert entry["workflow_id"] == "run-two-impl"


def test_inheritance_requires_matching_workflow_id(tmp_path):
    """Workflow-Test
    主题：退回验收计划后新增主题能走通门禁与追踪表
    测试项：TC-12 继承要求锚点 workflow_id 一致
    验收条件：AC-06 同一 Run 重进实施环节沿用首次入场基线
    测试方式：自动化测试
    测试层级：模块测试
    产品入口：workflow gate impl --discuss-done
    测试入口：tests/test_return_rework_flow.py::test_inheritance_requires_matching_workflow_id
    代码入口：src/workflow_loop/cli.py::_freeze_impl_code_baseline
    准备数据：锚点 workflow_id 被改为其他轮次
    执行动作：退回后再次入场冻结
    关键断言：不继承他人基线并重新冻结后锚点改写为当前轮次
    预期证据：pytest 结构化 junit 报告 1 条通过且退出码 0
    """
    from workflow_loop import cli as cli_mod
    from workflow_loop import verification as verification_mod

    root = tmp_path
    _install_project(root)
    state = _impl_state(root)
    cli_mod.ensure_impl_recovery_baseline(str(root), state)
    state.meta[rollback_mod.IMPL_ENTRY_BASELINE_META_KEY]["workflow_id"] = "other-run"
    verification_mod.clear_stage_gates(state.stages["impl"])
    _save_state(root, state)
    state = state_mod.load_state(str(root))

    cli_mod.ensure_impl_recovery_baseline(str(root), state)

    entry = state.meta[rollback_mod.IMPL_ENTRY_BASELINE_META_KEY]
    assert entry["workflow_id"] == "run-two-impl"  # 锚点被当前 Run 重新写入


# ─── BUG-05：复用既有实现说明豁免 ───


def _reuse_state_with_table(root: Path, *, with_exemption: bool, with_change: bool):
    from workflow_loop import cli as cli_mod

    _install_project(root)
    state = _impl_state(root)
    if not with_change:
        _write(root / "src" / "demo" / "helper.py", "def helper():\n    return 0\n")
    cli_mod.ensure_impl_recovery_baseline(str(root), state)
    if with_change:
        _write(root / "src" / "demo" / "core.py", "def f():\n    return 2\n")

    target = "src/demo/core.py" if with_change else "src/demo/helper.py"
    reason = "本轮复用既有实现，不修改" if with_exemption else "按验收条件实现新行为"
    relative = records_mod.create_or_complete_table(str(root), "run-two-impl", "impl_record", "旧主题甲")
    table_path = root / relative
    table = json.loads(table_path.read_text(encoding="utf-8"))
    table["实际代码修改"] = [
        {
            "文件": target,
            "代码位置（最终文件）": "L1-L2",
            "实际修改的代码逻辑": "f 返回 2" if with_change else "无代码改动",
            "数据、状态或输出的实际变化": "返回 2" if with_change else "无变化",
            "修改理由": reason,
            "对应验收条件": "AC-01",
            "测试证据": "本地运行",
        }
    ]
    table_path.write_text(json.dumps(table, ensure_ascii=False, indent=2), encoding="utf-8")
    _write(
        root / "acceptance" / "旧主题甲_验收计划.md",
        "# 【验收主题】旧主题甲\n\n<a id=\"ac-01\"></a>\n### AC-01：上传后可读取结果\n",
    )
    return state


def test_reuse_exemption_accepts_recorded_without_change(tmp_path):
    """Workflow-Test
    主题：退回验收计划后新增主题能走通门禁与追踪表
    测试项：TC-13 带复用说明的登记不报错
    验收条件：AC-07 复用既有实现说明按提示操作即生效
    测试方式：自动化测试
    测试层级：模块测试
    产品入口：workflow gate impl 第二道门
    测试入口：tests/test_return_rework_flow.py::test_reuse_exemption_accepts_recorded_without_change
    代码入口：src/workflow_loop/rollback.py::validate_actual_implementation_changes_report
    准备数据：登记文件入场后无变化且修改理由写明复用既有实现
    执行动作：调用实际改动报告校验
    关键断言：报告中没有该文件的 recorded_without_change 报错
    预期证据：pytest 结构化 junit 报告 1 条通过且退出码 0
    """
    state = _reuse_state_with_table(tmp_path, with_exemption=True, with_change=False)
    report = rollback_mod.validate_actual_implementation_changes_report(str(tmp_path), state)
    ids = [item.check_id for item in report.errors]
    assert not any("recorded_without_change" in cid for cid in ids), ids


def test_recorded_without_change_still_errors_without_exemption_text(tmp_path):
    """Workflow-Test
    主题：退回验收计划后新增主题能走通门禁与追踪表
    测试项：TC-14 无说明登记仍报错
    验收条件：AC-07 复用既有实现说明按提示操作即生效
    测试方式：自动化测试
    测试层级：模块测试
    产品入口：workflow gate impl 第二道门
    测试入口：tests/test_return_rework_flow.py::test_recorded_without_change_still_errors_without_exemption_text
    代码入口：src/workflow_loop/rollback.py::validate_actual_implementation_changes_report
    准备数据：登记文件入场后无变化且修改理由不含复用说明
    执行动作：调用实际改动报告校验
    关键断言：报告含该文件的 recorded_without_change 报错
    预期证据：pytest 结构化 junit 报告 1 条通过且退出码 0
    """
    state = _reuse_state_with_table(tmp_path, with_exemption=False, with_change=False)
    report = rollback_mod.validate_actual_implementation_changes_report(str(tmp_path), state)
    ids = [item.check_id for item in report.errors]
    assert any(cid.endswith("recorded_without_change:src/demo/helper.py") for cid in ids), ids


def test_reuse_word_alone_does_not_exempt(tmp_path):
    """Workflow-Test
    主题：退回验收计划后新增主题能走通门禁与追踪表
    测试项：TC-15 孤立复用词不豁免
    验收条件：AC-07 复用既有实现说明按提示操作即生效
    测试方式：自动化测试
    测试层级：模块测试
    产品入口：workflow gate impl 第二道门
    测试入口：tests/test_return_rework_flow.py::test_reuse_word_alone_does_not_exempt
    代码入口：src/workflow_loop/rollback.py::validate_actual_implementation_changes_report
    准备数据：理由先写含复用既有实现的完整句式再换成孤立复用措辞
    执行动作：分别调用实际改动报告校验
    关键断言：完整句式豁免生效而孤立复用措辞报 recorded_without_change
    预期证据：pytest 结构化 junit 报告 1 条通过且退出码 0
    """
    _install_project(tmp_path)
    from workflow_loop import cli as cli_mod

    root = tmp_path
    state = _impl_state(root)
    _write(root / "src" / "demo" / "helper.py", "def helper():\n    return 0\n")
    cli_mod.ensure_impl_recovery_baseline(str(root), state)
    relative = records_mod.create_or_complete_table(str(root), "run-two-impl", "impl_record", "旧主题甲")
    table_path = root / relative
    table = json.loads(table_path.read_text(encoding="utf-8"))
    table["实际代码修改"] = [
        {
            "文件": "src/demo/helper.py",
            "代码位置（最终文件）": "L1-L2",
            "实际修改的代码逻辑": "无",
            "数据、状态或输出的实际变化": "无变化",
            "修改理由": "这里只是提到复用一次，不是说明复用既有实现",
            "对应验收条件": "AC-01",
            "测试证据": "本地运行",
        }
    ]
    table_path.write_text(json.dumps(table, ensure_ascii=False, indent=2), encoding="utf-8")
    _write(
        root / "acceptance" / "旧主题甲_验收计划.md",
        "# 【验收主题】旧主题甲\n\n<a id=\"ac-01\"></a>\n### AC-01：上传后可读取结果\n",
    )
    report = rollback_mod.validate_actual_implementation_changes_report(str(root), state)
    assert not any("recorded_without_change" in i.check_id for i in report.errors)

    # 换成孤立的“复用”措辞则不放行
    table["实际代码修改"][0]["修改理由"] = "复用了一个组件的名字但实际改了逻辑"
    table_path.write_text(json.dumps(table, ensure_ascii=False, indent=2), encoding="utf-8")
    report = rollback_mod.validate_actual_implementation_changes_report(str(root), state)
    assert any("recorded_without_change" in i.check_id for i in report.errors)


# ─── BUG-06：注册规则边界（同 Run 过滤 / 跨 Run 拒绝） ───


def test_register_topics_empty_new_topics_is_noop(tmp_path):
    """Workflow-Test
    主题：退回验收计划后新增主题能走通门禁与追踪表
    测试项：TC-16 空新主题列表注册为无操作
    验收条件：AC-08 同一 Run 重走缺陷复现确认可幂等通过
    测试方式：自动化测试
    测试层级：模块测试
    产品入口：workflow gate reproduce --confirmed
    测试入口：tests/test_return_rework_flow.py::test_register_topics_empty_new_topics_is_noop
    代码入口：src/workflow_loop/project.py::register_topics
    准备数据：主题历史已含本 Run 第一遍登记的主题
    执行动作：用空列表调用 register_topics
    关键断言：主题历史保持不变
    预期证据：pytest 结构化 junit 报告 1 条通过且退出码 0
    """
    root = tmp_path
    _install_project(root)
    _register_topics(root, [TOPIC_A])
    before = project_mod.load_project(str(root)).topic_history
    project_mod.register_topics(str(root), [])
    assert project_mod.load_project(str(root)).topic_history == before


def test_register_topics_still_rejects_cross_run_duplicate(tmp_path):
    """Workflow-Test
    主题：退回验收计划后新增主题能走通门禁与追踪表
    测试项：TC-17 跨轮次重名主题仍被拒绝
    验收条件：AC-08 同一 Run 重走缺陷复现确认可幂等通过
    测试方式：自动化测试
    测试层级：模块测试
    产品入口：workflow gate reproduce --confirmed
    测试入口：tests/test_return_rework_flow.py::test_register_topics_still_rejects_cross_run_duplicate
    代码入口：src/workflow_loop/project.py::register_topics
    准备数据：主题历史含他轮注册过的主题
    执行动作：直接调用 register_topics 重复登记
    关键断言：抛出主题名称已经使用过
    预期证据：pytest 结构化 junit 报告 1 条通过且退出码 0
    """
    root = tmp_path
    _install_project(root)
    _register_topics(root, [TOPIC_A])
    with pytest.raises(ValueError, match="主题名称已经使用过"):
        project_mod.register_topics(str(root), [TOPIC_A])


# ─── BUG-09：引用回补不覆盖已生成的机器事实 ───


def _ac09_project(root: Path):
    """构造一张已填的 test_result 表与一条带机器记录的 qa 任务。"""
    from workflow_loop import state as _state

    _install_project(root)
    wf_id = "wf-ac09"
    topic = "引用回补保护"
    records_mod.create_or_complete_table(str(root), wf_id, "test_result", topic)
    rel = records_mod.table_relative_path(str(root), wf_id, "test_result", topic)
    table = json.loads((root / rel).read_text(encoding="utf-8"))
    table["测试结果"] = [
        {
            "测试项编号": "TC-01",
            "执行结论": "passed",
            "机器记录编号": "RUN-TEST-1",
            "实际结果说明": "一次真实执行退出码 0，报告精确匹配入口。",
        }
    ]
    (root / rel).write_text(json.dumps(table, ensure_ascii=False, indent=2), encoding="utf-8")
    record = _state.TestExecutionRecord(
        test_entries=["tests/x.py::t"], command=["pytest", "tests/x.py::t"],
        record_id="RUN-TEST-1", exit_code=0, executed_count=1,
        skipped_count=0, failed_count=0, error_count=0,
        report_adapter="pytest-junitxml", report_hash="h" * 64, report_size=100,
        matched_test_entries=["tests/x.py::t"],
        code_snapshot_hash="c" * 64, test_code_hash="t" * 64,
        started_at="2026-09-02T00:00:00+00:00", finished_at="2026-09-02T00:00:01+00:00",
        duration_seconds=1.0, timeout_seconds=600, output_tail="1 passed",
        output_sha256="o" * 64, output_bytes=8, platform="darwin",
        executable=".venv/bin/python",
    )
    task = _state.TestTaskState(
        test_entries=["tests/x.py::t"], command=["pytest"], current_record=record
    )
    state = _state.WorkflowState(
        workflow_id=wf_id, intent="product_change", current_stage="qa", topics=[topic]
    )
    state.stages.setdefault("qa", _state.StageState()).test_tasks = {topic: {"TC-01": task}}
    _state.save_state(str(root), state)
    return wf_id, topic, rel


def test_reference_backfill_keeps_machine_facts(tmp_path):
    """Workflow-Test
    主题：退回验收计划后新增主题能走通门禁与追踪表
    测试项：TC-18 机器任务集可用时回补保留机器事实
    验收条件：AC-09 引用回补不覆盖已生成的机器事实
    测试方式：自动化测试
    测试层级：模块测试
    产品入口：workflow gate topic_acceptance 引用回补
    测试入口：tests/test_return_rework_flow.py::test_reference_backfill_keeps_machine_facts
    代码入口：src/workflow_loop/records.py::_refresh_stage_document
    准备数据：已填 test_result 表与一条带机器通过记录的 qa 任务
    执行动作：调用 _refresh_stage_document 回补刷新结果文档
    关键断言：回补成功且文档含机器记录编号并通过结论不含未执行行
    预期证据：pytest 结构化 junit 报告 1 条通过且退出码 0
    """
    wf_id, topic, rel = _ac09_project(tmp_path)
    paths = records_mod._refresh_stage_document(str(tmp_path), wf_id, "test_result", topic)
    assert paths
    doc = (tmp_path / paths[0]).read_text(encoding="utf-8")
    assert "RUN-TEST-1" in doc
    assert "自动化测试结果：通过" in doc
    assert "未执行" not in doc


def test_reference_backfill_refuses_empty_task_set(tmp_path):
    """Workflow-Test
    主题：退回验收计划后新增主题能走通门禁与追踪表
    测试项：TC-19 机器任务集不可用时拒绝重写结果文档
    验收条件：AC-09 引用回补不覆盖已生成的机器事实
    测试方式：自动化测试
    测试层级：模块测试
    产品入口：workflow gate topic_acceptance 引用回补
    测试入口：tests/test_return_rework_flow.py::test_reference_backfill_refuses_empty_task_set
    代码入口：src/workflow_loop/records.py::_refresh_stage_document
    准备数据：结果文档已生成后把 state 换成其他轮次使机器任务集不可用
    执行动作：再次调用 _refresh_stage_document
    关键断言：返回空列表且磁盘文档逐字节不变
    预期证据：pytest 结构化 junit 报告 1 条通过且退出码 0
    """
    from workflow_loop import state as _state

    wf_id, topic, rel = _ac09_project(tmp_path)
    paths = records_mod._refresh_stage_document(str(tmp_path), wf_id, "test_result", topic)
    doc_full = tmp_path / paths[0]
    before = doc_full.read_text(encoding="utf-8")
    other = _state.WorkflowState(
        workflow_id="other-run", intent="product_change", current_stage="qa", topics=[topic]
    )
    _state.save_state(str(tmp_path), other)
    assert records_mod._refresh_stage_document(str(tmp_path), wf_id, "test_result", topic) == []
    assert doc_full.read_text(encoding="utf-8") == before


# ─── BUG-10：失效检查按登记责任范围比较 ───


def _ac10_state(root: Path):
    """构造带 impl 绑定与登记快照的活动轮次；架构文档只登记 src/a.py。"""
    from workflow_loop import verification as verification_mod

    _install_project(root)
    _write(root / "src" / "a.py", "value = 1\n")
    _write(root / "src" / "b.py", "value = 2\n")  # 登记集合外的既有文件
    _write(root / "src" / "c.py", "value = 3\n")  # 稍后被合法新登记的文件
    _write(
        root / "spec" / "代码架构设计.md",
        "# 架构\n\n| 场景 | 代码位置 | 说明 |\n|---|---|---|\n"
        "| 甲 | `src/a.py::f` | 已登记 |\n",
    )
    state = state_mod.WorkflowState(
        workflow_id="run-ac10",
        intent="product_change",
        run_status="active",
        current_stage="impl",
        topics=["甲"],
        stage_path=["impl"],
        stages={"impl": state_mod.StageState(status="done")},
    )
    # 先落盘再算快照：登记责任范围只在该轮活动状态可见时才精确
    _save_state(root, state)
    state = verification_mod.load_state(str(root))
    state.verification.impl_hash = verification_mod.compute_impl_hash(str(root), ["甲"])
    state.meta.setdefault("registered_snapshots", {})["impl"] = (
        verification_mod.compute_registered_file_snapshot(str(root), scope="product")
    )
    _save_state(root, state)
    return verification_mod.load_state(str(root))


def _ac10_arch(root: Path, extra_rows: str = "") -> None:
    _write(
        root / "spec" / "代码架构设计.md",
        "# 架构\n\n| 场景 | 代码位置 | 说明 |\n|---|---|---|\n"
        "| 甲 | `src/a.py::f` | 已登记 |\n" + extra_rows,
    )


def _inspection_facts(inspection) -> str:
    parts = [finding.reason for finding in inspection.findings]
    parts += [
        f"{d.check_id}|{d.location}|{d.actual}" for d in inspection.diagnostics
    ]
    return "\n".join(parts)


def test_invalidation_no_phantom_added_after_registry_expands(tmp_path):
    """Workflow-Test
    主题：退回验收计划后新增主题能走通门禁与追踪表
    测试项：TC-20 登记外既有文件不再被幻影报为新增核心代码
    验收条件：AC-10 登记快照基线用登记范围比较不误报
    测试方式：自动化测试
    测试层级：模块测试
    产品入口：后续阶段门禁的验证失效检查
    测试入口：tests/test_return_rework_flow.py::test_invalidation_no_phantom_added_after_registry_expands
    代码入口：src/workflow_loop/verification.py::inspect_invalidation
    准备数据：impl 绑定已确认且登记快照只含 src/a.py，登记集合外存在未修改的 src/b.py
    执行动作：修改已登记的 src/a.py 触发 impl 绑定变化并运行只读失效检查
    关键断言：失效事实列出 src/a.py 且全文不出现未登记的 src/b.py
    预期证据：pytest 结构化 junit 报告 1 条通过且退出码 0
    """
    from workflow_loop import verification as verification_mod

    state = _ac10_state(tmp_path)
    _write(tmp_path / "src" / "a.py", "value = 999\n")

    inspection = verification_mod.inspect_invalidation(state, str(tmp_path))

    facts = _inspection_facts(inspection)
    # 真实修改必须进入失效事实（finding 或阻塞诊断都算）
    assert "src/a.py" in facts
    # BUG-10 修复点：登记快照外的既有文件不再被幻影报成新增核心代码
    assert "src/b.py" not in facts


def test_invalidation_attributes_newly_registered_change(tmp_path):
    """Workflow-Test
    主题：退回验收计划后新增主题能走通门禁与追踪表
    测试项：TC-21 新登记文件的真实变化仍能归属
    验收条件：AC-10 登记快照基线用登记范围比较不误报
    测试方式：自动化测试
    测试层级：模块测试
    产品入口：后续阶段门禁的验证失效检查
    测试入口：tests/test_return_rework_flow.py::test_invalidation_attributes_newly_registered_change
    代码入口：src/workflow_loop/verification.py::inspect_invalidation
    准备数据：登记快照只含 src/a.py；把 src/c.py 合法新登记并修改其内容
    执行动作：修改 src/c.py 并更新架构登记后触发失效检查
    关键断言：失效事实列出 src/c.py 进入登记且未登记的 src/b.py 不出现
    预期证据：pytest 结构化 junit 报告 1 条通过且退出码 0
    """
    from workflow_loop import verification as verification_mod

    state = _ac10_state(tmp_path)
    _write(tmp_path / "src" / "c.py", "value = 42\n")
    _ac10_arch(tmp_path, "| 丙 | `src/c.py::g` | 本轮新登记 |\n")

    inspection = verification_mod.inspect_invalidation(state, str(tmp_path))

    facts = _inspection_facts(inspection)
    assert "src/c.py" in facts
    assert "src/b.py" not in facts
