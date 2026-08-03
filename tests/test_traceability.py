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
            f"| [产品设计](./spec/产品总说明.md) | [{topic}](./acceptance/{topic}_验收计划.md) | AC-01：{topic}完成 | 待制定 | 待制定 | 待执行 | 待执行 | 待执行 | 待更新 |"
        )
    _write(
        tmp_path / "需求交付追踪表.md",
        """# 需求交付追踪表

## 旧工作流

| 需求来源与设计依据 | 验收主题 | 验收条件 | 测试项 | 实施计划与任务 | 实施记录与代码 | 测试结果 | 验收结果 | 更新后的代码设计 |
|---|---|---|---|---|---|---|---|---|
| 旧来源 | [旧主题](./acceptance/旧主题_验收计划.md) | AC-01 | 旧测试 | 旧计划 | 旧实施 | 旧结果 | 旧验收 | 旧设计 |

## 2026-07-24-1200-test

### 交付链路

| 需求来源与设计依据 | 验收主题 | 验收条件 | 测试项 | 实施计划与任务 | 实施记录与代码 | 测试结果 | 验收结果 | 更新后的代码设计 |
|---|---|---|---|---|---|---|---|---|
""" + "\n".join(rows) + "\n",
    )


def _write_acceptance_plans(tmp_path: Path) -> None:
    for topic in TOPICS:
        _write(
            tmp_path / "acceptance" / f"{topic}_验收计划.md",
            f"# {topic}\n",
        )


def _write_test_plans(tmp_path: Path) -> None:
    for topic in TOPICS:
        _write(
            tmp_path / "qa" / f"{topic}_测试计划.md",
            f"""# {topic}测试计划

## 1. 验收条件覆盖

| 验收条件链接 | 测试项 | 前置测试项 | 测试方式 | 验证方向 | 预期观察结果 | 证据要求 |
|---|---|---|---|---|---|---|
| [AC-01：完成条件](../acceptance/{topic}_验收计划.md#ac-01) | <a id="tc-01"></a>[TC-01 验证{topic}完成](#tc-01) | 无 | 自动化测试 | 检查{topic} | 观察到{topic}完成 | 保留执行证据 |

## 2. 针对性回归范围

暂无

## 3. 测试条件要求

暂无

## 4. 未决测试条件

暂无

## 5. 上下游文档

- 上游验收计划：[验收计划](../acceptance/{topic}_验收计划.md)
- 下游实施计划：[实施计划](../impl/索引.md)
- 下游测试结果：[测试结果](./{topic}_测试结果.md)
""",
        )


def test_traceability_updates_only_current_workflow_and_is_idempotent(tmp_path):
    """Workflow-Test
    主题：验收测试和实施计划按同一主题完整追踪
    测试项：TC-03 追踪表逐条覆盖且保留历史
    验收条件：AC-03 交付关系逐条可追踪
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
    first = (tmp_path / "需求交付追踪表.md").read_text(encoding="utf-8")
    update_for_stage(str(tmp_path), WORKFLOW_ID, TOPICS, "test_plan")
    second = (tmp_path / "需求交付追踪表.md").read_text(encoding="utf-8")

    assert first == second
    assert "[测试计划](./qa/上传文件_测试计划.md)" in second
    assert "[测试计划](./qa/查看状态_测试计划.md)" in second
    assert "[TC-01 验证上传文件完成](./qa/上传文件_测试计划.md#tc-01)" in second
    assert "| 旧来源 | [旧主题]" in second


def test_traceability_updates_each_downstream_column(tmp_path):
    """Workflow-Test
    主题：验收测试和实施计划按同一主题完整追踪
    测试项：TC-03 追踪表逐条覆盖且保留历史
    验收条件：AC-03 交付关系逐条可追踪
    测试方式：自动化测试
    测试层级：模块测试
    测试目标：每个交付阶段只更新追踪表中自己负责的列，并保留具体文档入口
    测试入口：tests/test_traceability.py::test_traceability_updates_each_downstream_column
    代码入口：src/workflow_loop/traceability.py 的 update_for_stage()
    """
    _write_traceability(tmp_path)
    _write_acceptance_plans(tmp_path)
    _write_test_plans(tmp_path)
    _write(tmp_path / "impl" / "上传文件_实施记录.md", "# 实施记录\n")
    _write(tmp_path / "impl" / "查看状态_实施记录.md", "# 实施记录\n")
    _write(tmp_path / "impl" / "索引.md", "# 实施索引\n")
    _write(tmp_path / "qa" / "上传文件_测试结果.md", "# 测试结果\n")
    _write(tmp_path / "qa" / "查看状态_测试结果.md", "# 测试结果\n")
    _write(tmp_path / "acceptance" / "上传文件_验收结果.md", "# 验收结果\n")
    _write(tmp_path / "acceptance" / "查看状态_验收结果.md", "# 验收结果\n")
    _write(tmp_path / "spec" / "代码架构设计.md", "# 架构\n")

    for stage in ["test_plan", "impl", "test_execution", "topic_acceptance", "regression_test", "overall_acceptance", "update_code_design"]:
        update_for_stage(str(tmp_path), WORKFLOW_ID, TOPICS, stage)

    content = (tmp_path / "需求交付追踪表.md").read_text(encoding="utf-8")
    assert "./impl/上传文件_实施记录.md#2-实施前计划" in content
    assert "./impl/查看状态_实施记录.md#3-实施后记录" in content
    assert "[测试结果](./qa/上传文件_测试结果.md)" in content
    assert "[主题验收结果](./acceptance/查看状态_验收结果.md)" in content
    assert "最终全量回归：通过" in content
    assert "整体验收：用户已确认" in content
    assert "[最终代码设计](./spec/代码架构设计.md)" in content


def test_traceability_writes_only_each_acceptance_criterion_test_items(tmp_path):
    """Workflow-Test
    主题：验收测试和实施计划按同一主题完整追踪
    测试项：TC-03 追踪表逐条覆盖且保留历史
    验收条件：AC-03 交付关系逐条可追踪
    测试方式：自动化测试
    测试层级：模块测试
    测试目标：每条追踪行只包含当前 AC 对应的 TC，不复制同主题的其他测试项
    测试入口：tests/test_traceability.py::test_traceability_writes_only_each_acceptance_criterion_test_items
    代码入口：src/workflow_loop/traceability.py 的 _test_plan_links() 和 update_for_stage()
    """
    topic = "上传文件"
    _write(
        tmp_path / "需求交付追踪表.md",
        f"""# 需求交付追踪表

## {WORKFLOW_ID}

### 交付链路

| 需求来源与设计依据 | 验收主题 | 验收条件 | 测试项 | 实施计划与任务 | 实施记录与代码 | 测试结果 | 验收结果 | 更新后的代码设计 |
|---|---|---|---|---|---|---|---|---|
| [产品设计](./spec/产品总说明.md) | [{topic}](./acceptance/{topic}_验收计划.md) | AC-01：上传成功 | 待制定 | 待制定 | 待执行 | 待执行 | 待执行 | 待更新 |
| [产品设计](./spec/产品总说明.md) | [{topic}](./acceptance/{topic}_验收计划.md) | AC-02：上传失败有提示 | 待制定 | 待制定 | 待执行 | 待执行 | 待执行 | 待更新 |
""",
    )
    _write(
        tmp_path / "qa" / f"{topic}_测试计划.md",
        f"""# {topic}测试计划

## 1. 验收条件覆盖

| 验收条件链接 | 测试项 | 前置测试项 | 测试方式 | 验证方向 | 预期观察结果 | 证据要求 |
|---|---|---|---|---|---|---|
| [AC-01：上传成功](../acceptance/{topic}_验收计划.md#ac-01) | <a id="tc-01"></a>[TC-01 验证上传成功](#tc-01) | 无 | 自动化测试 | 检查成功结果 | 文件已保存 | 保留结果 |
| [AC-02：上传失败有提示](../acceptance/{topic}_验收计划.md#ac-02) | <a id="tc-02"></a>[TC-02 验证失败提示](#tc-02) | TC-01 | 自动化测试 | 检查失败结果 | 显示原因 | 保留结果 |
""",
    )

    update_for_stage(str(tmp_path), WORKFLOW_ID, [topic], "test_plan")

    rows = [
        line
        for line in (tmp_path / "需求交付追踪表.md").read_text(encoding="utf-8").splitlines()
        if f"acceptance/{topic}_验收计划.md" in line
    ]
    assert "TC-01 验证上传成功" in rows[0]
    assert "TC-02 验证失败提示" not in rows[0]
    assert "TC-02 验证失败提示" in rows[1]
    assert "TC-01 验证上传成功" not in rows[1]


def test_traceability_marks_manual_acceptance_per_criterion_in_mixed_topic(tmp_path):
    """Workflow-Test
    主题：验收测试和实施计划按同一主题完整追踪
    测试项：TC-03 追踪表逐条覆盖且保留历史
    验收条件：AC-03 交付关系逐条可追踪
    测试方式：自动化测试
    测试层级：集成测试
    测试目标：混合主题逐条件区分自动化结果和人工验收交接
    测试入口：tests/test_traceability.py::test_traceability_marks_manual_acceptance_per_criterion_in_mixed_topic
    代码入口：workflow_loop.traceability.update_for_stage
    """
    topic = "上传文件"
    _write(
        tmp_path / "需求交付追踪表.md",
        f"""# 需求交付追踪表

## {WORKFLOW_ID}

### 交付链路

| 需求来源与设计依据 | 验收主题 | 验收条件 | 测试项 | 实施计划与任务 | 实施记录与代码 | 测试结果 | 验收结果 | 更新后的代码设计 |
|---|---|---|---|---|---|---|---|---|
| [产品设计](./spec/产品总说明.md) | [{topic}](./acceptance/{topic}_验收计划.md) | AC-01：上传成功 | 待制定 | 待制定 | 待执行 | 待执行 | 待执行 | 待更新 |
| [产品设计](./spec/产品总说明.md) | [{topic}](./acceptance/{topic}_验收计划.md) | AC-02：界面文字易懂 | 待制定 | 待制定 | 待执行 | 待执行 | 待执行 | 待更新 |
""",
    )
    _write(
        tmp_path / "qa" / f"{topic}_测试计划.md",
        f"""# {topic}测试计划

## 1. 验收条件覆盖

| 验收条件链接 | 测试项 | 前置测试项 | 测试方式 | 验证方向 | 预期观察结果 | 证据要求 |
|---|---|---|---|---|---|---|
| [AC-01：上传成功](../acceptance/{topic}_验收计划.md#ac-01) | <a id="tc-01"></a>[TC-01 验证上传成功](#tc-01) | 无 | 自动化测试 | 检查成功结果 | 文件已保存 | 保留结果 |
| [AC-02：界面文字易懂](../acceptance/{topic}_验收计划.md#ac-02) | <a id="tc-02"></a>[TC-02 用户判断界面文字](#tc-02) | TC-01 | 人工验收 | 用户阅读文字 | 用户可以理解 | 保留确认 |
""",
    )

    update_for_stage(str(tmp_path), WORKFLOW_ID, [topic], "test_plan")
    update_for_stage(str(tmp_path), WORKFLOW_ID, [topic], "test_execution")

    rows = [
        line
        for line in (tmp_path / "需求交付追踪表.md").read_text(encoding="utf-8").splitlines()
        if f"acceptance/{topic}_验收计划.md" in line
    ]
    assert "[测试结果](./qa/上传文件_测试结果.md)" in rows[0]
    assert "无自动化测试项，转主题验收" not in rows[0]
    assert "无自动化测试项，转主题验收" in rows[1]
    assert "[测试结果](./qa/上传文件_测试结果.md)" not in rows[1]


def test_traceability_updates_do_not_change_acceptance_plan_hash(tmp_path):
    """Workflow-Test
    主题：验收测试和实施计划按同一主题完整追踪
    测试项：TC-03 追踪表逐条覆盖且保留历史
    验收条件：AC-03 交付关系逐条可追踪
    测试方式：自动化测试
    测试层级：集成测试
    测试目标：填写下游追踪列不会反向篡改已确认验收计划哈希
    测试入口：tests/test_traceability.py::test_traceability_updates_do_not_change_acceptance_plan_hash
    代码入口：workflow_loop.traceability.update_for_stage
    """
    _write_traceability(tmp_path)
    _write_acceptance_plans(tmp_path)
    before = compute_acceptance_plan_hash(str(tmp_path), TOPICS)

    _write_test_plans(tmp_path)
    update_for_stage(str(tmp_path), WORKFLOW_ID, TOPICS, "test_plan")

    assert compute_acceptance_plan_hash(str(tmp_path), TOPICS) == before


def test_reset_topic_test_results_only_resets_selected_topics(tmp_path):
    """Workflow-Test
    主题：返回上游或整轮作废后状态与项目内容正确恢复
    测试项：TC-03 只使直接受影响主题结果失效
    验收条件：AC-03 只清除真实受影响的结果
    测试方式：自动化测试
    测试层级：集成测试
    测试目标：按主题重置测试结果时保留其他独立主题的结果链接
    测试入口：tests/test_traceability.py::test_reset_topic_test_results_only_resets_selected_topics
    代码入口：workflow_loop.traceability.reset_topic_test_results
    """
    _write_traceability(tmp_path)
    _write_acceptance_plans(tmp_path)
    _write_test_plans(tmp_path)
    update_for_stage(str(tmp_path), WORKFLOW_ID, TOPICS, "test_plan")
    update_for_stage(str(tmp_path), WORKFLOW_ID, TOPICS, "test_execution")

    reset_topic_test_results(str(tmp_path), WORKFLOW_ID, ["上传文件"])

    rows = [
        line
        for line in (tmp_path / "需求交付追踪表.md").read_text(encoding="utf-8").splitlines()
        if "acceptance/" in line and "_验收计划.md" in line
    ]
    upload_row = next(line for line in rows if "acceptance/上传文件_验收计划.md" in line)
    status_row = next(line for line in rows if "acceptance/查看状态_验收计划.md" in line)
    assert "| 待执行 | 待执行 | 待更新 |" in upload_row
    assert "[测试结果](./qa/查看状态_测试结果.md)" in status_row


def test_reset_after_upstream_invalidation_clears_only_current_workflow_downstream_rows(tmp_path):
    """Workflow-Test
    主题：返回上游或整轮作废后状态与项目内容正确恢复
    测试项：TC-03 只使直接受影响主题结果失效
    验收条件：AC-03 只清除真实受影响的结果
    测试方式：自动化测试
    测试层级：集成测试
    测试目标：上游失效只重置当前轮次和指定主题并保留历史轮次
    测试入口：tests/test_traceability.py::test_reset_after_upstream_invalidation_clears_only_current_workflow_downstream_rows
    代码入口：workflow_loop.traceability.reset_after_upstream_invalidation
    """
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
    content = (tmp_path / "需求交付追踪表.md").read_text(encoding="utf-8")
    assert "| 旧来源 | [旧主题]" in content
    assert "[测试计划](./qa/上传文件_测试计划.md)" not in content
