import json
import subprocess
from pathlib import Path
from urllib.request import HTTPRedirectHandler, Request, build_opener


ROOT = Path(__file__).resolve().parents[1]
API_URL = "https://api.github.com/repos/yuzyf/workflow_loop"
GIT_URL = "https://github.com/yuzyf/workflow_loop.git"
HTML_URL = "https://github.com/yuzyf/workflow_loop"
DESCRIPTION = "为 AI 驱动的软件开发提供有状态、可验证、可回退的工作流管理。"


class _RejectRedirects(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _git_remote_url(*arguments: str) -> str:
    result = subprocess.run(
        ["git", "remote", "get-url", *arguments, "origin"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def _public_repository() -> tuple[dict, str]:
    request = Request(
        API_URL,
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": "workflow-loop-release-verification",
            "X-GitHub-Api-Version": "2022-11-28",
        },
    )
    with build_opener(_RejectRedirects).open(request, timeout=30) as response:
        return json.load(response), response.geturl()


def test_local_and_public_repository_identity_are_canonical():
    """Workflow-Test
    主题：公开项目身份和中文说明保持一致
    测试项：TC-01 当前项目与公开仓库身份一致
    验收条件：AC-01 公开项目身份一致
    测试方式：自动化测试
    测试层级：接口测试
    测试目标：确认真实本地目录、Git origin 拉取与推送地址和无重定向 GitHub API 响应均指向唯一的新公开仓库
    测试入口：tests/public_repository_checks.py::test_local_and_public_repository_identity_are_canonical
    代码入口：本地项目根目录；git remote get-url origin；https://api.github.com/repos/yuzyf/workflow_loop
    """
    fetch_url = _git_remote_url()
    push_url = _git_remote_url("--push")
    repository, response_url = _public_repository()

    assert ROOT.name == "workflow_loop"
    assert fetch_url == GIT_URL
    assert push_url == GIT_URL
    assert response_url == API_URL
    assert repository["full_name"] == "yuzyf/workflow_loop"
    assert repository["name"] == "workflow_loop"
    assert repository["owner"]["login"] == "yuzyf"
    assert repository["description"] == DESCRIPTION
    assert repository["private"] is False
    assert repository["visibility"] == "public"
    assert repository["html_url"] == HTML_URL

    evidence = {
        "api_url": response_url,
        "description": repository["description"],
        "full_name": repository["full_name"],
        "html_url": repository["html_url"],
        "origin_fetch": fetch_url,
        "origin_push": push_url,
        "owner": repository["owner"]["login"],
        "private": repository["private"],
        "root_name": ROOT.name,
        "visibility": repository["visibility"],
    }
    print(json.dumps(evidence, ensure_ascii=False, sort_keys=True))
