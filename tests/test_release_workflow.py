import json
from pathlib import Path
import subprocess
import sys
import tomllib

import yaml

from workflow_loop import PRODUCT_IDENTITY, PRODUCT_NAME, __version__
from workflow_loop.project import INSTALLER_VERSION


ROOT = Path(__file__).resolve().parents[1]
TOPIC = "一次安装后可在三种操作系统开始使用工作流"


def _workflow() -> dict:
    return yaml.load(
        (ROOT / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8"),
        Loader=yaml.BaseLoader,
    )


def _print_evidence(label: str, evidence: dict) -> None:
    print(f"{label}: {json.dumps(evidence, ensure_ascii=False, sort_keys=True)}")


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


def test_current_release_identity_and_non_tag_publish_rules_are_consistent():
    """Workflow-Test
    主题：0.1.0 在 GitHub 和 PyPI 完成正式发布
    测试项：TC-01 本次版本身份和非标签发布规则一致
    验收条件：AC-01 最终发布身份和前置条件一致
    测试方式：自动化测试
    测试层级：集成测试
    测试目标：本次全部版本身份固定为 0.1.0，非标签任务不能发布，未来公开修改必须使用未被 PyPI 占用的新版本号
    测试入口：tests/test_release_workflow.py::test_current_release_identity_and_non_tag_publish_rules_are_consistent
    代码入口：workflow_loop.cli.main；.github/workflows/release.yml jobs.verify-and-test；install.sh；install.ps1
    """
    expected_version = "0.1.0"
    expected_identity = "workflow-loop 0.1.0"
    workflow = _workflow()
    jobs = workflow["jobs"]
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    project_marker = json.loads(
        (ROOT / ".workflow_loop" / "project.json").read_text(encoding="utf-8")
    )
    install_sh = (ROOT / "install.sh").read_text(encoding="utf-8")
    install_ps1 = (ROOT / "install.ps1").read_text(encoding="utf-8-sig")

    assert pyproject["project"]["name"] == "workflow-loop"
    assert pyproject["project"]["version"] == expected_version
    assert __version__ == expected_version
    assert PRODUCT_NAME == "workflow-loop"
    assert PRODUCT_IDENTITY == expected_identity
    assert INSTALLER_VERSION == expected_version
    assert project_marker["installer_version"] == expected_version
    assert 'PRODUCT_VERSION="0.1.0"' in install_sh
    assert '"${PRODUCT_NAME}==${PRODUCT_VERSION}"' in install_sh
    assert '$ProductVersion = "0.1.0"' in install_ps1
    assert '"$ProductName==$ProductVersion"' in install_ps1
    assert workflow["env"]["PRODUCT_VERSION"] == expected_version
    assert workflow["on"]["push"] == {"tags": ["v0.1.0"]}

    actual_identity = subprocess.run(
        [sys.executable, "-m", "workflow_loop.cli", "--version"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    assert actual_identity.stdout.strip() == expected_identity
    assert actual_identity.stderr == ""

    assert set(workflow["on"]) == {"workflow_dispatch", "push"}
    for job_name in ("publish-pypi", "github-release"):
        publish_condition = jobs[job_name]["if"]
        assert "github.event_name == 'push'" in publish_condition
        assert "github.ref == 'refs/tags/v0.1.0'" in publish_condition
    assert "if" not in jobs["prepublish-smoke"]

    version_strategy = {
        "产品总说明": (ROOT / "spec" / "产品总说明.md").read_text(encoding="utf-8"),
        "安装到项目": (ROOT / "spec" / "功能_安装到项目.md").read_text(encoding="utf-8"),
        "领域决定": (ROOT / "CONTEXT.md").read_text(encoding="utf-8"),
        "版本决策": (
            ROOT / "docs" / "adr" / "0002-fix-product-version-at-0-1-0.md"
        ).read_text(encoding="utf-8"),
    }
    required_future_rule = "未在 PyPI 发布过的新版本号"
    assert required_future_rule in version_strategy["产品总说明"]
    assert (
        "未在 Python 公共软件包仓库发布过的新版本号"
        in version_strategy["安装到项目"]
    )
    assert "尚未被 PyPI 占用的新版本号" in version_strategy["领域决定"]
    assert "尚未被 PyPI 占用的新版本号" in version_strategy["版本决策"]
    assert "原“产品版本永久固定为 `0.1.0`”决定已" in version_strategy["版本决策"]
    _print_evidence(
        "CURRENT_RELEASE_IDENTITY",
        {
            "actual_command_identity": actual_identity.stdout.strip(),
            "future_version_rules": {
                "CONTEXT.md": "尚未被 PyPI 占用的新版本号",
                "docs/adr/0002-fix-product-version-at-0-1-0.md": (
                    "尚未被 PyPI 占用的新版本号"
                ),
                "spec/产品总说明.md": required_future_rule,
                "spec/功能_安装到项目.md": (
                    "未在 Python 公共软件包仓库发布过的新版本号"
                ),
            },
            "publish_conditions": {
                name: jobs[name]["if"]
                for name in ("publish-pypi", "github-release")
            },
            "release_triggers": workflow["on"],
            "version_locations": {
                ".github/workflows/release.yml": workflow["env"]["PRODUCT_VERSION"],
                ".workflow_loop/project.json": project_marker["installer_version"],
                "install.ps1": expected_version,
                "install.sh": expected_version,
                "pyproject.toml": pyproject["project"]["version"],
                "src/workflow_loop/__init__.py": __version__,
                "src/workflow_loop/project.py": INSTALLER_VERSION,
            },
        },
    )


def test_release_gate_matrix_and_assets_are_structurally_complete():
    """Workflow-Test
    主题：0.1.0 在 GitHub 和 PyPI 完成正式发布
    测试项：TC-03 发布任务门控平台矩阵和附件配置正确
    验收条件：AC-02 最终标签任务全部成功
    测试方式：自动化测试
    测试层级：模块测试
    测试目标：发布配置只有在完整测试、构建和四种托管环境验证成功后才依次发布 PyPI 包和带两个安装脚本的 GitHub 正式版本
    测试入口：tests/test_release_workflow.py::test_release_gate_matrix_and_assets_are_structurally_complete
    代码入口：.github/workflows/release.yml jobs.verify-and-test、build、prepublish-smoke、publish-pypi、github-release
    """
    workflow = _workflow()
    jobs = workflow["jobs"]

    assert jobs["build"]["needs"] == "verify-and-test"
    assert jobs["prepublish-smoke"]["needs"] == "build"
    assert jobs["publish-pypi"]["needs"] == "prepublish-smoke"
    assert jobs["github-release"]["needs"] == "publish-pypi"
    assert "python -m pytest -q" in "\n".join(
        step.get("run", "") for step in jobs["verify-and-test"]["steps"]
    )
    assert "python -m build" in "\n".join(
        step.get("run", "") for step in jobs["build"]["steps"]
    )

    smoke_job = jobs["prepublish-smoke"]
    assert smoke_job["strategy"] == {
        "fail-fast": "false",
        "matrix": {
            "os": ["ubuntu-latest", "macos-latest", "windows-latest"],
        },
    }
    platform_steps = {
        step.get("name"): step
        for step in smoke_job["steps"]
        if step.get("name", "").startswith("安装脚本冒烟：")
    }
    assert set(platform_steps) == {
        "安装脚本冒烟：确认、取消与安装（Linux）",
        "安装脚本冒烟：确认、取消与安装（macOS）",
        "安装脚本冒烟：PowerShell 7（Windows）",
        "安装脚本冒烟：Windows PowerShell 5.1（Windows）",
    }
    assert platform_steps["安装脚本冒烟：确认、取消与安装（Linux）"]["if"] == (
        "runner.os == 'Linux'"
    )
    assert platform_steps["安装脚本冒烟：确认、取消与安装（macOS）"]["if"] == (
        "runner.os == 'macOS'"
    )
    pwsh_step = platform_steps["安装脚本冒烟：PowerShell 7（Windows）"]
    powershell_step = platform_steps[
        "安装脚本冒烟：Windows PowerShell 5.1（Windows）"
    ]
    assert pwsh_step["if"] == "runner.os == 'Windows'"
    assert pwsh_step["shell"] == "pwsh"
    assert '"y" | pwsh -NoProfile' in pwsh_step["run"]
    assert powershell_step["if"] == "runner.os == 'Windows'"
    assert powershell_step["shell"] == "pwsh"
    assert '"y" | powershell -NoProfile' in powershell_step["run"]

    tag_condition = "github.event_name == 'push' && github.ref == 'refs/tags/v0.1.0'"
    assert jobs["publish-pypi"]["if"] == tag_condition
    assert jobs["github-release"]["if"] == tag_condition
    assert jobs["publish-pypi"]["permissions"] == {"id-token": "write"}
    publish_steps = jobs["publish-pypi"]["steps"]
    duplicate_check = publish_steps[0]
    assert duplicate_check["name"] == "检查 PyPI 是否已存在 0.1.0"
    assert (
        "https://pypi.org/pypi/workflow-loop/${PRODUCT_VERSION}/json"
        in duplicate_check["run"]
    )
    assert 'if [ "$status" = "200" ]' in duplicate_check["run"]
    assert "不能删除、覆盖或重发" in duplicate_check["run"]
    assert "exit 1" in duplicate_check["run"]
    assert publish_steps[-1]["uses"] == "pypa/gh-action-pypi-publish@release/v1"

    release_job = jobs["github-release"]
    assert release_job["permissions"] == {"contents": "write"}
    release_step = next(
        step
        for step in release_job["steps"]
        if step.get("uses") == "softprops/action-gh-release@v2"
    )
    release_config = release_step["with"]
    assert release_config["tag_name"] == "v0.1.0"
    assert release_config["name"] == "Workflow Loop 0.1.0"
    release_body = release_config["body"]
    for expected_text in (
        "macOS、Linux 和原生 Windows 使用一条命令完成安装",
        "从零创建、修改产品和修复缺陷三种工作意图",
        "讨论完成、程序检查和用户确认三道门",
        "需求交付追踪表",
        "命令、环境、时间、退出码和代码版本等机器执行记录",
        "返回上游修正、本轮修改回退和整轮作废恢复",
        "Python 3.11 或更高版本",
    ):
        assert expected_text in release_body
    assert release_config["files"].splitlines() == ["install.sh", "install.ps1"]
    _print_evidence(
        "RELEASE_WORKFLOW_STRUCTURE",
        {
            "dependency_chain": {
                "build": jobs["build"]["needs"],
                "github-release": jobs["github-release"]["needs"],
                "prepublish-smoke": jobs["prepublish-smoke"]["needs"],
                "publish-pypi": jobs["publish-pypi"]["needs"],
            },
            "github_release": {
                "assets": release_config["files"].splitlines(),
                "body_requirements": [
                    "macOS、Linux 和原生 Windows 使用一条命令完成安装",
                    "从零创建、修改产品和修复缺陷三种工作意图",
                    "讨论完成、程序检查和用户确认三道门",
                    "需求交付追踪表",
                    "命令、环境、时间、退出码和代码版本等机器执行记录",
                    "返回上游修正、本轮修改回退和整轮作废恢复",
                    "Python 3.11 或更高版本",
                ],
                "name": release_config["name"],
                "permissions": release_job["permissions"],
                "tag": release_config["tag_name"],
            },
            "platform_matrix": smoke_job["strategy"]["matrix"]["os"],
            "platform_steps": {
                name: {
                    "if": step["if"],
                    "shell": step.get("shell", "default"),
                }
                for name, step in sorted(platform_steps.items())
            },
            "pypi_publish": {
                "duplicate_status": "200 时退出 1",
                "permissions": jobs["publish-pypi"]["permissions"],
                "publisher": publish_steps[-1]["uses"],
                "url": "https://pypi.org/pypi/workflow-loop/${PRODUCT_VERSION}/json",
            },
            "tag_condition": tag_condition,
        },
    )
