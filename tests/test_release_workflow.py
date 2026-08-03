from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]
TOPIC = "一次安装后可在三种操作系统开始使用工作流"


def _workflow() -> dict:
    return yaml.load(
        (ROOT / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8"),
        Loader=yaml.BaseLoader,
    )


def test_release_identity_and_publish_order_are_fixed():
    """Workflow-Test
    主题：一次安装后可在三种操作系统开始使用工作流
    测试项：TC-03 固定工具摘要和产品身份一致
    验收条件：AC-03 安装来源和产品身份固定
    测试方式：自动化测试 + 人工验收
    测试层级：模块测试
    测试目标：同一固定版本构建包必须先完成三平台安装验证才允许发布
    测试入口：tests/test_release_workflow.py::test_release_identity_and_publish_order_are_fixed
    代码入口：.github/workflows/release.yml
    """
    workflow = _workflow()
    jobs = workflow["jobs"]

    assert workflow["env"]["PRODUCT_VERSION"] == "0.1.0"
    assert workflow["on"]["push"]["tags"] == ["v0.1.0"]
    assert jobs["build"]["needs"] == "verify-and-test"
    assert jobs["prepublish-smoke"]["needs"] == "build"
    assert jobs["publish-pypi"]["needs"] == "prepublish-smoke"
    assert jobs["github-release"]["needs"] == "publish-pypi"
    assert "refs/tags/v0.1.0" in jobs["publish-pypi"]["if"]
    assert "refs/tags/v0.1.0" in jobs["github-release"]["if"]


def test_manual_release_run_verifies_without_publishing():
    """Workflow-Test
    主题：一次安装后可在三种操作系统开始使用工作流
    测试项：TC-02 三平台一条命令完成完整安装
    验收条件：AC-02 一条命令完成三平台安装
    测试方式：自动化测试 + 人工验收
    测试层级：模块测试
    测试目标：手动任务可完整验证三平台安装但发布任务只能由固定标签触发
    测试入口：tests/test_release_workflow.py::test_manual_release_run_verifies_without_publishing
    代码入口：.github/workflows/release.yml
    """
    workflow = _workflow()
    jobs = workflow["jobs"]

    assert "workflow_dispatch" in workflow["on"]
    assert "github.event_name == 'push'" in jobs["publish-pypi"]["if"]
    assert "github.event_name == 'push'" in jobs["github-release"]["if"]
    assert "if" not in jobs["prepublish-smoke"]


def test_prepublish_matrix_covers_platforms_and_partial_install_states():
    """Workflow-Test
    主题：一次安装后可在三种操作系统开始使用工作流
    测试项：TC-05 重复安装只补缺失一侧
    验收条件：AC-05 重复安装只补缺少部分
    测试方式：自动化测试 + 人工验收
    测试层级：模块测试
    测试目标：发布前任务在三种系统使用同一构建包验证取消、完整和缺失一侧场景
    测试入口：tests/test_release_workflow.py::test_prepublish_matrix_covers_platforms_and_partial_install_states
    代码入口：.github/workflows/release.yml
    """
    job = _workflow()["jobs"]["prepublish-smoke"]
    steps = job["steps"]
    scripts = "\n".join(step.get("run", "") for step in steps)

    assert job["strategy"]["matrix"]["os"] == [
        "ubuntu-latest",
        "macos-latest",
        "windows-latest",
    ]
    assert any(
        step.get("uses") == "actions/download-artifact@v4"
        and step.get("with", {}).get("name") == "dist"
        for step in steps
    )
    assert sum("UV_FIND_LINKS" in step.get("env", {}) for step in steps) == 4
    assert "printf 'n" in scripts
    assert '"n" | pwsh' in scripts
    assert "project_only" in scripts
    assert "projectOnly" in scripts
    assert "Remove-Item -Recurse -Force" in scripts
