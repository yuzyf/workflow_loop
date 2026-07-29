from pathlib import Path

from workflow_loop.traceability import (
    reset_after_upstream_invalidation,
    reset_topic_test_results,
    update_for_stage,
    validate_structure,
)
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

| 验收条件链接 | 测试项 | 前置测试项 | 测试方式 | 验证方向 | 预期观察结果 | 证据要求 |
|---|---|---|---|---|---|---|
| [AC-01：完成条件](../acceptance/{topic}_plan.md#ac-01) | <a id="tc-01"></a>[TC-01 验证{topic}完成](#tc-01) | 无 | 自动化测试 | 检查{topic} | 观察到{topic}完成 | 保留执行证据 |

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


def test_traceability_updates_only_current_workflow_and_is_idempotent(tmp_path):
    """Workflow-Test
    主题：需求交付各阶段通过追踪表双向关联
    测试项：TC-03 保留历史工作流并保持更新幂等
    验收条件：AC-03 不同工作流的追踪记录互不覆盖
    测试方式：自动化测试
    测试层级：模块测试
    测试目标：重复更新当前工作流时不覆盖旧工作流，也不产生重复内容
    测试入口：tests/test_traceability.py::test_traceability_updates_only_current_workflow_and_is_idempotent
    代码入口：src/workflow_loop/traceability.py 的 update_for_stage()
    """
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
    """Workflow-Test
    主题：需求交付各阶段通过追踪表双向关联
    测试项：TC-01 逐条更新验收条件追踪关系
    验收条件：AC-01 每条验收条件都有完整的后续追踪位置
    测试方式：自动化测试
    测试层级：模块测试
    测试目标：每个交付阶段只更新追踪表中自己负责的列，并保留具体文档入口
    测试入口：tests/test_traceability.py::test_traceability_updates_each_downstream_column
    代码入口：src/workflow_loop/traceability.py 的 update_for_stage()
    """
    _write_traceability(tmp_path)
    _write_acceptance_plans(tmp_path)
    _write_test_plans(tmp_path)
    _write(tmp_path / "impl" / "上传文件.md", "# 实施记录\n")
    _write(tmp_path / "impl" / "查看状态.md", "# 实施记录\n")
    _write(tmp_path / "impl" / "index.md", "# 实施索引\n")
    _write(tmp_path / "qa" / "上传文件_result.md", "# 测试结果\n")
    _write(tmp_path / "qa" / "查看状态_result.md", "# 测试结果\n")
    _write(tmp_path / "acceptance" / "上传文件_result.md", "# 验收结果\n")
    _write(tmp_path / "acceptance" / "查看状态_result.md", "# 验收结果\n")
    _write(tmp_path / "spec" / "architecture_code_design.md", "# 架构\n")

    for stage in ["test_plan", "impl", "test_execution", "topic_acceptance", "regression_test", "overall_acceptance", "update_code_design"]:
        update_for_stage(str(tmp_path), WORKFLOW_ID, TOPICS, stage)

    content = (tmp_path / "traceability.md").read_text(encoding="utf-8")
    assert "./impl/上传文件.md#2-实施前计划" in content
    assert "./impl/查看状态.md#3-实施后记录" in content
    assert "[测试结果](./qa/上传文件_result.md)" in content
    assert "[主题验收结果](./acceptance/查看状态_result.md)" in content
    assert "最终全量回归：通过" in content
    assert "整体验收：用户已确认" in content
    assert "[最终代码设计](./spec/architecture_code_design.md)" in content


def test_traceability_writes_only_each_acceptance_criterion_test_items(tmp_path):
    """Workflow-Test
    主题：需求交付各阶段通过追踪表双向关联
    测试项：TC-01 逐条更新验收条件追踪关系
    验收条件：AC-01 每条验收条件都有完整的后续追踪位置
    测试方式：自动化测试
    测试层级：模块测试
    测试目标：每条追踪行只包含当前 AC 对应的 TC，不复制同主题的其他测试项
    测试入口：tests/test_traceability.py::test_traceability_writes_only_each_acceptance_criterion_test_items
    代码入口：src/workflow_loop/traceability.py 的 _test_plan_links() 和 update_for_stage()
    """
    topic = "上传文件"
    _write(
        tmp_path / "traceability.md",
        f"""# 需求交付追踪表

## {WORKFLOW_ID}

### 交付链路

| 需求来源与设计依据 | 验收主题 | 验收条件 | 测试项 | 实施计划与任务 | 实施记录与代码 | 测试结果 | 验收结果 | 更新后的代码设计 |
|---|---|---|---|---|---|---|---|---|
| [产品设计](./spec/product.md) | [{topic}](./acceptance/{topic}_plan.md) | AC-01：上传成功 | 待制定 | 待制定 | 待执行 | 待执行 | 待执行 | 待更新 |
| [产品设计](./spec/product.md) | [{topic}](./acceptance/{topic}_plan.md) | AC-02：上传失败有提示 | 待制定 | 待制定 | 待执行 | 待执行 | 待执行 | 待更新 |
""",
    )
    _write(
        tmp_path / "qa" / f"{topic}_plan.md",
        f"""# {topic}测试计划

## 1. 验收条件覆盖

| 验收条件链接 | 测试项 | 前置测试项 | 测试方式 | 验证方向 | 预期观察结果 | 证据要求 |
|---|---|---|---|---|---|---|
| [AC-01：上传成功](../acceptance/{topic}_plan.md#ac-01) | <a id="tc-01"></a>[TC-01 验证上传成功](#tc-01) | 无 | 自动化测试 | 检查成功结果 | 文件已保存 | 保留结果 |
| [AC-02：上传失败有提示](../acceptance/{topic}_plan.md#ac-02) | <a id="tc-02"></a>[TC-02 验证失败提示](#tc-02) | TC-01 | 自动化测试 | 检查失败结果 | 显示原因 | 保留结果 |
""",
    )

    update_for_stage(str(tmp_path), WORKFLOW_ID, [topic], "test_plan")

    rows = [
        line
        for line in (tmp_path / "traceability.md").read_text(encoding="utf-8").splitlines()
        if f"acceptance/{topic}_plan.md" in line
    ]
    assert "TC-01 验证上传成功" in rows[0]
    assert "TC-02 验证失败提示" not in rows[0]
    assert "TC-02 验证失败提示" in rows[1]
    assert "TC-01 验证上传成功" not in rows[1]


def test_traceability_marks_manual_acceptance_per_criterion_in_mixed_topic(tmp_path):
    topic = "上传文件"
    _write(
        tmp_path / "traceability.md",
        f"""# 需求交付追踪表

## {WORKFLOW_ID}

### 交付链路

| 需求来源与设计依据 | 验收主题 | 验收条件 | 测试项 | 实施计划与任务 | 实施记录与代码 | 测试结果 | 验收结果 | 更新后的代码设计 |
|---|---|---|---|---|---|---|---|---|
| [产品设计](./spec/product.md) | [{topic}](./acceptance/{topic}_plan.md) | AC-01：上传成功 | 待制定 | 待制定 | 待执行 | 待执行 | 待执行 | 待更新 |
| [产品设计](./spec/product.md) | [{topic}](./acceptance/{topic}_plan.md) | AC-02：界面文字易懂 | 待制定 | 待制定 | 待执行 | 待执行 | 待执行 | 待更新 |
""",
    )
    _write(
        tmp_path / "qa" / f"{topic}_plan.md",
        f"""# {topic}测试计划

## 1. 验收条件覆盖

| 验收条件链接 | 测试项 | 前置测试项 | 测试方式 | 验证方向 | 预期观察结果 | 证据要求 |
|---|---|---|---|---|---|---|
| [AC-01：上传成功](../acceptance/{topic}_plan.md#ac-01) | <a id="tc-01"></a>[TC-01 验证上传成功](#tc-01) | 无 | 自动化测试 | 检查成功结果 | 文件已保存 | 保留结果 |
| [AC-02：界面文字易懂](../acceptance/{topic}_plan.md#ac-02) | <a id="tc-02"></a>[TC-02 用户判断界面文字](#tc-02) | TC-01 | 人工验收 | 用户阅读文字 | 用户可以理解 | 保留确认 |
""",
    )

    update_for_stage(str(tmp_path), WORKFLOW_ID, [topic], "test_plan")
    update_for_stage(str(tmp_path), WORKFLOW_ID, [topic], "test_execution")

    rows = [
        line
        for line in (tmp_path / "traceability.md").read_text(encoding="utf-8").splitlines()
        if f"acceptance/{topic}_plan.md" in line
    ]
    assert "[测试结果](./qa/上传文件_result.md)" in rows[0]
    assert "无自动化测试项，转主题验收" not in rows[0]
    assert "无自动化测试项，转主题验收" in rows[1]
    assert "[测试结果](./qa/上传文件_result.md)" not in rows[1]


def test_traceability_updates_do_not_change_acceptance_plan_hash(tmp_path):
    _write_traceability(tmp_path)
    _write_acceptance_plans(tmp_path)
    before = compute_acceptance_plan_hash(str(tmp_path), TOPICS)

    _write_test_plans(tmp_path)
    update_for_stage(str(tmp_path), WORKFLOW_ID, TOPICS, "test_plan")

    assert compute_acceptance_plan_hash(str(tmp_path), TOPICS) == before


def test_reset_topic_test_results_only_resets_selected_topics(tmp_path):
    _write_traceability(tmp_path)
    _write_acceptance_plans(tmp_path)
    _write_test_plans(tmp_path)
    update_for_stage(str(tmp_path), WORKFLOW_ID, TOPICS, "test_plan")
    update_for_stage(str(tmp_path), WORKFLOW_ID, TOPICS, "test_execution")

    reset_topic_test_results(str(tmp_path), WORKFLOW_ID, ["上传文件"])

    rows = [
        line
        for line in (tmp_path / "traceability.md").read_text(encoding="utf-8").splitlines()
        if "acceptance/" in line and "_plan.md" in line
    ]
    upload_row = next(line for line in rows if "acceptance/上传文件_plan.md" in line)
    status_row = next(line for line in rows if "acceptance/查看状态_plan.md" in line)
    assert "| 待执行 | 待执行 | 待更新 |" in upload_row
    assert "[测试结果](./qa/查看状态_result.md)" in status_row


def test_reset_after_upstream_invalidation_clears_only_current_workflow_downstream_rows(tmp_path):
    _write_traceability(tmp_path)
    _write_acceptance_plans(tmp_path)
    _write_test_plans(tmp_path)

    update_for_stage(str(tmp_path), WORKFLOW_ID, TOPICS, "test_plan")
    result = reset_after_upstream_invalidation(
        str(tmp_path),
        WORKFLOW_ID,
        TOPICS,
        "acceptance_plan",
    )

    assert "重置" in result
    ok, detail = validate_structure(
        str(tmp_path),
        WORKFLOW_ID,
        TOPICS,
        require_initial_statuses=True,
    )
    assert ok is True, detail
    content = (tmp_path / "traceability.md").read_text(encoding="utf-8")
    assert "| 旧来源 | [旧主题]" in content
    assert "[测试计划](./qa/上传文件_plan.md)" not in content
