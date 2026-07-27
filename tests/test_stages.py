from workflow_loop.project import create_project, register_topics
from workflow_loop.state import StageState, WorkflowState, save_state
from workflow_loop.stages.stages import (
    AcceptancePlanStage,
    ImplStage,
    ProjectDesignInitStage,
    ReproduceStage,
    RegressionTestStage,
    OverallAcceptanceStage,
    ReviseCodeDesignStage,
    SpecStage,
    SpikeStage,
    TestPlanStage,
    TopicExecutionStage,
    UpdateCodeDesignStage,
)
from workflow_loop.verification import compute_file_hashes


def _write(path, content="ready"):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _write_test_plan(tmp_path, topic):
    _write(
        tmp_path / "qa" / f"{topic}_plan.md",
        f"""# {topic}测试计划

- 工作流编号：test
- 上游验收计划：[验收计划](../acceptance/{topic}_plan.md)

## 1. 验收条件覆盖

| 验收条件链接 | 测试项 | 验证方向 | 预期观察结果 | 证据要求 |
|---|---|---|---|---|
| [AC-01：完成条件](../acceptance/{topic}_plan.md#ac-01) | <a id="tc-01"></a>[TC-01 验证{topic}完成](#tc-01) | 检查{topic} | 观察到{topic}完成 | 保留执行证据 |

## 2. 针对性回归范围

暂无

## 3. 测试条件要求

暂无

## 4. 未决测试条件

暂无

## 5. 上下游文档

- 上游验收计划：[验收计划](../acceptance/{topic}_plan.md)
- 下游实施计划：[实施计划](../impl/index.md)
- 下游测试结果：[测试结果](./{topic}_result.md)
""",
    )


def _write_qa_index(tmp_path, workflow_id, topics):
    rows = []
    for order, topic in enumerate(topics, start=1):
        rows.append(
            f"| {order} | {topic} | 无 | "
            f"[验收计划](../acceptance/{topic}_plan.md) | "
            f"[测试计划](./{topic}_plan.md) | [测试结果](./{topic}_result.md) |"
        )
    _write(tmp_path / "qa" / "index.md", f"""# 测试计划索引

## {workflow_id}

### 主题关系

| 展示顺序 | 验收主题 | 前置主题 | 验收计划 | 测试计划 | 测试结果 |
|---|---|---|---|---|---|
{chr(10).join(rows)}
""")


def _write_impl_index(tmp_path, workflow_id, topics):
    rows = []
    for order, topic in enumerate(topics, start=1):
        rows.append(
            f"| {order} | {topic} | 无 | "
            f"[验收计划](../acceptance/{topic}_plan.md) | "
            f"[测试计划](../qa/{topic}_plan.md) | [实施文档](./{topic}.md) |"
        )
    _write(tmp_path / "impl" / "index.md", f"""# 实施索引

## {workflow_id}

### 主题关系

| 展示顺序 | 验收主题 | 前置主题 | 验收计划 | 测试计划 | 实施文档 |
|---|---|---|---|---|---|
{chr(10).join(rows)}
""")


def _write_impl_topic(tmp_path, workflow_id, topic, *, with_record=False, with_difference=False):
    record = """
## 3. 实施后记录

### 3.1 实际代码修改

| 对应计划步骤 | 文件 | 类、函数或配置项 | 实际修改的代码逻辑 | 数据、状态或输出的实际变化 | 对应验收条件和测试项 |
|---|---|---|---|---|---|
| 1 | src/app.py | run | 修改处理逻辑 | 输出改变 | AC-01；TC-01 |

### 3.2 开发检查记录

| 检查命令或方法 | 检查范围 | 实际反馈 | 是否需要继续修改 |
|---|---|---|---|
| pytest | 主题逻辑 | 通过 | 否 |

### 3.3 未完成内容

暂无
""" if with_record else ""
    difference = """
## 4. 计划与实际的差异

暂无
""" if with_difference else """
## 4. 上下游文档

| 关系 | 文档 | 说明 |
|---|---|---|
| 上游 | [验收计划](../acceptance/<topic>_plan.md) | 验收依据 |
| 上游 | [测试计划](../qa/<topic>_plan.md) | 测试依据 |
| 下游 | [测试结果](../qa/<topic>_result.md) | 正式测试 |
"""
    _write(
        tmp_path / "impl" / f"{topic}.md",
        f"""# 【实施】{topic}

- 工作流编号：{workflow_id}
- 验收主题：{topic}

## 1. 实施依据

| 依据类型 | 具体内容 | 文档位置 |
|---|---|---|
| 验收条件 | AC-01：{topic}完成 | [验收计划](../acceptance/{topic}_plan.md#ac-01) |
| 测试项 | TC-01：验证{topic}完成 | [测试计划](../qa/{topic}_plan.md#tc-01) |

## 2. 实施前计划

### 2.1 预期产品结果

用户得到 {topic} 的结果。

### 2.2 代码修改计划

| 顺序 | 文件 | 类、函数或配置项 | 当前逻辑 | 计划修改的具体逻辑 | 数据、状态或输出变化 | 对应验收条件和测试项 | 前置步骤 |
|---|---|---|---|---|---|---|---|
| 1 | src/app.py | run | 当前逻辑 | 修改处理 | 输出变化 | AC-01；TC-01 | 无 |

### 2.3 开发检查计划

| 检查命令或方法 | 检查范围 | 预期观察结果 |
|---|---|---|
| pytest | 主题逻辑 | 观察到结果 |

### 2.4 未决问题

暂无
{record}{difference}
""",
    )


def _save_stage_baseline(tmp_path, stage, paths):
    save_state(str(tmp_path), WorkflowState(
        workflow_id="2026-07-24-1200-test",
        intent="product_change",
        current_stage=stage.name(),
        stage_path=[stage.name()],
        stages={
            stage.name(): StageState(
                status="in_progress",
                artifact_paths=stage.artifact_paths(),
                artifact_baseline_captured_at="2026-07-24T04:00:00+00:00",
                artifact_baseline_hashes=compute_file_hashes(str(tmp_path), paths),
            ),
        },
    ))


def _write_project_init_evidence(tmp_path, *, run_condition="具备"):
    if run_condition == "具备":
        run_fields = """- 运行条件：具备
- 执行状态：已执行
- 执行命令：`.venv/bin/pytest -q`
- 执行结果：通过
- 结果摘要：测试全部通过
- 未执行原因：暂无
- 未验证范围：暂无"""
    else:
        run_fields = """- 运行条件：不具备
- 执行状态：未执行
- 执行命令：暂无
- 执行结果：未执行
- 结果摘要：暂无
- 未执行原因：缺少只能由用户提供的本地设备
- 未验证范围：设备连接后的真实交互结果"""

    _write(tmp_path / "spec" / "project_design_init_evidence.md", f"""# 项目设计初始化调查证据

- 工作流编号：2026-07-24-1200-test
- 代码检查状态：已完成

## 1. 已检查代码

| 代码路径 | 检查内容 | 得到的事实 |
|---|---|---|
| `src/app.py` | 检查实际入口和处理顺序 | 用户调用入口后会返回处理结果 |

## 2. 测试与运行记录

{run_fields}

## 3. 产品与代码设计校准结果

已经按代码入口和运行结果同步修改产品功能文档与代码架构文档。
""")


def _write_reproduce_documents(tmp_path):
    filename = "2026-07-24_1200-上传失败.md"
    _write(tmp_path / "bug" / "index.md", f"""# Bug 索引

| Bug 记录 | 现象 | 根因 | 状态 |
|---|---|---|---|
| [上传失败](./{filename}) | 上传返回错误 | 响应字段读取错误 | 根因已确认 |
""")
    _write(tmp_path / "bug" / filename, """# 【缺陷】上传失败

- 工作流编号：2026-07-24-1200-test
- 复现状态：已复现
- 根因状态：已确认
- 验收主题：上传真实文件后成功完成处理

## 1. 缺陷现象

用户上传真实文件后看到上传失败。

## 2. 真实复现条件

- 运行环境：macOS 本地测试环境
- 真实输入：用户选择的真实 PDF 文件

## 3. 复现步骤

1. 启动程序。
2. 选择真实 PDF 文件并上传。

## 4. 实际结果

程序提示上传失败并记录字段缺失错误。

## 5. 期望结果

程序读取返回结果并显示上传成功。

## 6. 根因

- 根因说明：代码读取了不存在的 response.url 字段。
- 根因位置：src/app.py 的 upload 函数
- 根因证据：真实接口返回 download_url，运行日志显示 url 字段不存在。

## 7. 修复仍存在的不确定性

暂无
""")


def _write_acceptance_documents(tmp_path, workflow_id, topics):
    rows = []
    for topic in topics:
        _write(tmp_path / "acceptance" / f"{topic}_plan.md", f"""# 【验收主题】{topic}

## 1. 本次需求与验收目标

用户完成 {topic}。

## 2. 产品设计依据

- [产品设计](../spec/product.md)

## 3. 验收范围

- 验收 {topic}。

## 4. 验收条件

### AC-01：{topic}完成

- 条件与触发：用户执行 {topic}。
- 预期结果：用户得到 {topic} 的结果。
- 产品设计依据：[产品设计](../spec/product.md)

## 5. 完成判定

- AC-01 通过。

## 6. 上下游文档

- [需求交付追踪表](../traceability.md)
- `../qa/{topic}_plan.md`
""")
        rows.append(
            f"| [产品设计](./spec/product.md) | "
            f"[{topic}](./acceptance/{topic}_plan.md) | "
            f"AC-01：{topic}完成 | 待制定 | 待制定 | 待执行 | 待执行 | 待执行 | 待更新 |"
        )

    _write(tmp_path / "traceability.md", f"""# 需求交付追踪表

## {workflow_id}

### 交付链路

| 需求来源与设计依据 | 验收主题 | 验收条件 | 测试项 | 实施计划与任务 | 实施记录与代码 | 测试结果 | 验收结果 | 更新后的代码设计 |
|---|---|---|---|---|---|---|---|---|
{chr(10).join(rows)}
""")
    index_rows = []
    for order, topic in enumerate(topics, start=1):
        index_rows.append(
            f"| {order} | {topic} | 无 | "
            f"[验收计划](./{topic}_plan.md) | [验收结果](./{topic}_result.md) |"
        )
    _write(tmp_path / "acceptance" / "index.md", f"""# 验收主题索引

## {workflow_id}

### 主题关系

| 展示顺序 | 验收主题 | 前置主题 | 验收计划 | 主题验收结果 |
|---|---|---|---|---|
{chr(10).join(index_rows)}
""")


def test_spec_stage_accepts_english_feature_filename(tmp_path):
    stage = SpecStage()
    _save_stage_baseline(tmp_path, stage, ["spec/product.md"])
    _write(tmp_path / "spec" / "product.md")
    _write(tmp_path / "spec" / "feature_product_design_document_generation.md")

    ok, detail = stage.code_validate(str(tmp_path))

    assert ok is True
    assert "feature_product_design_document_generation.md" in detail


def test_spec_stage_rejects_legacy_chinese_feature_filename(tmp_path):
    _write(tmp_path / "spec" / "product.md")
    _write(tmp_path / "spec" / "功能产品文档生成.md")

    ok, detail = SpecStage().code_validate(str(tmp_path))

    assert ok is False
    assert "feature_*.md" in detail


def test_project_design_init_accepts_english_feature_filename(tmp_path):
    stage = ProjectDesignInitStage()
    _save_stage_baseline(
        tmp_path,
        stage,
        [
            "spec/product.md",
            "spec/architecture_code_design.md",
            "spec/project_design_init_evidence.md",
        ],
    )
    _write(tmp_path / "src" / "app.py", "def upload():\n    return 'ok'\n")
    _write(tmp_path / "spec" / "product.md")
    _write(tmp_path / "spec" / "feature_existing_product.md")
    _write(tmp_path / "spec" / "architecture_code_design.md")
    _write_project_init_evidence(tmp_path)

    ok, detail = stage.code_validate(str(tmp_path))

    assert ok is True
    assert "feature_existing_product.md" in detail


def test_spec_stage_rejects_unchanged_existing_documents(tmp_path):
    stage = SpecStage()
    _write(tmp_path / "spec" / "product.md")
    _write(tmp_path / "spec" / "feature_existing.md")
    _save_stage_baseline(tmp_path, stage, stage.change_tracked_paths(str(tmp_path)))

    ok, detail = stage.code_validate(str(tmp_path))

    assert ok is False
    assert "讨论完成时相同" in detail


def test_product_change_spec_requires_product_and_feature_changes(tmp_path):
    stage = SpecStage()
    _write(tmp_path / "spec" / "product.md", "old product")
    _write(tmp_path / "spec" / "feature_existing.md", "old feature")
    _save_stage_baseline(tmp_path, stage, stage.change_tracked_paths(str(tmp_path)))

    _write(tmp_path / "spec" / "product.md", "new product")
    ok, detail = stage.code_validate(str(tmp_path))
    assert ok is False
    assert "至少一份功能文档" in detail

    _write(tmp_path / "spec" / "feature_existing.md", "new feature")
    ok, detail = stage.code_validate(str(tmp_path))
    assert ok is True


def test_revise_code_design_requires_current_stage_change(tmp_path):
    stage = ReviseCodeDesignStage()
    architecture = tmp_path / "spec" / "architecture_code_design.md"
    _write(architecture, "old")
    _save_stage_baseline(tmp_path, stage, stage.change_tracked_paths(str(tmp_path)))

    ok, detail = stage.code_validate(str(tmp_path))
    assert ok is False
    assert "讨论完成时相同" in detail

    _write(architecture, "new")
    ok, detail = stage.code_validate(str(tmp_path))
    assert ok is True
    assert "已按本阶段产品设计修改" in detail


def test_project_design_init_accepts_documented_unavailable_run_condition(tmp_path):
    stage = ProjectDesignInitStage()
    _save_stage_baseline(
        tmp_path,
        stage,
        [
            "spec/product.md",
            "spec/architecture_code_design.md",
            "spec/project_design_init_evidence.md",
        ],
    )
    _write(tmp_path / "src" / "app.py", "def main():\n    return 0\n")
    _write(tmp_path / "spec" / "product.md")
    _write(tmp_path / "spec" / "feature_existing_product.md")
    _write(tmp_path / "spec" / "architecture_code_design.md")
    _write_project_init_evidence(tmp_path, run_condition="不具备")

    ok, detail = stage.code_validate(str(tmp_path))

    assert ok is True
    assert "调查证据有效" in detail


def test_reproduce_stage_requires_current_structured_bug_record_and_index(tmp_path):
    stage = ReproduceStage()
    _save_stage_baseline(tmp_path, stage, ["bug/index.md"])
    _write_reproduce_documents(tmp_path)

    ok, detail = stage.code_validate(str(tmp_path))

    assert ok is True
    assert "已复现、确认根因并确定验收主题" in detail


def test_reproduce_stage_rejects_arbitrary_markdown(tmp_path):
    stage = ReproduceStage()
    _save_stage_baseline(tmp_path, stage, ["bug/index.md"])
    _write(tmp_path / "bug" / "index.md", "# index")
    _write(tmp_path / "bug" / "anything.md", "anything")

    ok, detail = stage.code_validate(str(tmp_path))

    assert ok is False
    assert "文件名不符合" in detail


def test_reproduce_stage_rejects_topic_that_escapes_acceptance_directory(tmp_path):
    stage = ReproduceStage()
    _save_stage_baseline(tmp_path, stage, ["bug/index.md"])
    _write_reproduce_documents(tmp_path)
    bug_path = tmp_path / "bug" / "2026-07-24_1200-上传失败.md"
    content = bug_path.read_text(encoding="utf-8")
    bug_path.write_text(
        content.replace("验收主题：上传真实文件后成功完成处理", "验收主题：../错误路径"),
        encoding="utf-8",
    )

    ok, detail = stage.code_validate(str(tmp_path))

    assert ok is False
    assert "唯一验收主题" in detail


def test_project_design_init_rejects_legacy_chinese_feature_filename(tmp_path):
    _write(tmp_path / "spec" / "product.md")
    _write(tmp_path / "spec" / "功能已有产品.md")
    _write(tmp_path / "spec" / "architecture_code_design.md")

    ok, detail = ProjectDesignInitStage().code_validate(str(tmp_path))

    assert ok is False
    assert "spec/feature_*.md" in detail


def test_project_design_init_loads_specialized_and_shared_documents():
    stage = ProjectDesignInitStage()

    assert stage.prompt_doc_path() == "Template_Repository/code_design/project_design_init_evidence.md"
    assert stage.standard_doc_path() == "Standardized_Repository/code_design/project_design_init.md"
    assert stage.additional_doc_paths() == [
        ("Template_Repository/spec/spec.md", "Standardized_Repository/spec/spec.md"),
        ("Template_Repository/code_design/code_design.md", "Standardized_Repository/code_design/code_design.md"),
    ]
    assert "必须查看代码和测试" in stage.instruction()


def test_code_design_update_stages_share_architecture_document_template():
    assert ReviseCodeDesignStage().prompt_doc_path() == (
        "Template_Repository/code_design/code_design.md"
    )
    assert UpdateCodeDesignStage().prompt_doc_path() == (
        "Template_Repository/code_design/code_design.md"
    )


def test_topic_execution_loads_theme_acceptance_materials():
    stage = TopicExecutionStage()
    assert stage.prompt_doc_path() is None
    assert stage.standard_doc_path() == (
        "Standardized_Repository/execution/topic_execution.md"
    )
    assert stage.additional_doc_paths() == [
        (
            "Template_Repository/acceptance/acceptance_result.md",
            "Standardized_Repository/acceptance/acceptance.md",
        ),
    ]


def test_overall_acceptance_has_no_independent_document_materials():
    stage = OverallAcceptanceStage()
    assert stage.artifact_paths() == []
    assert stage.prompt_doc_path() is None
    assert stage.standard_doc_path() is None


def test_spike_stage_uses_index_as_artifact_entry():
    stage = SpikeStage()

    assert stage.artifact_paths() == ["spec/spike_index.md"]
    assert "真实场景中的技术不确定性" in stage.instruction()


def test_spike_stage_advance_returns_cleaned_paths(tmp_path):
    stage = SpikeStage()
    _write(tmp_path / ".workflow_loop" / "spike_tmp" / "api_probe" / "result.json")

    cleaned = stage.on_advance(str(tmp_path))

    assert cleaned == ["api_probe"]
    assert list((tmp_path / ".workflow_loop" / "spike_tmp").iterdir()) == []


def test_acceptance_plan_finds_new_topics_and_test_plan_requires_same_topics(tmp_path):
    create_project(str(tmp_path))
    save_state(str(tmp_path), WorkflowState(
        workflow_id="test",
        intent="from_scratch",
    ))
    _write_acceptance_documents(tmp_path, "test", ["上传文件"])

    ok, detail = AcceptancePlanStage().code_validate(str(tmp_path))
    assert ok is True
    assert "上传文件" in detail

    save_state(str(tmp_path), WorkflowState(
        workflow_id="test",
        intent="from_scratch",
        topics=["上传文件", "查看状态"],
    ))
    _write_test_plan(tmp_path, "上传文件")
    _write_qa_index(tmp_path, "test", ["上传文件"])

    ok, detail = TestPlanStage().code_validate(str(tmp_path))
    assert ok is False
    assert "查看状态_plan.md" in detail

    _write_acceptance_documents(tmp_path, "test", ["上传文件", "查看状态"])
    _write_test_plan(tmp_path, "查看状态")
    _write_qa_index(tmp_path, "test", ["上传文件", "查看状态"])
    ok, detail = TestPlanStage().code_validate(str(tmp_path))
    assert ok is True, detail
    assert "覆盖 2 条验收条件" in detail


def test_acceptance_plan_requires_topic_index(tmp_path):
    create_project(str(tmp_path))
    save_state(str(tmp_path), WorkflowState(
        workflow_id="test",
        intent="from_scratch",
        topics=["上传文件"],
    ))
    _write_acceptance_documents(tmp_path, "test", ["上传文件"])
    (tmp_path / "acceptance" / "index.md").unlink()

    ok, detail = AcceptancePlanStage().code_validate(str(tmp_path))

    assert ok is False
    assert "acceptance/index.md 不存在" in detail


def test_acceptance_plan_rejects_cyclic_topic_dependencies(tmp_path):
    create_project(str(tmp_path))
    save_state(str(tmp_path), WorkflowState(
        workflow_id="test",
        intent="from_scratch",
        topics=["上传文件", "查看状态"],
    ))
    _write_acceptance_documents(tmp_path, "test", ["上传文件", "查看状态"])
    _write(
        tmp_path / "acceptance" / "index.md",
        """# 验收主题索引

## test

### 主题关系

| 展示顺序 | 验收主题 | 前置主题 | 验收计划 | 主题验收结果 |
|---|---|---|---|---|
| 1 | 上传文件 | 查看状态 | [验收计划](./上传文件_plan.md) | [验收结果](./上传文件_result.md) |
| 2 | 查看状态 | 上传文件 | [验收计划](./查看状态_plan.md) | [验收结果](./查看状态_result.md) |
""",
    )

    ok, detail = AcceptancePlanStage().code_validate(str(tmp_path))

    assert ok is False
    assert "前置主题“查看状态”必须排在前面" in detail


def _prepare_impl_stage(tmp_path, *, with_record=False, with_difference=False):
    topic = "上传文件"
    _write_acceptance_documents(tmp_path, "test", [topic])
    _write_test_plan(tmp_path, topic)
    _write_qa_index(tmp_path, "test", [topic])
    _write_impl_index(tmp_path, "test", [topic])
    _write_impl_topic(
        tmp_path,
        "test",
        topic,
        with_record=with_record,
        with_difference=with_difference,
    )
    state = WorkflowState(
        workflow_id="test",
        intent="from_scratch",
        current_stage="impl",
        topics=[topic],
        stages={
            "impl": StageState(
                status="in_progress",
                artifact_paths=["impl/index.md"],
                code_baseline_hash=__import__(
                    "workflow_loop.verification",
                    fromlist=["compute_code_snapshot_hash"],
                ).compute_code_snapshot_hash(str(tmp_path)),
            ),
        },
    )
    save_state(str(tmp_path), state)
    return topic


def test_impl_discussion_requires_all_confirmed_plans_before_code(tmp_path):
    topic = _prepare_impl_stage(tmp_path)

    ok, detail = ImplStage().discussion_validate(str(tmp_path), __import__(
        "workflow_loop.state",
        fromlist=["load_state"],
    ).load_state(str(tmp_path)))

    assert ok is True, detail
    assert topic in detail or "实施前计划" in detail


def test_impl_code_gate_requires_actual_record_and_code_change(tmp_path):
    topic = _prepare_impl_stage(tmp_path, with_record=True)
    _write(tmp_path / "src" / "app.py", "def run():\n    return 'ok'\n")
    state = __import__("workflow_loop.state", fromlist=["load_state"]).load_state(str(tmp_path))

    ok, detail = ImplStage().code_validate(str(tmp_path))

    assert ok is True, detail
    assert "实施计划和实施记录完整" in detail


def test_impl_code_gate_rejects_plan_difference_section(tmp_path):
    _prepare_impl_stage(tmp_path, with_record=True, with_difference=True)
    _write(tmp_path / "src" / "app.py", "def run():\n    return 'ok'\n")

    ok, detail = ImplStage().code_validate(str(tmp_path))

    assert ok is False
    assert "计划与实际的差异" in detail


def test_test_plan_rejects_missing_acceptance_to_test_item_mapping(tmp_path):
    create_project(str(tmp_path))
    save_state(str(tmp_path), WorkflowState(
        workflow_id="test",
        intent="from_scratch",
        current_stage="test_plan",
        topics=["上传文件"],
    ))
    _write_acceptance_documents(tmp_path, "test", ["上传文件"])
    _write_test_plan(tmp_path, "上传文件")
    plan_path = tmp_path / "qa" / "上传文件_plan.md"
    plan_path.write_text(
        plan_path.read_text(encoding="utf-8").replace(
            "[TC-01 验证上传文件完成](#tc-01)",
            "TC-01",
        ),
        encoding="utf-8",
    )
    _write_qa_index(tmp_path, "test", ["上传文件"])

    ok, detail = TestPlanStage().code_validate(str(tmp_path))

    assert ok is False
    assert "没有带编号、名称和锚点的测试项" in detail


def test_update_code_design_rejects_unchanged_architecture_document(tmp_path):
    stage = UpdateCodeDesignStage()
    architecture_path = "spec/architecture_code_design.md"
    _write(tmp_path / architecture_path, "# 当前代码架构\n")
    _save_stage_baseline(tmp_path, stage, [architecture_path])

    ok, detail = stage.code_validate(str(tmp_path))

    assert ok is False
    assert "与讨论完成时相同" in detail


def test_acceptance_plan_keeps_current_topics_and_accepts_new_unique_topic(tmp_path):
    create_project(str(tmp_path))
    register_topics(str(tmp_path), ["上传文件"])
    save_state(str(tmp_path), WorkflowState(
        workflow_id="test",
        intent="from_scratch",
        topics=["上传文件"],
    ))
    _write_acceptance_documents(tmp_path, "test", ["上传文件", "查看状态"])

    ok, detail = AcceptancePlanStage().code_validate(str(tmp_path))

    assert ok is True
    assert "上传文件" in detail
    assert "查看状态" in detail


def test_topic_execution_requires_results_for_every_topic(tmp_path):
    create_project(str(tmp_path))
    save_state(str(tmp_path), WorkflowState(
        workflow_id="test",
        intent="from_scratch",
        topics=["上传文件", "查看状态"],
    ))
    _write_acceptance_documents(tmp_path, "test", ["上传文件", "查看状态"])
    _write(tmp_path / "impl" / "上传文件.md")
    _write(tmp_path / "impl" / "查看状态.md")
    _write(tmp_path / "qa" / "上传文件_result.md", "- 工作流编号：test\n- 测试结果：通过\n")
    _write(tmp_path / "qa" / "查看状态_result.md", "- 工作流编号：test\n- 测试结果：通过\n")
    _write(tmp_path / "acceptance" / "上传文件_result.md", "- 工作流编号：test\n- 验收结果：通过\n")

    ok, detail = TopicExecutionStage().code_validate(str(tmp_path))
    assert ok is False
    assert "查看状态_result.md" in detail

    _write(tmp_path / "acceptance" / "查看状态_result.md", "- 工作流编号：test\n- 验收结果：通过\n")
    ok, detail = TopicExecutionStage().code_validate(str(tmp_path))
    assert ok is True
    assert "全部主题" in detail


def test_final_regression_requires_current_workflow_and_passed_status(tmp_path):
    save_state(str(tmp_path), WorkflowState(
        workflow_id="2026-07-24-1200-test",
        intent="from_scratch",
        topics=["上传文件"],
    ))
    _write_acceptance_documents(tmp_path, "2026-07-24-1200-test", ["上传文件"])
    stage = RegressionTestStage()

    _write(tmp_path / "qa" / "final_regression_result.md", """# 最终全量回归结果

- 工作流编号：2026-07-24-1200-test
- 回归状态：失败
""")
    ok, detail = stage.code_validate(str(tmp_path))
    assert ok is False
    assert "不能进入整体验收" in detail

    _write(tmp_path / "qa" / "final_regression_result.md", """# 最终全量回归结果

- 工作流编号：2026-07-24-1200-test
- 回归状态：通过
""")
    ok, detail = stage.code_validate(str(tmp_path))
    assert ok is True
    assert "明确通过" in detail


def test_overall_acceptance_requires_all_topic_acceptance_and_passed_regression(tmp_path):
    save_state(str(tmp_path), WorkflowState(
        workflow_id="2026-07-24-1200-test",
        intent="from_scratch",
        topics=["上传文件"],
    ))
    _write_acceptance_documents(tmp_path, "2026-07-24-1200-test", ["上传文件"])
    stage = OverallAcceptanceStage()
    _write(tmp_path / "qa" / "final_regression_result.md", """# 最终全量回归结果

- 工作流编号：2026-07-24-1200-test
- 回归状态：通过
""")

    ok, detail = stage.code_validate(str(tmp_path))
    assert ok is False
    assert "上传文件_result.md" in detail

    _write(tmp_path / "qa" / "上传文件_result.md", """# 主题测试结果

- 工作流编号：2026-07-24-1200-test
- 测试结果：通过
""")
    _write(tmp_path / "acceptance" / "上传文件_result.md", """# 主题验收结果

- 工作流编号：2026-07-24-1200-test
- 验收结果：通过
""")
    ok, detail = stage.code_validate(str(tmp_path))
    assert ok is True
    assert "可以请用户确认整体验收" in detail
