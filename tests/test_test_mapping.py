from pathlib import Path

import pytest

from workflow_loop.test_mapping import (
    parse_test_plan_items,
    validate_workflow_test_markers,
)


TOPIC = "上传文件"
PLAN_TOPIC = "验收测试和实施计划按同一主题完整追踪"
EXECUTION_TOPIC = "项目修改可恢复且正式测试结果来自真实执行"


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _plan(root: Path, rows: str) -> None:
    _write(
        root / "qa" / "上传文件_测试计划.md",
        f"""# 上传文件测试计划

## 1. 验收条件覆盖

| 验收条件链接 | 测试项 | 前置测试项 | 测试方式 | 验证方向 | 预期观察结果 | 证据要求 |
| --- | --- | --- | --- | --- | --- | --- |
{rows}

## 2. 针对性回归范围

暂无

## 3. 测试条件要求

暂无

## 4. 未决测试条件

暂无

## 5. 上下游文档

- [验收计划](../acceptance/上传文件_验收计划.md)
""",
    )


def _row(test_id="TC-01", name="验证上传完成", dependency="无", method="自动化测试"):
    return (
        "| [AC-01：上传完成](../acceptance/上传文件_验收计划.md#ac-01) | "
        f'<a id="{test_id.lower()}"></a>[{test_id} {name}](#{test_id.lower()}) | '
        f"{dependency} | {method} | 检查上传结果 | 文件被保存 | 保留结果证据 |"
    )


def _python_marker(test_name="验证上传完成", method="自动化测试") -> str:
    return f'''def test_upload():
    """Workflow-Test
    主题：上传文件
    测试项：TC-01 {test_name}
    验收条件：AC-01 上传完成
    测试方式：{method}
    测试层级：模块测试
    测试目标：上传后检查文件真实保存
    测试入口：tests/test_upload.py::test_upload
    代码入口：src/upload.py 的 upload_file
    """
    assert True
'''


def test_test_plan_parses_method_primary_criterion_and_direct_dependencies(tmp_path):
    """Workflow-Test
    主题：验收测试和实施计划按同一主题完整追踪
    测试项：TC-04 每条验收条件都有合法测试项
    验收条件：AC-04 每条验收条件都有测试设计
    测试方式：自动化测试 + 人工验收
    测试层级：模块测试
    测试目标：测试计划逐项读取主要验收条件、测试方式和同主题直接依赖
    测试入口：tests/test_test_mapping.py::test_test_plan_parses_method_primary_criterion_and_direct_dependencies
    代码入口：workflow_loop.test_mapping.parse_test_plan_items
    """
    _plan(
        tmp_path,
        _row() + "\n" + _row("TC-02", "检查上传状态", "TC-01"),
    )

    items = parse_test_plan_items(str(tmp_path), TOPIC)

    assert [(item.test_id, item.criterion_id, item.dependencies) for item in items] == [
        ("TC-01", "AC-01", ()),
        ("TC-02", "AC-01", ("TC-01",)),
    ]


@pytest.mark.parametrize(
    ("rows", "message"),
    [
        (_row() + "\n" + _row(), "只能对应一条主要验收条件"),
        (
            _row("TC-01", dependency="TC-02")
            + "\n"
            + _row("TC-02", "检查上传状态", "TC-01"),
            "依赖存在循环",
        ),
        (
            _row(method="人工验收")
            + "\n"
            + _row("TC-02", "自动检查上传状态", "TC-01", "自动化测试"),
            "不能依赖人工验收项",
        ),
    ],
)
def test_test_plan_rejects_duplicate_cycle_and_manual_dependency(tmp_path, rows, message):
    """Workflow-Test
    主题：验收测试和实施计划按同一主题完整追踪
    测试项：TC-04 每条验收条件都有合法测试项
    验收条件：AC-04 每条验收条件都有测试设计
    测试方式：自动化测试 + 人工验收
    测试层级：模块测试
    测试目标：重复编号、循环依赖和自动化依赖人工项都必须被拒绝
    测试入口：tests/test_test_mapping.py::test_test_plan_rejects_duplicate_cycle_and_manual_dependency
    代码入口：workflow_loop.test_mapping.parse_test_plan_items
    """
    _plan(tmp_path, rows)

    with pytest.raises(ValueError, match=message):
        parse_test_plan_items(str(tmp_path), TOPIC)


def test_python_workflow_marker_binds_readable_names_method_and_entry(tmp_path):
    """Workflow-Test
    主题：项目修改可恢复且正式测试结果来自真实执行
    测试项：TC-03 测试代码追踪标识准确绑定要求
    验收条件：AC-03 测试代码能够追踪到产品要求
    测试方式：自动化测试
    测试层级：模块测试
    测试目标：真实 Python 测试文档字符串完整绑定主题、TC、AC、方式和两个入口
    测试入口：tests/test_test_mapping.py::test_python_workflow_marker_binds_readable_names_method_and_entry
    代码入口：workflow_loop.test_mapping.validate_workflow_test_markers
    """
    _plan(tmp_path, _row())
    _write(tmp_path / "tests" / "test_upload.py", _python_marker())

    ok, detail = validate_workflow_test_markers(str(tmp_path), [TOPIC])

    assert ok is True, detail


def test_marker_name_or_method_mismatch_is_rejected(tmp_path):
    """Workflow-Test
    主题：项目修改可恢复且正式测试结果来自真实执行
    测试项：TC-03 测试代码追踪标识准确绑定要求
    验收条件：AC-03 测试代码能够追踪到产品要求
    测试方式：自动化测试
    测试层级：模块测试
    测试目标：错误名称或测试方式不能冒充当前计划的追踪标识
    测试入口：tests/test_test_mapping.py::test_marker_name_or_method_mismatch_is_rejected
    代码入口：workflow_loop.test_mapping.validate_workflow_test_markers
    """
    _plan(tmp_path, _row())
    _write(tmp_path / "tests" / "test_upload.py", _python_marker("错误名称"))

    ok, detail = validate_workflow_test_markers(str(tmp_path), [TOPIC])

    assert ok is False
    assert "测试项名称应为“验证上传完成”" in detail


def test_marker_inside_python_test_data_string_cannot_satisfy_gate(tmp_path):
    """Workflow-Test
    主题：项目修改可恢复且正式测试结果来自真实执行
    测试项：TC-03 测试代码追踪标识准确绑定要求
    验收条件：AC-03 测试代码能够追踪到产品要求
    测试方式：自动化测试
    测试层级：模块测试
    测试目标：测试数据中的伪标识不能被当作测试函数的正式文档字符串
    测试入口：tests/test_test_mapping.py::test_marker_inside_python_test_data_string_cannot_satisfy_gate
    代码入口：workflow_loop.test_mapping.validate_workflow_test_markers
    """
    _plan(tmp_path, _row())
    _write(
        tmp_path / "tests" / "test_upload.py",
        "def test_upload():\n    marker = " + repr(_python_marker()) + "\n    assert marker\n",
    )

    ok, detail = validate_workflow_test_markers(str(tmp_path), [TOPIC])

    assert ok is False
    assert "缺少 Workflow-Test 标识" in detail


def test_cross_language_marker_must_be_next_to_real_test_definition(tmp_path):
    """Workflow-Test
    主题：项目修改可恢复且正式测试结果来自真实执行
    测试项：TC-03 测试代码追踪标识准确绑定要求
    验收条件：AC-03 测试代码能够追踪到产品要求
    测试方式：自动化测试
    测试层级：模块测试
    测试目标：非 Python 标识只有紧邻真实测试定义时才有效
    测试入口：tests/test_test_mapping.py::test_cross_language_marker_must_be_next_to_real_test_definition
    代码入口：workflow_loop.test_mapping.validate_workflow_test_markers
    """
    _plan(tmp_path, _row())
    _write(
        tmp_path / "src" / "upload_test.go",
        """// Workflow-Test
// 主题：上传文件
// 测试项：TC-01 验证上传完成
// 验收条件：AC-01 上传完成
// 测试方式：自动化测试
// 测试层级：模块测试
// 测试目标：上传后检查文件保存
// 测试入口：src/upload_test.go::TestUpload
// 代码入口：src/upload.go 的 UploadFile
func TestUpload(t *testing.T) {}
""",
    )

    ok, detail = validate_workflow_test_markers(str(tmp_path), [TOPIC])

    assert ok is True, detail


def test_one_python_function_cannot_bind_two_test_items(tmp_path):
    """Workflow-Test
    主题：项目修改可恢复且正式测试结果来自真实执行
    测试项：TC-03 测试代码追踪标识准确绑定要求
    验收条件：AC-03 测试代码能够追踪到产品要求
    测试方式：自动化测试
    测试层级：模块测试
    测试目标：一个测试函数不能用两个标识混合证明两个主要测试项
    测试入口：tests/test_test_mapping.py::test_one_python_function_cannot_bind_two_test_items
    代码入口：workflow_loop.test_mapping.validate_workflow_test_markers
    """
    _plan(tmp_path, _row())
    content = _python_marker().replace(
        '    """\n    assert True',
        """    Workflow-Test
    主题：上传文件
    测试项：TC-02 另一个测试项
    验收条件：AC-02 另一个条件
    测试方式：自动化测试
    测试层级：模块测试
    测试目标：另一个目标
    测试入口：tests/test_upload.py::test_upload
    代码入口：other
    \"\"\"
    assert True""",
    )
    _write(tmp_path / "tests" / "test_upload.py", content)

    ok, detail = validate_workflow_test_markers(str(tmp_path), [TOPIC])

    assert ok is False
    assert "只能写一个 Workflow-Test 标识" in detail
