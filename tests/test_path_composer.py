import os

from workflow_loop.path_composer import build_stage_path, INTENT_CHOICES
from workflow_loop.project import create_project, set_project_design_initialized


# 测试 from_scratch 意图的完整 stage 路径（从零开始：spec → ... → update_code_design）
def test_from_scratch_path(tmp_path):
    # 先创建项目
    create_project(str(tmp_path))
    # 构造 from_scratch 意图的 stage 序列
    stages = build_stage_path("from_scratch", str(tmp_path))
    # 提取 stage 名字列表
    names = [s.name() for s in stages]
    # 验证 10 个 stage 的顺序与 CONTEXT.md 规定一致
    assert names == [
        "spec", "code_design", "spike", "plan",
        "acceptance_plan", "test_plan", "impl",
        "test", "acceptance", "update_code_design",
    ]


# 测试 product_change 意图在 project_design 未初始化时的 stage 路径（含 project_design_init 前置）
def test_product_change_with_uninitialized(tmp_path):
    # 创建项目（project_design_initialized 默认 False）
    create_project(str(tmp_path))
    # 构造 product_change 意图的 stage 序列
    stages = build_stage_path("product_change", str(tmp_path))
    # 提取 stage 名字列表
    names = [s.name() for s in stages]
    # 验证第 1 个 stage 是 project_design_init（前置初始化）
    assert names[0] == "project_design_init"
    # 验证第 2 个 stage 是 spec
    assert names[1] == "spec"
    # 验证第 3 个 stage 是 revise_code_design（不是 code_design）
    assert names[2] == "revise_code_design"
    # 验证末段 stage 是 update_code_design
    assert names[-1] == "update_code_design"
    # 验证不包含 code_design（被 revise_code_design 替代）
    assert "code_design" not in names
    # 验证总 stage 数为 11
    assert len(names) == 11


# 测试 product_change 意图在 project_design 已初始化时跳过 project_design_init
def test_product_change_with_initialized(tmp_path):
    # 创建项目
    create_project(str(tmp_path))
    # 标记 project_design 已初始化
    set_project_design_initialized(str(tmp_path), True)
    # 构造 product_change 意图的 stage 序列
    stages = build_stage_path("product_change", str(tmp_path))
    # 提取 stage 名字列表
    names = [s.name() for s in stages]
    # 验证不再包含 project_design_init（已初始化过，跳过）
    assert "project_design_init" not in names
    # 验证仍包含 revise_code_design
    assert "revise_code_design" in names
    # 验证总 stage 数为 10（比未初始化少 1 个）
    assert len(names) == 10


# 测试 bugfix 意图在 project_design 未初始化时的 stage 路径（含 project_design_init 前置）
def test_bugfix_with_uninitialized(tmp_path):
    # 创建项目
    create_project(str(tmp_path))
    # 构造 bugfix 意图的 stage 序列
    stages = build_stage_path("bugfix", str(tmp_path))
    # 提取 stage 名字列表
    names = [s.name() for s in stages]
    # 验证第 1 个 stage 是 project_design_init
    assert names[0] == "project_design_init"
    # 验证第 2 个 stage 是 reproduce（bugfix 特有：先复现）
    assert names[1] == "reproduce"
    # 验证第 3 个 stage 是 fix_plan（bugfix 特有：修复计划）
    assert names[2] == "fix_plan"
    # 验证末段 stage 是 update_code_design
    assert names[-1] == "update_code_design"
    # 验证总 stage 数为 9
    assert len(names) == 9


# 测试 bugfix 意图在 project_design 已初始化时跳过 project_design_init
def test_bugfix_with_initialized(tmp_path):
    # 创建项目
    create_project(str(tmp_path))
    # 标记 project_design 已初始化
    set_project_design_initialized(str(tmp_path), True)
    # 构造 bugfix 意图的 stage 序列
    stages = build_stage_path("bugfix", str(tmp_path))
    # 提取 stage 名字列表
    names = [s.name() for s in stages]
    # 验证不包含 project_design_init
    assert "project_design_init" not in names
    # 验证第 1 个 stage 是 reproduce
    assert names[0] == "reproduce"
    # 验证第 2 个 stage 是 fix_plan
    assert names[1] == "fix_plan"
    # 验证总 stage 数为 8
    assert len(names) == 8


# 测试传入未知 intent 时抛 ValueError（防止拼写错误静默通过）
def test_invalid_intent_raises(tmp_path):
    # 创建项目
    create_project(str(tmp_path))
    try:
        # 传入非法 intent "invalid"，期望抛 ValueError
        build_stage_path("invalid", str(tmp_path))
        # 如果没抛异常，测试失败
        assert False, "Should have raised ValueError"
    except ValueError as e:
        # 验证异常信息包含非法 intent 名（中英文皆可）
        assert "invalid" in str(e).lower() or "未知" in str(e)


# 测试 INTENT_CHOICES 常量包含三种合法意图
def test_intent_choices():
    # 验证意图列表顺序与内容
    assert INTENT_CHOICES == ["from_scratch", "product_change", "bugfix"]
