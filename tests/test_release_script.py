from __future__ import annotations

import json
import hashlib
from pathlib import Path
import shutil
import subprocess
from collections.abc import Sequence

import pytest
import yaml

from scripts import release as release_script


ROOT = Path(__file__).resolve().parents[1]
VERSION = "0.3.0"
BASELINE_VERSION = "0.2.0"


def _run_git(root: Path, *arguments: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *arguments],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    )


def _copy_release_inputs(target: Path) -> None:
    current_version = release_script.read_current_version(ROOT)
    current_bytes = current_version.encode("ascii")
    baseline_bytes = BASELINE_VERSION.encode("ascii")
    for relative_path in release_script.CURRENT_VERSION_FILES:
        source = ROOT / relative_path
        destination = target / relative_path
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
        content = destination.read_bytes()
        assert current_bytes in content
        destination.write_bytes(content.replace(current_bytes, baseline_bytes))

    project_state = target / release_script.PROJECT_STATE_PATH
    project_state.parent.mkdir(parents=True, exist_ok=True)
    state = json.loads(
        (ROOT / release_script.PROJECT_STATE_PATH).read_text(encoding="utf-8")
    )
    state["installer_version"] = BASELINE_VERSION
    project_state.write_text(
        json.dumps(state, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _initialize_repository(root: Path) -> None:
    _run_git(root, "init", "--initial-branch=main")
    _run_git(root, "config", "user.name", "Workflow Loop Test")
    _run_git(root, "config", "user.email", "workflow-loop@example.invalid")
    _run_git(root, "add", "-A")
    _run_git(root, "commit", "-m", "baseline")


def _expected_release_commands(version: str) -> list[list[str]]:
    return [
        ["uv", "lock"],
        ["git", "add", "-A"],
        ["git", "commit", "-m", f"release: prepare workflow-loop {version}"],
        ["git", "push", "origin", "HEAD:main"],
        ["git", "tag", "-a", f"v{version}", "-m", f"Workflow Loop {version}"],
        ["git", "push", "origin", f"v{version}"],
    ]


def test_release_updates_only_current_identity_and_preserves_history(tmp_path: Path):
    """Workflow-Test
    主题：当前仓库可由一条命令直接发布为新版本
    测试项：TC-01 当前发布身份更新且历史事实不变
    验收条件：AC-01 只更新当前发布身份并纳入全部当前修改
    测试方式：自动化测试
    测试层级：集成测试
    产品入口：`uv run python scripts/release.py 0.3.0`
    测试入口：`tests/test_release_script.py::test_release_updates_only_current_identity_and_preserves_history`
    代码入口：`scripts/release.py::update_release_identity`
    准备数据：在临时目录复制 10 个当前版本身份文件和项目状态；旧版本设为 0.2.0，新版本设为 0.3.0；项目状态保留包含 0.2.0 的历史主题和正式文件标识；另准备脚本执行前已有的未忽略修改清单
    执行动作：调用真实版本身份更新入口，再通过发布编排的纳入修改命令检查提交输入范围
    关键断言：10 个固定身份文件和安装版本全部使用 0.3.0；历史主题与历史正式文件字节不变；旧有未忽略修改和版本修改都进入同一提交输入集合
    预期证据：pytest JUnit XML 结构化报告、各目标文件修改前后哈希、项目历史字段比较和 Git 暂存路径集合
    """
    _copy_release_inputs(tmp_path)
    historical_document = tmp_path / "acceptance" / "0_2_0_历史验收.md"
    historical_document.parent.mkdir(parents=True)
    historical_document.write_text("0.2.0 已正式发布。\n", encoding="utf-8")
    existing_change = tmp_path / "notes.txt"
    existing_change.write_text("修改前\n", encoding="utf-8")
    _initialize_repository(tmp_path)

    original_state = json.loads(
        (tmp_path / release_script.PROJECT_STATE_PATH).read_text(encoding="utf-8")
    )
    original_history = historical_document.read_bytes()
    identity_paths = [
        *(tmp_path / path for path in release_script.CURRENT_VERSION_FILES),
        tmp_path / release_script.PROJECT_STATE_PATH,
    ]
    hashes_before = {path.relative_to(tmp_path): _sha256(path) for path in identity_paths}
    existing_change.write_text("脚本调用前已经修改\n", encoding="utf-8")
    (tmp_path / "new-file.txt").write_text("脚本调用前已经新增\n", encoding="utf-8")

    release_script.update_release_identity(tmp_path, BASELINE_VERSION, VERSION)

    commands: list[list[str]] = []

    def recording_runner(step: str, command: Sequence[str], root: Path) -> None:
        del step
        arguments = list(command)
        commands.append(arguments)
        if arguments == ["git", "add", "-A"]:
            _run_git(root, "add", "-A")

    release_script.run_release(VERSION, tmp_path, recording_runner)

    for relative_path in release_script.CURRENT_VERSION_FILES:
        content = (tmp_path / relative_path).read_bytes()
        assert VERSION.encode("ascii") in content
        assert b"0.2.0" not in content

    updated_state = json.loads(
        (tmp_path / release_script.PROJECT_STATE_PATH).read_text(encoding="utf-8")
    )
    expected_state = dict(original_state)
    expected_state["installer_version"] = VERSION
    assert updated_state == expected_state
    assert historical_document.read_bytes() == original_history
    hashes_after = {path.relative_to(tmp_path): _sha256(path) for path in identity_paths}
    assert hashes_after.keys() == hashes_before.keys()
    assert all(hashes_after[path] != hashes_before[path] for path in hashes_before)

    staged_paths = set(_run_git(tmp_path, "diff", "--cached", "--name-only").stdout.splitlines())
    expected_paths = {str(path) for path in release_script.CURRENT_VERSION_FILES}
    expected_paths.update(
        {
            str(release_script.PROJECT_STATE_PATH),
            "notes.txt",
            "new-file.txt",
        }
    )
    assert staged_paths == expected_paths
    assert commands == _expected_release_commands(VERSION)


def test_release_runs_only_confirmed_actions_in_order(tmp_path: Path):
    """Workflow-Test
    主题：当前仓库可由一条命令直接发布为新版本
    测试项：TC-02 发布动作顺序固定且不执行本地检查
    验收条件：AC-02 调用后按固定顺序触发远程发布且不做本地检查
    测试方式：自动化测试
    测试层级：模块测试
    产品入口：`uv run python scripts/release.py 0.3.0`
    测试入口：`tests/test_release_script.py::test_release_runs_only_confirmed_actions_in_order`
    代码入口：`scripts/release.py::run_release`
    准备数据：使用 0.3.0 作为新版本；给真实发布编排入口传入只记录参数、不执行外部命令的执行器
    执行动作：调用真实发布编排入口，收集它准备执行的每一步名称、参数数组和工作目录
    关键断言：命令恰好依次为 `uv lock`、`git add -A`、发布提交、推送 `origin HEAD:main`、创建带说明的 `v0.3.0` 标签、推送 `v0.3.0`；没有测试、构建、远程查询、二次确认或强制参数；标签与远程任务触发条件一致
    预期证据：pytest JUnit XML 结构化报告、完整命令参数数组和远程标签触发配置
    """
    _copy_release_inputs(tmp_path)
    release_script.update_release_identity(tmp_path, BASELINE_VERSION, VERSION)
    calls: list[tuple[str, list[str], Path]] = []

    def recording_runner(step: str, command: Sequence[str], root: Path) -> None:
        calls.append((step, list(command), root))

    release_script.run_release(VERSION, tmp_path, recording_runner)

    assert [command for _, command, _ in calls] == _expected_release_commands(VERSION)
    assert all(root == tmp_path for _, _, root in calls)
    assert len({step for step, _, _ in calls}) == len(calls)

    workflow = yaml.load(
        (tmp_path / ".github" / "workflows" / "release.yml").read_text(
            encoding="utf-8"
        ),
        Loader=yaml.BaseLoader,
    )
    assert workflow["on"]["push"]["tags"] == [f"v{VERSION}"]
    assert f"refs/tags/v{VERSION}" in workflow["jobs"]["publish-pypi"]["if"]
    assert f"refs/tags/v{VERSION}" in workflow["jobs"]["github-release"]["if"]

    all_arguments = [argument for _, command, _ in calls for argument in command]
    assert not ({"pytest", "build", "curl", "gh", "--force", "--force-with-lease"} & set(all_arguments))


def test_release_stops_after_each_failed_action_without_force_or_rollback(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    """Workflow-Test
    主题：当前仓库可由一条命令直接发布为新版本
    测试项：TC-03 每个失败位置都停止后续动作且不回滚
    验收条件：AC-03 任一步失败立即停止且保留真实状态
    测试方式：自动化测试
    测试层级：模块测试
    产品入口：`uv run python scripts/release.py 0.3.0`
    测试入口：`tests/test_release_script.py::test_release_stops_after_each_failed_action_without_force_or_rollback`
    代码入口：`scripts/release.py::run_command`
    准备数据：对依赖锁定、纳入修改、提交、分支推送、标签创建和标签推送六个位置分别设置执行器在该步失败；为前置步骤保存可识别的完成记录
    执行动作：每次调用真实发布编排入口直到安排的步骤失败，捕获错误并检查已记录命令、后续命令和完成记录
    关键断言：六种失败都以非成功结果停止；错误包含准确步骤名；失败后的命令数为零；失败前记录保持；全部命令没有强制覆盖、重置、删除标签或自动回滚
    预期证据：pytest JUnit XML 结构化报告、六个失败位置参数、逐轮命令序列、错误步骤名和保留记录
    """
    expected_commands = _expected_release_commands(VERSION)
    step_names = [
        "更新依赖锁定",
        "纳入当前全部修改",
        "创建发布提交",
        "推送远程默认分支",
        "创建本地版本标签",
        "推送版本标签",
    ]

    for failed_index, failed_step in enumerate(step_names):
        attempted: list[list[str]] = []
        completed: list[list[str]] = []

        def fail_at_selected_step(
            arguments: Sequence[str],
            *,
            cwd: Path,
            check: bool,
        ) -> subprocess.CompletedProcess[str]:
            assert cwd == tmp_path
            assert check is True
            command = list(arguments)
            attempted.append(command)
            if len(attempted) - 1 == failed_index:
                raise subprocess.CalledProcessError(41, command)
            completed.append(command)
            return subprocess.CompletedProcess(command, 0)

        monkeypatch.setattr(release_script.subprocess, "run", fail_at_selected_step)
        with pytest.raises(release_script.ReleaseError, match=failed_step) as error:
            release_script.run_release(VERSION, tmp_path)

        assert "退出码 41" in str(error.value)
        assert attempted == expected_commands[: failed_index + 1]
        assert completed == expected_commands[:failed_index]
        assert all(
            argument not in {"--force", "--force-with-lease", "reset", "delete"}
            for command in attempted
            for argument in command
        )
