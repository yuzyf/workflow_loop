from pathlib import Path

from workflow_loop.artifact_validation import (
    validate_test_execution_results,
    validate_test_plan_documents,
)
from workflow_loop.project import create_project
from workflow_loop.state import StageState, WorkflowState, save_state
from workflow_loop.stages.stages import TestCodeStage
from workflow_loop.test_mapping import (
    parse_test_plan_items,
    validate_workflow_test_markers,
)
from workflow_loop.verification import (
    compute_non_test_code_snapshot_hash,
    compute_test_code_snapshot_hash,
)


WORKFLOW_ID = "2026-07-28-1200-test"
TOPIC = "上传文件"


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _write_topic_documents(tmp_path: Path, method: str) -> None:
    result_cell = (
        f"[测试结果](./{TOPIC}_result.md)"
        if method != "人工验收"
        else "无自动化测试项"
    )
    downstream = (
        f"[主题测试结果](./{TOPIC}_result.md)"
        if method != "人工验收"
        else "无自动化测试结果，转主题验收"
    )
    _write(
        tmp_path / "acceptance" / "index.md",
        f"""# 验收主题索引

## {WORKFLOW_ID}

### 主题关系

| 展示顺序 | 验收主题 | 前置主题 | 验收计划 | 主题验收结果 |
|---|---|---|---|---|
| 1 | {TOPIC} | 无 | [验收计划](./{TOPIC}_plan.md) | [验收结果](./{TOPIC}_result.md) |
""",
    )
    _write(
        tmp_path / "acceptance" / f"{TOPIC}_plan.md",
        f"""# 【验收主题】{TOPIC}

## 1. 本次需求与验收目标

上传完成。

## 2. 产品设计依据

- [产品设计](../spec/product.md)

## 3. 验收范围

- 上传文件。

## 4. 验收条件

### AC-01：上传完成

- 条件与触发：用户上传文件。
- 预期结果：系统保存文件。
- 产品设计依据：[产品设计](../spec/product.md)

## 5. 完成判定

- AC-01 通过。

## 6. 上下游文档

- [需求交付追踪表](../traceability.md)
- [测试计划](../qa/{TOPIC}_plan.md)
""",
    )
    _write(
        tmp_path / "qa" / "index.md",
        f"""# 测试计划索引

## {WORKFLOW_ID}

### 主题关系

| 展示顺序 | 验收主题 | 前置主题 | 验收计划 | 测试计划 | 测试结果 |
|---|---|---|---|---|---|
| 1 | {TOPIC} | 无 | [验收计划](../acceptance/{TOPIC}_plan.md) | [测试计划](./{TOPIC}_plan.md) | {result_cell} |
""",
    )
    _write(
        tmp_path / "qa" / f"{TOPIC}_plan.md",
        f"""# {TOPIC}测试计划

- 工作流编号：{WORKFLOW_ID}
- 上游验收计划：[验收计划](../acceptance/{TOPIC}_plan.md)

## 1. 验收条件覆盖

| 验收条件链接 | 测试项 | 前置测试项 | 测试方式 | 验证方向 | 预期观察结果 | 证据要求 |
|---|---|---|---|---|---|---|
| [AC-01：上传完成](../acceptance/{TOPIC}_plan.md#ac-01) | <a id="tc-01"></a>[TC-01 验证上传完成](#tc-01) | 无 | {method} | 检查上传结果 | 文件被保存 | 保留结果证据 |

## 2. 针对性回归范围

暂无

## 3. 测试条件要求

暂无

## 4. 未决测试条件

暂无

## 5. 上下游文档

- 上游验收计划：[验收计划](../acceptance/{TOPIC}_plan.md)
- 下游实施计划：[实施计划](../impl/index.md)
- 下游测试结果：{downstream}
""",
    )
    _write(
        tmp_path / "traceability.md",
        f"""# 需求交付追踪表

## {WORKFLOW_ID}

### 交付链路

| 需求来源与设计依据 | 验收主题 | 验收条件 | 测试项 | 实施计划与任务 | 实施记录与代码 | 测试结果 | 验收结果 | 更新后的代码设计 |
|---|---|---|---|---|---|---|---|---|
| [产品设计](./spec/product.md) | [{TOPIC}](./acceptance/{TOPIC}_plan.md) | AC-01：上传完成 | 待制定 | 待制定 | 待执行 | 待执行 | 待执行 | 待更新 |
""",
    )


def test_parse_test_plan_reads_test_method_and_primary_acceptance_criterion(tmp_path):
    _write_topic_documents(tmp_path, "自动化测试 + 人工验收")

    items = parse_test_plan_items(str(tmp_path), TOPIC)

    assert len(items) == 1
    assert items[0].criterion_id == "AC-01"
    assert items[0].criterion_name == "上传完成"
    assert items[0].test_id == "TC-01"
    assert items[0].test_name == "验证上传完成"
    assert items[0].test_method == "自动化测试 + 人工验收"
    assert items[0].dependencies == ()
    assert items[0].requires_test_code is True


def test_test_plan_reads_direct_dependencies_and_rejects_cycles(tmp_path):
    _write_topic_documents(tmp_path, "自动化测试")
    path = tmp_path / "qa" / f"{TOPIC}_plan.md"
    content = path.read_text(encoding="utf-8")
    first_row = (
        f'| [AC-01：上传完成](../acceptance/{TOPIC}_plan.md#ac-01) | '
        '<a id="tc-01"></a>[TC-01 验证上传完成](#tc-01) | 无 | '
        '自动化测试 | 检查上传结果 | 文件被保存 | 保留结果证据 |'
    )
    second_row = (
        f'| [AC-01：上传完成](../acceptance/{TOPIC}_plan.md#ac-01) | '
        '<a id="tc-02"></a>[TC-02 检查上传状态](#tc-02) | TC-01 | '
        '自动化测试 | 检查上传状态 | 状态为已完成 | 保留状态证据 |'
    )
    path.write_text(content.replace(first_row, first_row + "\n" + second_row), encoding="utf-8")

    items = parse_test_plan_items(str(tmp_path), TOPIC)

    assert items[1].dependencies == ("TC-01",)

    cyclic = path.read_text(encoding="utf-8").replace(
        '| <a id="tc-01"></a>[TC-01 验证上传完成](#tc-01) | 无 |',
        '| <a id="tc-01"></a>[TC-01 验证上传完成](#tc-01) | TC-02 |',
    )
    path.write_text(cyclic, encoding="utf-8")
    try:
        parse_test_plan_items(str(tmp_path), TOPIC)
    except ValueError as exc:
        assert "依赖存在循环" in str(exc)
    else:
        raise AssertionError("循环测试项依赖必须被拒绝")


def test_automated_test_cannot_depend_on_manual_acceptance(tmp_path):
    _write_topic_documents(tmp_path, "人工验收")
    path = tmp_path / "qa" / f"{TOPIC}_plan.md"
    content = path.read_text(encoding="utf-8")
    first_row = (
        "| [AC-01：上传完成](../acceptance/上传文件_plan.md#ac-01) | "
        '<a id="tc-01"></a>[TC-01 验证上传完成](#tc-01) | 无 | '
        "人工验收 | 检查上传结果 | 文件被保存 | 保留结果证据 |"
    )
    second_row = (
        "| [AC-01：上传完成](../acceptance/上传文件_plan.md#ac-01) | "
        '<a id="tc-02"></a>[TC-02 自动检查上传结果](#tc-02) | TC-01 | '
        "自动化测试 | 检查机器结果 | 已完成 | 保留执行证据 |"
    )
    content = content.replace(
        first_row,
        first_row + "\n" + second_row,
    )
    path.write_text(content, encoding="utf-8")

    try:
        parse_test_plan_items(str(tmp_path), TOPIC)
    except ValueError as exc:
        assert "不能依赖人工验收项" in str(exc)
    else:
        raise AssertionError("自动化测试依赖人工验收项必须被拒绝")


def test_manual_only_topic_needs_no_test_result_or_test_code_change(tmp_path):
    create_project(str(tmp_path))
    _write_topic_documents(tmp_path, "人工验收")
    state = WorkflowState(
        workflow_id=WORKFLOW_ID,
        intent="from_scratch",
        current_stage="test_code",
        topics=[TOPIC],
        stages={"test_code": StageState(status="in_progress")},
    )
    state.stages["test_code"].test_code_baseline_hash = compute_test_code_snapshot_hash(
        str(tmp_path)
    )
    state.stages["test_code"].non_test_code_baseline_hash = (
        compute_non_test_code_snapshot_hash(str(tmp_path))
    )
    save_state(str(tmp_path), state)

    plan_ok, plan_detail = validate_test_plan_documents(
        str(tmp_path), WORKFLOW_ID, [TOPIC]
    )
    code_ok, code_detail = TestCodeStage().code_validate(str(tmp_path))
    result_ok, result_detail = validate_test_execution_results(
        str(tmp_path), WORKFLOW_ID, [TOPIC]
    )

    assert plan_ok is True, plan_detail
    assert code_ok is True, code_detail
    assert "无需新增测试代码" in code_detail
    assert result_ok is True, result_detail
    assert "直接进入主题验收" in result_detail


def test_workflow_test_marker_must_match_plan_names_method_level_and_entry(tmp_path):
    _write_topic_documents(tmp_path, "自动化测试")
    _write(
        tmp_path / "tests" / "test_upload.py",
        """def test_upload():
    \"\"\"Workflow-Test
    主题：上传文件
    测试项：TC-01 验证上传完成
    验收条件：AC-01 上传完成
    测试方式：自动化测试
    测试层级：命令测试
    测试目标：运行上传命令后检查文件已经保存
    测试入口：tests/test_upload.py::test_upload
    代码入口：workflow upload 调用 src/upload.py 的 upload_file()
    \"\"\"
    assert True
""",
    )

    ok, detail = validate_workflow_test_markers(str(tmp_path), [TOPIC])

    assert ok is True, detail
    assert "1 个自动化测试项" in detail


def test_workflow_test_marker_rejects_bare_ids_without_readable_names(tmp_path):
    _write_topic_documents(tmp_path, "自动化测试")
    _write(
        tmp_path / "tests" / "test_upload.py",
        """def test_upload():
    \"\"\"Workflow-Test
    主题：上传文件
    测试项：TC-01 错误名称
    验收条件：AC-01 上传完成
    测试方式：自动化测试
    测试层级：命令测试
    测试目标：运行上传命令后检查文件已经保存
    测试入口：tests/test_upload.py::test_upload
    代码入口：workflow upload 调用 src/upload.py 的 upload_file()
    \"\"\"
    assert True
""",
    )

    ok, detail = validate_workflow_test_markers(str(tmp_path), [TOPIC])

    assert ok is False
    assert "测试项名称应为“验证上传完成”" in detail


def test_workflow_test_marker_scans_cross_language_test_filenames(tmp_path):
    _write_topic_documents(tmp_path, "自动化测试")
    _write(
        tmp_path / "src" / "upload_test.go",
        """// Workflow-Test
// 主题：上传文件
// 测试项：TC-01 验证上传完成
// 验收条件：AC-01 上传完成
// 测试方式：自动化测试
// 测试层级：模块测试
// 测试目标：调用上传逻辑后检查文件已经保存
// 测试入口：src/upload_test.go::TestUpload
// 代码入口：src/upload.go 的 UploadFile()
func TestUpload(t *testing.T) {}
""",
    )

    ok, detail = validate_workflow_test_markers(str(tmp_path), [TOPIC])

    assert ok is True, detail


def test_python_marker_inside_test_data_string_cannot_satisfy_gate(tmp_path):
    _write_topic_documents(tmp_path, "自动化测试")
    _write(
        tmp_path / "tests" / "test_upload.py",
        '''def test_build_marker_sample():
    marker_sample = """Workflow-Test
主题：上传文件
测试项：TC-01 验证上传完成
验收条件：AC-01 上传完成
测试方式：自动化测试
测试层级：命令测试
测试目标：运行上传命令后检查文件已经保存
测试入口：tests/test_upload.py::test_build_marker_sample
代码入口：workflow upload 调用 src/upload.py 的 upload_file()
"""
    assert "Workflow-Test" in marker_sample
''',
    )

    ok, detail = validate_workflow_test_markers(str(tmp_path), [TOPIC])

    assert ok is False
    assert "缺少 Workflow-Test 标识" in detail


def test_non_python_marker_inside_plain_string_cannot_satisfy_gate(tmp_path):
    _write_topic_documents(tmp_path, "自动化测试")
    _write(
        tmp_path / "tests" / "upload.test.ts",
        """const marker = `Workflow-Test
主题：上传文件
测试项：TC-01 验证上传完成
验收条件：AC-01 上传完成
测试方式：自动化测试
测试层级：接口测试
测试目标：上传后检查保存结果
测试入口：tests/upload.test.ts::upload
代码入口：uploadFile()
`;
test('upload', () => expect(marker).toContain('Workflow-Test'));
""",
    )

    ok, detail = validate_workflow_test_markers(str(tmp_path), [TOPIC])

    assert ok is False
    assert "缺少 Workflow-Test 标识" in detail


def test_python_test_function_cannot_bind_two_workflow_test_items(tmp_path):
    _write_topic_documents(tmp_path, "自动化测试")
    _write(
        tmp_path / "tests" / "test_upload.py",
        '''def test_upload():
    """Workflow-Test
    主题：上传文件
    测试项：TC-01 验证上传完成
    验收条件：AC-01 上传完成
    测试方式：自动化测试
    测试层级：命令测试
    测试目标：验证上传完成
    测试入口：tests/test_upload.py::test_upload
    代码入口：upload_file()
    Workflow-Test
    主题：上传文件
    测试项：TC-02 验证另一个结果
    验收条件：AC-02 另一个结果
    测试方式：自动化测试
    测试层级：命令测试
    测试目标：验证另一个结果
    测试入口：tests/test_upload.py::test_upload
    代码入口：other_entry()
    """
    assert True
''',
    )

    ok, detail = validate_workflow_test_markers(str(tmp_path), [TOPIC])

    assert ok is False
    assert "只能写一个 Workflow-Test 标识" in detail
