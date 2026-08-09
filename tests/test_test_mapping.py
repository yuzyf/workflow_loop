from pathlib import Path

import pytest

from workflow_loop.test_mapping import (
    collect_workflow_test_markers,
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
        root / "src" / "upload.py",
        "from pathlib import Path\n\n"
        "def upload_file(target, content):\n"
        "    Path(target).write_text(content, encoding='utf-8')\n",
    )
    _write(
        root / "qa" / "上传文件_测试计划.md",
        f"""# 上传文件测试计划

## 1. 验收条件覆盖

| 验收条件链接 | 测试项 | 前置测试项 | 测试方式 | 产品入口 | 代码入口 | 测试入口 | 准备数据 | 执行动作 | 观察位置 | 预期结果 | 不通过表现 | 证据要求 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
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


def _row(
    test_id="TC-01",
    name="验证上传完成",
    dependency="无",
    method="自动化测试",
    test_entry="tests/test_upload.py::test_upload",
    code_entry="src/upload.py::upload_file",
):
    return (
        "| [AC-01：上传完成](../acceptance/上传文件_验收计划.md#ac-01) | "
        f'<a id="{test_id.lower()}"></a>[{test_id} {name}](#{test_id.lower()}) | '
        f"{dependency} | {method} | 上传命令 | `{code_entry}` | "
        f"`{test_entry}` | 创建隔离临时目录 | 调用上传入口写入文件 | "
        "临时目录中的目标文件 | 目标文件存在且内容正确 | 文件缺失或内容错误 | "
        "结构化报告和目标文件内容 |"
    )


def _python_marker(
    test_name="验证上传完成",
    method="自动化测试",
    *,
    body: str | None = None,
) -> str:
    if body is None:
        body = '''    target = tmp_path / "uploaded.txt"
    upload_file(target, "saved")
    assert target.read_text(encoding="utf-8") == "saved"'''
    return f'''from src.upload import upload_file
import pytest


def test_upload(tmp_path):
    """Workflow-Test
    主题：上传文件
    测试项：TC-01 {test_name}
    验收条件：AC-01 上传完成
    测试方式：{method}
    测试层级：模块测试
    产品入口：上传命令
    测试入口：`tests/test_upload.py::test_upload`
    代码入口：`src/upload.py::upload_file`
    准备数据：创建隔离临时目录
    执行动作：调用上传入口写入文件
    关键断言：目标文件存在且内容正确
    预期证据：结构化报告和目标文件内容
    """
{body}
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
    assert "用户确认前逐项核对" in detail
    assert "测试定义=tests/test_upload.py:" in detail
    assert "动作=调用上传入口写入文件" in detail
    assert "关键断言=目标文件存在且内容正确" in detail
    assert "正文 SHA-256=" in detail
    assert "upload_file(target, \"saved\")" in detail
    marker = collect_workflow_test_markers(str(tmp_path), [TOPIC])[0]
    assert marker.definition_line > 0
    assert marker.definition_end_line >= marker.definition_line
    assert "upload_file(target, \"saved\")" in marker.body_excerpt
    assert len(marker.body_sha256) == 64


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
    _plan(
        tmp_path,
        _row(
            test_entry="src/upload_test.go::TestUpload",
            code_entry="src/upload.go::UploadFile",
        ),
    )
    _write(tmp_path / "src" / "upload.go", "func UploadFile() {}\n")
    _write(
        tmp_path / "src" / "upload_test.go",
        """// Workflow-Test
// 主题：上传文件
// 测试项：TC-01 验证上传完成
// 验收条件：AC-01 上传完成
// 测试方式：自动化测试
// 测试层级：模块测试
// 产品入口：上传命令
// 测试入口：`src/upload_test.go::TestUpload`
// 代码入口：`src/upload.go::UploadFile`
// 准备数据：创建隔离临时目录
// 执行动作：调用上传入口写入文件
// 关键断言：目标文件存在且内容正确
// 预期证据：结构化报告和目标文件内容
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
        "    预期证据：结构化报告和目标文件内容\n    \"\"\"",
        """    预期证据：结构化报告和目标文件内容

    Workflow-Test
    主题：上传文件
    测试项：TC-02 另一个测试项
    验收条件：AC-02 另一个条件
    测试方式：自动化测试
    测试层级：模块测试
    产品入口：上传命令
    测试入口：`tests/test_upload.py::test_upload`
    代码入口：`src/upload.py::upload_file`
    准备数据：创建隔离临时目录
    执行动作：调用上传入口写入文件
    关键断言：目标文件存在且内容正确
    预期证据：结构化报告和目标文件内容
    \"\"\"""",
    )
    _write(tmp_path / "tests" / "test_upload.py", content)

    ok, detail = validate_workflow_test_markers(str(tmp_path), [TOPIC])

    assert ok is False
    assert "只能写一个 Workflow-Test 标识" in detail


@pytest.mark.parametrize(
    ("body", "expected_reason"),
    [
        ("", "没有测试代码"),
        ("    pass", "只有 pass 空语句"),
        ("    ...", "只有 Ellipsis（...）空语句"),
        ("    return True", "只返回固定常量"),
        ("    return {'status': 'passed'}", "只返回固定常量"),
        ("    assert True", "只有恒真的字面量断言"),
        ("    assert 'always true'", "只有恒真的字面量断言"),
    ],
)
def test_python_workflow_marker_rejects_only_obvious_noop_body(
    tmp_path,
    body,
    expected_reason,
):
    """明显不会验证行为的 Python 测试必须在登记前被拒绝。"""
    _plan(tmp_path, _row())
    _write(tmp_path / "tests" / "test_upload.py", _python_marker(body=body))

    ok, detail = validate_workflow_test_markers(str(tmp_path), [TOPIC])

    assert ok is False
    assert expected_reason in detail
    assert "tests/test_upload.py:" in detail
    assert "调用真实目标并断言操作后的可检查状态" in detail


@pytest.mark.parametrize(
    "body",
    [
        "    role = 'superadmin'\n    assert role == 'superadmin'",
        (
            "    target = type('Target', (), {})()\n"
            "    target.manually_edited = 1\n"
            "    assert target.manually_edited == 1"
        ),
    ],
)
def test_python_workflow_marker_rejects_self_authored_results(tmp_path, body):
    """自己写入常量或属性再原样断言不能证明产品行为。"""
    _plan(tmp_path, _row())
    _write(tmp_path / "tests" / "test_upload.py", _python_marker(body=body))

    ok, detail = validate_workflow_test_markers(str(tmp_path), [TOPIC])

    assert ok is False
    assert "只断言测试代码刚写入的常量或属性（自造结果）" in detail
    assert "tests/test_upload.py:" in detail
    assert "调用真实目标并断言操作后的可检查状态" in detail


@pytest.mark.parametrize(
    "body",
    [
        "    assert helper_result()",
        "    return helper_result()",
        "    result = helper_result()\n    assert result == 'saved'",
        "    with pytest.raises(ValueError):\n        raise ValueError('expected')",
    ],
)
def test_python_workflow_marker_keeps_nontrivial_helpers_and_expected_errors(
    tmp_path,
    body,
):
    """调用辅助函数或检查预期异常的测试不能被空测试规则误伤。"""
    _plan(tmp_path, _row())
    _write(tmp_path / "tests" / "test_upload.py", _python_marker(body=body))

    ok, detail = validate_workflow_test_markers(str(tmp_path), [TOPIC])

    assert ok is True, detail
