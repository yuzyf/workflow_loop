import json
from pathlib import Path
import urllib.request

from packaging.version import Version


ROOT = Path(__file__).resolve().parents[1]
PYPI_URL = "https://pypi.org/pypi/workflow-loop/json"
GITHUB_LATEST_URL = "https://api.github.com/repos/yuzyf/workflow_loop/releases/latest"


def _read_json(url: str) -> dict:
    request = urllib.request.Request(
        url,
        headers={
            "Accept": "application/json",
            "User-Agent": "workflow-loop-public-test",
        },
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        value = json.loads(response.read().decode("utf-8"))
    assert isinstance(value, dict)
    return value


def test_public_pypi_and_github_latest_stable_release_agree():
    """Workflow-Test
    主题：已安装项目一条命令更新到目标正式版本
    测试项：TC-02 正式版本和发布来源判断
    验收条件：AC-02 目标正式版本选择正确
    测试方式：自动化测试
    测试层级：接口测试
    测试目标：正式测试时只读核对 PyPI 最新可用正式版本与 GitHub 最新正式发布标记一致
    测试入口：tests/maintenance_public_checks.py::test_public_pypi_and_github_latest_stable_release_agree
    代码入口：PyPI workflow-loop JSON 接口；GitHub workflow_loop latest release 接口
    """
    pypi = _read_json(PYPI_URL)
    github = _read_json(GITHUB_LATEST_URL)
    raw_version = pypi.get("info", {}).get("version")
    version = Version(raw_version)
    files = pypi.get("releases", {}).get(str(version), [])

    assert not version.is_prerelease
    assert not version.is_devrelease
    assert version.local is None
    assert any(
        isinstance(item, dict) and not item.get("yanked", False) for item in files
    )
    assert github.get("draft") is False
    assert github.get("prerelease") is False
    assert github.get("tag_name") == f"v{version}"
    print(
        json.dumps(
            {
                "github_url": github.get("html_url"),
                "pypi_url": f"https://pypi.org/project/workflow-loop/{version}/",
                "version": str(version),
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
