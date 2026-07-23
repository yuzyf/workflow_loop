import json
import os

from workflow_loop.state import (
    WorkflowState, StageState, GateState, ArchitectureState, VerificationState, SpikeBaselineState,
    state_to_dict, state_from_dict, load_state, save_state, is_active_run, now_iso,
)


# 测试 state 往返序列化：WorkflowState → state.json → WorkflowState 数据一致
def test_state_round_trip(tmp_path):
    # 构造一个包含嵌套 StageState 和 GateState 的完整 WorkflowState
    state = WorkflowState(
        workflow_id="2026-07-20-0347-from_scratch",
        intent="from_scratch",
        run_status="active",
        current_stage="spec",
        started_at="2026-07-20T03:47:00+00:00",
        stage_path=["spec", "code_design", "spike"],
        stages={
            "spec": StageState(
                status="in_progress",
                artifact_paths=["spec/product.md"],
                gate=GateState(discussion_complete=True, code_validated=False, user_confirmed=False),
            ),
            "code_design": StageState(status="pending", artifact_paths=["spec/architecture_code_design.md"]),
        },
        architecture=ArchitectureState(preliminary_done=False, detailed_done=False),
        verification=VerificationState(impl_hash=None, test_plan_hash=None, acceptance_plan_hash=None, test_result_hash=None),
        spike_baseline=SpikeBaselineState(
            captured_at="2026-07-20T03:48:00+00:00",
            product_design_hash="product123",
            product_design_paths=["spec/product.md", "spec/feature_example.md"],
            code_design_hash="code123",
            legacy_unavailable=False,
        ),
    )
    # 把 state 落盘到临时目录的 .workflow_loop/state.json
    save_state(str(tmp_path), state)
    # 从同一目录读回 state
    loaded = load_state(str(tmp_path))
    # 验证读回的对象非空（文件存在且解析成功）
    assert loaded is not None
    # 验证 workflow_id 往返一致
    assert loaded.workflow_id == state.workflow_id
    # 验证 intent 往返一致
    assert loaded.intent == state.intent
    # 验证 run_status 往返一致
    assert loaded.run_status == state.run_status
    # 验证 current_stage 往返一致
    assert loaded.current_stage == state.current_stage
    # 验证 stage_path 列表往返一致
    assert loaded.stage_path == state.stage_path
    # 验证嵌套 stages["spec"].status 往返一致
    assert loaded.stages["spec"].status == "in_progress"
    # 验证嵌套 gate.discussion_complete 往返一致
    assert loaded.stages["spec"].gate.discussion_complete is True
    # 验证嵌套 gate.code_validated 往返一致
    assert loaded.stages["spec"].gate.code_validated is False
    # 验证 architecture.preliminary_done 往返一致
    assert loaded.architecture.preliminary_done is False
    # 验证 verification.impl_hash 往返一致（None 不会被改成空字符串）
    assert loaded.verification.impl_hash is None
    # 验证穿刺设计基线往返一致
    assert loaded.spike_baseline.product_design_hash == "product123"
    assert loaded.spike_baseline.product_design_paths == ["spec/product.md", "spec/feature_example.md"]
    assert loaded.spike_baseline.legacy_unavailable is False


# 测试 load_state 在 state.json 不存在时返回 None（项目未初始化或首次启动）
def test_load_state_returns_none_if_not_exists(tmp_path):
    # 验证空目录读回 None，不抛异常
    assert load_state(str(tmp_path)) is None


# 测试 save_state 会自动创建 .workflow_loop/ 嵌套目录（支持深层项目路径）
def test_save_state_creates_directory(tmp_path):
    # 构造一个深层项目根路径（.workflow_loop/ 尚不存在）
    project_root = str(tmp_path / "nested" / "project")
    # 构造最小可用的 WorkflowState
    state = WorkflowState(
        workflow_id="test",
        intent="from_scratch",
        current_stage="spec",
        started_at=now_iso(),
        stage_path=["spec"],
    )
    # 保存到深层路径，应自动 mkdir -p
    save_state(project_root, state)
    # 验证 state.json 文件确实在嵌套目录中被创建
    assert os.path.exists(os.path.join(project_root, ".workflow_loop", "state.json"))


# 测试 is_active_run 判定：根据 run_status 字段区分 active / completed / aborted
def test_is_active_run(tmp_path):
    # 空目录：没有 Run，自然不是 active
    assert is_active_run(str(tmp_path)) is False
    # 构造一个 active 状态的 WorkflowState
    state = WorkflowState(
        workflow_id="test",
        intent="from_scratch",
        run_status="active",
        current_stage="spec",
        started_at=now_iso(),
        stage_path=["spec"],
    )
    # 落盘 active 状态
    save_state(str(tmp_path), state)
    # 验证 active Run 被识别为 True
    assert is_active_run(str(tmp_path)) is True
    # 把状态改成 completed（done 收工）
    state.run_status = "completed"
    # 再次落盘
    save_state(str(tmp_path), state)
    # 验证 completed Run 不再算 active
    assert is_active_run(str(tmp_path)) is False


# 测试 state.json 完整 schema 字段都正确落盘（防止后续重构悄悄丢字段）
def test_full_schema_fields(tmp_path):
    # 构造一个覆盖所有字段的 WorkflowState（bugfix 意图，多字段非默认值）
    state = WorkflowState(
        workflow_id="test",
        intent="bugfix",
        run_status="active",
        current_stage="reproduce",
        started_at="2026-07-20T03:47:00+00:00",
        ended_at=None,
        aborted_at=None,
        topic=None,
        clean_confirmed=False,
        spike_skipped=False,
        stage_path=["reproduce", "fix_plan"],
        stages={"reproduce": StageState()},
        architecture=ArchitectureState(preliminary_done=True, detailed_done=False),
        verification=VerificationState(
            impl_hash="abc123",
            test_plan_hash="def456",
            acceptance_plan_hash=None,
            test_result_hash=None,
        ),
        spike_baseline=SpikeBaselineState(
            captured_at="2026-07-20T03:48:00+00:00",
            product_design_hash="product123",
            product_design_paths=["spec/product.md"],
            code_design_hash="code123",
            legacy_unavailable=True,
        ),
    )
    # 落盘
    save_state(str(tmp_path), state)
    # 直接打开 state.json 原始 JSON，绕过 dataclass 反序列化
    with open(os.path.join(str(tmp_path), ".workflow_loop", "state.json")) as f:
        data = json.load(f)
    # 验证顶层 intent 字段存在
    assert "intent" in data
    # 验证顶层 run_status 字段存在
    assert "run_status" in data
    # 验证顶层 ended_at 字段存在（即使值为 None）
    assert "ended_at" in data
    # 验证顶层 aborted_at 字段存在
    assert "aborted_at" in data
    # 验证顶层 clean_confirmed 字段存在
    assert "clean_confirmed" in data
    # 验证顶层 spike_skipped 字段存在
    assert "spike_skipped" in data
    # 验证顶层 stage_path 字段存在
    assert "stage_path" in data
    # 验证顶层 architecture 子对象存在
    assert "architecture" in data
    # 验证顶层 verification 子对象存在
    assert "verification" in data
    # 验证顶层 spike_baseline 子对象存在
    assert "spike_baseline" in data
    # 验证 architecture.preliminary_done 子字段存在
    assert "preliminary_done" in data["architecture"]
    # 验证 architecture.detailed_done 子字段存在
    assert "detailed_done" in data["architecture"]
    # 验证 verification.impl_hash 子字段存在
    assert "impl_hash" in data["verification"]
    # 验证 verification.impl_hash 的值正确落盘
    assert data["verification"]["impl_hash"] == "abc123"
    # 验证穿刺基线字段正确落盘
    assert data["spike_baseline"]["product_design_hash"] == "product123"
    assert data["spike_baseline"]["code_design_hash"] == "code123"
    assert data["spike_baseline"]["legacy_unavailable"] is True


# 测试旧 state.json 没有 spike_baseline 时仍可读取
def test_old_state_without_spike_baseline_is_compatible():
    data = {
        "workflow_id": "legacy",
        "intent": "from_scratch",
        "current_stage": "spike",
        "started_at": "2026-07-20T03:47:00+00:00",
        "stage_path": ["spec", "code_design", "spike"],
        "stages": {},
    }

    loaded = state_from_dict(data)

    assert loaded.spike_baseline.captured_at is None
    assert loaded.spike_baseline.product_design_paths == []
    assert loaded.spike_baseline.legacy_unavailable is False
