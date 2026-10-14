"""人工收工入口测试。

本次改动按用户明确授权走简化处理，未走工具自身完整研发轮次。
测试只在临时项目中执行流程工具，不执行交易系统测试或人工验收。
"""

from dataclasses import asdict
from types import SimpleNamespace

import pytest

from test_commands import _install_project, _run
from workflow_loop import cli, journal
from workflow_loop.state import GateState, load_state, save_state


REASON = "用户明确要求不再运行测试，人工确认实施结果后收工"
NOTE = "架构文档已经人工同步；不是门禁通过或测试证明"
TAIL = ["qa", "topic_acceptance", "regression_test", "overall_acceptance", "update_code_design"]


@pytest.fixture
def active_project(tmp_path):
    _install_project(tmp_path)
    code, out, err = _run(["start", "--intent", "product_change"], tmp_path)
    assert code == 0, out + err
    state = load_state(str(tmp_path))
    for name in state.stage_path[:state.stage_path.index("qa")]:
        state.stages[name].status = "done"
        state.stages[name].gate = GateState(True, True, True)
    state.current_stage = "qa"
    state.stages["qa"].status = "in_progress"
    state.stages["qa"].gate.discussion_complete = True
    save_state(str(tmp_path), state)
    design = tmp_path / "spec" / "代码架构设计.md"
    design.parent.mkdir(exist_ok=True)
    design.write_text("# 代码架构设计\n\n已按真实代码人工同步。\n", encoding="utf-8")
    return tmp_path


def test_manual_close_preserves_facts_and_only_cleans_this_runs_temporary_files(active_project):
    root = active_project
    before = load_state(str(root))
    protected = ["spec/代码架构设计.md", "app.ts", "data/real.json", "Dockerfile", "qa/existing.md"]
    for path in protected[1:]:
        target = root / path
        target.parent.mkdir(exist_ok=True)
        target.write_text("keep current content", encoding="utf-8")
    contents = {path: (root / path).read_bytes() for path in protected}
    rollback = root / ".workflow_loop" / "rollback" / before.workflow_id
    rollback.mkdir(parents=True, exist_ok=True)
    (rollback / "baseline.txt").write_text("temporary", encoding="utf-8")
    other = root / ".workflow_loop" / "rollback" / "other-run"
    other.mkdir()
    (other / "keep.txt").write_text("other", encoding="utf-8")
    spike = root / ".workflow_loop" / "spike_tmp" / before.workflow_id
    spike.mkdir(parents=True)
    (spike / "unfinished.txt").write_text("temporary", encoding="utf-8")

    code, out, err = _run(["close-manual", "--reason", REASON, "--code-design-note", NOTE], root)

    assert code == 0, out + err
    after = load_state(str(root))
    assert after.run_status == "completed"
    assert after.current_stage == "completed"
    assert after.ended_at and after.aborted_at is None
    assert not rollback.exists() and not spike.exists()
    assert (other / "keep.txt").read_text(encoding="utf-8") == "other"
    assert {path: (root / path).read_bytes() for path in protected} == contents
    assert sorted(path.name for path in (root / "qa").iterdir()) == ["existing.md"]
    assert not (root / "acceptance").exists()
    for name in before.stage_path:
        expected = "done" if name not in TAIL else "skipped_by_user"
        if name == "update_code_design":
            expected = "manually_synced"
        assert after.stages[name].status == expected
        assert asdict(after.stages[name].gate) == asdict(before.stages[name].gate)
        assert after.stages[name].test_tasks == before.stages[name].test_tasks
        assert after.stages[name].acceptance_records == before.stages[name].acceptance_records
        assert after.stages[name].validation_credential == before.stages[name].validation_credential
    assert asdict(after.regression_test) == asdict(before.regression_test)
    assert asdict(after.architecture) == asdict(before.architecture)
    audit = after.meta["manual_close"]
    assert audit["reason"] == REASON and audit["operator"]
    assert audit["closed_at"] == after.ended_at
    assert audit["previous_stage"] == "qa"
    assert audit["code_design_note"] == NOTE
    assert audit["code_design_path"] == "spec/代码架构设计.md"
    assert len(audit["code_design_hash"]) == 64
    assert [row["stage"] for row in audit["processed_stages"]] == TAIL
    assert audit["processed_stages"][0]["previous_status"] == "in_progress"
    events = journal.read_all(str(root))
    event = next(entry for entry in events if entry["action"] == "人工收工依据已记录")
    assert event["manual_close"] == audit
    assert event["completion_pending"] is True
    assert event["cleaned_rollback_paths"] == [f".workflow_loop/rollback/{before.workflow_id}"]
    assert "用户要求未执行" in out and "已人工同步" in out
    assert out.rstrip().endswith("工作流完成。本次 workflow 结束。")


def test_closed_status_lists_real_stage_facts_and_start_is_read_only(active_project):
    root = active_project
    assert _run(["close-manual", "--reason", REASON, "--code-design-note", NOTE], root)[0] == 0
    state_path = root / ".workflow_loop" / "state.json"
    journal_path = root / ".workflow_loop" / "journal.jsonl"
    before = (state_path.read_bytes(), journal_path.read_bytes())

    code, out, err = _run(["status"], root)

    assert code == 0, out + err
    assert "run_status: completed" in out
    for name in TAIL[:-1]:
        line = next(line for line in out.splitlines() if name in line and "[" in line)
        assert "skipped_by_user" in line and "用户要求未执行" in line
        assert "校验:✗" in line and "确认:✗" in line
    line = next(line for line in out.splitlines() if "update_code_design" in line and "[" in line)
    assert "manually_synced" in line and "已人工同步" in line and "校验:✗" in line
    assert REASON in out and NOTE in out
    code, out, err = _run(["start"], root)
    assert code == 0, out + err
    assert "当前没有进行中的工作轮次" in out
    assert (state_path.read_bytes(), journal_path.read_bytes()) == before


def test_without_design_note_records_unfinished_design_as_skipped(active_project):
    root = active_project
    (root / "spec" / "代码架构设计.md").unlink()
    code, out, err = _run(["close-manual", "--reason", REASON], root)
    assert code == 0, out + err
    state = load_state(str(root))
    assert all(state.stages[name].status == "skipped_by_user" for name in TAIL)
    assert state.meta["manual_close"]["code_design_note"] is None


def test_already_completed_stages_are_not_relabelled(active_project):
    root = active_project
    state = load_state(str(root))
    state.current_stage = "topic_acceptance"
    state.stages["qa"].status = "done"
    state.stages["qa"].gate = GateState(True, True, True)
    save_state(str(root), state)
    code, out, err = _run(["close-manual", "--reason", REASON], root)
    assert code == 0, out + err
    after = load_state(str(root))
    assert asdict(after.stages["qa"]) == asdict(state.stages["qa"])
    assert "qa" not in [row["stage"] for row in after.meta["manual_close"]["processed_stages"]]


@pytest.mark.parametrize("case", ["missing_reason", "blank_reason", "completed", "aborted", "light_task", "unknown_intent", "impl_pending", "impl_unconfirmed", "missing_impl", "restore_started", "restored", "abort_cleaned"])
def test_ineligible_requests_do_not_mutate_state_or_clean_files(active_project, case):
    root = active_project
    state = load_state(str(root))
    args = ["close-manual", "--reason", REASON]
    if case == "missing_reason":
        args = ["close-manual"]
    elif case == "blank_reason":
        args[-1] = "  "
    elif case in ("completed", "aborted"):
        state.run_status = case
    elif case in ("light_task", "unknown_intent"):
        state.intent = case
    elif case == "impl_pending":
        state.stages["impl"].status = "pending"
    elif case == "impl_unconfirmed":
        state.stages["impl"].gate.user_confirmed = False
    elif case == "missing_impl":
        del state.stages["impl"]
    elif case == "restore_started":
        state.rollback.restore_started_at = "2026-10-14T00:00:00+00:00"
    elif case == "restored":
        state.rollback.restored_at = "2026-10-14T00:00:00+00:00"
    elif case == "abort_cleaned":
        state.rollback.cleanup_completed_at = "2026-10-14T00:00:00+00:00"
    save_state(str(root), state)
    temporary = root / ".workflow_loop" / "rollback" / state.workflow_id / "keep.txt"
    temporary.parent.mkdir(parents=True, exist_ok=True)
    temporary.write_text("keep on rejection", encoding="utf-8")
    state_path = root / ".workflow_loop" / "state.json"
    journal_path = root / ".workflow_loop" / "journal.jsonl"
    before = (state_path.read_bytes(), journal_path.read_bytes())
    code, out, err = _run(args, root)
    assert code != 0, out + err
    assert (state_path.read_bytes(), journal_path.read_bytes()) == before
    assert temporary.read_text(encoding="utf-8") == "keep on rejection"


@pytest.mark.parametrize("case", ["missing", "empty", "directory", "outside_symlink", "blank_note"])
def test_design_note_requires_an_existing_readable_nonempty_project_document(active_project, case):
    root = active_project
    design = root / "spec" / "代码架构设计.md"
    note = NOTE
    if case == "missing":
        design.unlink()
    elif case == "empty":
        design.write_text("  ", encoding="utf-8")
    elif case == "directory":
        design.unlink()
        design.mkdir()
    elif case == "outside_symlink":
        design.unlink()
        outside = root.parent / f"{root.name}-outside.md"
        outside.write_text("outside document", encoding="utf-8")
        design.symlink_to(outside)
    else:
        note = "  "
    state_path = root / ".workflow_loop" / "state.json"
    before = state_path.read_bytes()
    code, out, err = _run(["close-manual", "--reason", REASON, "--code-design-note", note], root)
    assert code != 0, out + err
    assert state_path.read_bytes() == before


def test_cleanup_failure_keeps_active_state_and_reports_retry(active_project, monkeypatch, capsys):
    root = active_project
    state_path = root / ".workflow_loop" / "state.json"
    before = state_path.read_bytes()
    monkeypatch.chdir(root)

    def fail_cleanup(*args):
        raise OSError("temporary cleanup denied")

    monkeypatch.setattr(cli.rollback_mod, "cleanup", fail_cleanup)
    with pytest.raises(SystemExit) as exc:
        cli.cmd_close_manual(SimpleNamespace(reason=REASON, code_design_note=NOTE))
    assert exc.value.code == 1
    assert state_path.read_bytes() == before
    out = capsys.readouterr().out
    assert "temporary cleanup denied" in out and "workflow close-manual" in out


def test_entry_refuses_project_without_a_run(tmp_path):
    _install_project(tmp_path)
    code, out, err = _run(["close-manual", "--reason", REASON], tmp_path)
    assert code != 0, out + err
    assert not (tmp_path / ".workflow_loop" / "state.json").exists()


@pytest.mark.parametrize("failure", ["journal", "state"])
def test_persistence_failure_does_not_finish_and_can_be_retried(active_project, monkeypatch, capsys, failure):
    root = active_project
    state_path = root / ".workflow_loop" / "state.json"
    before = state_path.read_bytes()
    monkeypatch.chdir(root)
    target = cli.journal_mod if failure == "journal" else cli.state_mod
    method = "append_entry" if failure == "journal" else "save_state"

    def fail_write(*args, **kwargs):
        raise OSError(f"{failure} write denied")

    with monkeypatch.context() as patch:
        patch.setattr(target, method, fail_write)
        with pytest.raises(SystemExit) as exc:
            cli.cmd_close_manual(SimpleNamespace(reason=REASON, code_design_note=NOTE))
        assert exc.value.code == 1
    assert state_path.read_bytes() == before
    out = capsys.readouterr().out
    assert f"{failure} write denied" in out
    assert "未完成收工" in out and "workflow close-manual" in out
    if failure == "state":
        event = journal.read_all(str(root))[-1]
        assert event["action"] == "人工收工依据已记录"
        assert event["completion_pending"] is True
    code, out, err = _run(["close-manual", "--reason", REASON, "--code-design-note", NOTE], root)
    assert code == 0, out + err
    assert load_state(str(root)).run_status == "completed"


def test_entry_journal_write_failure_returns_error_without_completing(active_project):
    root = active_project
    state_path = root / ".workflow_loop" / "state.json"
    before = state_path.read_bytes()
    journal_path = root / ".workflow_loop" / "journal.jsonl"
    saved_journal = journal_path.with_suffix(".previous")
    journal_path.rename(saved_journal)
    journal_path.mkdir()
    code, out, err = _run(["close-manual", "--reason", REASON], root)
    assert code == 1, out + err
    assert "未完成收工" in out
    assert state_path.read_bytes() == before
