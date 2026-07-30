from pathlib import Path

from workflow_loop.artifact_validation import validate_final_code_design_document
from workflow_loop.stages.stages import UpdateCodeDesignStage
from workflow_loop.state import StageState, WorkflowState, save_state
from workflow_loop.verification import compute_file_hashes


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _write_complete_final_architecture(tmp_path: Path, workflow_id: str = "test") -> None:
    _write(tmp_path / "src" / "app.py", "def upload():\n    return 'ok'\n")
    _write(tmp_path / "tests" / "test_app.py", "def test_upload():\n    assert True\n")
    _write(tmp_path / "spec" / "product.md", "# 产品\n")
    _write(
        tmp_path / "spec" / "feature_upload.md",
        "# 【功能】上传文件\n",
    )
    _write(
        tmp_path / "spec" / "architecture_code_design.md",
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

- 产品依据：[功能文档](./feature_upload.md)
- 代码位置：`src/app.py` 中的 `upload()`，负责接收文件并写入结果。
- 验证位置：`tests/test_app.py`。

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
- 核对依据：[功能文档](./feature_upload.md)、[测试](../tests/test_app.py)
""",
    )


def test_final_architecture_requires_feature_to_code_mapping(tmp_path):
    _write_complete_final_architecture(tmp_path)

    ok, detail = validate_final_code_design_document(str(tmp_path), "test")

    assert ok is True, detail
    assert "真实代码映射" in detail


def test_final_architecture_rejects_missing_sync_conclusion(tmp_path):
    _write_complete_final_architecture(tmp_path)
    architecture = tmp_path / "spec" / "architecture_code_design.md"
    architecture.write_text(
        architecture.read_text(encoding="utf-8").replace("## 9. 最终同步结论", "## 9. 未完成"),
        encoding="utf-8",
    )

    ok, detail = validate_final_code_design_document(str(tmp_path), "test")

    assert ok is False
    assert "9. 最终同步结论" in detail


def test_update_code_design_rejects_product_document_change(tmp_path):
    stage = UpdateCodeDesignStage()
    _write(tmp_path / "spec" / "product.md", "old product")
    _write(tmp_path / "spec" / "feature_upload.md", "old feature")
    _write(tmp_path / "spec" / "architecture_code_design.md", "old architecture")
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
    _write(tmp_path / "spec" / "product.md", "new product")
    _write(tmp_path / "spec" / "architecture_code_design.md", "new architecture")

    ok, detail = stage.code_validate(str(tmp_path))

    assert ok is False
    assert "必须返回 spec" in detail
