import pytest

from workflow_loop.test_entry import (
    normalized_entry_config,
    referenced_project_scripts,
    select_entry,
    validate_entry_config,
)


TOPIC = "验收测试和实施计划按同一主题完整追踪"


def test_platform_entry_prefers_exact_platform_then_default():
    """Workflow-Test
    主题：验收测试和实施计划按同一主题完整追踪
    测试项：TC-05 项目专属全量入口按系统保存且不执行修改前回归
    验收条件：AC-05 全量测试入口属于当前项目
    测试方式：自动化测试
    测试层级：单元测试
    测试目标：当前系统使用自己的参数数组且仅在缺失时回退默认入口
    测试入口：tests/test_test_entry.py::test_platform_entry_prefers_exact_platform_then_default
    代码入口：workflow_loop.test_entry.select_entry
    """
    config = {
        "default": ["python", "-m", "pytest"],
        "windows": [".venv\\Scripts\\python.exe", "-m", "pytest", "-q"],
    }

    assert select_entry(config, "windows") == config["windows"]
    assert select_entry(config, "linux") == config["default"]


@pytest.mark.parametrize(
    "config",
    [
        {"unknown": ["pytest"]},
        {"linux": []},
        {"linux": "pytest -q"},
        {"linux": ["pytest", "|", "tee", "out.txt"]},
        {"linux": ["pytest", 3]},
    ],
)
def test_entry_rejects_strings_shell_operators_and_invalid_platforms(config):
    """Workflow-Test
    主题：验收测试和实施计划按同一主题完整追踪
    测试项：TC-05 项目专属全量入口按系统保存且不执行修改前回归
    验收条件：AC-05 全量测试入口属于当前项目
    测试方式：自动化测试
    测试层级：单元测试
    测试目标：入口只接受已知系统的非空字符串数组且不能隐式调用 Shell
    测试入口：tests/test_test_entry.py::test_entry_rejects_strings_shell_operators_and_invalid_platforms
    代码入口：workflow_loop.test_entry.validate_entry_config
    """
    assert validate_entry_config(config)
    with pytest.raises(ValueError):
        normalized_entry_config(config)


def test_project_scripts_are_discovered_without_path_escape():
    """Workflow-Test
    主题：验收测试和实施计划按同一主题完整追踪
    测试项：TC-05 项目专属全量入口按系统保存且不执行修改前回归
    验收条件：AC-05 全量测试入口属于当前项目
    测试方式：自动化测试
    测试层级：单元测试
    测试目标：只把项目内明确引用的复杂入口脚本纳入测试代码哈希
    测试入口：tests/test_test_entry.py::test_project_scripts_are_discovered_without_path_escape
    代码入口：workflow_loop.test_entry.referenced_project_scripts
    """
    config = {
        "linux": ["bash", "scripts/test_all.sh"],
        "windows": ["powershell", "-File", "scripts\\test_all.ps1"],
        "default": ["python", "../outside.py"],
    }

    assert referenced_project_scripts(config) == [
        "scripts/test_all.ps1",
        "scripts/test_all.sh",
    ]
