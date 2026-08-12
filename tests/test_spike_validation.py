from workflow_loop.spike_validation import validate_spike_stage
from workflow_loop.state import SpikeBaselineState, WorkflowState, load_state, save_state
from workflow_loop.verification import compute_code_design_hash, compute_product_design_hash


def _write(path, content):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _detail_document(
    workflow_id="wf-1",
    item_id="SP-001",
    result_status="已确认",
    blocked="否",
    product_impact="无需修改",
    product_location="无",
    code_impact="无需修改",
    code_location="无",
    remaining_risk="无",
    follow_up="无",
    follow_up_check="无",
    unresolved="无",
):
    return f"""# 【穿刺】确认真实接口返回

- 工作流编号：{workflow_id}
- 穿刺项编号：{item_id}

## 1. 真实场景与不确定性

用户执行真实业务操作时，代码需要读取接口返回字段，当前没有实际返回证据。

## 2. 验证结果用于决定什么

结果用于决定接口解析和错误处理怎样设计。

## 3. 已知事实与验证范围

- 当前代码没有保存真实返回。
- 本次只调用真实的只读接口。

## 4. 验证方法

- 使用的方法：调用真实只读接口
- 临时内容位置：无
- 执行步骤：执行真实请求并保存脱敏输出
- 外部影响：只读，不修改外部数据

## 5. 实际执行记录

- 执行时间：2026-07-23T12:00:00+08:00
- 运行环境：macOS，测试接口版本 v1
- 实际命令：curl 调用真实接口，凭据已省略
- 真实输入或样本：真实账号下的只读查询，响应哈希 abc123
- 执行失败：无

## 6. 实际观察结果

接口返回 data.items、error.code 和 error.message，成功与失败响应均已观察。

## 7. 结论

- 结果状态：{result_status}
- 是否阻塞后续：{blocked}
- 已确认内容：确认真实成功和失败返回字段
- 仍未确认内容：{unresolved}

## 8. 对后续工作的影响

- 产品设计影响：{product_impact}
- 产品设计更新位置：{product_location}
- 代码设计影响：{code_impact}
- 代码设计更新位置：{code_location}
- 剩余风险：{remaining_risk}
- 后续处理阶段：{follow_up}
- 后续需要检查什么：{follow_up_check}

## 9. 可复用资产

暂无
"""


def _setup_valid_project(tmp_path, intent="from_scratch"):
    _write(
        tmp_path / "spec" / "产品总说明.md",
        "# Product\n\n[功能](./功能_示例.md)\n",
    )
    _write(tmp_path / "spec" / "功能_示例.md", "# 【功能】Example\n")
    _write(tmp_path / "spec" / "代码架构设计.md", "# Architecture\n")

    product_hash, product_paths = compute_product_design_hash(str(tmp_path))
    state = WorkflowState(
        workflow_id="wf-1",
        intent=intent,
        current_stage="spike",
        started_at="2026-07-23T11:00:00+08:00",
        stage_path=["spike"],
        spike_baseline=SpikeBaselineState(
            captured_at="2026-07-23T11:00:00+08:00",
            product_design_hash=product_hash,
            product_design_paths=product_paths,
            code_design_hash=compute_code_design_hash(str(tmp_path)),
        ),
    )
    save_state(str(tmp_path), state)
    _write(
        tmp_path / "spec" / "穿刺清单.md",
        """# 【穿刺】穿刺清单

- 工作流编号：wf-1

## SP-001 确认真实接口返回

- 真实场景：用户执行真实业务操作
- 要验证的不确定性：接口实际返回哪些字段
- 验证结果用于决定什么：决定接口解析和错误处理
- 结论文档：[确认真实接口返回](./穿刺_真实接口返回.md)
- 穿刺状态：已确认
- 是否阻塞后续：否
- 产品设计影响：无需修改
- 代码设计影响：无需修改
- 后续处理阶段：无
""",
    )
    _write(
        tmp_path / "spec" / "穿刺_真实接口返回.md",
        _detail_document(),
    )
    return state


def test_validate_spike_stage_accepts_complete_current_run(tmp_path):
    """Workflow-Test
    主题：产品和代码设计及缺陷穿刺结论保持真实一致
    测试项：TC-05 穿刺候选执行和跳过符合真实场景
    验收条件：AC-05 穿刺只验证真正未知的技术事实
    测试方式：自动化测试 + 人工验收
    测试层级：模块测试
    测试目标：当前工作流的真实执行记录、观察结果和非阻塞结论完整时允许推进
    测试入口：tests/test_spike_validation.py::test_validate_spike_stage_accepts_complete_current_run
    代码入口：workflow_loop.spike_validation.validate_spike_stage
    """
    _setup_valid_project(tmp_path)

    ok, detail = validate_spike_stage(str(tmp_path))

    assert ok is True
    assert "1 份结论文档" in detail


def test_validate_spike_stage_rejects_old_workflow_document(tmp_path):
    _setup_valid_project(tmp_path)
    index_path = tmp_path / "spec" / "穿刺清单.md"
    index_path.write_text(index_path.read_text().replace("工作流编号：wf-1", "工作流编号：old-wf"), encoding="utf-8")

    ok, detail = validate_spike_stage(str(tmp_path))

    assert ok is False
    assert "当前工作流" in detail


def test_validate_spike_stage_rejects_blocking_item(tmp_path):
    _setup_valid_project(tmp_path)
    index_path = tmp_path / "spec" / "穿刺清单.md"
    index_path.write_text(index_path.read_text().replace("是否阻塞后续：否", "是否阻塞后续：是"), encoding="utf-8")
    _write(
        tmp_path / "spec" / "穿刺_真实接口返回.md",
        _detail_document(blocked="是"),
    )

    ok, detail = validate_spike_stage(str(tmp_path))

    assert ok is False
    assert "仍然阻塞后续" in detail


def test_validate_spike_stage_requires_design_hash_change(tmp_path):
    """Workflow-Test
    主题：产品和代码设计及缺陷穿刺结论保持真实一致
    测试项：TC-06 证据冲突阻止推进并同步设计
    验收条件：AC-06 证据冲突时不能自行定论
    测试方式：自动化测试 + 人工验收
    测试层级：模块测试
    测试目标：结论声称需要更新产品设计但产品文档哈希未变化时阻止推进
    测试入口：tests/test_spike_validation.py::test_validate_spike_stage_requires_design_hash_change
    代码入口：workflow_loop.spike_validation.validate_spike_stage
    """
    _setup_valid_project(tmp_path)
    index_path = tmp_path / "spec" / "穿刺清单.md"
    index_path.write_text(index_path.read_text().replace("产品设计影响：无需修改", "产品设计影响：需要修改"), encoding="utf-8")
    _write(
        tmp_path / "spec" / "穿刺_真实接口返回.md",
        _detail_document(
            product_impact="需要修改",
            product_location="spec/功能_示例.md 第 4 节",
        ),
    )

    ok, detail = validate_spike_stage(str(tmp_path))

    assert ok is False
    assert "产品设计哈希没有变化" in detail


def test_validate_spike_stage_allows_code_plan_impact_without_changing_architecture(tmp_path):
    _setup_valid_project(tmp_path)
    index_path = tmp_path / "spec" / "穿刺清单.md"
    index_path.write_text(index_path.read_text().replace("代码设计影响：无需修改", "代码设计影响：需要修改"), encoding="utf-8")
    _write(
        tmp_path / "spec" / "穿刺_真实接口返回.md",
        _detail_document(
            code_impact="需要修改",
            code_location="spec/代码架构设计.md 第 6.2 节",
        ),
    )
    ok, detail = validate_spike_stage(str(tmp_path))

    assert ok is True, detail


def test_validate_spike_stage_requires_unresolved_risk_fields(tmp_path):
    _setup_valid_project(tmp_path)
    index_path = tmp_path / "spec" / "穿刺清单.md"
    index_path.write_text(
        index_path.read_text()
        .replace("穿刺状态：已确认", "穿刺状态：仍未确认")
        .replace("后续处理阶段：无", "后续处理阶段：test"),
        encoding="utf-8",
    )
    _write(
        tmp_path / "spec" / "穿刺_真实接口返回.md",
        _detail_document(
            result_status="仍未确认",
            unresolved="接口高并发限流阈值仍未知",
            follow_up="test",
        ),
    )

    ok, detail = validate_spike_stage(str(tmp_path))

    assert ok is False
    assert "剩余风险" in detail
    assert "后续需要检查什么" in detail


def test_validate_spike_stage_rejects_product_change_in_bugfix(tmp_path):
    _setup_valid_project(tmp_path, intent="bugfix")
    index_path = tmp_path / "spec" / "穿刺清单.md"
    index_path.write_text(index_path.read_text().replace("产品设计影响：无需修改", "产品设计影响：需要修改"), encoding="utf-8")
    _write(
        tmp_path / "spec" / "穿刺_真实接口返回.md",
        _detail_document(
            product_impact="需要修改",
            product_location="spec/功能_示例.md 第 4 节",
        ),
    )
    _write(tmp_path / "spec" / "功能_示例.md", "# 【功能】Example changed\n")

    ok, detail = validate_spike_stage(str(tmp_path))

    assert ok is False
    assert "不能继续 bugfix" in detail


def test_validate_spike_stage_allows_legacy_missing_baseline_when_design_does_not_change(tmp_path):
    _setup_valid_project(tmp_path)
    state = load_state(str(tmp_path))
    assert state is not None
    state.spike_baseline = SpikeBaselineState(legacy_unavailable=True)
    save_state(str(tmp_path), state)

    ok, detail = validate_spike_stage(str(tmp_path))

    assert ok is True, detail


def test_validate_spike_stage_rejects_design_change_when_legacy_baseline_is_missing(tmp_path):
    _setup_valid_project(tmp_path)
    state = load_state(str(tmp_path))
    assert state is not None
    state.spike_baseline = SpikeBaselineState(legacy_unavailable=True)
    save_state(str(tmp_path), state)
    index_path = tmp_path / "spec" / "穿刺清单.md"
    index_path.write_text(
        index_path.read_text().replace("产品设计影响：无需修改", "产品设计影响：需要修改"),
        encoding="utf-8",
    )
    _write(
        tmp_path / "spec" / "穿刺_真实接口返回.md",
        _detail_document(
            product_impact="需要修改",
            product_location="spec/功能_示例.md 第 4 节",
        ),
    )
    _write(tmp_path / "spec" / "功能_示例.md", "# 【功能】Example changed\n")

    ok, detail = validate_spike_stage(str(tmp_path))

    assert ok is False
    assert "旧工作流" in detail
    assert "无法证明" in detail
