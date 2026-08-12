import hashlib
import json
from pathlib import Path

import workflow_loop.installer as installer
from workflow_loop import PRODUCT_NAME, __version__
from workflow_loop.project import check_skeleton


TOPIC = "一次安装后可在三种操作系统开始使用工作流"


def _write_token(project_root: Path, token_path: Path, **overrides) -> None:
    token = {
        "product": PRODUCT_NAME,
        "version": __version__,
        "project_root": str(project_root.resolve()),
        "allowed_paths": sorted(installer.PROJECT_WRITE_PATHS),
        "used": False,
    }
    token.update(overrides)
    token_path.write_text(json.dumps(token, ensure_ascii=False), encoding="utf-8")


def _tree_hash(root: Path) -> str:
    digest = hashlib.sha256()
    if not root.exists():
        return digest.hexdigest()
    for path in sorted(root.rglob("*")):
        digest.update(path.relative_to(root).as_posix().encode("utf-8"))
        if path.is_file():
            digest.update(path.read_bytes())
    return digest.hexdigest()


def test_invalid_transaction_token_does_not_modify_project(tmp_path, capsys):
    """Workflow-Test
    主题：一次安装后可在三种操作系统开始使用工作流
    测试项：TC-01 安装预检和取消保持零修改
    验收条件：AC-01 安装前可审查
    测试方式：自动化测试 + 人工验收
    测试层级：集成测试
    测试目标：事务文件无效时安装器在任何项目写入前停止
    测试入口：tests/test_installer.py::test_invalid_transaction_token_does_not_modify_project
    代码入口：workflow_loop.installer.install_project_transaction
    """
    before = _tree_hash(tmp_path)

    code = installer.install_project_transaction(str(tmp_path), str(tmp_path / "missing.json"))

    assert code == 1
    assert _tree_hash(tmp_path) == before
    assert "项目文件未修改" in capsys.readouterr().out


def test_transaction_installs_complete_project_skeleton(tmp_path, capsys):
    """Workflow-Test
    主题：一次安装后可在三种操作系统开始使用工作流
    测试项：TC-02 三平台一条命令完成完整安装
    验收条件：AC-02 一条命令完成三平台安装
    测试方式：自动化测试 + 人工验收
    测试层级：集成测试
    测试目标：一次事务同时生成完整项目骨架和 AI 契约
    测试入口：tests/test_installer.py::test_transaction_installs_complete_project_skeleton
    代码入口：workflow_loop.installer.install_project_transaction
    """
    token_path = tmp_path / "token.json"
    _write_token(tmp_path, token_path)

    code = installer.install_project_transaction(str(tmp_path), str(token_path))

    assert code == 0
    assert check_skeleton(str(tmp_path)).state == "installed"
    assert (tmp_path / "AGENTS.md").is_file()
    assert (tmp_path / ".workflow_loop" / "Template_Repository").is_dir()
    assert (tmp_path / ".workflow_loop" / "Standardized_Repository").is_dir()
    assert (tmp_path / ".workflow_loop" / "project.json").is_file()
    assert not (tmp_path / installer.TRANSACTION_DIRNAME).exists()
    assert "项目安装完成" in capsys.readouterr().out


def test_installed_materials_use_confirmed_chinese_names(tmp_path):
    """Workflow-Test
    主题：一次安装后可在三种操作系统开始使用工作流
    测试项：TC-02 三平台一条命令完成完整安装
    验收条件：AC-02 一条命令完成三平台安装
    测试方式：自动化测试 + 人工验收
    测试层级：集成测试
    测试目标：安装包下发已确认的中文模板和生命周期规范
    测试入口：tests/test_installer.py::test_installed_materials_use_confirmed_chinese_names
    代码入口：workflow_loop.installer.install_project_transaction
    """
    token_path = tmp_path / "token.json"
    _write_token(tmp_path, token_path)

    assert installer.install_project_transaction(str(tmp_path), str(token_path)) == 0

    template_root = tmp_path / ".workflow_loop" / "Template_Repository"
    standard_root = tmp_path / ".workflow_loop" / "Standardized_Repository"
    assert "`spec/产品总说明.md`" in (template_root / "spec" / "spec.md").read_text(
        encoding="utf-8"
    )
    assert "# 测试验证计划文档模板" in (template_root / "qa" / "test_plan.md").read_text(
        encoding="utf-8"
    )
    assert (standard_root / "global" / "workflow_lifecycle.md").is_file()


def test_token_requires_fixed_product_version_and_write_scope(tmp_path, capsys):
    """Workflow-Test
    主题：一次安装后可在三种操作系统开始使用工作流
    测试项：TC-03 固定工具摘要和产品身份一致
    验收条件：AC-03 安装来源和产品身份固定
    测试方式：自动化测试 + 人工验收
    测试层级：模块测试
    测试目标：拒绝版本、产品名或允许写入范围不一致的事务
    测试入口：tests/test_installer.py::test_token_requires_fixed_product_version_and_write_scope
    代码入口：workflow_loop.installer._validate_transaction_token
    """
    token_path = tmp_path / "token.json"
    _write_token(tmp_path, token_path, version="9.9.9")

    assert installer.install_project_transaction(str(tmp_path), str(token_path)) == 1
    assert not (tmp_path / ".workflow_loop").exists()
    assert f"当前产品固定为 '{installer.PRODUCT_VERSION}'" in capsys.readouterr().out


def test_failed_install_restores_existing_content(tmp_path, monkeypatch, capsys):
    """Workflow-Test
    主题：一次安装后可在三种操作系统开始使用工作流
    测试项：TC-04 所有失败路径恢复确认前状态
    验收条件：AC-04 异常不留下半套安装
    测试方式：自动化测试 + 人工验收
    测试层级：集成测试
    测试目标：项目骨架写入后发生异常时恢复旧契约并删除新骨架
    测试入口：tests/test_installer.py::test_failed_install_restores_existing_content
    代码入口：workflow_loop.installer.install_project_transaction
    """
    old_agents = "# existing contract\n"
    (tmp_path / "AGENTS.md").write_text(old_agents, encoding="utf-8")
    token_path = tmp_path / "token.json"
    _write_token(tmp_path, token_path)

    def fail_create_project(_project_root):
        raise OSError("injected failure")

    monkeypatch.setattr(installer, "create_project", fail_create_project)

    assert installer.install_project_transaction(str(tmp_path), str(token_path)) == 1
    assert (tmp_path / "AGENTS.md").read_text(encoding="utf-8") == old_agents
    assert not (tmp_path / ".workflow_loop").exists()
    assert not (tmp_path / installer.TRANSACTION_DIRNAME).exists()
    assert "全部修改已恢复" in capsys.readouterr().out


def test_broken_existing_skeleton_is_not_overwritten(tmp_path, capsys):
    """Workflow-Test
    主题：一次安装后可在三种操作系统开始使用工作流
    测试项：TC-04 所有失败路径恢复确认前状态
    验收条件：AC-04 异常不留下半套安装
    测试方式：自动化测试 + 人工验收
    测试层级：集成测试
    测试目标：遇到不完整旧骨架时停止而不覆盖其中内容
    测试入口：tests/test_installer.py::test_broken_existing_skeleton_is_not_overwritten
    代码入口：workflow_loop.installer.install_project_transaction
    """
    workflow_dir = tmp_path / ".workflow_loop"
    workflow_dir.mkdir()
    custom = workflow_dir / "custom.txt"
    custom.write_text("keep", encoding="utf-8")
    token_path = tmp_path / "token.json"
    _write_token(tmp_path, token_path)

    assert installer.install_project_transaction(str(tmp_path), str(token_path)) == 1
    assert custom.read_text(encoding="utf-8") == "keep"
    assert "安装骨架不完整" in capsys.readouterr().out


def test_repeat_install_keeps_complete_project_unchanged(tmp_path, capsys):
    """Workflow-Test
    主题：一次安装后可在三种操作系统开始使用工作流
    测试项：TC-05 重复安装只补缺失一侧
    验收条件：AC-05 重复安装只补缺少部分
    测试方式：自动化测试 + 人工验收
    测试层级：集成测试
    测试目标：项目侧已完整时重复安装不改动定制内容
    测试入口：tests/test_installer.py::test_repeat_install_keeps_complete_project_unchanged
    代码入口：workflow_loop.installer.install_project_transaction
    """
    first_token = tmp_path / "first-token.json"
    _write_token(tmp_path, first_token)
    assert installer.install_project_transaction(str(tmp_path), str(first_token)) == 0
    custom = tmp_path / ".workflow_loop" / "custom.txt"
    custom.write_text("keep", encoding="utf-8")
    before = _tree_hash(tmp_path / ".workflow_loop")

    second_token = tmp_path / "second-token.json"
    _write_token(tmp_path, second_token)
    assert installer.install_project_transaction(str(tmp_path), str(second_token)) == 0

    assert _tree_hash(tmp_path / ".workflow_loop") == before
    assert custom.read_text(encoding="utf-8") == "keep"
    assert "已经安装，未修改任何文件" in capsys.readouterr().out
