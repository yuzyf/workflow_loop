from workflow_loop.project import create_project, register_topics
from workflow_loop.state import StageState, WorkflowState, save_state
from workflow_loop.stages.stages import (
    AcceptancePlanStage,
    ProjectDesignInitStage,
    ReproduceStage,
    ReviseCodeDesignStage,
    SpecStage,
    SpikeStage,
    TestPlanStage,
    TopicExecutionStage,
)
from workflow_loop.verification import compute_file_hashes


def _write(path, content="ready"):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


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
    assert "已复现并确认根因" in detail


def test_reproduce_stage_rejects_arbitrary_markdown(tmp_path):
    stage = ReproduceStage()
    _save_stage_baseline(tmp_path, stage, ["bug/index.md"])
    _write(tmp_path / "bug" / "index.md", "# index")
    _write(tmp_path / "bug" / "anything.md", "anything")

    ok, detail = stage.code_validate(str(tmp_path))

    assert ok is False
    assert "文件名不符合" in detail


def test_project_design_init_rejects_legacy_chinese_feature_filename(tmp_path):
    _write(tmp_path / "spec" / "product.md")
    _write(tmp_path / "spec" / "功能已有产品.md")
    _write(tmp_path / "spec" / "architecture_code_design.md")

    ok, detail = ProjectDesignInitStage().code_validate(str(tmp_path))

    assert ok is False
    assert "spec/feature_*.md" in detail


def test_project_design_init_loads_specialized_and_shared_documents():
    stage = ProjectDesignInitStage()

    assert stage.prompt_doc_path() == "Template_Repository/code_design/project_design_init.md"
    assert stage.standard_doc_path() == "Standardized_Repository/code_design/project_design_init.md"
    assert stage.additional_doc_paths() == [
        ("Template_Repository/spec/spec.md", "Standardized_Repository/spec/spec.md"),
        ("Template_Repository/code_design/code_design.md", "Standardized_Repository/code_design/code_design.md"),
    ]
    assert "必须查看代码和测试" in stage.instruction()


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
    _write(tmp_path / "acceptance" / "上传文件_plan.md")

    ok, detail = AcceptancePlanStage().code_validate(str(tmp_path))
    assert ok is True
    assert "上传文件" in detail

    save_state(str(tmp_path), WorkflowState(
        workflow_id="test",
        intent="from_scratch",
        topics=["上传文件", "查看状态"],
    ))
    _write(tmp_path / "qa" / "上传文件_plan.md")

    ok, detail = TestPlanStage().code_validate(str(tmp_path))
    assert ok is False
    assert "查看状态_plan.md" in detail


def test_acceptance_plan_keeps_current_topics_and_accepts_new_unique_topic(tmp_path):
    create_project(str(tmp_path))
    register_topics(str(tmp_path), ["上传文件"])
    save_state(str(tmp_path), WorkflowState(
        workflow_id="test",
        intent="from_scratch",
        topics=["上传文件"],
    ))
    _write(tmp_path / "acceptance" / "上传文件_plan.md")
    _write(tmp_path / "acceptance" / "查看状态_plan.md")

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
    _write(tmp_path / "impl" / "upload_task.md")
    _write(tmp_path / "qa" / "上传文件_result.md")
    _write(tmp_path / "qa" / "查看状态_result.md")
    _write(tmp_path / "acceptance" / "上传文件_result.md")

    ok, detail = TopicExecutionStage().code_validate(str(tmp_path))
    assert ok is False
    assert "查看状态_result.md" in detail

    _write(tmp_path / "acceptance" / "查看状态_result.md")
    ok, detail = TopicExecutionStage().code_validate(str(tmp_path))
    assert ok is True
    assert "全部主题" in detail
