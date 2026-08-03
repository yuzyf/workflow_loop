import json
import os

from workflow_loop.project import (
    ProjectState, load_project, save_project, is_project_design_initialized,
    set_project_design_initialized, is_installed, create_project, register_topics,
)


# 测试 create_project：首次安装时初始化 project.json 并写入默认字段
def test_create_project(tmp_path):
    # 在空目录创建项目
    project = create_project(str(tmp_path))
    # 验证 installer_version 默认值
    assert project.installer_version == "0.1.0"
    # 验证 project_design_initialized 默认 False（未做过 project_design_init）
    assert project.project_design_initialized is False
    assert project.topic_history == []
    assert project.test_parallelism == 2
    # 验证 installed_at 非空（写入时间戳）
    assert project.installed_at != ""
    # 拼出 project.json 的预期路径
    path = os.path.join(str(tmp_path), ".workflow_loop", "project.json")
    # 验证文件确实落盘
    assert os.path.exists(path)


# 测试 load_project 在 project.json 不存在时返回 None（项目未安装）
def test_load_project_returns_none_if_not_exists(tmp_path):
    # 验证空目录读回 None，不抛异常
    assert load_project(str(tmp_path)) is None


# 测试 is_project_design_initialized / set_project_design_initialized 读写一致
def test_is_project_design_initialized(tmp_path):
    # 先创建项目
    create_project(str(tmp_path))
    # 验证初始状态为 False
    assert is_project_design_initialized(str(tmp_path)) is False
    # 标记为 True（用户做完了 project_design_init stage）
    set_project_design_initialized(str(tmp_path), True)
    # 验证读回 True
    assert is_project_design_initialized(str(tmp_path)) is True


# 测试 set_project_design_initialized 在 project.json 缺失时也能自动创建（幂等安装场景）
def test_set_project_design_initialized_creates_if_missing(tmp_path):
    # 直接在空目录调用 set（不先 create_project）
    set_project_design_initialized(str(tmp_path), True)
    # 读回 project
    project = load_project(str(tmp_path))
    # 验证 project 被自动创建
    assert project is not None
    # 验证标记被正确写入
    assert project.project_design_initialized is True


# 测试 is_installed：只有 project.json 不能冒充完整安装骨架
def test_is_installed_rejects_project_state_without_complete_skeleton(tmp_path):
    """Workflow-Test
    主题：一次安装后可在三种操作系统开始使用工作流
    测试项：TC-04 所有失败路径恢复确认前状态
    验收条件：AC-04 异常不留下半套安装
    测试方式：自动化测试 + 人工验收
    测试层级：单元测试
    测试目标：空目录和只有项目状态文件的残缺骨架都不能被判定为已安装
    测试入口：tests/test_project.py::test_is_installed_rejects_project_state_without_complete_skeleton
    代码入口：workflow_loop.project.is_installed
    """
    assert is_installed(str(tmp_path)) is False
    create_project(str(tmp_path))
    assert is_installed(str(tmp_path)) is False


# 测试 project.json 跨 Run 持久化：即使 state.json 被覆盖成 aborted，project 标记依然保留
def test_project_json_cross_run_persistence(tmp_path):
    # 创建项目
    create_project(str(tmp_path))
    # 标记 project_design 已初始化
    set_project_design_initialized(str(tmp_path), True)
    # 模拟一次旧 Run 的 state.json（已被 abort）
    fake_state_path = os.path.join(str(tmp_path), ".workflow_loop", "state.json")
    # 写入一个 aborted 状态的伪 state
    with open(fake_state_path, "w") as f:
        json.dump({"workflow_id": "old", "run_status": "aborted"}, f)
    # 验证 project 标记不受 state.json 影响（project.json 独立持久化）
    assert is_project_design_initialized(str(tmp_path)) is True


def test_register_topics_persists_and_rejects_reuse(tmp_path):
    create_project(str(tmp_path))

    register_topics(str(tmp_path), ["上传文件", "查看状态"])

    project = load_project(str(tmp_path))
    assert project.topic_history == ["上传文件", "查看状态"]

    try:
        register_topics(str(tmp_path), ["上传文件"])
        assert False, "重复主题应被拒绝"
    except ValueError as exc:
        assert "已经使用过" in str(exc)
