"""旧日志恢复只使用能够归属于当前轮次的事实。"""

from copy import deepcopy

from workflow_loop import cli, journal
from workflow_loop import state as state_mod
from test_workflow_guidance import WORKFLOW_ID, _project


START = "2026-09-07T07:00:00+00:00"


def _state(root):
    state = _project(root, stage="impl")
    state.started_at = START
    state_mod.save_state(str(root), state)
    return state


def test_foreign_and_invalid_entries_do_not_restore(tmp_path):
    """Workflow-Test
    主题：恢复说明不再引用其他轮次日志
    测试项：TC-01 旧轮次和无效时间不能恢复
    验收条件：AC-01 旧轮次不得恢复为本轮
    测试方式：自动化测试
    测试层级：集成测试
    产品入口：调用继续工作时的旧日志恢复入口
    测试入口：tests/test_recovery_journal_boundary.py::test_foreign_and_invalid_entries_do_not_restore
    代码入口：src/workflow_loop/cli.py::restore_recovery_context_from_journal
    准备数据：首次进入实施阶段的当前轮次，日志含开工前事件、其他编号事件、无效时间及无时区记录。
    执行动作：逐个恢复内存状态副本并核对日志原文与恢复说明。
    关键断言：开工前、其他编号和无法确认归属的无编号记录全部排除，首次进入不显示虚假退回。
    预期证据：当前执行的结构化测试报告中入口精确匹配，执行数大于零，跳过失败错误均为零且退出码为零。
    """
    entries = [
        {"ts": "2026-07-30T02:27:11+00:00"},
        {"ts": "2026-09-07T14:59:59+08:00"},
        {"ts": "2026-09-07T07:00:01+00:00", "workflow_id": "other-run"},
        {"ts": "2026-09-07T07:00:01+00:00", "workflow_id": ""},
        {"ts": "not-a-time"},
        {"ts": "2026-09-07T08:00:00"},
        {"ts": None},
        {"ts": []},
        {"ts": "2026-09-07T08:00:00+00:00", "from_stage": []},
        {"ts": "2026-09-07T08:00:00+00:00", "recovery_created_at": []},
    ]
    for index, fields in enumerate(entries):
        root = tmp_path / str(index)
        state = _state(root)
        payload = {"from_stage": "impl", "reason": "不可作为当前轮次的恢复原因", **fields}
        journal.append_entry(str(root), "验证失效", "workflow.py", **payload)
        original_journal = (root / journal.JOURNAL_FILE).read_bytes()
        original_state = (root / ".workflow_loop/state.json").read_bytes()
        for _ in range(2):
            candidate = deepcopy(state)
            assert not cli.restore_recovery_context_from_journal(str(root), candidate), fields
            assert candidate.recovery.source_stage is None
            assert not cli.recovery_instruction(candidate)
        assert (root / journal.JOURNAL_FILE).read_bytes() == original_journal
        assert (root / ".workflow_loop/state.json").read_bytes() == original_state

    root = tmp_path / "unknown-start"
    state = _state(root)
    journal.append_entry(str(root), "验证失效", "workflow.py", ts=START, from_stage="impl")
    for invalid_start in (None, "", "bad", "2026-09-07T07:00:00"):
        candidate = deepcopy(state)
        candidate.started_at = invalid_start
        assert not cli.restore_recovery_context_from_journal(str(root), candidate)


def test_current_legacy_entries_and_handled_markers(tmp_path):
    """Workflow-Test
    主题：恢复说明不再引用其他轮次日志
    测试项：TC-02 本轮旧日志恢复及处理标记生效
    验收条件：AC-02 同轮旧格式仍可恢复
    测试方式：自动化测试
    测试层级：集成测试
    产品入口：调用继续工作时的旧日志恢复入口
    测试入口：tests/test_recovery_journal_boundary.py::test_current_legacy_entries_and_handled_markers
    代码入口：src/workflow_loop/cli.py::restore_recovery_context_from_journal
    准备数据：同轮有效无编号事件和显式编号事件，包含跨时区时间、本轮与外轮次已处理标记。
    执行动作：逐个恢复事件，记录已处理事实后再次恢复，并核对重复读取。
    关键断言：按真实时刻比较时区和开工边界，编号精确归属；同轮处理记录生效且重复读取稳定。
    预期证据：当前执行的结构化测试报告中入口精确匹配，执行数大于零，跳过失败错误均为零且退出码为零。
    """
    entries = [
        {"ts": "2026-09-07T15:00:00+08:00"},
        {"ts": "2026-09-07T03:00:01-04:00", "workflow_id": None},
        {"ts": "2026-07-30T02:27:11+00:00", "workflow_id": WORKFLOW_ID,
         "recovery_created_at": "explicit-current-recovery"},
    ]
    for index, fields in enumerate(entries):
        root = tmp_path / str(index)
        state = _state(root)
        reason = f"当前轮次真实恢复原因 {index}"
        journal.append_entry(
            str(root), "验证失效", "workflow.py",
            from_stage="impl", reason=reason, **fields,
        )
        recovery_id = fields.get("recovery_created_at", fields["ts"])
        for marker_fields in (
            {"workflow_id": "other-run", "ts": START},
            {"ts": "2026-07-30T03:00:00+00:00"},
        ):
            journal.append_entry(
                str(root), "恢复提示已处理", "workflow.py",
                recovery_created_at=recovery_id, **marker_fields,
            )
        original_journal = (root / journal.JOURNAL_FILE).read_bytes()
        candidate = deepcopy(state)
        assert cli.restore_recovery_context_from_journal(str(root), candidate)
        assert candidate.recovery.reason == reason
        assert candidate.recovery.created_at == recovery_id
        assert not cli.restore_recovery_context_from_journal(str(root), candidate)
        assert (root / journal.JOURNAL_FILE).read_bytes() == original_journal

        journal.append_entry(
            str(root), "恢复提示已处理", "workflow.py",
            workflow_id=WORKFLOW_ID, recovery_created_at=recovery_id,
        )
        assert not cli.restore_recovery_context_from_journal(str(root), deepcopy(state))

    root = tmp_path / "completed-source"
    state = _state(root)
    state.stages["impl"].status = "done"
    journal.append_entry(str(root), "验证失效", "workflow.py", ts=START, from_stage="impl")
    assert not cli.restore_recovery_context_from_journal(str(root), state)

    root = tmp_path / "explicit-return"
    state = _state(root)
    journal.append_entry(
        str(root), "流程退回", "workflow.py", ts=START,
        workflow_id=WORKFLOW_ID, to_stage="impl", reason="本轮显式返回实施",
    )
    assert cli.restore_recovery_context_from_journal(str(root), state)
    assert state.recovery.reason == "本轮显式返回实施"
