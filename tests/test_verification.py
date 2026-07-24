import os

from workflow_loop.project import create_project, register_topics
from workflow_loop.state import WorkflowState, StageState, GateState, save_state
from workflow_loop.verification import (
    compute_file_hash, compute_impl_hash, compute_test_plan_hash,
    compute_acceptance_plan_hash, compute_test_result_hash,
    compute_product_design_hash, compute_code_design_hash,
    get_linked_product_design_paths, check_invalidation, clear_stage_gates,
)


# 测试辅助函数：构造一个已经进入后半段、带验证哈希的 WorkflowState
def _make_state(project_root, impl_hash=None, test_plan_hash=None, acceptance_plan_hash=None, test_result_hash=None):
    stage_path = [
        "acceptance_plan", "test_plan", "plan", "topic_execution",
        "regression_test", "overall_acceptance", "update_code_design",
    ]
    state = WorkflowState(
        workflow_id="test",
        intent="from_scratch",
        current_stage="regression_test",
        started_at="2026-07-20T00:00:00+00:00",
        stage_path=stage_path,
        topics=["test_topic"],
    )
    state.stages = {
        stage_name: StageState(
            status="done",
            gate=GateState(True, True, True),
        )
        for stage_name in stage_path
    }
    state.stages["regression_test"].status = "in_progress"
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


def test_product_design_hash_uses_only_linked_feature_documents(tmp_path):
    spec_dir = tmp_path / "spec"
    spec_dir.mkdir()
    (spec_dir / "product.md").write_text(
        "[功能 A](./feature_a.md)\n[外部文档](https://example.com)\n",
        encoding="utf-8",
    )
    (spec_dir / "feature_a.md").write_text("A", encoding="utf-8")
    (spec_dir / "feature_old.md").write_text("old", encoding="utf-8")

    paths = get_linked_product_design_paths(str(tmp_path))
    first_hash, _ = compute_product_design_hash(str(tmp_path))
    (spec_dir / "feature_old.md").write_text("changed old", encoding="utf-8")
    second_hash, _ = compute_product_design_hash(str(tmp_path))

    assert paths == ["spec/feature_a.md", "spec/product.md"]
    assert first_hash == second_hash


def test_product_and_code_design_hash_change_with_content(tmp_path):
    spec_dir = tmp_path / "spec"
    spec_dir.mkdir()
    (spec_dir / "product.md").write_text("[功能 A](./feature_a.md)\n", encoding="utf-8")
    (spec_dir / "feature_a.md").write_text("A", encoding="utf-8")
    (spec_dir / "architecture_code_design.md").write_text("code v1", encoding="utf-8")

    product_hash_1, _ = compute_product_design_hash(str(tmp_path))
    code_hash_1 = compute_code_design_hash(str(tmp_path))
    (spec_dir / "feature_a.md").write_text("A changed", encoding="utf-8")
    (spec_dir / "architecture_code_design.md").write_text("code v2", encoding="utf-8")

    product_hash_2, _ = compute_product_design_hash(str(tmp_path))
    code_hash_2 = compute_code_design_hash(str(tmp_path))
    assert product_hash_1 != product_hash_2
    assert code_hash_1 != code_hash_2


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


# 测试实施内容变化时退回 topic_execution（主题执行）
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
    # 修改 impl 记录内容（触发 invalidation）
    with open(os.path.join(impl_dir, "test_topic.md"), "w") as f:
        f.write("changed")
    # 检查 invalidation
    invalidations = check_invalidation(state, str(tmp_path))
    # 验证有 1 条 invalidation
    assert len(invalidations) == 1
    # 验证实施变化会让主题测试、主题验收、最终回归和整体验收失效
    assert invalidations[0] == (
        "impl",
        "topic_execution 及全部后续阶段",
    )
    assert state.current_stage == "topic_execution"
    assert state.stages["topic_execution"].status == "in_progress"
    assert state.stages["regression_test"].gate.code_validated is False
    assert state.verification.impl_hash is None


# 测试验收计划变化时退回 acceptance_plan（验收计划）
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
    # 修改 acceptance plan 内容（触发 invalidation）
    with open(os.path.join(acc_dir, "test_topic_plan.md"), "w") as f:
        f.write("changed")
    # 检查 invalidation
    invalidations = check_invalidation(state, str(tmp_path))
    # 验证有 1 条 invalidation
    assert len(invalidations) == 1
    # 验证验收计划变化会让测试计划、实施计划和执行结果失效
    assert invalidations[0] == (
        "acceptance_plan",
        "acceptance_plan 及全部后续阶段",
    )
    assert state.current_stage == "acceptance_plan"
    assert state.stages["acceptance_plan"].status == "in_progress"
    assert state.stages["test_plan"].gate.code_validated is False
    assert state.verification.acceptance_plan_hash is None


def test_new_acceptance_topic_invalidates_confirmed_plan(tmp_path):
    create_project(str(tmp_path))
    acc_dir = tmp_path / "acceptance"
    acc_dir.mkdir()
    (acc_dir / "test_topic_plan.md").write_text("original", encoding="utf-8")
    register_topics(str(tmp_path), ["test_topic"])

    state = _make_state(str(tmp_path))
    state.verification.acceptance_plan_hash = compute_acceptance_plan_hash(
        str(tmp_path),
        ["test_topic"],
    )
    save_state(str(tmp_path), state)

    (acc_dir / "new_topic_plan.md").write_text("new", encoding="utf-8")
    invalidations = check_invalidation(state, str(tmp_path))

    assert invalidations == [("acceptance_plan", "acceptance_plan 及全部后续阶段")]
    assert state.current_stage == "acceptance_plan"
