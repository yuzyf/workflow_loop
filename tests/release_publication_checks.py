from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import urlparse
from urllib.request import Request, urlopen


ROOT = Path(__file__).resolve().parents[1]
OWNER = "yuzyf"
REPOSITORY = "workflow_loop"
PACKAGE = "workflow-loop"
VERSION = "0.2.0"
TAG = f"v{VERSION}"
GITHUB_API = f"https://api.github.com/repos/{OWNER}/{REPOSITORY}"
PYPI_API = f"https://pypi.org/pypi/{PACKAGE}/{VERSION}/json"
RELEASE_SIGNAL = (
    Path(tempfile.gettempdir()) / "workflow-loop-release-v0.2.0-preflight.json"
)
EXPECTED_DESCRIPTION = "为 AI 驱动的软件开发提供有状态、可验证、可回退的工作流管理。"
EXPECTED_JOBS = {
    "verify-and-test",
    "build",
    "prepublish-smoke (ubuntu-latest)",
    "prepublish-smoke (macos-latest)",
    "prepublish-smoke (windows-latest)",
    "publish-pypi",
    "github-release",
}
EXPECTED_PLATFORM_STEPS = {
    "prepublish-smoke (ubuntu-latest)": {"安装脚本冒烟：确认、取消与安装（Linux）"},
    "prepublish-smoke (macos-latest)": {"安装脚本冒烟：确认、取消与安装（macOS）"},
    "prepublish-smoke (windows-latest)": {
        "安装脚本冒烟：PowerShell 7（Windows）",
        "安装脚本冒烟：Windows PowerShell 5.1（Windows）",
    },
}


@dataclass(frozen=True)
class HttpResponse:
    status: int
    url: str
    body: bytes

    def json(self) -> dict:
        return json.loads(self.body.decode("utf-8"))


def _run(
    arguments: list[str],
    *,
    cwd: Path = ROOT,
    env: dict[str, str] | None = None,
    text: bool = True,
) -> subprocess.CompletedProcess:
    result = subprocess.run(
        arguments,
        cwd=cwd,
        env=env,
        capture_output=True,
        text=text,
        check=False,
    )
    if result.returncode != 0:
        stdout = result.stdout if text else result.stdout.decode("utf-8", errors="replace")
        stderr = result.stderr if text else result.stderr.decode("utf-8", errors="replace")
        raise AssertionError(
            f"命令执行失败 ({result.returncode}): {arguments!r}\n{stdout}\n{stderr}"
        )
    return result


def _git(*arguments: str) -> str:
    return _run(["git", *arguments]).stdout.strip()


@lru_cache(maxsize=1)
def _github_token() -> str:
    result = subprocess.run(
        ["gh", "auth", "token"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    token = result.stdout.strip()
    assert result.returncode == 0 and token, (
        "正式发布检查需要当前 gh 登录身份，以免 GitHub API 匿名限额中断轮询"
    )
    return token


def _get(url: str, *, github: bool = False, timeout: int = 30) -> HttpResponse:
    headers = {"User-Agent": "workflow-loop-release-verification"}
    if github:
        headers.update(
            {
                "Accept": "application/vnd.github+json",
                "Authorization": f"Bearer {_github_token()}",
                "X-GitHub-Api-Version": "2022-11-28",
            }
        )
    request = Request(url, headers=headers)
    try:
        with urlopen(request, timeout=timeout) as response:
            return HttpResponse(response.status, response.geturl(), response.read())
    except HTTPError as error:
        return HttpResponse(error.code, error.geturl(), error.read())


def _print_evidence(label: str, payload: dict) -> None:
    print(f"{label}: {json.dumps(payload, ensure_ascii=False, sort_keys=True)}")


def _local_tag_commit() -> str:
    return _git("rev-parse", f"{TAG}^{{commit}}")


def _remote_tag_commit() -> str | None:
    result = _run(
        [
            "git",
            "ls-remote",
            "origin",
            f"refs/tags/{TAG}",
            f"refs/tags/{TAG}^{{}}",
        ]
    ).stdout.strip()
    if not result:
        return None
    references = dict(
        line.split("\t", 1)[::-1]
        for line in result.splitlines()
        if "\t" in line
    )
    return references.get(f"refs/tags/{TAG}^{{}}") or references.get(f"refs/tags/{TAG}")


def _required_tag_files() -> set[str]:
    return {
        "README.md",
        "LICENSE",
        "pyproject.toml",
        "uv.lock",
        ".workflow_loop/project.json",
        "install.sh",
        "install.ps1",
        "update.sh",
        "update.ps1",
        "uninstall.sh",
        "uninstall.ps1",
        ".github/workflows/release.yml",
        "tests/test_public_project.py",
        "tests/public_repository_checks.py",
        "tests/test_release_workflow.py",
        "tests/release_publication_checks.py",
    }


def _write_release_signal(evidence: dict) -> None:
    temporary = RELEASE_SIGNAL.with_name(f"{RELEASE_SIGNAL.name}.{os.getpid()}.tmp")
    temporary.write_text(
        json.dumps(evidence, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, RELEASE_SIGNAL)


def _find_release_run(expected_commit: str) -> dict | None:
    response = _get(
        f"{GITHUB_API}/actions/workflows/release.yml/runs?event=push&per_page=100",
        github=True,
    )
    assert response.status == 200, f"读取 GitHub Actions 任务失败: HTTP {response.status}"
    candidates = [
        run
        for run in response.json().get("workflow_runs", [])
        if run.get("event") == "push" and run.get("head_sha") == expected_commit
    ]
    if not candidates:
        return None
    candidates.sort(key=lambda run: run.get("run_number", 0), reverse=True)
    return candidates[0]


def _jobs_for_run(run: dict) -> list[dict]:
    response = _get(f"{run['jobs_url']}?per_page=100", github=True)
    assert response.status == 200, f"读取 GitHub Actions 作业失败: HTTP {response.status}"
    return response.json().get("jobs", [])


def _assert_successful_release_jobs(run: dict, jobs: list[dict]) -> dict:
    assert run["event"] == "push"
    assert run["head_sha"] == _local_tag_commit()
    assert run["status"] == "completed"
    assert run["conclusion"] == "success"
    assert run["html_url"].startswith(
        f"https://github.com/{OWNER}/{REPOSITORY}/actions/runs/"
    )

    jobs_by_name = {job["name"]: job for job in jobs}
    assert set(jobs_by_name) == EXPECTED_JOBS
    assert all(job.get("conclusion") == "success" for job in jobs_by_name.values())

    platform_evidence: dict[str, list[str]] = {}
    for job_name, expected_steps in EXPECTED_PLATFORM_STEPS.items():
        steps = {step["name"]: step for step in jobs_by_name[job_name].get("steps", [])}
        assert expected_steps <= set(steps)
        assert all(steps[name].get("conclusion") == "success" for name in expected_steps)
        platform_evidence[job_name] = sorted(expected_steps)
    return platform_evidence


def _wait_for_remote_tag(expected_commit: str, timeout_seconds: int = 1200) -> None:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        remote_commit = _remote_tag_commit()
        if remote_commit is not None:
            assert remote_commit == expected_commit
            return
        time.sleep(10)
    raise AssertionError(f"等待远程标签 {TAG} 超过 {timeout_seconds} 秒")


def _wait_for_successful_release_run(
    expected_commit: str,
    timeout_seconds: int = 1800,
) -> tuple[dict, list[dict]]:
    deadline = time.monotonic() + timeout_seconds
    last_state = "尚未出现"
    while time.monotonic() < deadline:
        run = _find_release_run(expected_commit)
        if run is None:
            time.sleep(30)
            continue
        last_state = f"{run.get('status')}/{run.get('conclusion')}"
        if run.get("status") == "completed":
            assert run.get("conclusion") == "success", (
                f"最终标签任务没有成功: {run.get('html_url')} {last_state}"
            )
            jobs = _jobs_for_run(run)
            _assert_successful_release_jobs(run, jobs)
            return run, jobs
        time.sleep(30)
    raise AssertionError(
        f"等待最终标签任务成功超过 {timeout_seconds} 秒，最后状态为 {last_state}"
    )


def _wait_for_public_release(timeout_seconds: int = 600) -> tuple[dict, dict]:
    deadline = time.monotonic() + timeout_seconds
    statuses = (None, None)
    while time.monotonic() < deadline:
        pypi_response = _get(PYPI_API)
        github_response = _get(f"{GITHUB_API}/releases/tags/{TAG}", github=True)
        statuses = (pypi_response.status, github_response.status)
        if statuses == (200, 200):
            return pypi_response.json(), github_response.json()
        assert pypi_response.status in {200, 404}
        assert github_response.status in {200, 404}
        time.sleep(15)
    raise AssertionError(
        f"等待 PyPI 和 GitHub 正式发布超过 {timeout_seconds} 秒，最后 HTTP 状态为 {statuses}"
    )


def _release_body_requirements() -> tuple[str, ...]:
    return (
        "Workflow Loop 0.2.0 为 AI 驱动的软件开发提供有状态、可验证、可回退的工作流管理。",
        "支持 macOS、Linux 和原生 Windows 使用一条命令完成安装。",
        "支持从零创建、修改产品、修复缺陷和无需开发任务四种工作意图。",
        "完整研发任务的每个正式环节依次经过讨论完成、程序检查和用户确认三道门",
        "无需开发任务按调查讨论、执行约定任务、核对结果和用户确认结果的简单流程处理。",
        "需求交付追踪表",
        "机器执行记录",
        "返回上游修正、本轮修改回退和整轮作废恢复",
        "Python 3.11 或更高版本",
    )


def test_public_version_is_absent_and_local_tag_is_ready():
    """Workflow-Test
    主题：0.2.0 在 GitHub 和 PyPI 完成正式发布
    测试项：TC-02 发布前公共版本空缺且最终标签指向正确
    验收条件：AC-01 全部发布身份统一为 0.2.0
    测试方式：自动化测试 + 人工验收
    测试层级：接口测试
    测试目标：在远程标签推送前确认两个公开渠道均无 0.2.0，且本地标签准确指向已推送的最终主分支提交
    测试入口：tests/release_publication_checks.py::test_public_version_is_absent_and_local_tag_is_ready
    代码入口：本地 HEAD、main 和 v0.2.0；Git origin；GitHub 与 PyPI 公开接口
    """
    RELEASE_SIGNAL.unlink(missing_ok=True)
    head_commit = _git("rev-parse", "HEAD")
    main_commit = _git("rev-parse", "refs/heads/main")
    tag_commit = _local_tag_commit()
    remote_main_line = _run(
        ["git", "ls-remote", "origin", "refs/heads/main"]
    ).stdout.strip()
    assert remote_main_line, "远程 main 主分支不存在"
    remote_main_commit = remote_main_line.split("\t", 1)[0]

    assert head_commit == main_commit == tag_commit == remote_main_commit
    assert _remote_tag_commit() is None, f"远程标签 {TAG} 已存在，必须停止发布"

    tag_files = set(_git("ls-tree", "-r", "--name-only", TAG).splitlines())
    assert _required_tag_files() <= tag_files

    github_tag = _get(f"{GITHUB_API}/git/ref/tags/{TAG}", github=True)
    github_release = _get(f"{GITHUB_API}/releases/tags/{TAG}", github=True)
    pypi_release = _get(PYPI_API)
    assert github_tag.status == 404, f"GitHub 已存在 {TAG} 标签，必须停止发布"
    assert github_release.status == 404, f"GitHub 已存在 {TAG} 正式发布，必须停止发布"
    assert pypi_release.status == 404, f"PyPI 已存在 {PACKAGE} {VERSION}，必须停止发布"

    evidence = {
        "checked_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "github_release": {
            "body": github_release.body.decode("utf-8", errors="replace"),
            "status": github_release.status,
            "url": github_release.url,
        },
        "github_tag": {
            "body": github_tag.body.decode("utf-8", errors="replace"),
            "status": github_tag.status,
            "url": github_tag.url,
        },
        "head_commit": head_commit,
        "local_tag_commit": tag_commit,
        "pypi_release": {
            "body": pypi_release.body.decode("utf-8", errors="replace"),
            "status": pypi_release.status,
            "url": pypi_release.url,
        },
        "ready": True,
        "remote_main_commit": remote_main_commit,
        "required_tag_files": sorted(_required_tag_files()),
        "tag": TAG,
    }
    _write_release_signal(evidence)
    _print_evidence("RELEASE_PREFLIGHT_READY", evidence)


def test_final_tag_workflow_succeeds():
    """Workflow-Test
    主题：0.2.0 在 GitHub 和 PyPI 完成正式发布
    测试项：TC-05 v0.2.0 标签对应的真实发布任务全部成功
    验收条件：AC-03 最终标签任务全部成功
    测试方式：自动化测试 + 人工验收
    测试层级：端到端测试
    测试目标：等待用户批准后推送的最终标签，并确认该提交触发的全部发布作业和要求步骤真实成功
    测试入口：tests/release_publication_checks.py::test_final_tag_workflow_succeeds
    代码入口：Git origin 的 v0.2.0 标签；GitHub Actions release.yml 运行与作业接口
    """
    expected_commit = _local_tag_commit()
    _wait_for_remote_tag(expected_commit)
    run, jobs = _wait_for_successful_release_run(expected_commit)
    platform_steps = _assert_successful_release_jobs(run, jobs)
    evidence = {
        "commit": expected_commit,
        "jobs": {job["name"]: job.get("conclusion") for job in jobs},
        "platform_steps": platform_steps,
        "run_id": run["id"],
        "run_number": run["run_number"],
        "run_url": run["html_url"],
        "tag": TAG,
    }
    _print_evidence("FINAL_TAG_WORKFLOW", evidence)


def test_pypi_and_github_release_contents_match():
    """Workflow-Test
    主题：0.2.0 在 GitHub 和 PyPI 完成正式发布
    测试项：TC-06 PyPI 与 GitHub Release 内容和附件一致
    验收条件：AC-04 两个公开渠道内容一致并提供六个脚本
    测试方式：自动化测试
    测试层级：接口测试
    测试目标：确认 PyPI 包元数据和 GitHub 正式发布名称、说明与附件共同公开同一份 0.2.0
    测试入口：tests/release_publication_checks.py::test_pypi_and_github_release_contents_match
    代码入口：PyPI workflow-loop 0.2.0 JSON 接口；GitHub v0.2.0 Release 接口
    """
    pypi, release = _wait_for_public_release()
    info = pypi["info"]
    assert info["name"] == PACKAGE
    assert info["version"] == VERSION
    assert info["summary"] == EXPECTED_DESCRIPTION
    assert info["author"] == OWNER
    assert info["description_content_type"] == "text/markdown"
    assert info["description"] == (ROOT / "README.md").read_text(encoding="utf-8")
    assert info["requires_python"] == ">=3.11"
    assert info.get("license_expression") == "MIT"
    assert info["project_urls"] == {
        "Homepage": f"https://github.com/{OWNER}/{REPOSITORY}",
        "Repository": f"https://github.com/{OWNER}/{REPOSITORY}",
    }

    distributions = {(item["packagetype"], item["filename"]): item for item in pypi["urls"]}
    expected_distributions = {
        ("bdist_wheel", "workflow_loop-0.2.0-py3-none-any.whl"),
        ("sdist", "workflow_loop-0.2.0.tar.gz"),
    }
    assert set(distributions) == expected_distributions
    for distribution in distributions.values():
        assert urlparse(distribution["url"]).hostname == "files.pythonhosted.org"
        assert len(distribution["digests"]["sha256"]) == 64

    assert release["tag_name"] == TAG
    assert release["name"] == "Workflow Loop 0.2.0"
    assert release["draft"] is False
    assert release["prerelease"] is False
    assert release["html_url"] == (
        f"https://github.com/{OWNER}/{REPOSITORY}/releases/tag/{TAG}"
    )
    assert all(requirement in release["body"] for requirement in _release_body_requirements())
    assets = {asset["name"]: asset for asset in release["assets"]}
    assert set(assets) == {
        "install.sh",
        "install.ps1",
        "update.sh",
        "update.ps1",
        "uninstall.sh",
        "uninstall.ps1",
    }

    evidence = {
        "github": {
            "assets": sorted(assets),
            "name": release["name"],
            "tag": release["tag_name"],
            "url": release["html_url"],
        },
        "pypi": {
            "author": info["author"],
            "distributions": sorted(item[1] for item in distributions),
            "license_expression": info.get("license_expression"),
            "name": info["name"],
            "project_urls": info["project_urls"],
            "summary": info["summary"],
            "version": info["version"],
        },
    }
    _print_evidence("PUBLIC_RELEASE_CONTENT", evidence)


def test_clean_install_uses_public_pypi_package():
    """Workflow-Test
    主题：0.2.0 在 GitHub 和 PyPI 完成正式发布
    测试项：TC-07 公网全新安装得到 0.2.0（本次不执行 0.1.0 升级）
    验收条件：AC-05 公网安装和从 0.1.0 更新后得到 0.2.0
    测试方式：自动化测试 + 人工验收
    测试层级：端到端测试
    测试目标：禁用本地源码和缓存后从 PyPI 全新安装明确版本，并执行实际 workflow 命令确认身份；本次不执行 0.1.0 公网升级
    测试入口：tests/release_publication_checks.py::test_clean_install_uses_public_pypi_package
    代码入口：https://pypi.org/simple；workflow-loop==0.2.0；安装后的 workflow --version
    """
    with tempfile.TemporaryDirectory(prefix="workflow-loop-public-install-") as directory:
        temporary_root = Path(directory)
        environment_root = temporary_root / "venv"
        report_path = temporary_root / "pip-report.json"
        clean_environment = {
            key: value
            for key, value in os.environ.items()
            if key not in {"PYTHONHOME", "PYTHONPATH", "UV_FIND_LINKS"}
            and not key.startswith("PIP_")
            and not key.startswith("UV_INDEX")
        }
        clean_environment["PIP_CONFIG_FILE"] = os.devnull

        _run(
            [sys.executable, "-m", "venv", str(environment_root)],
            cwd=temporary_root,
            env=clean_environment,
        )
        if os.name == "nt":
            python = environment_root / "Scripts" / "python.exe"
            workflow = environment_root / "Scripts" / "workflow.exe"
        else:
            python = environment_root / "bin" / "python"
            workflow = environment_root / "bin" / "workflow"
        install_command = [
            str(python),
            "-m",
            "pip",
            "install",
            "--isolated",
            "--disable-pip-version-check",
            "--no-cache-dir",
            "--index-url",
            "https://pypi.org/simple",
            "--report",
            str(report_path),
            f"{PACKAGE}=={VERSION}",
        ]
        _run(install_command, cwd=temporary_root, env=clean_environment)

        report = json.loads(report_path.read_text(encoding="utf-8"))
        installed = [
            item
            for item in report["install"]
            if item["metadata"]["name"].lower().replace("_", "-") == PACKAGE
        ]
        assert len(installed) == 1
        package_record = installed[0]
        assert package_record["metadata"]["version"] == VERSION
        download_url = package_record["download_info"]["url"]
        assert urlparse(download_url).hostname == "files.pythonhosted.org"
        archive_hash = package_record["download_info"]["archive_info"].get("hash", "")
        assert archive_hash.startswith("sha256=") and len(archive_hash) == 71

        identity = _run(
            [str(workflow), "--version"],
            cwd=temporary_root,
            env=clean_environment,
        ).stdout.strip()
        assert identity == f"{PACKAGE} {VERSION}"
        _print_evidence(
            "PUBLIC_INSTALL",
            {
                "cache_disabled": True,
                "download_url": download_url,
                "identity": identity,
                "index": "https://pypi.org/simple",
                "local_sources_disabled": True,
                "requested": f"{PACKAGE}=={VERSION}",
                "sha256": archive_hash.removeprefix("sha256="),
            },
        )


def test_release_assets_and_platform_evidence_match_final_tag():
    """Workflow-Test
    主题：0.2.0 在 GitHub 和 PyPI 完成正式发布
    测试项：TC-06 PyPI 与 GitHub Release 内容和附件一致
    验收条件：AC-04 两个公开渠道内容一致并提供六个脚本
    测试方式：自动化测试
    测试层级：端到端测试
    测试目标：逐字节核对六个公开维护脚本与最终标签源码，并确认四种平台步骤属于同一最终任务
    测试入口：tests/release_publication_checks.py::test_release_assets_and_platform_evidence_match_final_tag
    代码入口：GitHub v0.2.0 Release 附件；v0.2.0 标签源码；最终 GitHub Actions 作业步骤
    """
    release_response = _get(f"{GITHUB_API}/releases/tags/{TAG}", github=True)
    assert release_response.status == 200
    release = release_response.json()
    assets = {asset["name"]: asset for asset in release["assets"]}
    assert set(assets) == {
        "install.sh",
        "install.ps1",
        "update.sh",
        "update.ps1",
        "uninstall.sh",
        "uninstall.ps1",
    }

    asset_evidence = {}
    for name, asset in assets.items():
        downloaded = _get(asset["browser_download_url"])
        assert downloaded.status == 200
        tagged = _run(
            ["git", "show", f"{TAG}:{name}"],
            text=False,
        ).stdout
        assert downloaded.body == tagged
        digest = hashlib.sha256(downloaded.body).hexdigest()
        asset_evidence[name] = {
            "download_url": asset["browser_download_url"],
            "sha256": digest,
            "size": len(downloaded.body),
        }

    expected_commit = _local_tag_commit()
    run = _find_release_run(expected_commit)
    assert run is not None, "没有找到最终标签对应的 GitHub Actions 任务"
    jobs = _jobs_for_run(run)
    platform_steps = _assert_successful_release_jobs(run, jobs)
    _print_evidence(
        "RELEASE_ASSETS_AND_PLATFORMS",
        {
            "assets": asset_evidence,
            "commit": expected_commit,
            "platform_steps": platform_steps,
            "run_url": run["html_url"],
            "tag": TAG,
        },
    )
