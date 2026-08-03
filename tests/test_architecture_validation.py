from pathlib import Path

from workflow_loop import acceptance_records as acceptance_records_mod
from workflow_loop.artifact_validation import validate_final_code_design_document
from workflow_loop.stages.stages import UpdateCodeDesignStage
from workflow_loop.state import (
    AcceptanceCriterionRecord,
    RegressionTestState,
    StageState,
    WorkflowState,
    save_state,
)
from workflow_loop.verification import compute_file_hashes


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _write_complete_final_architecture(tmp_path: Path, workflow_id: str = "test") -> None:
    _write(tmp_path / "src" / "app.py", "def upload():\n    return 'ok'\n")
    _write(tmp_path / "tests" / "test_app.py", "def test_upload():\n    assert True\n")
    _write(
        tmp_path / "spec" / "产品总说明.md",
        "# 产品\n\n[上传文件](./功能_上传文件.md)\n",
    )
    _write(
        tmp_path / "spec" / "功能_上传文件.md",
        "# 【功能】上传文件\n",
    )
    acceptance_record = AcceptanceCriterionRecord(
        topic="上传文件",
        criterion_id="AC-01",
        method="人工验收",
        result="passed",
        actual_result="用户确认上传结果符合要求",
        user_answer="通过",
        evidence="用户确认记录",
        confirmed_at="2026-07-30T00:00:00+00:00",
    )
    acceptance_record.record_id = acceptance_records_mod.compute_record_id(acceptance_record)
    save_state(
        str(tmp_path),
        WorkflowState(
            workflow_id=workflow_id,
            intent="from_scratch",
            topics=["上传文件"],
            stages={
                "topic_acceptance": StageState(
                    acceptance_records={"上传文件": {"AC-01": acceptance_record}}
                )
            },
            regression_test=RegressionTestState(status="passed", record_id="REG-test-1"),
        ),
    )
    _write(
        tmp_path / "spec" / "代码架构设计.md",
        f"""# 产品 — 代码架构设计

## 1. 文档说明

已按真实代码更新。

## 2. 产品概览

上传文件。

## 3. 产品设计如何决定代码架构

产品要求映射到代码职责。

## 4. 代码架构分层

分层和依赖方向。

## 5. 架构关键节点

关键节点。

## 6. 各产品功能的代码设计

### 6.1 【功能】上传文件

- 产品依据：[功能文档](./功能_上传文件.md)

| 图中步骤 | 触发和输入 | 代码位置 | 具体处理逻辑 | 产生的状态、数据或输出 | 失败时的结果 | 验证位置 |
|---|---|---|---|---|---|---|
| 上传文件 | 收到上传请求 | `src/app.py::upload` | `upload`（上传函数）返回保存结果 | 返回 `ok` | 抛出原始错误 | `tests/test_app.py::test_upload` |

## 7. 多个功能共同使用的代码

暂无。

## 8. 产品设计与代码实现的差异

暂无。

## 9. 最终同步结论

- 工作流编号：{workflow_id}
- 本次同步类型：架构未变化
- 产品设计核对：一致
- 功能文档核对：一致
- 代码实现核对：一致
- 功能到代码映射：完整
- 未处理差异：暂无
- 核对依据：[功能文档](./功能_上传文件.md)、[测试](../tests/test_app.py)、REG-test-1
""",
    )


def test_final_architecture_requires_feature_to_code_mapping(tmp_path):
    """Workflow-Test
    主题：产品和代码设计及缺陷穿刺结论保持真实一致
    测试项：TC-03 代码设计区分计划实现和证据
    验收条件：AC-03 代码设计区分计划和事实
    测试方式：自动化测试 + 人工验收
    测试层级：模块测试
    测试目标：最终代码设计中的每个功能映射到真实产品依据、代码位置和验证位置
    测试入口：tests/test_architecture_validation.py::test_final_architecture_requires_feature_to_code_mapping
    代码入口：workflow_loop.artifact_validation.validate_final_code_design_document
    """
    _write_complete_final_architecture(tmp_path)

    ok, detail = validate_final_code_design_document(str(tmp_path), "test")

    assert ok is True, detail
    assert "真实代码映射" in detail


def test_final_architecture_rejects_missing_sync_conclusion(tmp_path):
    """Workflow-Test
    主题：主题验收、全量回归和最终同步完成后正式收工
    测试项：TC-06 最终代码设计映射真实实现
    验收条件：AC-06 最终代码设计反映真实交付
    测试方式：自动化测试 + 人工验收
    测试层级：模块测试
    测试目标：缺少最终同步结论的代码设计不能作为真实交付地图
    测试入口：tests/test_architecture_validation.py::test_final_architecture_rejects_missing_sync_conclusion
    代码入口：workflow_loop.artifact_validation.validate_final_code_design_document
    """
    _write_complete_final_architecture(tmp_path)
    architecture = tmp_path / "spec" / "代码架构设计.md"
    architecture.write_text(
        architecture.read_text(encoding="utf-8").replace("## 9. 最终同步结论", "## 9. 未完成"),
        encoding="utf-8",
    )

    ok, detail = validate_final_code_design_document(str(tmp_path), "test")

    assert ok is False
    assert "9. 最终同步结论" in detail


def test_update_code_design_rejects_product_document_change(tmp_path):
    """Workflow-Test
    主题：主题验收、全量回归和最终同步完成后正式收工
    测试项：TC-06 最终代码设计映射真实实现
    验收条件：AC-06 最终代码设计反映真实交付
    测试方式：自动化测试 + 人工验收
    测试层级：模块测试
    测试目标：最终同步发现产品文档变化时返回产品处理流程而不是自行改写结论
    测试入口：tests/test_architecture_validation.py::test_update_code_design_rejects_product_document_change
    代码入口：workflow_loop.stages.stages.UpdateCodeDesignStage.code_validate
    """
    stage = UpdateCodeDesignStage()
    _write(tmp_path / "spec" / "产品总说明.md", "old product")
    _write(tmp_path / "spec" / "功能_上传文件.md", "old feature")
    _write(tmp_path / "spec" / "代码架构设计.md", "old architecture")
    tracked_paths = stage.change_tracked_paths(str(tmp_path))
    save_state(
        str(tmp_path),
        WorkflowState(
            workflow_id="test",
            intent="from_scratch",
            current_stage="update_code_design",
            stage_path=["update_code_design"],
            stages={
                "update_code_design": StageState(
                    status="in_progress",
                    artifact_paths=stage.artifact_paths(),
                    artifact_baseline_captured_at="2026-07-30T00:00:00+00:00",
                    artifact_baseline_hashes=compute_file_hashes(str(tmp_path), tracked_paths),
                )
            },
        ),
    )
    _write(tmp_path / "spec" / "产品总说明.md", "new product")
    _write(tmp_path / "spec" / "代码架构设计.md", "new architecture")

    ok, detail = stage.code_validate(str(tmp_path))

    assert ok is False
    assert "必须返回 spec" in detail
