"""当前产品规则引用同一安装与发布来源，版本替换保留历史事实。"""

from pathlib import Path
import re
import shutil

from markdown_it import MarkdownIt

from scripts import release


ROOT = Path(__file__).resolve().parents[1]
DOCUMENTS = (
    Path("spec/产品总说明.md"),
    Path("spec/功能_安装到项目.md"),
    Path("spec/功能_发布正式版本.md"),
)


def _current_text(content):
    lines = content.splitlines(keepends=True)
    tokens = MarkdownIt("commonmark").enable("table").parse(content)
    for index, token in enumerate(tokens):
        if token.type == "heading_open" and "修改记录" in tokens[index + 1].content:
            return "".join(lines[:token.map[0]])
    raise AssertionError("产品文档缺少历史修改记录边界")


def test_current_docs_use_shared_release_sources(tmp_path):
    """Workflow-Test
    主题：发布版本说明始终引用统一来源
    测试项：TC-01 版本更新不使当前说明滞后
    验收条件：AC-01 当前引用统一且历史保留
    测试方式：自动化测试
    测试层级：集成测试
    产品入口：阅读产品和安装说明并调用版本身份更新入口
    测试入口：tests/test_version_document_sources.py::test_current_docs_use_shared_release_sources
    代码入口：scripts/release.py::update_release_identity
    准备数据：复制当前版本身份文件、产品说明及历史记录到隔离目录，准备一个不同的新版本。
    执行动作：核对当前文档的统一来源，在副本执行版本身份替换并再次核对当前和历史内容。
    关键断言：当前规则不写死特定产品版本，安装入口仍指向正式来源；历史版本不被批量替换。
    预期证据：当前执行的结构化测试报告中入口精确匹配，执行数大于零，跳过失败错误均为零且退出码为零。
    """
    relative_paths = (*release.CURRENT_VERSION_FILES, release.PROJECT_STATE_PATH, *DOCUMENTS)
    for relative in relative_paths:
        target = tmp_path / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / relative, target)
    originals = {relative: (tmp_path / relative).read_bytes() for relative in DOCUMENTS}
    for relative in DOCUMENTS:
        content = originals[relative].decode("utf-8")
        current = _current_text(content)
        assert not re.search(r"(?<![0-9.])v?[0-9]+\.[0-9]+\.[0-9]+(?![0-9.])", current), relative
        if relative.name != "功能_发布正式版本.md":
            assert "(../README.md)" in current
            assert "https://github.com/yuzyf/workflow_loop/releases/latest" in current
    assert b"0.1.0" in originals[DOCUMENTS[0]]
    assert b"0.2.0" in originals[DOCUMENTS[1]]

    old = release.read_current_version(tmp_path)
    major, minor, patch = map(int, old.split("."))
    new = f"{major}.{minor}.{patch + 1}"
    release.update_release_identity(tmp_path, old, new)
    assert release.read_current_version(tmp_path) == new
    readme = (tmp_path / "README.md").read_text(encoding="utf-8")
    assert f"/releases/download/v{new}/install.sh" in readme
    assert f"/releases/download/v{new}/install.ps1" in readme
    for relative, before in originals.items():
        assert (tmp_path / relative).read_bytes() == before, relative
    assert not (tmp_path / ".git").exists()
