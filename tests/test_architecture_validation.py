from pathlib import Path

from workflow_loop import acceptance_records as acceptance_records_mod
from workflow_loop.artifact_validation import (
    validate_final_code_design_document,
    validate_project_design_feature_consistency,
)
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
    测试方式：自动化测试
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


def test_final_architecture_reports_all_mapping_and_sync_errors_once(tmp_path):
    """最终设计门禁必须同时指出表格位置错误和同步字段错误。"""
    _write_complete_final_architecture(tmp_path)
    architecture = tmp_path / "spec" / "代码架构设计.md"
    content = architecture.read_text(encoding="utf-8")
    content = content.replace(
        "`src/app.py::upload`",
        "路由对超级账号放行审批人即发起人",
    ).replace(
        "`tests/test_app.py::test_upload`",
        "测试结果符合预期",
    ).replace(
        "- 功能到代码映射：完整",
        "- 功能到代码映射：待确认",
    )
    architecture.write_text(content, encoding="utf-8")

    ok, detail = validate_final_code_design_document(str(tmp_path), "test")

    assert ok is False
    assert "第 1 张表第 1 行“代码位置”列" in detail
    assert "代码位置没有项目内真实代码文件" in detail
    assert "第 1 张表第 1 行“验证位置”列" in detail
    assert "验证位置没有项目内真实文件" in detail
    assert "第 9 章“功能到代码映射”字段" in detail


def test_update_code_design_rejects_product_document_change(tmp_path):
    """Workflow-Test
    主题：主题验收、全量回归和最终同步完成后正式收工
    测试项：TC-06 最终代码设计映射真实实现
    验收条件：AC-06 最终代码设计反映真实交付
    测试方式：自动化测试
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


def test_initial_architecture_requires_one_complete_section_per_confirmed_feature(tmp_path):
    """Workflow-Test
    主题：首次接入已有项目时功能完整且产品文档面向用户
    测试项：TC-03 每个确认功能有唯一完整代码过程
    验收条件：AC-02 四类初始化产物使用完全相同的功能集合
    测试方式：自动化测试
    测试层级：模块测试
    测试目标：架构第 6 章漏功能、重复功能段和缺少处理过程时一次返回具体功能错误
    测试入口：tests/test_architecture_validation.py::test_initial_architecture_requires_one_complete_section_per_confirmed_feature
    代码入口：workflow_loop.artifact_validation.validate_project_design_feature_consistency
    """
    _write(tmp_path / "spec" / "产品总说明.md", "[上传文档](./功能_上传文档.md)\n[搜索文档](./功能_搜索文档.md)\n")
    _write(tmp_path / "spec" / "功能_上传文档.md", "# 【功能】上传文档\n")
    _write(tmp_path / "spec" / "功能_搜索文档.md", "# 【功能】搜索文档\n")
    _write(
        tmp_path / "spec" / "代码架构设计.md",
        """## 6. 各产品功能的代码设计

### 6.1 【功能】上传文档
- 产品依据：[上传文档](./功能_上传文档.md)

### 6.2 【功能】上传文档
- 产品依据：[上传文档](./功能_上传文档.md)
""",
    )
    _write(
        tmp_path / "spec" / "项目设计初始化证据.md",
        """- 初始化范围确认状态：已确认

## 1. 入口清单
| 入口 | 入口类型 | 调查证据 | 功能归属 | 排除理由 | 用户确认 |
|---|---|---|---|---|---|
| 上传页面 | 用户操作入口 | 运行确认 | 上传文档 | 暂无 | 已确认 |
| 搜索框 | 用户操作入口 | 运行确认 | 搜索文档 | 暂无 | 已确认 |

## 2. 功能清单
| 功能名称 | 独立完成的用户事情 | 覆盖入口 | 用户确认 |
|---|---|---|---|
| 上传文档 | 上传并保存文档 | 上传页面 | 已确认 |
| 搜索文档 | 查找已有文档 | 搜索框 | 已确认 |

## 3. 产出文件清单
| 预期正式路径 | 所属功能或全局用途 | 实际状态 |
|---|---|---|
| `spec/产品总说明.md` | 全局 | 已生成 |
| `spec/功能_上传文档.md` | 上传文档 | 已生成 |
| `spec/功能_搜索文档.md` | 搜索文档 | 已生成 |
| `spec/代码架构设计.md` | 全局 | 已生成 |
| `spec/项目设计初始化证据.md` | 全局 | 已生成 |
""",
    )

    ok, detail = validate_project_design_feature_consistency(str(tmp_path))

    assert ok is False
    assert "上传文档" in detail
    assert "重复" in detail or "2" in detail
    assert "搜索文档" in detail
    assert "缺少" in detail
    assert "触发和输入" in detail or "完整过程" in detail
