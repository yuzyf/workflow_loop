from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import shlex
import subprocess
import sys
import tomllib
from collections.abc import Callable, Sequence


ROOT = Path(__file__).resolve().parents[1]
CURRENT_VERSION_FILES = (
    Path("pyproject.toml"),
    Path("src/workflow_loop/__init__.py"),
    Path("README.md"),
    Path("install.sh"),
    Path("install.ps1"),
    Path("update.sh"),
    Path("update.ps1"),
    Path("uninstall.sh"),
    Path("uninstall.ps1"),
    Path(".github/workflows/release.yml"),
)
PROJECT_STATE_PATH = Path(".workflow_loop/project.json")
STABLE_VERSION_PATTERN = re.compile(r"(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)")


class ReleaseError(RuntimeError):
    """An actionable release failure that should stop all later steps."""


CommandRunner = Callable[[str, Sequence[str], Path], None]


def read_current_version(root: Path = ROOT) -> str:
    path = root / "pyproject.toml"
    try:
        project = tomllib.loads(path.read_text(encoding="utf-8"))["project"]
        version = project["version"]
    except (OSError, KeyError, tomllib.TOMLDecodeError) as exc:
        raise ReleaseError(f"读取当前版本失败：{path}: {exc}") from exc
    if not isinstance(version, str):
        raise ReleaseError(f"读取当前版本失败：{path} 的 project.version 不是字符串")
    return version


def normalize_release_version(value: str) -> str:
    version = value.strip()
    if STABLE_VERSION_PATTERN.fullmatch(version) is None:
        raise ReleaseError("新版本号必须使用 X.Y.Z 格式，例如 0.3.0")
    return version


def update_release_identity(root: Path, old_version: str, new_version: str) -> None:
    old_bytes = old_version.encode("ascii")
    new_bytes = new_version.encode("ascii")
    updated_files: dict[Path, bytes] = {}

    for relative_path in CURRENT_VERSION_FILES:
        path = root / relative_path
        try:
            content = path.read_bytes()
        except OSError as exc:
            raise ReleaseError(f"读取当前版本文件失败：{relative_path}: {exc}") from exc
        if old_bytes not in content:
            raise ReleaseError(
                f"更新当前版本失败：{relative_path} 中没有旧版本 {old_version}"
            )
        updated_files[path] = content.replace(old_bytes, new_bytes)

    project_state_path = root / PROJECT_STATE_PATH
    try:
        project_state = json.loads(project_state_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ReleaseError(f"读取项目安装版本失败：{PROJECT_STATE_PATH}: {exc}") from exc
    if not isinstance(project_state, dict):
        raise ReleaseError(f"读取项目安装版本失败：{PROJECT_STATE_PATH} 不是对象")
    if project_state.get("installer_version") != old_version:
        raise ReleaseError(
            "更新项目安装版本失败："
            f"{PROJECT_STATE_PATH} 的 installer_version 不是 {old_version}"
        )
    project_state["installer_version"] = new_version
    project_state_bytes = (
        json.dumps(project_state, ensure_ascii=False, indent=2) + "\n"
    ).encode("utf-8")

    try:
        for path, content in updated_files.items():
            path.write_bytes(content)
        project_state_path.write_bytes(project_state_bytes)
    except OSError as exc:
        raise ReleaseError(f"写入新版本身份失败：{exc}") from exc


def run_command(step: str, command: Sequence[str], root: Path) -> None:
    arguments = list(command)
    print(f"\n[{step}]", flush=True)
    print(f"$ {shlex.join(arguments)}", flush=True)
    try:
        subprocess.run(arguments, cwd=root, check=True)
    except subprocess.CalledProcessError as exc:
        raise ReleaseError(f"{step}失败，退出码 {exc.returncode}") from exc
    except OSError as exc:
        raise ReleaseError(f"{step}无法启动：{exc}") from exc


def run_release(
    version: str,
    root: Path = ROOT,
    runner: CommandRunner = run_command,
) -> None:
    tag = f"v{version}"
    steps = (
        ("更新依赖锁定", ("uv", "lock")),
        ("纳入当前全部修改", ("git", "add", "-A")),
        (
            "创建发布提交",
            ("git", "commit", "-m", f"release: prepare workflow-loop {version}"),
        ),
        ("推送远程默认分支", ("git", "push", "origin", "HEAD:main")),
        (
            "创建本地版本标签",
            ("git", "tag", "-a", tag, "-m", f"Workflow Loop {version}"),
        ),
        ("推送版本标签", ("git", "push", "origin", tag)),
    )
    for step, command in steps:
        runner(step, command, root)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="直接发布当前 Workflow Loop 仓库内容，不执行本地发布检查。"
    )
    parser.add_argument("version", help="要发布的新稳定版本号，例如 0.3.0")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    arguments = build_parser().parse_args(argv)
    try:
        new_version = normalize_release_version(arguments.version)
        old_version = read_current_version(ROOT)
        if new_version == old_version:
            raise ReleaseError(f"新版本号不能与当前版本 {old_version} 相同")

        print(
            f"准备把当前仓库从 {old_version} 发布为 {new_version}。\n"
            "本命令不执行本地测试、构建、远程版本查询或二次确认；"
            "失败后不自动回滚。",
            flush=True,
        )
        update_release_identity(ROOT, old_version, new_version)
        run_release(new_version, ROOT)
    except ReleaseError as exc:
        print(f"错误：{exc}", file=sys.stderr, flush=True)
        return 1

    print(
        f"版本标签 v{new_version} 已推送，远程发布流程已触发。"
        "请以 GitHub Actions 的最终结果判断公开发布是否完成。",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
