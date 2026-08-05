import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

from workflow_loop import __version__


ROOT = Path(__file__).resolve().parents[1]


def _write_legacy_project(root: Path, version: str = "0.0.9") -> None:
    template = root / ".workflow_loop" / "Template_Repository"
    standardized = root / ".workflow_loop" / "Standardized_Repository"
    template.mkdir(parents=True)
    standardized.mkdir(parents=True)
    (template / "legacy.md").write_text("legacy template", encoding="utf-8")
    (standardized / "legacy.md").write_text("legacy standard", encoding="utf-8")
    (root / "AGENTS.md").write_text("legacy agents", encoding="utf-8")
    (root / ".workflow_loop" / "project.json").write_text(
        json.dumps(
            {
                "installer_version": version,
                "installed_at": "2026-01-01T00:00:00+00:00",
                "project_design_initialized": True,
                "topic_history": ["history"],
                "test_entry": {},
                "test_parallelism": 2,
                "artifact_file_keys": {},
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )


def _write_workflow_wrapper(path: Path, version: str) -> None:
    path.write_text(
        "#!/usr/bin/env bash\n"
        "set -eu\n"
        "if [ \"${1:-}\" = \"--version\" ]; then\n"
        f"  echo \"workflow-loop {version}\"\n"
        "  exit 0\n"
        "fi\n"
        "exec \"${TEST_PYTHON}\" -m workflow_loop.cli \"$@\"\n",
        encoding="utf-8",
    )
    path.chmod(0o755)


def _write_fake_uv(path: Path) -> None:
    path.write_text(
        """#!/usr/bin/env bash
set -eu
printf '%s\n' "$*" >> "${FAKE_UV_LOG}"
if [ "${1:-}" = "--version" ]; then
  echo "uv 0.11.33"
  exit 0
fi
if [ "${1:-}" = "run" ]; then
  shift
  while [ "$#" -gt 0 ]; do
    if [ "$1" = "python" ]; then
      shift
      exec "${TEST_PYTHON}" "$@"
    fi
    shift
  done
  exit 64
fi
if [ "${1:-}" = "tool" ] && [ "${2:-}" = "run" ]; then
  shift 2
  while [ "$#" -gt 0 ] && [ "$1" != "workflow" ]; do shift; done
  [ "$#" -gt 0 ] || exit 65
  shift
  exec "${TEST_PYTHON}" -m workflow_loop.cli "$@"
fi
if [ "${1:-}" = "tool" ] && [ "${2:-}" = "install" ]; then
  [ -z "${FAKE_UV_FAIL_INSTALL:-}" ] || exit 47
  mkdir -p "${UV_TOOL_BIN_DIR}" "${UV_TOOL_DIR}/workflow-loop"
  cat > "${UV_TOOL_BIN_DIR}/workflow" <<'WRAPPER'
#!/usr/bin/env bash
set -eu
if [ "${1:-}" = "--version" ]; then
  echo "workflow-loop ${FAKE_TARGET_VERSION}"
  exit 0
fi
exec "${TEST_PYTHON}" -m workflow_loop.cli "$@"
WRAPPER
  chmod +x "${UV_TOOL_BIN_DIR}/workflow"
  exit 0
fi
if [ "${1:-}" = "tool" ] && [ "${2:-}" = "uninstall" ]; then
  [ -z "${FAKE_UV_FAIL_UNINSTALL:-}" ] || exit 48
  rm -f "${UV_TOOL_BIN_DIR}/workflow"
  rm -rf "${UV_TOOL_DIR}/workflow-loop"
  exit 0
fi
exit 66
""",
        encoding="utf-8",
    )
    path.chmod(0o755)


def _isolated_environment(tmp_path: Path, global_version: str = "0.0.9") -> dict[str, str]:
    if os.name == "nt" or shutil.which("bash") is None:
        pytest.skip("Bash 脚本由 macOS/Linux 本地测试和远程平台任务验证")
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    _write_fake_uv(fake_bin / "uv")
    _write_workflow_wrapper(fake_bin / "workflow", global_version)
    tool_dir = tmp_path / "tools"
    (tool_dir / "workflow-loop").mkdir(parents=True)
    log = tmp_path / "uv.log"
    log.write_text("", encoding="utf-8")
    home = tmp_path / "home"
    data = home / ".local" / "share"
    home.mkdir()
    data.mkdir(parents=True)

    pypi = tmp_path / "pypi.json"
    pypi.write_text(
        json.dumps(
            {
                "info": {"version": __version__},
                "releases": {__version__: [{"yanked": False}]},
            }
        ),
        encoding="utf-8",
    )
    github = tmp_path / "github"
    latest = github / "releases" / "latest"
    tagged = github / "releases" / "tags" / f"v{__version__}"
    latest.parent.mkdir(parents=True)
    tagged.parent.mkdir(parents=True)
    release = json.dumps(
        {"tag_name": f"v{__version__}", "draft": False, "prerelease": False}
    )
    latest.write_text(release, encoding="utf-8")
    tagged.write_text(release, encoding="utf-8")

    environment = os.environ.copy()
    environment.update(
        {
            "FAKE_TARGET_VERSION": __version__,
            "FAKE_UV_LOG": str(log),
            "HOME": str(home),
            "PATH": os.pathsep.join((str(fake_bin), environment.get("PATH", ""))),
            "PYTHONPATH": os.pathsep.join(
                part
                for part in (str(ROOT / "src"), environment.get("PYTHONPATH", ""))
                if part
            ),
            "TEST_PYTHON": sys.executable,
            "TMPDIR": str(tmp_path),
            "UV_TOOL_BIN_DIR": str(fake_bin),
            "UV_TOOL_DIR": str(tool_dir),
            "WORKFLOW_LOOP_GITHUB_API_URL": github.as_uri(),
            "WORKFLOW_LOOP_INSTALL_RECORD": str(data / "workflow-loop" / "install.json"),
            "WORKFLOW_LOOP_PYPI_JSON_URL": pypi.as_uri(),
            "XDG_DATA_HOME": str(data),
        }
    )
    return environment


def _run_script(
    filename: str,
    arguments: list[str],
    cwd: Path,
    environment: dict[str, str],
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", str(ROOT / filename), *arguments],
        cwd=cwd,
        env=environment,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )


def _project_version(root: Path) -> str:
    return json.loads(
        (root / ".workflow_loop" / "project.json").read_text(encoding="utf-8")
    )["installer_version"]


def test_update_script_updates_both_sides_and_only_the_lagging_side(tmp_path):
    """Workflow-Test
    主题：已安装项目一条命令更新到目标正式版本
    测试项：TC-03 两侧更新和只补落后一侧
    验收条件：AC-03 一条操作更新电脑和当前项目
    测试方式：自动化测试
    测试层级：端到端测试
    测试目标：隔离脚本覆盖两侧落后、只落后一侧和两侧达标，并且达标一侧保持不变
    测试入口：tests/test_maintenance_scripts.py::test_update_script_updates_both_sides_and_only_the_lagging_side
    代码入口：update.sh；workflow_loop.cli.cmd_internal_update_project
    """
    environment = _isolated_environment(tmp_path)
    root = tmp_path / "project"
    _write_legacy_project(root)
    business = root / "business.txt"
    business.write_text("keep", encoding="utf-8")
    log = Path(environment["FAKE_UV_LOG"])

    both_old = _run_script(
        "update.sh",
        ["--version", __version__, "--confirmed"],
        root,
        environment,
    )
    assert both_old.returncode == 0, both_old.stdout + both_old.stderr
    assert _project_version(root) == __version__
    assert subprocess.run(
        [str(Path(environment["UV_TOOL_BIN_DIR"]) / "workflow"), "--version"],
        env=environment,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip() == f"workflow-loop {__version__}"
    assert "tool install --force" in log.read_text(encoding="utf-8")
    assert business.read_text(encoding="utf-8") == "keep"

    installed_count = log.read_text(encoding="utf-8").count("tool install --force")
    project_before = (root / ".workflow_loop" / "project.json").read_bytes()
    already_current = _run_script(
        "update.sh",
        ["--version", __version__, "--confirmed"],
        root,
        environment,
    )
    assert already_current.returncode == 0, already_current.stdout + already_current.stderr
    assert log.read_text(encoding="utf-8").count("tool install --force") == installed_count
    assert (root / ".workflow_loop" / "project.json").read_bytes() == project_before

    project_data = json.loads(
        (root / ".workflow_loop" / "project.json").read_text(encoding="utf-8")
    )
    project_data["installer_version"] = "0.0.9"
    (root / ".workflow_loop" / "project.json").write_text(
        json.dumps(project_data), encoding="utf-8"
    )
    project_only = _run_script(
        "update.sh",
        ["--version", __version__, "--confirmed"],
        root,
        environment,
    )
    assert project_only.returncode == 0, project_only.stdout + project_only.stderr
    assert _project_version(root) == __version__
    assert log.read_text(encoding="utf-8").count("tool install --force") == installed_count

    _write_workflow_wrapper(
        Path(environment["UV_TOOL_BIN_DIR"]) / "workflow", "0.0.9"
    )
    project_before = (root / ".workflow_loop" / "project.json").read_bytes()
    global_only = _run_script(
        "update.sh",
        ["--version", __version__, "--confirmed"],
        root,
        environment,
    )
    assert global_only.returncode == 0, global_only.stdout + global_only.stderr
    assert log.read_text(encoding="utf-8").count("tool install --force") == installed_count + 1
    assert (root / ".workflow_loop" / "project.json").read_bytes() == project_before


def test_legacy_update_script_reaches_target_without_intermediate_install(tmp_path):
    """Workflow-Test
    主题：已安装项目一条命令更新到目标正式版本
    测试项：TC-04 旧版本脚本跨版本更新
    验收条件：AC-04 旧版本可以直接跨版本更新
    测试方式：自动化测试 + 人工验收
    测试层级：端到端测试
    测试目标：没有更新命令的旧项目通过一个公开脚本直接把全局命令和项目更新到目标版本
    测试入口：tests/test_maintenance_scripts.py::test_legacy_update_script_reaches_target_without_intermediate_install
    代码入口：update.sh
    """
    environment = _isolated_environment(tmp_path)
    root = tmp_path / "legacy"
    _write_legacy_project(root, "0.0.1")

    result = _run_script(
        "update.sh",
        ["--version", __version__, "--confirmed"],
        root,
        environment,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert _project_version(root) == __version__
    log = Path(environment["FAKE_UV_LOG"]).read_text(encoding="utf-8")
    assert f"--from workflow-loop=={__version__}" in log
    assert f"workflow-loop=={__version__}" in log
    assert "0.0.2" not in log and "0.0.9" not in log


def test_legacy_project_uninstall_script_never_upgrades_global_command(tmp_path):
    """Workflow-Test
    主题：从当前项目强制卸载 Workflow Loop
    测试项：TC-05 旧版本通过两种脚本直接卸载
    验收条件：AC-05 旧版本无需先升级即可卸载
    测试方式：自动化测试 + 人工验收
    测试层级：端到端测试
    测试目标：旧项目通过一个卸载脚本直接删除固定管理范围，不安装新全局命令且保留业务内容
    测试入口：tests/test_maintenance_scripts.py::test_legacy_project_uninstall_script_never_upgrades_global_command
    代码入口：uninstall.sh
    """
    environment = _isolated_environment(tmp_path)
    root = tmp_path / "legacy"
    _write_legacy_project(root, "0.0.1")
    business = root / "src" / "business.py"
    business.parent.mkdir()
    business.write_text("keep = True\n", encoding="utf-8")

    result = _run_script("uninstall.sh", ["--confirmed"], root, environment)

    assert result.returncode == 0, result.stdout + result.stderr
    assert not (root / "AGENTS.md").exists()
    assert not (root / ".workflow_loop").exists()
    assert business.read_text(encoding="utf-8") == "keep = True\n"
    assert "tool install" not in Path(environment["FAKE_UV_LOG"]).read_text(
        encoding="utf-8"
    )


def test_global_uninstall_removes_only_proven_path_contribution(tmp_path):
    """Workflow-Test
    主题：单独卸载电脑全局 Workflow Loop 命令
    测试项：TC-03 命令和命令搜索路径按来源删除
    验收条件：AC-03 只删除来源明确的电脑级内容
    测试方式：自动化测试
    测试层级：端到端测试
    测试目标：来源记录精确匹配时删除对应 PATH 配置，原有或来源不明的配置保持不变并报告
    测试入口：tests/test_maintenance_scripts.py::test_global_uninstall_removes_only_proven_path_contribution
    代码入口：uninstall.sh --global
    """
    environment = _isolated_environment(tmp_path, __version__)
    working = tmp_path / "outside-project"
    working.mkdir()
    shell_config = tmp_path / "home" / ".zshrc"
    marker = "# Workflow Loop PATH"
    path_line = 'export PATH="/temporary/workflow/bin:$PATH"'
    shell_config.write_text(
        f"export USER_SETTING=keep\n\n{marker}\n{path_line}\n",
        encoding="utf-8",
    )
    record = Path(environment["WORKFLOW_LOOP_INSTALL_RECORD"])
    record.parent.mkdir(parents=True)
    record.write_text(
        json.dumps(
            {
                "product": "workflow-loop",
                "path_added": True,
                "path_config_file": str(shell_config),
                "path_marker_line": marker,
                "path_config_line": path_line,
            }
        ),
        encoding="utf-8",
    )

    proven = _run_script(
        "uninstall.sh", ["--global", "--confirmed"], working, environment
    )

    assert proven.returncode == 0, proven.stdout + proven.stderr
    assert shell_config.read_text(encoding="utf-8") == "export USER_SETTING=keep\n"
    assert not record.exists()
    assert not (Path(environment["UV_TOOL_BIN_DIR"]) / "workflow").exists()
    assert "已删除 Workflow Loop 写入的 PATH 配置" in proven.stdout

    _write_workflow_wrapper(
        Path(environment["UV_TOOL_BIN_DIR"]) / "workflow", __version__
    )
    (Path(environment["UV_TOOL_DIR"]) / "workflow-loop").mkdir(parents=True)
    shell_config.write_text("export PREEXISTING=keep\n", encoding="utf-8")
    record.parent.mkdir(parents=True, exist_ok=True)
    record.write_text(
        json.dumps({"product": "workflow-loop", "path_added": False}),
        encoding="utf-8",
    )
    unknown = _run_script(
        "uninstall.sh", ["--global", "--confirmed"], working, environment
    )
    assert unknown.returncode == 0, unknown.stdout + unknown.stderr
    assert shell_config.read_text(encoding="utf-8") == "export PREEXISTING=keep\n"
    assert "PATH 保留" in unknown.stdout


def test_global_uninstall_failure_keeps_residue_and_retry_cleans_it(tmp_path):
    """Workflow-Test
    主题：单独卸载电脑全局 Workflow Loop 命令
    测试项：TC-05 全局部分删除失败后报告并重试
    验收条件：AC-05 部分失败可以核实和重试
    测试方式：自动化测试
    测试层级：端到端测试
    测试目标：工具环境删除失败时不显示成功并保留残留，解除故障后同一命令清理完成
    测试入口：tests/test_maintenance_scripts.py::test_global_uninstall_failure_keeps_residue_and_retry_cleans_it
    代码入口：uninstall.sh --global
    """
    environment = _isolated_environment(tmp_path, __version__)
    working = tmp_path / "outside-project"
    working.mkdir()
    workflow = Path(environment["UV_TOOL_BIN_DIR"]) / "workflow"
    tool = Path(environment["UV_TOOL_DIR"]) / "workflow-loop"
    environment["FAKE_UV_FAIL_UNINSTALL"] = "1"

    failed = _run_script(
        "uninstall.sh", ["--global", "--confirmed"], working, environment
    )

    assert failed.returncode != 0
    assert workflow.exists() and tool.exists()
    assert "全局工具删除失败" in failed.stderr
    assert "卸载完成" not in failed.stdout

    environment.pop("FAKE_UV_FAIL_UNINSTALL")
    retry = _run_script(
        "uninstall.sh", ["--global", "--confirmed"], working, environment
    )
    assert retry.returncode == 0, retry.stdout + retry.stderr
    assert not workflow.exists() and not tool.exists()
    assert "卸载完成" in retry.stdout
