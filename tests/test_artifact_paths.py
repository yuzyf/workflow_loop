from types import SimpleNamespace

import pytest

from workflow_loop import artifact_paths


TOPIC = "产品和代码设计及缺陷穿刺结论保持真实一致"


@pytest.mark.parametrize(
    ("display_name", "expected"),
    [
        ("中文 功能/名称?", "中文_功能_名称"),
        ("CON", "CON_"),
        ("A" * 100, "A" * 80),
        ("中文e\u0301", "中文"),
    ],
)
def test_file_key_is_cross_platform_safe(display_name, expected):
    """Workflow-Test
    主题：产品和代码设计及缺陷穿刺结论保持真实一致
    测试项：TC-01 中文正式路径和稳定文件标识
    验收条件：AC-01 正式文档统一使用中文文件名
    测试方式：自动化测试
    测试层级：单元测试
    测试目标：危险字符、Windows 保留名和超长名称生成跨平台安全标识
    测试入口：tests/test_artifact_paths.py::test_file_key_is_cross_platform_safe
    代码入口：workflow_loop.artifact_paths.make_file_key
    """
    assert artifact_paths.make_file_key(display_name) == expected


def test_registered_file_keys_remain_stable_and_case_insensitive_unique():
    """Workflow-Test
    主题：产品和代码设计及缺陷穿刺结论保持真实一致
    测试项：TC-01 中文正式路径和稳定文件标识
    验收条件：AC-01 正式文档统一使用中文文件名
    测试方式：自动化测试
    测试层级：模块测试
    测试目标：已登记名称保持原标识且大小写冲突的新名称获得稳定后缀
    测试入口：tests/test_artifact_paths.py::test_registered_file_keys_remain_stable_and_case_insensitive_unique
    代码入口：workflow_loop.artifact_paths.register_file_keys
    """
    project = SimpleNamespace(
        artifact_file_keys={
            "feature": {"旧功能": "File"},
            "topic": {},
            "spike": {},
            "bug": {},
        }
    )

    added = artifact_paths.register_file_keys(project, "topic", ["file", "新主题"])
    repeated = artifact_paths.register_file_keys(project, "topic", ["file", "新主题"])

    assert added == {"file": "file_2", "新主题": "新主题"}
    assert repeated == {}
    assert project.artifact_file_keys["feature"]["旧功能"] == "File"


def test_dynamic_artifact_paths_use_chinese_formal_names():
    """Workflow-Test
    主题：产品和代码设计及缺陷穿刺结论保持真实一致
    测试项：TC-01 中文正式路径和稳定文件标识
    验收条件：AC-01 正式文档统一使用中文文件名
    测试方式：自动化测试
    测试层级：单元测试
    测试目标：功能、穿刺、缺陷和主题各阶段产物统一由中文命名函数生成
    测试入口：tests/test_artifact_paths.py::test_dynamic_artifact_paths_use_chinese_formal_names
    代码入口：workflow_loop.artifact_paths
    """
    assert artifact_paths.feature_doc("安装") == "spec/功能_安装.md"
    assert artifact_paths.spike_doc("隔离安装") == "spec/穿刺_隔离安装.md"
    assert artifact_paths.bug_doc("恢复失败") == "bug/缺陷_恢复失败.md"
    assert artifact_paths.topic_acceptance_plan("安装") == "acceptance/安装_验收计划.md"
    assert artifact_paths.topic_test_result("安装") == "qa/安装_测试结果.md"
    assert artifact_paths.topic_impl_doc("安装") == "impl/安装_实施记录.md"
