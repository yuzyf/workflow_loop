import os

from workflow_loop.state import WorkflowState, StageState, GateState
from workflow_loop.verification import (
    compute_file_hash, compute_impl_hash, compute_test_plan_hash,
    compute_acceptance_plan_hash, compute_test_result_hash,
    check_invalidation, clear_stage_gates,
)


# 测试辅助函数：构造一个带 verification 哈希和 test/acceptance/test_plan stage 的 WorkflowState
def _make_state(project_root, impl_hash=None, test_plan_hash=None, acceptance_plan_hash=None, test_result_hash=None):
    # 构造基础 WorkflowState（intent=from_scratch，current_stage=test）
    state = WorkflowState(
        workflow_id="test",
        intent="from_scratch",
        current_stage="test",
        started_at="2026-07-20T00:00:00+00:00",
        stage_path=["spec", "code_design", "spike", "plan", "acceptance_plan", "test_plan", "impl", "test", "acceptance", "update_code_design"],
        topic="test_topic",
    )
    # 填充 test / acceptance / test_plan 三个 stage 的空 StageState
    state.stages = {
        "test": StageState(),
        "acceptance": StageState(),
        "test_plan": StageState(),
    }
    # 写入 impl_hash（impl --confirmed 时记录）
    state.verification.impl_hash = impl_hash
    # 写入 test_plan_hash（test_plan --confirmed 时记录）
    state.verification.test_plan_hash = test_plan_hash
    # 写入 acceptance_plan_hash（acceptance_plan --confirmed 时记录）
    state.verification.acceptance_plan_hash = acceptance_plan_hash
    # 写入 test_result_hash（test --confirmed 时记录）
    state.verification.test_result_hash = test_result_hash
    # 返回构造好的 state
    return state


# 测试 compute_file_hash：对单个文件计算 SHA256，文件不存在时返回 None
def test_compute_file_hash(tmp_path):
    # 拼出测试文件路径
    path = os.path.join(str(tmp_path), "test.txt")
    # 写入二进制内容
    with open(path, "wb") as f:
        f.write(b"hello world")
    # 计算文件哈希
    h = compute_file_hash(str(tmp_path), "test.txt")
    # 验证哈希非空
    assert h is not None
    # 验证 SHA256 长度为 64 字符
    assert len(h) == 64
    # 验证文件不存在时返回 None（不抛异常）
    assert compute_file_hash(str(tmp_path), "nonexistent.txt") is None


# 测试 compute_impl_hash 包含代码快照：impl 记录 + 项目代码任一变化都会改变哈希
def test_compute_impl_hash_includes_code_snapshot(tmp_path):
    # 创建 impl 目录
    impl_dir = os.path.join(str(tmp_path), "impl")
    os.makedirs(impl_dir)
    # 写入实施记录文件
    with open(os.path.join(impl_dir, "test_topic.md"), "w") as f:
        f.write("impl record")
    # 第一次计算 impl 哈希
    h1 = compute_impl_hash(str(tmp_path), "test_topic")
    # 第二次计算（无变化）
    h2 = compute_impl_hash(str(tmp_path), "test_topic")
    # 验证两次哈希一致（确定性）
    assert h1 == h2
    # 新增一个代码文件
    with open(os.path.join(str(tmp_path), "new_code.py"), "w") as f:
        f.write("print('hello')")
    # 再次计算 impl 哈希
    h3 = compute_impl_hash(str(tmp_path), "test_topic")
    # 验证代码变化后哈希改变（用于 invalidation 检测）
    assert h1 != h3


# 测试 check_invalidation 在无变化时返回空列表（impl 哈希一致）
def test_check_invalidation_no_change(tmp_path):
    # 创建 impl 目录
    impl_dir = os.path.join(str(tmp_path), "impl")
    os.makedirs(impl_dir)
    # 写入实施记录
    with open(os.path.join(impl_dir, "test_topic.md"), "w") as f:
        f.write("impl record")
    # 计算 impl 哈希
    impl_hash = compute_impl_hash(str(tmp_path), "test_topic")
    # 构造 state，绑定 impl_hash
    state = _make_state(str(tmp_path), impl_hash=impl_hash)
    # 检查 invalidation
    invalidations = check_invalidation(state, str(tmp_path))
    # 验证无 invalidation
    assert invalidations == []


# 测试 check_invalidation 在 impl 变化时清零 test/acceptance 的 gate（Verification Invalidation 核心机制）
def test_check_invalidation_impl_changed(tmp_path):
    # 创建 impl 目录
    impl_dir = os.path.join(str(tmp_path), "impl")
    os.makedirs(impl_dir)
    # 写入原始实施记录
    with open(os.path.join(impl_dir, "test_topic.md"), "w") as f:
        f.write("original")
    # 计算 impl 哈希
    impl_hash = compute_impl_hash(str(tmp_path), "test_topic")
    # 构造 state，绑定 impl_hash
    state = _make_state(str(tmp_path), impl_hash=impl_hash)
    # 模拟 test stage 已通过讨论和代码校验
    state.stages["test"].gate.discussion_complete = True
    state.stages["test"].gate.code_validated = True
    # 模拟 acceptance stage 已用户确认
    state.stages["acceptance"].gate.user_confirmed = True
    # 修改 impl 记录内容（触发 invalidation）
    with open(os.path.join(impl_dir, "test_topic.md"), "w") as f:
        f.write("changed")
    # 检查 invalidation
    invalidations = check_invalidation(state, str(tmp_path))
    # 验证有 1 条 invalidation
    assert len(invalidations) == 1
    # 验证 invalidation 来源是 impl，影响范围是 test/acceptance
    assert invalidations[0] == ("impl", "test/acceptance")
    # 验证 test stage 的 discussion_complete 被清零
    assert state.stages["test"].gate.discussion_complete is False
    # 验证 test stage 的 code_validated 被清零
    assert state.stages["test"].gate.code_validated is False
    # 验证 acceptance stage 的 user_confirmed 被清零
    assert state.stages["acceptance"].gate.user_confirmed is False


# 测试 check_invalidation 在 acceptance_plan 变化时清零 acceptance 和 test_plan 的 gate
def test_check_invalidation_acceptance_plan_changed(tmp_path):
    # 创建 acceptance 目录
    acc_dir = os.path.join(str(tmp_path), "acceptance")
    os.makedirs(acc_dir)
    # 写入原始 acceptance plan
    with open(os.path.join(acc_dir, "test_topic_plan.md"), "w") as f:
        f.write("original")
    # 计算 acceptance_plan 哈希
    ap_hash = compute_acceptance_plan_hash(str(tmp_path), "test_topic")
    # 构造 state，绑定 acceptance_plan_hash
    state = _make_state(str(tmp_path), acceptance_plan_hash=ap_hash)
    # 模拟 test_plan stage 已通过代码校验和用户确认
    state.stages["test_plan"].gate.code_validated = True
    state.stages["test_plan"].gate.user_confirmed = True
    # 模拟 acceptance stage 已通过讨论
    state.stages["acceptance"].gate.discussion_complete = True
    # 修改 acceptance plan 内容（触发 invalidation）
    with open(os.path.join(acc_dir, "test_topic_plan.md"), "w") as f:
        f.write("changed")
    # 检查 invalidation
    invalidations = check_invalidation(state, str(tmp_path))
    # 验证有 1 条 invalidation
    assert len(invalidations) == 1
    # 验证 invalidation 影响范围包含 acceptance
    assert "acceptance" in invalidations[0][1]
    # 验证 acceptance stage 的 discussion_complete 被清零
    assert state.stages["acceptance"].gate.discussion_complete is False
    # 验证 test_plan stage 的 code_validated 被清零
    assert state.stages["test_plan"].gate.code_validated is False
    # 验证 test_plan stage 的 user_confirmed 被清零
    assert state.stages["test_plan"].gate.user_confirmed is False
