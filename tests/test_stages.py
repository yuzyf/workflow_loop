from pathlib import Path

from workflow_loop.project import create_project
from workflow_loop.state import StageState, WorkflowState, save_state
from workflow_loop.stages.stages import (
    AcceptancePlanStage,
    ImplStage,
    SpikeStage,
    SpecStage,
    TestCodeStage,
    TestExecutionStage,
)
from workflow_loop.verification import compute_non_test_code_snapshot_hash


DESIGN_TOPIC = "产品和代码设计及缺陷穿刺结论保持真实一致"
PLAN_TOPIC = "验收测试和实施计划按同一主题完整追踪"


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _acceptance_fixture(root: Path, *, missing_expected_result: bool = False) -> WorkflowState:
    create_project(str(root))
    state = WorkflowState(
        workflow_id="wf",
        intent="product_change",
        current_stage="acceptance_plan",
        topics=["上传文件"],
        stages={"acceptance_plan": StageState(status="in_progress")},
    )
    save_state(str(root), state)
    _write(
        root / "acceptance" / "索引.md",
        """# 验收主题索引

## wf

| 展示顺序 | 验收主题 | 前置主题 | 验收计划 | 主题验收结果 |
| --- | --- | --- | --- | --- |
| 1 | 上传文件 | 无 | [验收计划](./上传文件_验收计划.md) | [验收结果](./上传文件_验收结果.md) |
""",
    )
    expected_result = "" if missing_expected_result else "- 预期结果：文件被保存并返回明确结果。\n"
    _write(
        root / "acceptance" / "上传文件_验收计划.md",
        f"""# 【验收主题】上传文件

- 工作流编号：wf
- 验收主题：上传文件

## 1. 本次需求与验收目标

验证上传结果。

## 2. 产品设计依据

- [上传功能](../spec/功能_上传文件.md)

## 3. 验收范围

- 只验收上传行为。

## 4. 验收条件

### AC-01：上传完成

- 条件与触发：用户选择有效文件并提交。
{expected_result}- 产品设计依据：[上传功能](../spec/功能_上传文件.md)

## 5. 完成判定

- AC-01 通过。

## 6. 上下游文档

- [需求交付追踪表](../需求交付追踪表.md)
- [测试计划](../qa/上传文件_测试计划.md)
""",
    )
    _write(
        root / "需求交付追踪表.md",
        """# 需求交付追踪表

## wf

| 需求来源与设计依据 | 验收主题 | 验收条件 | 测试项 | 实施计划与任务 | 实施记录与代码 | 测试结果 | 验收结果 | 更新后的代码设计 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| [产品设计](./spec/功能_上传文件.md) | [上传文件](./acceptance/上传文件_验收计划.md) | AC-01：上传完成 | 待制定 | 待制定 | 待执行 | 待执行 | 待执行 | 待更新 |
""",
    )
    return state


def _impl_fixture(root: Path) -> WorkflowState:
    state = _acceptance_fixture(root)
    state.current_stage = "impl"
    state.stages["impl"] = StageState(status="in_progress")
    _write(
        root / "qa" / "索引.md",
        """# 测试计划索引

## wf

| 展示顺序 | 验收主题 | 前置主题 | 验收计划 | 测试计划 | 测试结果 |
| --- | --- | --- | --- | --- | --- |
| 1 | 上传文件 | 无 | [验收计划](../acceptance/上传文件_验收计划.md) | [测试计划](./上传文件_测试计划.md) | [测试结果](./上传文件_测试结果.md) |
""",
    )
    _write(
        root / "impl" / "索引.md",
        """# 实施索引

## wf

| 展示顺序 | 验收主题 | 前置主题 | 验收计划 | 测试计划 | 实施文档 |
| --- | --- | --- | --- | --- | --- |
| 1 | 上传文件 | 无 | [验收计划](../acceptance/上传文件_验收计划.md) | [测试计划](../qa/上传文件_测试计划.md) | [实施文档](./上传文件_实施记录.md) |
""",
    )
    _write(
        root / "impl" / "上传文件_实施记录.md",
        """# 【实施】上传文件

- 工作流编号：wf
- 验收主题：上传文件

## 1. 实施依据

- AC-01；TC-01。

## 2. 实施前计划

### 2.1 实施目标

实现上传。

### 2.2 代码修改计划

| 文件 | 类、函数或配置项 | 当前逻辑 | 计划修改的具体逻辑 |
| --- | --- | --- | --- |
| src/upload.py | upload | 暂无 | 新增上传 |

### 2.3 开发检查计划

- 语法检查。

### 2.4 未决问题

暂无

## 4. 上下游文档

- [验收计划](../acceptance/上传文件_验收计划.md)
- [测试计划](../qa/上传文件_测试计划.md)
""",
    )
    state.stages["impl"].code_baseline_hash = compute_non_test_code_snapshot_hash(str(root))
    save_state(str(root), state)
    return state


def test_spec_stage_accepts_linked_chinese_product_documents(tmp_path):
    """Workflow-Test
    主题：产品和代码设计及缺陷穿刺结论保持真实一致
    测试项：TC-02 产品设计结构和修改范围
    验收条件：AC-02 产品设计只记录已确认内容
    测试方式：自动化测试 + 人工验收
    测试层级：模块测试
    测试目标：本轮新建的产品总说明必须链接至少一份有完整中文标题的功能文档
    测试入口：tests/test_stages.py::test_spec_stage_accepts_linked_chinese_product_documents
    代码入口：workflow_loop.stages.stages.SpecStage.code_validate
    """
    create_project(str(tmp_path))
    stage_state = StageState(
        status="in_progress",
        artifact_baseline_captured_at="2026-08-03T00:00:00+00:00",
        artifact_baseline_hashes={
            "spec/产品总说明.md": None,
            "spec/功能_安装.md": None,
        },
    )
    save_state(
        str(tmp_path),
        WorkflowState(
            workflow_id="wf",
            intent="from_scratch",
            current_stage="spec",
            stages={"spec": stage_state},
        ),
    )
    _write(tmp_path / "spec" / "产品总说明.md", "# 产品总说明\n\n[安装](./功能_安装.md)\n")
    _write(tmp_path / "spec" / "功能_安装.md", "# 【功能】一次安装\n")

    ok, detail = SpecStage().code_validate(str(tmp_path))

    assert ok is True, detail


def test_spec_stage_rejects_missing_linked_feature_document(tmp_path):
    """Workflow-Test
    主题：产品和代码设计及缺陷穿刺结论保持真实一致
    测试项：TC-02 产品设计结构和修改范围
    验收条件：AC-02 产品设计只记录已确认内容
    测试方式：自动化测试 + 人工验收
    测试层级：模块测试
    测试目标：产品总说明链接不存在的当前功能文档时阻止确认
    测试入口：tests/test_stages.py::test_spec_stage_rejects_missing_linked_feature_document
    代码入口：workflow_loop.stages.stages.SpecStage.code_validate
    """
    create_project(str(tmp_path))
    save_state(
        str(tmp_path),
        WorkflowState(
            workflow_id="wf",
            intent="product_change",
            current_stage="spec",
            stages={"spec": StageState(status="in_progress")},
        ),
    )
    _write(tmp_path / "spec" / "产品总说明.md", "[缺失功能](./功能_缺失.md)\n")

    ok, detail = SpecStage().code_validate(str(tmp_path))

    assert ok is False
    assert "链接的功能文档不存在" in detail


def test_acceptance_plan_requires_complete_judgable_fields(tmp_path):
    """Workflow-Test
    主题：验收测试和实施计划按同一主题完整追踪
    测试项：TC-02 验收条件字段和产品依据可判断
    验收条件：AC-02 验收条件可以直接判断
    测试方式：自动化测试 + 人工验收
    测试层级：模块测试
    测试目标：完整触发、结果和产品依据可以通过而缺少明确结果必须失败
    测试入口：tests/test_stages.py::test_acceptance_plan_requires_complete_judgable_fields
    代码入口：workflow_loop.artifact_validation.validate_acceptance_plan_documents
    """
    _acceptance_fixture(tmp_path)
    ok, detail = AcceptancePlanStage().code_validate(str(tmp_path))
    assert ok is True, detail

    broken = tmp_path / "broken"
    _acceptance_fixture(broken, missing_expected_result=True)
    ok, detail = AcceptancePlanStage().code_validate(str(broken))
    assert ok is False
    assert "缺少具体“预期结果”" in detail


def test_impl_discussion_requires_every_topic_plan_and_no_unresolved_question(tmp_path):
    """Workflow-Test
    主题：验收测试和实施计划按同一主题完整追踪
    测试项：TC-06 全部实施计划确认后才能改代码
    验收条件：AC-06 全部实施计划确认后才能改代码
    测试方式：自动化测试 + 人工验收
    测试层级：模块测试
    测试目标：主题索引、实施文档、代码位置和未决问题全部就绪后才允许确认实施计划
    测试入口：tests/test_stages.py::test_impl_discussion_requires_every_topic_plan_and_no_unresolved_question
    代码入口：workflow_loop.stages.stages.ImplStage.discussion_validate
    """
    state = _impl_fixture(tmp_path)

    ok, detail = ImplStage().discussion_validate(str(tmp_path), state)

    assert ok is True, detail

    impl_path = tmp_path / "impl" / "上传文件_实施记录.md"
    impl_path.write_text(
        impl_path.read_text(encoding="utf-8").replace("### 2.4 未决问题\n\n暂无", "### 2.4 未决问题\n\n接口未确定"),
        encoding="utf-8",
    )
    ok, detail = ImplStage().discussion_validate(str(tmp_path), state)
    assert ok is False
    assert "仍有未决问题" in detail


def test_stage_artifact_entries_use_confirmed_chinese_formal_paths():
    """Workflow-Test
    主题：产品和代码设计及缺陷穿刺结论保持真实一致
    测试项：TC-01 中文正式路径和稳定文件标识
    验收条件：AC-01 正式文档统一使用中文文件名
    测试方式：自动化测试
    测试层级：单元测试
    测试目标：各阶段向状态登记中文正式入口而不是旧英文文件名
    测试入口：tests/test_stages.py::test_stage_artifact_entries_use_confirmed_chinese_formal_paths
    代码入口：workflow_loop.stages.stages
    """
    assert SpecStage().artifact_paths() == ["spec/产品总说明.md"]
    assert SpikeStage().artifact_paths() == ["spec/穿刺清单.md"]
    assert AcceptancePlanStage().artifact_paths()[:2] == [
        "需求交付追踪表.md",
        "acceptance/索引.md",
    ]


def test_test_code_and_execution_use_separate_development_and_execution_rules():
    """Workflow-Test
    主题：项目修改可恢复且正式测试结果来自真实执行
    测试项：TC-06 测试结果严格匹配当前机器记录
    验收条件：AC-06 正式测试结果与机器记录一致
    测试方式：自动化测试
    测试层级：单元测试
    测试目标：测试代码开发规范和正式执行规范属于两个不同环节且不能混用结果
    测试入口：tests/test_stages.py::test_test_code_and_execution_use_separate_development_and_execution_rules
    代码入口：workflow_loop.stages.stages.TestCodeStage
    """
    assert TestCodeStage().standard_doc_path() == "Standardized_Repository/qa/test_code.md"
    assert TestCodeStage().additional_standard_doc_paths() == [
        "Standardized_Repository/qa/test_code_implementation.md"
    ]
    assert TestExecutionStage().standard_doc_path() == "Standardized_Repository/qa/test.md"
