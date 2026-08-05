import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

import pytest

from workflow_loop import PRODUCT_NAME, __version__
from workflow_loop import cli
from workflow_loop import installer
from workflow_loop import project


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW_CMD = [sys.executable, "-m", "workflow_loop.cli"]
UPDATE_TOPIC = "已安装项目一条命令更新到目标正式版本"
PROJECT_UNINSTALL_TOPIC = "从当前项目强制卸载 Workflow Loop"
GLOBAL_UNINSTALL_TOPIC = "单独卸载电脑全局 Workflow Loop 命令"


def _tree_hash(root: Path) -> str:
    digest = hashlib.sha256()
    if not root.exists() and not root.is_symlink():
        return digest.hexdigest()
    paths = [root]
    if root.is_dir() and not root.is_symlink():
        paths.extend(sorted(root.rglob("*")))
    for path in paths:
        digest.update(path.relative_to(root.parent).as_posix().encode("utf-8"))
        if path.is_symlink():
            digest.update(os.readlink(path).encode("utf-8"))
        elif path.is_file():
            digest.update(path.read_bytes())
    return digest.hexdigest()


def _write_legacy_project(root: Path, version: str = "0.0.9") -> None:
    workflow_root = root / ".workflow_loop"
    template = workflow_root / "Template_Repository"
    standardized = workflow_root / "Standardized_Repository"
    template.mkdir(parents=True)
    standardized.mkdir(parents=True)
    (template / "legacy-template.md").write_text("legacy template", encoding="utf-8")
    (standardized / "legacy-standard.md").write_text("legacy standard", encoding="utf-8")
    (root / "AGENTS.md").write_text("legacy agents", encoding="utf-8")
    (workflow_root / "project.json").write_text(
        json.dumps(
            {
                "installer_version": version,
                "installed_at": "2026-01-01T00:00:00+00:00",
                "project_design_initialized": True,
                "topic_history": ["保留的历史主题"],
                "test_entry": {"default": ["pytest", "-q"]},
                "test_parallelism": 3,
                "artifact_file_keys": {"feature": {"显示名": "stable-key"}},
                "custom_project_field": "keep-me",
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


def _install_current_project(root: Path) -> None:
    token = root / ".install-token.json"
    token.write_text(
        json.dumps(
            {
                "product": PRODUCT_NAME,
                "version": __version__,
                "project_root": str(root.resolve()),
                "allowed_paths": sorted(installer.PROJECT_WRITE_PATHS),
                "used": False,
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    assert installer.install_project_transaction(str(root), str(token)) == 0


def _run_cli(arguments: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    environment = os.environ.copy()
    environment["PYTHONPATH"] = os.pathsep.join(
        part
        for part in (str(ROOT / "src"), environment.get("PYTHONPATH", ""))
        if part
    )
    return subprocess.run(
        WORKFLOW_CMD + arguments,
        cwd=cwd,
        env=environment,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )


def test_update_preflight_cancel_and_exact_root_are_read_only(
    tmp_path, monkeypatch, capsys
):
    """Workflow-Test
    主题：已安装项目一条命令更新到目标正式版本
    测试项：TC-01 更新预检和取消保持零修改
    验收条件：AC-01 根目录预检和一次确认
    测试方式：自动化测试
    测试层级：命令测试
    测试目标：更新只接受当前项目根，完整显示范围，并在用户取消时保持电脑和项目零修改
    测试入口：tests/test_maintenance.py::test_update_preflight_cancel_and_exact_root_are_read_only
    代码入口：workflow_loop.cli.cmd_update
    """
    _write_legacy_project(tmp_path)
    before = _tree_hash(tmp_path)
    maintenance_calls = []
    confirmations = []
    monkeypatch.setattr(cli, "_resolve_update_version", lambda _value: __version__)
    monkeypatch.setattr(
        cli,
        "_run_maintenance_script",
        lambda *args: maintenance_calls.append(args) or 0,
    )
    monkeypatch.setattr(
        "builtins.input",
        lambda prompt: confirmations.append(prompt) or "n",
    )
    monkeypatch.chdir(tmp_path)

    cli.cmd_update(SimpleNamespace(version=None))

    output = capsys.readouterr().out
    assert len(confirmations) == 1
    assert maintenance_calls == []
    assert _tree_hash(tmp_path) == before
    assert "当前项目版本: 0.0.9" in output
    assert f"目标正式版本: {__version__}" in output
    assert "不创建备份" in output
    for relative in installer.UPDATE_PROJECT_PATHS:
        assert str(tmp_path.joinpath(*relative.split("/"))) in output

    child = tmp_path / "child"
    child.mkdir()
    monkeypatch.chdir(child)
    with pytest.raises(SystemExit) as stopped:
        cli.cmd_update(SimpleNamespace(version=None))
    assert stopped.value.code == 1
    assert "不会向父目录查找" in capsys.readouterr().out
    assert _tree_hash(tmp_path) != hashlib.sha256().hexdigest()
    assert (tmp_path / ".workflow_loop").is_dir()


def test_update_version_resolution_accepts_only_matching_stable_releases(monkeypatch):
    """Workflow-Test
    主题：已安装项目一条命令更新到目标正式版本
    测试项：TC-02 正式版本和发布来源判断
    验收条件：AC-02 目标正式版本选择正确
    测试方式：自动化测试
    测试层级：模块测试
    测试目标：默认、指定和相等正式版本可用，降级、预发布、缺失或两个发布来源不一致时拒绝
    测试入口：tests/test_maintenance.py::test_update_version_resolution_accepts_only_matching_stable_releases
    代码入口：workflow_loop.cli._resolve_update_version
    """
    pypi = {
        "info": {"version": "0.2.0"},
        "releases": {
            "0.0.9": [{"yanked": False}],
            "0.1.0": [{"yanked": False}],
            "0.2.0": [{"yanked": False}],
            "0.3.0rc1": [{"yanked": False}],
        },
    }
    github = {"tag_name": "v0.2.0", "draft": False, "prerelease": False}
    monkeypatch.setattr(
        cli,
        "_fetch_json",
        lambda url: pypi if "pypi" in url else github,
    )

    assert cli._resolve_update_version(None) == "0.2.0"
    assert cli._resolve_update_version("0.2.0") == "0.2.0"
    github["tag_name"] = "v0.1.0"
    assert cli._resolve_update_version("0.1.0") == "0.1.0"

    github["tag_name"] = "v0.0.9"
    with pytest.raises(ValueError, match="不允许降级"):
        cli._resolve_update_version("0.0.9")
    with pytest.raises(ValueError, match="不是正式版本"):
        cli._resolve_update_version("0.3.0rc1")
    with pytest.raises(ValueError, match="没有可用"):
        cli._resolve_update_version("9.9.9")
    github["tag_name"] = "v9.9.9"
    with pytest.raises(ValueError, match="两个来源不一致"):
        cli._resolve_update_version("0.2.0")


def test_update_overwrites_static_management_and_preserves_runtime_data(tmp_path):
    """Workflow-Test
    主题：已安装项目一条命令更新到目标正式版本
    测试项：TC-05 静态管理文件覆盖且运行资料保留
    验收条件：AC-05 项目覆盖和保留范围准确
    测试方式：自动化测试
    测试层级：集成测试
    测试目标：只覆盖契约、两套静态仓库和安装版本字段，运行资料、项目字段、业务代码与正式产物保持不变
    测试入口：tests/test_maintenance.py::test_update_overwrites_static_management_and_preserves_runtime_data
    代码入口：workflow_loop.installer.update_project
    """
    _write_legacy_project(tmp_path)
    workflow_root = tmp_path / ".workflow_loop"
    preserved = {
        workflow_root / "state.json": '{"run_status":"active"}\n',
        workflow_root / "journal.jsonl": '{"event":"keep"}\n',
        workflow_root / "rollback" / "copy.txt": "rollback-copy",
        tmp_path / "src" / "business.py": "answer = 42\n",
        tmp_path / "spec" / "正式产物.md": "accepted",
    }
    for path, content in preserved.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    before_hashes = {path: _tree_hash(path) for path in preserved}
    project_path = workflow_root / "project.json"
    before_project = json.loads(project_path.read_text(encoding="utf-8"))

    result = installer.update_project(str(tmp_path), expected_installed_version="0.0.9")

    assert result.success
    assert result.changed_paths == [
        "AGENTS.md",
        ".workflow_loop/Template_Repository",
        ".workflow_loop/Standardized_Repository",
        ".workflow_loop/project.json:installer_version",
    ]
    assert (tmp_path / "AGENTS.md").read_text(encoding="utf-8") == installer.AGENTS_MD_CONTENT
    assert not (workflow_root / "Template_Repository" / "legacy-template.md").exists()
    assert not (workflow_root / "Standardized_Repository" / "legacy-standard.md").exists()
    after_project = json.loads(project_path.read_text(encoding="utf-8"))
    assert after_project.pop("installer_version") == __version__
    before_project.pop("installer_version")
    assert after_project == before_project
    assert {path: _tree_hash(path) for path in preserved} == before_hashes


def test_update_invalidates_old_material_confirmation_without_removing_run(tmp_path):
    """Workflow-Test
    主题：已安装项目一条命令更新到目标正式版本
    测试项：TC-06 变化材料使旧确认失效
    验收条件：AC-06 进行中轮次重新确认变化材料
    测试方式：自动化测试
    测试层级：命令测试
    测试目标：更新当前环节使用的规范后保留进行中轮次，但后续门禁拒绝沿用旧讨论确认
    测试入口：tests/test_maintenance.py::test_update_invalidates_old_material_confirmation_without_removing_run
    代码入口：workflow_loop.installer.update_project；workflow_loop.cli.cmd_gate
    """
    _install_current_project(tmp_path)
    project_path = tmp_path / ".workflow_loop" / "project.json"
    project_data = json.loads(project_path.read_text(encoding="utf-8"))
    project_data["project_design_initialized"] = True
    project_path.write_text(
        json.dumps(project_data, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    material = (
        tmp_path
        / ".workflow_loop"
        / "Standardized_Repository"
        / "spec"
        / "spec.md"
    )
    material.write_text("old spec material", encoding="utf-8")

    started = _run_cli(["start", "--intent", "product_change"], tmp_path)
    assert started.returncode == 0, started.stdout + started.stderr
    discussed = _run_cli(["discuss"], tmp_path)
    assert discussed.returncode == 0, discussed.stdout + discussed.stderr
    first_gate = _run_cli(["gate", "spec", "--discuss-done"], tmp_path)
    assert first_gate.returncode == 0, first_gate.stdout + first_gate.stderr
    state_path = tmp_path / ".workflow_loop" / "state.json"
    workflow_id = json.loads(state_path.read_text(encoding="utf-8"))["workflow_id"]

    project_data = json.loads(project_path.read_text(encoding="utf-8"))
    project_data["installer_version"] = "0.0.9"
    project_path.write_text(
        json.dumps(project_data, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    updated = installer.update_project(str(tmp_path), expected_installed_version="0.0.9")
    assert updated.success
    stale_gate = _run_cli(["gate", "spec"], tmp_path)

    assert stale_gate.returncode == 0
    assert "讨论材料已变化" in stale_gate.stdout
    assert "旧的讨论确认已经失效" in stale_gate.stdout
    assert "workflow discuss" in stale_gate.stdout
    state = json.loads(state_path.read_text(encoding="utf-8"))
    assert state["workflow_id"] == workflow_id
    assert state["run_status"] == "active"
    assert state["stages"]["spec"]["gate"]["discussion_complete"] is False


def test_update_failure_keeps_real_partial_result_and_retry_completes(
    tmp_path, monkeypatch
):
    """Workflow-Test
    主题：已安装项目一条命令更新到目标正式版本
    测试项：TC-07 残缺项目和中途失败报告真实版本
    验收条件：AC-07 异常结果真实并允许重试
    测试方式：自动化测试
    测试层级：集成测试
    测试目标：残缺骨架零写入，中途失败不回滚已覆盖内容并能在解除故障后补齐
    测试入口：tests/test_maintenance.py::test_update_failure_keeps_real_partial_result_and_retry_completes
    代码入口：workflow_loop.project.inspect_skeleton_for_update；workflow_loop.installer.update_project
    """
    broken = tmp_path / "broken"
    _write_legacy_project(broken)
    (broken / "AGENTS.md").unlink()
    before_broken = _tree_hash(broken)
    rejected = installer.update_project(str(broken))
    assert not rejected.success
    assert _tree_hash(broken) == before_broken

    target = tmp_path / "partial"
    _write_legacy_project(target)
    original_sync = installer._sync_plain_tree
    calls = []

    def fail_second_tree(source: str, destination: str) -> None:
        calls.append(destination)
        if len(calls) == 2:
            raise PermissionError("injected standardized repository failure")
        original_sync(source, destination)

    monkeypatch.setattr(installer, "_sync_plain_tree", fail_second_tree)
    partial = installer.update_project(str(target), expected_installed_version="0.0.9")
    assert not partial.success
    assert partial.changed_paths[:3] == [
        "AGENTS.md",
        ".workflow_loop/Template_Repository",
        ".workflow_loop/Standardized_Repository",
    ]
    assert "injected standardized repository failure" in partial.failures[0]
    assert json.loads(
        (target / ".workflow_loop" / "project.json").read_text(encoding="utf-8")
    )["installer_version"] == "0.0.9"
    assert (target / "AGENTS.md").read_text(encoding="utf-8") == installer.AGENTS_MD_CONTENT

    monkeypatch.setattr(installer, "_sync_plain_tree", original_sync)
    retry = installer.update_project(str(target), expected_installed_version="0.0.9")
    assert retry.success
    assert project.check_skeleton(str(target)).state == "installed"


def test_project_uninstall_scope_cancel_and_child_directory_are_safe(
    tmp_path, monkeypatch, capsys
):
    """Workflow-Test
    主题：从当前项目强制卸载 Workflow Loop
    测试项：TC-01 项目卸载范围和取消保持零修改
    验收条件：AC-01 根目录检查和一次确认
    测试方式：自动化测试
    测试层级：命令测试
    测试目标：项目根完整显示固定删除范围，取消零修改，子目录不向上查找也不删除父项目
    测试入口：tests/test_maintenance.py::test_project_uninstall_scope_cancel_and_child_directory_are_safe
    代码入口：workflow_loop.cli.cmd_uninstall
    """
    _write_legacy_project(tmp_path)
    transaction = tmp_path / installer.TRANSACTION_DIRNAME
    transaction.mkdir()
    before = _tree_hash(tmp_path)
    confirmations = []
    monkeypatch.setattr(
        "builtins.input",
        lambda prompt: confirmations.append(prompt) or "n",
    )
    monkeypatch.chdir(tmp_path)

    cli.cmd_uninstall(SimpleNamespace(global_scope=False))

    output = capsys.readouterr().out
    assert len(confirmations) == 1
    assert _tree_hash(tmp_path) == before
    for relative in installer.PROJECT_UNINSTALL_PATHS:
        assert str(tmp_path / relative) in output
    assert "删除没有备份" in output

    child = tmp_path / "child"
    child.mkdir()
    monkeypatch.chdir(child)
    cli.cmd_uninstall(SimpleNamespace(global_scope=False))
    child_output = capsys.readouterr().out
    assert "已经卸载干净" in child_output
    assert (tmp_path / ".workflow_loop").is_dir()
    assert _tree_hash(tmp_path) != hashlib.sha256().hexdigest()


@pytest.mark.parametrize("run_status", ["active", "completed", "aborted"])
def test_project_uninstall_ignores_every_run_status(tmp_path, run_status):
    """Workflow-Test
    主题：从当前项目强制卸载 Workflow Loop
    测试项：TC-02 所有轮次状态均可强制卸载
    验收条件：AC-02 任何轮次状态都能强制卸载
    测试方式：自动化测试
    测试层级：集成测试
    测试目标：进行中、已完成和已作废状态都不阻止删除管理目录，也不恢复轮次中的业务修改
    测试入口：tests/test_maintenance.py::test_project_uninstall_ignores_every_run_status
    代码入口：workflow_loop.installer.uninstall_project
    """
    root = tmp_path / run_status
    _write_legacy_project(root)
    state = root / ".workflow_loop" / "state.json"
    state.write_text(json.dumps({"run_status": run_status}), encoding="utf-8")
    business = root / "business.txt"
    business.write_text(f"modified during {run_status}", encoding="utf-8")

    result = installer.uninstall_project(str(root))

    assert result.success
    assert not (root / ".workflow_loop").exists()
    assert business.read_text(encoding="utf-8") == f"modified during {run_status}"


def test_project_uninstall_removes_only_fixed_paths_and_unlinks_symlinks(tmp_path):
    """Workflow-Test
    主题：从当前项目强制卸载 Workflow Loop
    测试项：TC-03 删除完整或部分项目管理内容
    验收条件：AC-03 项目管理内容按固定范围删除
    测试方式：自动化测试
    测试层级：集成测试
    测试目标：完整或部分残留都删除固定路径，符号链接只解除链接而不删除项目外目标
    测试入口：tests/test_maintenance.py::test_project_uninstall_removes_only_fixed_paths_and_unlinks_symlinks
    代码入口：workflow_loop.installer.inspect_uninstall_scope；workflow_loop.installer.uninstall_project
    """
    external = tmp_path / "external"
    external.mkdir()
    sentinel = external / "keep.txt"
    sentinel.write_text("outside", encoding="utf-8")
    root = tmp_path / "project"
    root.mkdir()
    (root / "AGENTS.md").write_text("custom agents", encoding="utf-8")
    (root / ".workflow_loop").symlink_to(external, target_is_directory=True)
    transaction = root / installer.TRANSACTION_DIRNAME
    transaction.mkdir()

    scope = installer.inspect_uninstall_scope(str(root))
    result = installer.uninstall_project(str(root))

    assert scope.existing_paths == list(installer.PROJECT_UNINSTALL_PATHS)
    assert result.success
    assert result.changed_paths == list(installer.PROJECT_UNINSTALL_PATHS)
    assert all(not os.path.lexists(root / path) for path in installer.PROJECT_UNINSTALL_PATHS)
    assert sentinel.read_text(encoding="utf-8") == "outside"


def test_project_uninstall_preserves_business_artifacts_and_global_command(tmp_path):
    """Workflow-Test
    主题：从当前项目强制卸载 Workflow Loop
    测试项：TC-04 项目保留内容和全局命令不受影响
    验收条件：AC-04 项目业务和正式产物保持不变
    测试方式：自动化测试
    测试层级：集成测试
    测试目标：卸载不扫描或修改固定管理路径外的业务、测试、Git 数据、正式产物与隔离全局命令
    测试入口：tests/test_maintenance.py::test_project_uninstall_preserves_business_artifacts_and_global_command
    代码入口：workflow_loop.installer.uninstall_project
    """
    project_root = tmp_path / "project"
    _write_legacy_project(project_root)
    preserved = [
        project_root / "src" / "business.py",
        project_root / "tests" / "test_business.py",
        project_root / ".git" / "HEAD",
        project_root / "spec" / "功能.md",
        project_root / "acceptance" / "验收.md",
        project_root / "qa" / "测试计划.md",
        project_root / "impl" / "实施.md",
        project_root / "bug" / "缺陷.md",
        tmp_path / "global-bin" / "workflow",
    ]
    for index, path in enumerate(preserved):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"keep-{index}", encoding="utf-8")
    before = {path: _tree_hash(path) for path in preserved}

    result = installer.uninstall_project(str(project_root))

    assert result.success
    assert {path: _tree_hash(path) for path in preserved} == before


def test_project_uninstall_failure_reports_residue_and_retry_finishes(
    tmp_path, monkeypatch
):
    """Workflow-Test
    主题：从当前项目强制卸载 Workflow Loop
    测试项：TC-06 重复卸载、部分残留和删除故障可重试
    验收条件：AC-06 重复卸载和失败结果可以继续处理
    测试方式：自动化测试
    测试层级：集成测试
    测试目标：未安装重复卸载成功，删除失败保留真实残留，解除故障后只继续清理剩余路径
    测试入口：tests/test_maintenance.py::test_project_uninstall_failure_reports_residue_and_retry_finishes
    代码入口：workflow_loop.installer.uninstall_project
    """
    clean = tmp_path / "clean"
    clean.mkdir()
    assert installer.uninstall_project(str(clean)).success

    root = tmp_path / "partial"
    _write_legacy_project(root)
    transaction = root / installer.TRANSACTION_DIRNAME
    transaction.mkdir()
    original_rmtree = installer.shutil.rmtree

    def fail_workflow_tree(path, *args, **kwargs):
        if Path(path).name == ".workflow_loop":
            raise PermissionError("injected delete failure")
        return original_rmtree(path, *args, **kwargs)

    monkeypatch.setattr(installer.shutil, "rmtree", fail_workflow_tree)
    partial = installer.uninstall_project(str(root))
    assert not partial.success
    assert partial.changed_paths == ["AGENTS.md", installer.TRANSACTION_DIRNAME]
    assert ".workflow_loop: injected delete failure" in partial.failures[0]
    assert (root / ".workflow_loop").is_dir()

    monkeypatch.setattr(installer.shutil, "rmtree", original_rmtree)
    retry = installer.uninstall_project(str(root))
    assert retry.success
    assert retry.changed_paths == [".workflow_loop"]
    assert installer.uninstall_project(str(root)).success


def test_project_reinstall_after_uninstall_starts_fresh(tmp_path):
    """Workflow-Test
    主题：从当前项目强制卸载 Workflow Loop
    测试项：TC-07 卸载后重新安装得到全新状态
    验收条件：AC-07 重新安装和公开卸载入口符合边界
    测试方式：自动化测试
    测试层级：集成测试
    测试目标：卸载含轮次历史的项目后重新安装，只得到当前版本初始状态且业务文件仍在
    测试入口：tests/test_maintenance.py::test_project_reinstall_after_uninstall_starts_fresh
    代码入口：workflow_loop.installer.uninstall_project；workflow_loop.installer.install_project_transaction
    """
    _install_current_project(tmp_path)
    workflow_root = tmp_path / ".workflow_loop"
    project_path = workflow_root / "project.json"
    project_data = json.loads(project_path.read_text(encoding="utf-8"))
    project_data["topic_history"] = ["old topic"]
    project_path.write_text(json.dumps(project_data), encoding="utf-8")
    (workflow_root / "state.json").write_text('{"run_status":"active"}', encoding="utf-8")
    (workflow_root / "journal.jsonl").write_text("old journal", encoding="utf-8")
    (workflow_root / "rollback").mkdir()
    business = tmp_path / "business.txt"
    business.write_text("keep", encoding="utf-8")

    assert installer.uninstall_project(str(tmp_path)).success
    _install_current_project(tmp_path)

    fresh = json.loads(project_path.read_text(encoding="utf-8"))
    assert fresh["installer_version"] == __version__
    assert fresh["topic_history"] == []
    assert not (workflow_root / "state.json").exists()
    assert not (workflow_root / "journal.jsonl").exists()
    assert not (workflow_root / "rollback").exists()
    assert business.read_text(encoding="utf-8") == "keep"


def test_global_uninstall_warning_cancel_and_single_confirmation_are_read_only(
    tmp_path, monkeypatch, capsys
):
    """Workflow-Test
    主题：单独卸载电脑全局 Workflow Loop 命令
    测试项：TC-01 全局范围警告和取消保持零修改
    验收条件：AC-01 全局范围单独确认并明确警告
    测试方式：自动化测试
    测试层级：命令测试
    测试目标：全局卸载明确警告其它项目影响，只确认一次，取消后电脑与项目均零修改
    测试入口：tests/test_maintenance.py::test_global_uninstall_warning_cancel_and_single_confirmation_are_read_only
    代码入口：workflow_loop.cli.cmd_uninstall
    """
    _write_legacy_project(tmp_path)
    global_command = tmp_path / "isolated-global" / "workflow"
    global_command.parent.mkdir()
    global_command.write_text("global command", encoding="utf-8")
    before_project = _tree_hash(tmp_path / ".workflow_loop")
    before_global = _tree_hash(global_command)
    confirmations = []
    maintenance_calls = []
    monkeypatch.setattr(
        "builtins.input",
        lambda prompt: confirmations.append(prompt) or "n",
    )
    monkeypatch.setattr(
        cli,
        "_run_maintenance_script",
        lambda *args: maintenance_calls.append(args) or 0,
    )
    monkeypatch.chdir(tmp_path)

    cli.cmd_uninstall(SimpleNamespace(global_scope=True))

    output = capsys.readouterr().out
    assert len(confirmations) == 1
    assert maintenance_calls == []
    assert "不会查找、扫描、读取或删除任何项目目录" in output
    assert "其它已安装项目也暂时无法运行" in output
    assert _tree_hash(tmp_path / ".workflow_loop") == before_project
    assert _tree_hash(global_command) == before_global


def test_global_uninstall_never_calls_project_scope(tmp_path, monkeypatch):
    """Workflow-Test
    主题：单独卸载电脑全局 Workflow Loop 命令
    测试项：TC-02 全局卸载不访问或删除项目
    验收条件：AC-02 全局卸载绝不扩大到项目
    测试方式：自动化测试
    测试层级：命令测试
    测试目标：从项目目录执行全局卸载时不调用项目范围检查，项目内容与所在目录不影响全局结果
    测试入口：tests/test_maintenance.py::test_global_uninstall_never_calls_project_scope
    代码入口：workflow_loop.cli.cmd_uninstall
    """
    _write_legacy_project(tmp_path)
    before = _tree_hash(tmp_path)
    calls = []
    monkeypatch.setattr("builtins.input", lambda _prompt: "y")
    monkeypatch.setattr(
        installer,
        "inspect_uninstall_scope",
        lambda _root: pytest.fail("global uninstall inspected project scope"),
    )
    monkeypatch.setattr(
        cli,
        "_run_maintenance_script",
        lambda filename, version, arguments: calls.append(
            (filename, version, arguments)
        )
        or 0,
    )
    monkeypatch.chdir(tmp_path)

    with pytest.raises(SystemExit) as finished:
        cli.cmd_uninstall(SimpleNamespace(global_scope=True))

    assert finished.value.code == 0
    assert calls == [("uninstall.sh", __version__, ["--global", "--confirmed"])]
    assert _tree_hash(tmp_path) == before
