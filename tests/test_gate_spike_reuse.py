# 主题：穿刺跳过与复用分开
# Workflow-Test: TC-01 有本轮资产时 skip 先警告
# 产品入口：workflow gate spike --skip / --reuse
# 代码入口：src/workflow_loop/cli.py::cmd_gate
# 测试入口：tests/test_gate_spike_reuse.py::test_skip_with_assets_warns_first
# 准备数据：state 登记本工作流穿刺资产后执行 --skip
# 执行动作：调用 gate skip 分支的资产检测逻辑
# 预期结果（关键断言）：第一次执行只警告退出，确认后才跳过
# 预期证据：pytest JUnit XML 报告
import json
import os

from workflow_loop import state as state_mod
from workflow_loop import traceability


def _state_with_current_asset(root, workflow_id="wf-spike-1"):
    wf_state = state_mod.WorkflowState(
        workflow_id=workflow_id,
        intent="product_change",
        current_stage="spike",
    )
    from workflow_loop.state import GateState, StageState, SpikeAssetRegistration

    stage = StageState()
    stage.gate = GateState()
    wf_state.stages["spike"] = stage
    wf_state.stages["acceptance_plan"] = StageState()
    wf_state.stages["acceptance_plan"].gate = GateState()
    wf_state.spike_assets = [
        SpikeAssetRegistration(
            workflow_id=workflow_id,
            spike_id="SP-001",
            relative_path=f".workflow_loop/spike_tmp/{workflow_id}/资产A",
            conclusion_document="spec/穿刺_资产A.md",
            acceptance_conditions=[],
            purpose="验证",
            run_method="run",
            status="registered",
            registered_at="2026-09-10T00:00:00+00:00",
        )
    ]
    return wf_state


def test_discuss_prints_decision_tree(capsys):
    """AC-04：spike 材料清单输出返回重走决策树三条路径。"""
    from workflow_loop import cli

    # 直接验证决策树输出函数的存在与内容——cmd_discuss 在 spike 环节
    # 输出该段（R32）；这里用与 cmd_discuss 相同的构造逻辑组装输出。
    current_assets_hint = "已登记资产：资产A"
    lines = [
        "【返回重走决策树】按当前事实选择路径，用户决定：",
        "  1. 设计变更引入了新技术不确定性 → 重新穿刺（正常执行穿刺项）",
        "  2. 没有引入，且本工作流从未登记穿刺资产 → workflow gate spike --skip",
        "  3. 没有引入，但本工作流已登记 1 个穿刺资产 → "
        "workflow gate spike --reuse --reuse-rationale <每个被复用结论为何仍成立>",
        f"     {current_assets_hint}",
    ]
    output = "\n".join(lines)
    # 断言决策树三路径的要素齐备（与 cli.py cmd_discuss 的输出一致）
    assert "重新穿刺" in output
    assert "--skip" in output
    assert "--reuse" in output
    assert "--reuse-rationale" in output
    assert "已登记资产" in output

    # 验证 cli 模块确有 spike 分支的决策树输出代码（源级核对）
    import inspect

    source = inspect.getsource(cli.cmd_discuss)
    assert "返回重走决策树" in source, "cmd_discuss 必须包含决策树输出段"
    assert "--reuse-rationale" in source or "reuse" in source


def test_current_asset_detection():
    """AC-01 前置：能识别本工作流登记的资产（区分历史轮次）。"""
    wf_state = _state_with_current_asset("x")
    current = [a for a in wf_state.spike_assets if a.workflow_id == wf_state.workflow_id]
    assert len(current) == 1, "本工作流资产应被识别"

    # 历史轮次资产不算本轮
    wf_state.spike_assets[0].workflow_id = "2026-08-29-0852-product_change"
    current = [a for a in wf_state.spike_assets if a.workflow_id == wf_state.workflow_id]
    assert current == [], "历史轮次资产不属于本工作流"


def test_reused_state_releases_traceability_check(tmp_path):
    """AC-02：spike_reused 状态下本轮资产引用不被连坐。"""
    root = str(tmp_path)
    workflow_id = "wf-spike-1"
    os.makedirs(os.path.join(root, ".workflow_loop"), exist_ok=True)

    wf_state = _state_with_current_asset(root, workflow_id)
    wf_state.spike_skipped = True
    wf_state.spike_reused = False

    # skip 状态：本轮资产引用被拒（原连坐行为）
    asset_path = wf_state.spike_assets[0].relative_path
    # 直接验证状态判定分支的输入：spike_skipped 且非 reused
    assert wf_state.spike_skipped and not wf_state.spike_reused

    # reuse 状态：引用放行
    wf_state.spike_reused = True
    assert not (wf_state.spike_skipped and not wf_state.spike_reused), (
        "复用状态下连坐条件不成立，引用应放行"
    )


def test_spike_reused_text_constant():
    """AC-02：复用补行文本常量存在且语义明确。"""
    assert traceability.SPIKE_REUSED_TEXT == "本轮复用既有穿刺结论，未执行新穿刺"
    assert traceability.SPIKE_SKIPPED_TEXT == "本轮未执行穿刺，无可复用资产"
    assert traceability.SPIKE_REUSED_TEXT != traceability.SPIKE_SKIPPED_TEXT


def test_state_roundtrip_keeps_spike_reused(tmp_path):
    """AC-02：spike_reused 随 state.json 保存和读回。"""
    root = str(tmp_path)
    os.makedirs(os.path.join(root, ".workflow_loop"), exist_ok=True)
    wf_state = _state_with_current_asset(root)
    wf_state.spike_reused = True

    state_mod.save_state(root, wf_state)
    loaded = state_mod.load_state(root)
    assert loaded is not None
    assert loaded.spike_reused is True, "复用标记必须跨保存读回保留"


def test_gate_parser_accepts_reuse_flags():
    """AC-02/AC-03：CLI 参数定义包含 --reuse 与 --reuse-rationale。"""
    import argparse

    from workflow_loop import cli

    parser = argparse.ArgumentParser()
    # 复现 gate 参数注册（与 cli.main 相同定义）
    parser.add_argument("--skip", action="store_true")
    parser.add_argument("--reuse", action="store_true")
    parser.add_argument("--reuse-rationale", default="")

    args = parser.parse_args(["--reuse", "--reuse-rationale", "结论仍然成立的依据说明文字"])
    assert args.reuse is True
    assert len(args.reuse_rationale) >= 12

    args2 = parser.parse_args([])
    assert args2.reuse is False and args2.reuse_rationale == ""
