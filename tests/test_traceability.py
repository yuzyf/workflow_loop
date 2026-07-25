from pathlib import Path

from workflow_loop.traceability import update_for_stage, validate_structure
from workflow_loop.verification import compute_acceptance_plan_hash


WORKFLOW_ID = "2026-07-24-1200-test"
TOPICS = ["上传文件", "查看状态"]


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _write_traceability(tmp_path: Path) -> None:
    rows = []
    for topic in TOPICS:
        rows.append(
            f"| [产品设计](./spec/product.md) | [{topic}](./acceptance/{topic}_plan.md) | AC-01：{topic}完成 | 待制定 | 待制定 | 待执行 | 待执行 | 待执行 | 待更新 |"
        )
    _write(
        tmp_path / "traceability.md",
        """# 需求交付追踪表

## 旧工作流

| 需求来源与设计依据 | 验收主题 | 验收条件 | 测试项 | 实施计划与任务 | 实施记录与代码 | 测试结果 | 验收结果 | 更新后的代码设计 |
|---|---|---|---|---|---|---|---|---|
| 旧来源 | [旧主题](./acceptance/旧主题_plan.md) | AC-01 | 旧测试 | 旧计划 | 旧实施 | 旧结果 | 旧验收 | 旧设计 |

## 2026-07-24-1200-test

### 交付链路

| 需求来源与设计依据 | 验收主题 | 验收条件 | 测试项 | 实施计划与任务 | 实施记录与代码 | 测试结果 | 验收结果 | 更新后的代码设计 |
|---|---|---|---|---|---|---|---|---|
""" + "\n".join(rows) + "\n",
    )


def _write_acceptance_plans(tmp_path: Path) -> None:
    for topic in TOPICS:
        _write(
            tmp_path / "acceptance" / f"{topic}_plan.md",
            f"# {topic}\n",
        )


def _write_test_plans(tmp_path: Path) -> None:
    for topic in TOPICS:
        _write(
            tmp_path / "qa" / f"{topic}_plan.md",
            f"""# {topic}测试计划

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
- 下游实施计划：[实施计划](../plan/index.md)
- 下游测试结果：[测试结果](./{topic}_result.md)
""",
        )


def test_traceability_updates_only_current_workflow_and_is_idempotent(tmp_path):
    _write_traceability(tmp_path)
    _write_acceptance_plans(tmp_path)
    _write_test_plans(tmp_path)

    ok, detail = validate_structure(str(tmp_path), WORKFLOW_ID, TOPICS, require_initial_statuses=True)
    assert ok is True, detail

    update_for_stage(str(tmp_path), WORKFLOW_ID, TOPICS, "test_plan")
    first = (tmp_path / "traceability.md").read_text(encoding="utf-8")
    update_for_stage(str(tmp_path), WORKFLOW_ID, TOPICS, "test_plan")
    second = (tmp_path / "traceability.md").read_text(encoding="utf-8")

    assert first == second
    assert "[测试计划](./qa/上传文件_plan.md)" in second
    assert "[测试计划](./qa/查看状态_plan.md)" in second
    assert "[TC-01 验证上传文件完成](./qa/上传文件_plan.md#tc-01)" in second
    assert "| 旧来源 | [旧主题]" in second


def test_traceability_updates_each_downstream_column(tmp_path):
    _write_traceability(tmp_path)
    _write_acceptance_plans(tmp_path)
    _write_test_plans(tmp_path)
    _write(tmp_path / "impl" / "upload.md", "# 实施记录\n")
    _write(tmp_path / "plan" / "index.md", "# 实施计划索引\n")
    _write(tmp_path / "qa" / "上传文件_result.md", "# 测试结果\n")
    _write(tmp_path / "qa" / "查看状态_result.md", "# 测试结果\n")
    _write(tmp_path / "acceptance" / "上传文件_result.md", "# 验收结果\n")
    _write(tmp_path / "acceptance" / "查看状态_result.md", "# 验收结果\n")
    _write(tmp_path / "qa" / "final_regression_result.md", "# 回归\n")
    _write(tmp_path / "spec" / "architecture_code_design.md", "# 架构\n")

    for stage in ["test_plan", "plan", "topic_execution", "regression_test", "overall_acceptance", "update_code_design"]:
        update_for_stage(str(tmp_path), WORKFLOW_ID, TOPICS, stage)

    content = (tmp_path / "traceability.md").read_text(encoding="utf-8")
    assert "[实施计划索引](./plan/index.md)" in content
    assert "[upload.md](./impl/upload.md)" in content
    assert "[测试结果](./qa/上传文件_result.md)" in content
    assert "[主题验收结果](./acceptance/查看状态_result.md)" in content
    assert "[最终全量回归](./qa/final_regression_result.md)" in content
    assert "整体验收：用户已确认" in content
    assert "[最终代码设计](./spec/architecture_code_design.md)" in content


def test_traceability_updates_do_not_change_acceptance_plan_hash(tmp_path):
    _write_traceability(tmp_path)
    _write_acceptance_plans(tmp_path)
    before = compute_acceptance_plan_hash(str(tmp_path), TOPICS)

    _write_test_plans(tmp_path)
    update_for_stage(str(tmp_path), WORKFLOW_ID, TOPICS, "test_plan")

    assert compute_acceptance_plan_hash(str(tmp_path), TOPICS) == before
