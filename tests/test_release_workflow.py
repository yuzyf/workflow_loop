import json
import os
from pathlib import Path
import subprocess
import sys
import tomllib
from urllib.request import urlopen

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
    主题：0.2.0 在 GitHub 和 PyPI 完成正式发布
    测试项：TC-04 发布作业顺序、平台矩阵和六个附件配置完整
    验收条件：AC-03 最终标签任务全部成功
    测试方式：自动化测试
    测试层级：模块测试
    测试目标：同一固定版本构建包必须先完成四种托管环境安装、更新和卸载验证才允许发布
    测试入口：tests/test_release_workflow.py::test_release_identity_and_publish_order_are_fixed
    代码入口：.github/workflows/release.yml
    """
    workflow = _workflow()
    jobs = workflow["jobs"]

    assert workflow["env"]["PRODUCT_VERSION"] == __version__
    assert workflow["on"]["push"]["tags"] == [f"v{__version__}"]
    assert jobs["build"]["needs"] == "verify-and-test"
    assert jobs["prepublish-smoke"]["needs"] == "build"
    assert jobs["publish-pypi"]["needs"] == "prepublish-smoke"
    assert jobs["github-release"]["needs"] == "publish-pypi"
    assert f"refs/tags/v{__version__}" in jobs["publish-pypi"]["if"]
    assert f"refs/tags/v{__version__}" in jobs["github-release"]["if"]


def test_manual_release_run_verifies_without_publishing():
    """Workflow-Test
    主题：0.2.0 在 GitHub 和 PyPI 完成正式发布
    测试项：TC-03 手动任务和普通分支不能公开发布
    验收条件：AC-02 只有 v0.2.0 标签可以公开发布
    测试方式：自动化测试
    测试层级：模块测试
    测试目标：手动任务和普通分支只验证，不上传 PyPI 或创建 GitHub Release
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
    主题：0.2.0 在 GitHub 和 PyPI 完成正式发布
    测试项：TC-04 发布作业顺序、平台矩阵和六个附件配置完整
    验收条件：AC-03 最终标签任务全部成功
    测试方式：自动化测试
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
    主题：0.2.0 在 GitHub 和 PyPI 完成正式发布
    测试项：TC-01 本地版本身份和发布配置统一为 0.2.0
    验收条件：AC-01 全部发布身份统一为 0.2.0
    测试方式：自动化测试
    测试层级：集成测试
    测试目标：本次全部版本身份固定为 0.2.0，非标签任务不能发布，未来公开修改必须使用未被 PyPI 占用的新版本号
    测试入口：tests/test_release_workflow.py::test_current_release_identity_and_non_tag_publish_rules_are_consistent
    代码入口：workflow_loop.cli.main；.github/workflows/release.yml jobs.verify-and-test；install.sh；install.ps1
    """
    expected_version = __version__
    expected_identity = f"workflow-loop {expected_version}"
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
    assert f'PRODUCT_VERSION="{expected_version}"' in install_sh
    assert '"${PRODUCT_NAME}==${PRODUCT_VERSION}"' in install_sh
    assert f'$ProductVersion = "{expected_version}"' in install_ps1
    assert '"$ProductName==$ProductVersion"' in install_ps1
    assert workflow["env"]["PRODUCT_VERSION"] == expected_version
    assert workflow["on"]["push"] == {"tags": [f"v{expected_version}"]}

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
        assert f"github.ref == 'refs/tags/v{expected_version}'" in publish_condition
    assert "if" not in jobs["prepublish-smoke"]

    version_strategy = {
        "产品总说明": (ROOT / "spec" / "产品总说明.md").read_text(encoding="utf-8"),
        "安装到项目": (ROOT / "spec" / "功能_安装到项目.md").read_text(encoding="utf-8"),
    }
    historical_version_decision = (
        ROOT / "docs" / "adr" / "0002-fix-product-version-at-0-1-0.md"
    ).read_text(encoding="utf-8")
    required_future_rule = "未在 PyPI 发布过的新版本号"
    assert required_future_rule in version_strategy["产品总说明"]
    assert (
        "未在 Python 公共软件包仓库发布过的新版本号"
        in version_strategy["安装到项目"]
    )
    assert "已被后续发布与项目更新功能取代" in historical_version_decision
    _print_evidence(
        "CURRENT_RELEASE_IDENTITY",
        {
            "actual_command_identity": actual_identity.stdout.strip(),
            "future_version_rules": {
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
    主题：0.2.0 在 GitHub 和 PyPI 完成正式发布
    测试项：TC-04 发布作业顺序、平台矩阵和六个附件配置完整
    验收条件：AC-03 最终标签任务全部成功
    测试方式：自动化测试
    测试层级：模块测试
    测试目标：发布配置只有在完整测试、构建和四种托管环境验证成功后才依次发布 PyPI 包和带六个维护脚本的 GitHub 正式版本
    测试入口：tests/test_release_workflow.py::test_release_gate_matrix_and_assets_are_structurally_complete
    代码入口：.github/workflows/release.yml jobs.verify-and-test、build、prepublish-smoke、publish-pypi、github-release
    """
    workflow = _workflow()
    jobs = workflow["jobs"]

    assert jobs["build"]["needs"] == "verify-and-test"
    assert jobs["prepublish-smoke"]["needs"] == "build"
    assert jobs["publish-pypi"]["needs"] == "prepublish-smoke"
    assert jobs["github-release"]["needs"] == "publish-pypi"
    verify_script = "\n".join(
        step.get("run", "") for step in jobs["verify-and-test"]["steps"]
    )
    assert "python -m pytest -q" in verify_script
    assert 'uv.lock' in verify_script
    assert '.workflow_loop/project.json' in verify_script
    assert 'README.md' in verify_script
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

    tag_condition = (
        "github.event_name == 'push' && "
        f"github.ref == 'refs/tags/v{__version__}'"
    )
    assert jobs["publish-pypi"]["if"] == tag_condition
    assert jobs["github-release"]["if"] == tag_condition
    assert jobs["publish-pypi"]["permissions"] == {"id-token": "write"}
    publish_steps = jobs["publish-pypi"]["steps"]
    duplicate_check = publish_steps[0]
    assert duplicate_check["name"] == f"检查 PyPI 是否已存在 {__version__}"
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
    assert release_config["tag_name"] == f"v{__version__}"
    assert release_config["name"] == f"Workflow Loop {__version__}"
    release_body = release_config["body"]
    for expected_text in (
        "macOS、Linux 和原生 Windows 使用一条命令完成安装",
        "支持从零创建、修改产品、修复缺陷和无需开发任务四种工作意图",
        "完整研发任务的每个正式环节依次经过讨论完成、程序检查和用户确认三道门",
        "无需开发任务按调查讨论、执行约定任务、核对结果和用户确认结果的简单流程处理",
        "需求交付追踪表",
        "命令、环境、时间、退出码和代码版本等机器执行记录",
        "返回上游修正、本轮修改回退和整轮作废恢复",
        "Python 3.11 或更高版本",
    ):
        assert expected_text in release_body
    assert release_config["files"].splitlines() == [
        "install.sh",
        "install.ps1",
        "update.sh",
        "update.ps1",
        "uninstall.sh",
        "uninstall.ps1",
    ]
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
                    "支持从零创建、修改产品、修复缺陷和无需开发任务四种工作意图",
                    "完整研发任务的每个正式环节依次经过讨论完成、程序检查和用户确认三道门",
                    "无需开发任务按调查讨论、执行约定任务、核对结果和用户确认结果的简单流程处理",
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


def test_update_release_assets_and_readme_entries_are_consistent():
    """Workflow-Test
    主题：已安装项目一条命令更新到目标正式版本
    测试项：TC-08 更新发布资产和 README 入口一致
    验收条件：AC-08 正式发布提供一条命令更新入口
    测试方式：自动化测试 + 人工验收
    测试层级：集成测试
    测试目标：正式发布携带两个同版本更新脚本，README 提供命令更新和旧版脚本更新的三平台入口
    测试入口：tests/test_release_workflow.py::test_update_release_assets_and_readme_entries_are_consistent
    代码入口：.github/workflows/release.yml；update.sh；update.ps1；README.md
    """
    workflow = _workflow()
    release_step = next(
        step
        for step in workflow["jobs"]["github-release"]["steps"]
        if step.get("uses") == "softprops/action-gh-release@v2"
    )
    assets = release_step["with"]["files"].splitlines()
    shell = (ROOT / "update.sh").read_text(encoding="utf-8")
    powershell = (ROOT / "update.ps1").read_text(encoding="utf-8-sig")
    readme = (ROOT / "README.md").read_text(encoding="utf-8")

    assert "update.sh" in assets and "update.ps1" in assets
    assert f'SCRIPT_VERSION="{__version__}"' in shell
    assert f'$ScriptVersion = "{__version__}"' in powershell
    assert "workflow update" in readme
    assert f"workflow update --version {__version__}" in readme
    assert "/releases/latest/download/update.sh" in readme
    assert "/releases/latest/download/update.ps1" in readme
    assert "不创建备份" in readme and "重新执行同一命令" in readme


def test_update_release_smoke_uses_deterministic_metadata(tmp_path):
    """Workflow-Test
    主题：已安装项目一条命令更新到目标正式版本
    测试项：TC-04 旧版本脚本跨版本更新
    验收条件：AC-04 旧版本可以直接跨版本更新
    测试方式：自动化测试 + 人工验收
    测试层级：模块测试
    测试目标：发布冒烟在各平台使用本地固定版本元数据验证更新，同时用户脚本默认仍读取真实公开发布源
    测试入口：tests/test_release_workflow.py::test_update_release_smoke_uses_deterministic_metadata
    代码入口：.github/workflows/release.yml jobs.prepublish-smoke；update.sh；update.ps1
    """
    workflow = _workflow()
    steps = workflow["jobs"]["prepublish-smoke"]["steps"]
    metadata_step = next(
        step for step in steps if step.get("name") == "准备发布冒烟固定版本元数据"
    )
    metadata_index = steps.index(metadata_step)
    download_index = next(
        index
        for index, step in enumerate(steps)
        if step.get("uses") == "actions/download-artifact@v4"
    )
    platform_indexes = [
        index
        for index, step in enumerate(steps)
        if step.get("name", "").startswith("安装脚本冒烟：")
    ]

    assert metadata_step["shell"] == "python"
    assert download_index < metadata_index < min(platform_indexes)

    github_env = tmp_path / "github-env"
    environment = os.environ.copy()
    environment.update(
        {
            "GITHUB_ENV": str(github_env),
            "PRODUCT_VERSION": workflow["env"]["PRODUCT_VERSION"],
            "RUNNER_TEMP": str(tmp_path),
        }
    )
    subprocess.run(
        [sys.executable, "-c", metadata_step["run"]],
        cwd=ROOT,
        env=environment,
        check=True,
        capture_output=True,
        text=True,
    )

    metadata_urls = dict(
        line.split("=", 1)
        for line in github_env.read_text(encoding="utf-8").splitlines()
    )
    assert set(metadata_urls) == {
        "WORKFLOW_LOOP_PYPI_JSON_URL",
        "WORKFLOW_LOOP_GITHUB_API_URL",
    }
    assert all(url.startswith("file://") for url in metadata_urls.values())

    version = workflow["env"]["PRODUCT_VERSION"]
    with urlopen(metadata_urls["WORKFLOW_LOOP_PYPI_JSON_URL"]) as response:
        pypi = json.load(response)
    assert pypi == {
        "info": {"version": version},
        "releases": {version: [{"yanked": False}]},
    }

    github_base = metadata_urls["WORKFLOW_LOOP_GITHUB_API_URL"]
    for suffix in (f"releases/tags/v{version}", "releases/latest"):
        with urlopen(f"{github_base}/{suffix}") as response:
            github = json.load(response)
        assert github == {
            "tag_name": f"v{version}",
            "draft": False,
            "prerelease": False,
        }

    platform_scripts = "\n".join(steps[index]["run"] for index in platform_indexes)
    assert "update.sh" in platform_scripts
    assert "update.ps1" in platform_scripts

    shell = (ROOT / "update.sh").read_text(encoding="utf-8")
    powershell = (ROOT / "update.ps1").read_text(encoding="utf-8-sig")
    for script in (shell, powershell):
        assert "WORKFLOW_LOOP_PYPI_JSON_URL" in script
        assert "WORKFLOW_LOOP_GITHUB_API_URL" in script
        assert "https://pypi.org/pypi/workflow-loop/json" in script
        assert "https://api.github.com/repos/yuzyf/workflow_loop" in script


def test_project_uninstall_release_assets_and_readme_boundary_are_complete():
    """Workflow-Test
    主题：从当前项目强制卸载 Workflow Loop
    测试项：TC-08 卸载发布资产和 README 项目入口完整
    验收条件：AC-07 重新安装和公开卸载入口符合边界
    测试方式：自动化测试 + 人工验收
    测试层级：集成测试
    测试目标：正式发布携带两个同版本卸载脚本，README 明确项目卸载命令、删除范围、保留范围和不可恢复边界
    测试入口：tests/test_release_workflow.py::test_project_uninstall_release_assets_and_readme_boundary_are_complete
    代码入口：.github/workflows/release.yml；uninstall.sh；uninstall.ps1；README.md
    """
    workflow = _workflow()
    release_step = next(
        step
        for step in workflow["jobs"]["github-release"]["steps"]
        if step.get("uses") == "softprops/action-gh-release@v2"
    )
    assets = release_step["with"]["files"].splitlines()
    shell = (ROOT / "uninstall.sh").read_text(encoding="utf-8")
    powershell = (ROOT / "uninstall.ps1").read_text(encoding="utf-8-sig")
    readme = (ROOT / "README.md").read_text(encoding="utf-8")

    assert "uninstall.sh" in assets and "uninstall.ps1" in assets
    assert f'PRODUCT_VERSION="{__version__}"' in shell
    assert f'$ProductVersion = "{__version__}"' in powershell
    assert "workflow uninstall" in readme
    assert "AGENTS.md、整个 .workflow_loop/ 和安装事务残留" in readme
    assert "不恢复本轮业务修改" in readme
    assert "删除没有备份" in readme
    assert "/releases/latest/download/uninstall.sh" in readme
    assert "/releases/latest/download/uninstall.ps1" in readme


def test_windows_powershell_matrix_covers_global_self_uninstall_contract():
    """Workflow-Test
    主题：单独卸载电脑全局 Workflow Loop 命令
    测试项：TC-04 两种 Windows PowerShell 完成命令自卸载
    验收条件：AC-04 受支持的 Windows PowerShell 能完成自卸载
    测试方式：自动化测试 + 人工验收
    测试层级：端到端测试
    测试目标：PowerShell 5.1 和 7 远程任务都执行全局卸载，脚本等待父命令并按真实退出码分别处理标准输出与错误输出
    测试入口：tests/test_release_workflow.py::test_windows_powershell_matrix_covers_global_self_uninstall_contract
    代码入口：.github/workflows/release.yml；workflow_loop.cli._run_maintenance_script；uninstall.ps1
    """
    steps = _workflow()["jobs"]["prepublish-smoke"]["steps"]
    windows_runs = {
        step["name"]: step["run"]
        for step in steps
        if step.get("name")
        in {
            "安装脚本冒烟：PowerShell 7（Windows）",
            "安装脚本冒烟：Windows PowerShell 5.1（Windows）",
        }
    }
    cli_source = (ROOT / "src" / "workflow_loop" / "cli.py").read_text(
        encoding="utf-8"
    )
    script = (ROOT / "uninstall.ps1").read_text(encoding="utf-8-sig")

    assert set(windows_runs) == {
        "安装脚本冒烟：PowerShell 7（Windows）",
        "安装脚本冒烟：Windows PowerShell 5.1（Windows）",
    }
    assert "pwsh -NoProfile" in windows_runs["安装脚本冒烟：PowerShell 7（Windows）"]
    assert "powershell -NoProfile" in windows_runs[
        "安装脚本冒烟：Windows PowerShell 5.1（Windows）"
    ]
    assert all("uninstall.ps1\" -Global -Confirmed" in run for run in windows_runs.values())
    assert '"-WaitForProcessId"' in cli_source
    assert "[int]$WaitForProcessId = 0" in script
    assert "while (Get-Process -Id $WaitForProcessId" in script
    assert "$process.StandardOutput.ReadToEndAsync()" in script
    assert "$process.StandardError.ReadToEndAsync()" in script
    assert "ExitCode = $process.ExitCode" in script


def test_readme_separates_project_and_global_uninstall_boundaries():
    """Workflow-Test
    主题：单独卸载电脑全局 Workflow Loop 命令
    测试项：TC-06 README 区分两种卸载范围
    验收条件：AC-06 公开说明区分项目卸载和全局卸载
    测试方式：自动化测试 + 人工验收
    测试层级：模块测试
    测试目标：README 分开给出项目和全局卸载入口，并说明全局卸载不删除项目但会让依赖项目暂时不能运行
    测试入口：tests/test_release_workflow.py::test_readme_separates_project_and_global_uninstall_boundaries
    代码入口：README.md
    """
    readme = (ROOT / "README.md").read_text(encoding="utf-8")

    assert "项目卸载和电脑全局命令卸载是两个独立动作" in readme
    assert "workflow uninstall\n" in readme
    assert "workflow uninstall --global" in readme
    assert "只删除电脑全局命令；不会扫描或删除任何项目" in readme
    assert "其它已安装项目仍保留" in readme
    assert "重新安装全局命令前不能运行 `workflow`" in readme
