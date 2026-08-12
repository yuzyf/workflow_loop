import re
from pathlib import Path

import pytest

from workflow_loop.project import create_project
from workflow_loop.state import StageState, WorkflowState, save_state
from workflow_loop.stages.stages import (
    AcceptancePlanStage,
    ImplStage,
    ReproduceStage,
    ReviseCodeDesignStage,
    SpikeStage,
    SpecStage,
    TestCodeStage,
    TestExecutionStage,
    QaStage,
)
from workflow_loop.verification import compute_non_test_code_snapshot_hash


DESIGN_TOPIC = "产品和代码设计及缺陷穿刺结论保持真实一致"
PLAN_TOPIC = "验收测试和实施计划按同一主题完整追踪"


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def test_stage_prerequisite_failures_list_all_independent_and_unchecked_items(tmp_path):
    """缺少多个前置事实时，阶段门禁一次列全并标出不能继续的检查。"""
    cases = [
        (
            SpikeStage(),
            ("工作流状态", "spec/穿刺清单.md 不存在", "穿刺清单和结论：未检查"),
        ),
        (
            ReproduceStage(),
            ("bug/ 目录不存在", "bug/索引.md 不存在", "缺陷记录内容：未检查"),
        ),
        (
            ReviseCodeDesignStage(),
            ("spec/代码架构设计.md 不存在", "本阶段修改范围"),
        ),
        (
            TestExecutionStage(),
            ("工作流状态", "测试代码确认哈希：未检查", "需求交付追踪关系：未检查"),
        ),
    ]

    for stage, expected_parts in cases:
        ok, detail = stage.code_validate(str(tmp_path))
        assert ok is False
        for expected in expected_parts:
            assert expected in detail


def _acceptance_fixture(root: Path, *, missing_checkable_result: bool = False) -> WorkflowState:
    create_project(str(root))
    state = WorkflowState(
        workflow_id="wf",
        intent="product_change",
        current_stage="acceptance_plan",
        topics=["上传文件"],
        stages={"acceptance_plan": StageState(status="in_progress")},
        spike_skipped=True,
    )
    save_state(str(root), state)
    _write(
        root / "acceptance" / "索引.md",
        """# 验收主题索引

## wf

| 展示顺序 | 验收主题 | 前置主题 | 验收计划 | 主题验收结果 |
| --- | --- | --- | --- | --- |
| 1 | 上传文件 | 无 | [验收计划](./上传文件_验收计划.md) | `./上传文件_验收结果.md`（待生成） |
""",
    )
    checkable_result = (
        "" if missing_checkable_result else "- 可检查结果：目标文件被保存，界面显示成功结果。\n"
    )
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

<a id="ac-01"></a>
### AC-01：上传完成

- 开始前状态：用户已进入上传界面且目标文件存在。
- 触发动作：用户选择有效文件并提交。
{checkable_result}- 通过标准：保存后的文件可读取且内容与输入一致。
- 不通过标准：文件缺失、内容不一致或界面没有成功结果。
- 产品设计依据：[上传功能](../spec/功能_上传文件.md)，第 4 章 R1。

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

| 需求来源与设计依据 | 验收主题 | 验收条件 | 穿刺结论与可复用内容 | 测试项 | 实施计划与任务 | 实施记录与代码 | 测试结果 | 验收结果 | 更新后的代码设计 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| [产品设计](./spec/功能_上传文件.md) | [上传文件](./acceptance/上传文件_验收计划.md) | AC-01：上传完成 | 本轮未执行穿刺，无可复用资产 | 待制定 | 待制定 | 待执行 | 待执行 | 待执行 | 待更新 |
""",
    )
    return state


def _impl_fixture(root: Path) -> WorkflowState:
    state = _acceptance_fixture(root)
    state.current_stage = "impl"
    state.stages["impl"] = StageState(status="in_progress")
    _write(
        root / "impl" / "索引.md",
        """# 实施索引

## wf

| 展示顺序 | 验收主题 | 前置主题 | 验收计划 | 实施文档 |
| --- | --- | --- | --- | --- |
| 1 | 上传文件 | 无 | [验收计划](../acceptance/上传文件_验收计划.md) | [实施文档](./上传文件_实施记录.md) |
""",
    )
    _write(
        root / "impl" / "上传文件_实施记录.md",
        """# 【实施】上传文件

- 工作流编号：wf
- 验收主题：上传文件

## 1. 实施依据

- AC-01。

## 2. 实施前计划

### 2.1 实施目标

实现上传。

### 2.2 最低实现设计

| 设计项 | 已确认做法 | 选择理由 | 对应验收条件 |
| --- | --- | --- | --- |
| 模块与职责 | `src/upload.py` 负责接收并保存上传内容 | 当前主题只需要一个上传入口 | AC-01 |
| 接口与调用顺序 | `upload` 接收输入后保存文件 | 调用方可直接取得保存结果 | AC-01 |
| 数据、状态与副作用 | 写入目标文件 | 保存结果可以直接读取核对 | AC-01 |
| 错误与边界 | 无效输入返回错误且不写文件 | 避免产生不完整结果 | AC-01 |

### 2.3 代码修改计划

| 文件 | 类、函数或配置项 | 当前逻辑 | 计划修改的具体逻辑 |
| --- | --- | --- | --- |
| src/upload.py | upload | 暂无 | 新增上传 |

#### 开发检查计划

- 语法检查。

### 2.4 未决问题

暂无

## 4. 上下游文档

- [验收计划](../acceptance/上传文件_验收计划.md)
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


def test_spec_stage_reports_all_independent_document_errors_once(tmp_path):
    """同一阶段的两个独立文档问题必须一次列出，不能首错即停。"""
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
    _write(
        tmp_path / "spec" / "产品总说明.md",
        "[缺失功能](./功能_缺失.md)\n[标题错误](./功能_标题错误.md)\n",
    )
    _write(tmp_path / "spec" / "功能_标题错误.md", "# 标题错误\n")

    ok, detail = SpecStage().code_validate(str(tmp_path))

    assert ok is False
    assert "产品总说明链接的功能文档不存在: ['spec/功能_缺失.md']" in detail
    assert "spec/功能_标题错误.md 的一级标题必须是“# 【功能】<功能名称>”" in detail


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
    _acceptance_fixture(broken, missing_checkable_result=True)
    ok, detail = AcceptancePlanStage().code_validate(str(broken))
    assert ok is False
    assert "AC-01“可检查结果”字段：缺少具体内容" in detail


@pytest.mark.parametrize(
    ("label", "valid_value"),
    [
        ("开始前状态", "用户已进入上传界面且目标文件存在。"),
        ("触发动作", "用户选择有效文件并提交。"),
        ("可检查结果", "目标文件被保存，界面显示成功结果。"),
        ("通过标准", "保存后的文件可读取且内容与输入一致。"),
        ("不通过标准", "文件缺失、内容不一致或界面没有成功结果。"),
        ("产品设计依据", "[上传功能](../spec/功能_上传文件.md)，第 4 章 R1。"),
    ],
)
def test_acceptance_plan_rejects_each_missing_or_placeholder_outcome_field(
    tmp_path,
    label,
    valid_value,
):
    """六个判断字段任一缺失或写占位词时，都必须准确指出主题和字段。"""
    for case_name, replacement, expected in (
        ("missing", "", "缺少具体内容"),
        ("placeholder", "待补充", "是占位词"),
    ):
        root = tmp_path / f"{label}-{case_name}"
        _acceptance_fixture(root)
        plan = root / "acceptance" / "上传文件_验收计划.md"
        content = plan.read_text(encoding="utf-8")
        content = content.replace(
            f"- {label}：{valid_value}",
            f"- {label}：{replacement}",
        )
        plan.write_text(content, encoding="utf-8")

        ok, detail = AcceptancePlanStage().code_validate(str(root))

        assert ok is False
        assert "acceptance/上传文件_验收计划.md" in detail
        assert f"AC-01“{label}”字段" in detail
        assert expected in detail


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


def test_impl_discussion_accepts_legacy_plan_structure_for_legacy_path(tmp_path):
    """旧路径版本继续读取旧实施计划标题，不把当前结构倒灌进历史轮次。"""
    state = _impl_fixture(tmp_path)
    state.stage_path_version = 1
    impl_path = tmp_path / "impl" / "上传文件_实施记录.md"
    content = impl_path.read_text(encoding="utf-8")
    content = re.sub(
        r"### 2\.2 最低实现设计\n.*?(?=### 2\.3 代码修改计划)",
        "",
        content,
        flags=re.DOTALL,
    ).replace("### 2.3 代码修改计划", "### 2.2 代码修改计划")
    content = content.replace("#### 开发检查计划", "### 2.3 开发检查计划")
    impl_path.write_text(content, encoding="utf-8")

    ok, detail = ImplStage().discussion_validate(str(tmp_path), state)

    assert ok is True, detail


def test_impl_gate_prefers_real_changes_over_existing_code_marker(tmp_path, monkeypatch):
    """基线后已有真实修改时，既有代码标记不能绕过三方文件集合核对。"""
    create_project(str(tmp_path))
    state = WorkflowState(
        workflow_id="wf",
        intent="product_change",
        current_stage="impl",
        topics=["上传文件"],
        stage_path=["impl"],
        stages={
            "impl": StageState(
                status="in_progress",
                code_baseline_hash="current-hash",
                existing_code_accepted_hash="current-hash",
            )
        },
    )
    save_state(str(tmp_path), state)
    stage = ImplStage()
    monkeypatch.setattr(
        stage,
        "validate_implementation_records",
        lambda _root, _state: (True, "实施文档完整", ["上传文件"]),
    )
    monkeypatch.setattr(
        "workflow_loop.stages.stages.rollback_mod.validate_prepared",
        lambda _root, _state: (True, "回退依据完整", {"prepares": [{}]}),
    )
    monkeypatch.setattr(
        "workflow_loop.stages.stages.rollback_mod.implementation_changed_paths_since_prepare",
        lambda _root, _manifest: ["src/upload.py"],
    )
    monkeypatch.setattr(
        "workflow_loop.stages.stages.rollback_mod.validate_implementation_changes",
        lambda _root, _state: (
            True,
            "实施前计划、基线后真实差异和实施后记录三方文件集合完全一致：['src/upload.py']",
        ),
    )

    def existing_code_must_not_be_used(*_args, **_kwargs):
        raise AssertionError("有真实修改时不得进入既有代码例外")

    monkeypatch.setattr(
        "workflow_loop.stages.stages.rollback_mod.validate_existing_implementation_paths",
        existing_code_must_not_be_used,
    )

    ok, detail = stage.code_validate(str(tmp_path))

    assert ok is True, detail
    assert "三方文件集合完全一致" in detail
    assert "既有实现例外" not in detail


def test_impl_gate_reports_real_change_mismatch_even_with_existing_code_marker(
    tmp_path,
    monkeypatch,
):
    """既有代码标记存在时，四类真实差异仍必须完整展示。"""
    create_project(str(tmp_path))
    state = WorkflowState(
        workflow_id="wf",
        intent="product_change",
        current_stage="impl",
        topics=["上传文件"],
        stage_path=["impl"],
        stages={
            "impl": StageState(
                status="in_progress",
                code_baseline_hash="current-hash",
                existing_code_accepted_hash="current-hash",
            )
        },
    )
    save_state(str(tmp_path), state)
    stage = ImplStage()
    monkeypatch.setattr(
        stage,
        "validate_implementation_records",
        lambda _root, _state: (True, "实施文档完整", ["上传文件"]),
    )
    monkeypatch.setattr(
        "workflow_loop.stages.stages.rollback_mod.validate_prepared",
        lambda _root, _state: (True, "回退依据完整", {"prepares": [{}]}),
    )
    monkeypatch.setattr(
        "workflow_loop.stages.stages.rollback_mod.implementation_changed_paths_since_prepare",
        lambda _root, _manifest: ["src/unplanned.py", "src/unrecorded.py"],
    )
    monkeypatch.setattr(
        "workflow_loop.stages.stages.rollback_mod.validate_implementation_changes",
        lambda _root, _state: (
            False,
            "1. 实际修改但不在实施计划：['src/unplanned.py']\n"
            "2. 实际修改但实施后记录未列出：['src/unrecorded.py']",
        ),
    )

    ok, detail = stage.code_validate(str(tmp_path))

    assert ok is False
    assert "实际修改但不在实施计划" in detail
    assert "实际修改但实施后记录未列出" in detail
    assert "既有代码例外不适用" in detail
    assert "src/unplanned.py" in detail and "src/unrecorded.py" in detail


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


def test_qa_materials_include_plan_and_result_documents_without_duplicates():
    """Workflow-Test
    主题：测试验证一次确认后连续完成并保留真实测试证据
    测试项：TC-07 QA 阶段材料同时覆盖计划、代码和结果
    验收条件：AC-07 合并测试环节仍保留各类证据边界
    测试方式：自动化测试
    测试层级：单元测试
    测试目标：qa（测试验证）一次加载测试计划模板、测试结果模板和全部对应规范，且每份材料只出现一次
    测试入口：tests/test_stages.py::test_qa_materials_include_plan_and_result_documents_without_duplicates
    代码入口：workflow_loop.stages.stages.QaStage
    """
    paths = [
        spec.relative_path
        for spec in QaStage().materials()
        if spec.relative_path is not None
    ]

    assert paths == [
        "Template_Repository/qa/test_plan.md",
        "Standardized_Repository/qa/test_plan.md",
        "Template_Repository/qa/test.md",
        "Standardized_Repository/qa/test.md",
        "Standardized_Repository/qa/test_code.md",
        "Standardized_Repository/qa/test_code_implementation.md",
    ]
    assert len(paths) == len(set(paths))
