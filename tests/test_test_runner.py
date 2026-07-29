from workflow_loop.cli import validate_stage_output
from workflow_loop.state import WorkflowState, load_state, save_state
from workflow_loop.test_runner import ensure_test_baseline, run_final_regression


def _state():
    return WorkflowState(
        workflow_id="2026-07-25-1200-test",
        intent="from_scratch",
        current_stage="test_plan",
        stage_path=["test_plan"],
    )


def _write_entry(tmp_path, body):
    path = tmp_path / "scripts" / "test_all.sh"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"#!/usr/bin/env bash\nset -eu\n{body}\n", encoding="utf-8")
    path.chmod(0o755)
    return path


def test_test_baseline_requires_unified_entry(tmp_path):
    tests_dir = tmp_path / "tests"
    tests_dir.mkdir()
    (tests_dir / "test_existing.py").write_text("def test_existing():\n    assert True\n", encoding="utf-8")
    state = _state()

    result = ensure_test_baseline(str(tmp_path), state)

    assert result.passed is False
    assert state.test_baseline.status == "unavailable"
    assert "找不到统一测试入口" in state.test_baseline.output_tail


def test_test_baseline_allows_project_without_existing_tests(tmp_path):
    state = _state()

    result = ensure_test_baseline(str(tmp_path), state)

    assert result.passed is True
    assert result.ran is False
    assert state.test_baseline.status == "not_applicable"
    assert "没有已有测试" in state.test_baseline.output_tail


def test_test_baseline_records_pass_and_reuses_unchanged_code(tmp_path):
    _write_entry(tmp_path, "echo 'all unit tests passed'")
    state = _state()

    first = ensure_test_baseline(str(tmp_path), state)
    second = ensure_test_baseline(str(tmp_path), state)

    assert first.passed is True
    assert first.ran is True
    assert second.passed is True
    assert second.ran is False
    assert second.reused is True
    assert state.test_baseline.status == "passed"
    assert state.test_baseline.exit_code == 0


def test_test_baseline_reruns_after_test_entry_changes(tmp_path):
    entry = _write_entry(tmp_path, "echo 'version one'")
    state = _state()

    first = ensure_test_baseline(str(tmp_path), state)
    entry.write_text(
        "#!/usr/bin/env bash\nset -eu\necho 'version two'\n",
        encoding="utf-8",
    )
    entry.chmod(0o755)
    second = ensure_test_baseline(str(tmp_path), state)

    assert first.passed is True
    assert second.passed is True
    assert second.ran is True
    assert second.reused is False


def test_test_baseline_failure_blocks_gate(tmp_path):
    _write_entry(tmp_path, "echo 'unit test failed' >&2\nexit 7")
    state = _state()

    result = ensure_test_baseline(str(tmp_path), state)

    assert result.passed is False
    assert state.test_baseline.status == "failed"
    assert state.test_baseline.exit_code == 7
    assert "unit test failed" in state.test_baseline.output_tail


def test_test_baseline_round_trips_through_state_json(tmp_path):
    _write_entry(tmp_path, "echo ok")
    state = _state()
    ensure_test_baseline(str(tmp_path), state)
    save_state(str(tmp_path), state)

    loaded = load_state(str(tmp_path))

    assert loaded is not None
    assert loaded.test_baseline.entry == "scripts/test_all.sh"
    assert loaded.test_baseline.status == "passed"
    assert loaded.test_baseline.exit_code == 0


def test_final_regression_runs_unified_entry_without_reusing_baseline(tmp_path):
    _write_entry(tmp_path, "echo 'all tests passed'")
    state = _state()

    passed, detail = run_final_regression(str(tmp_path), state)

    assert passed is True
    assert "最终全量测试通过" in detail
    assert state.regression_test.status == "passed"
    assert state.regression_test.exit_code == 0


def test_final_regression_failure_is_saved_in_state(tmp_path):
    _write_entry(tmp_path, "echo 'unit test failed' >&2\nexit 7")
    state = _state()

    passed, detail = run_final_regression(str(tmp_path), state)

    assert passed is False
    assert state.regression_test.status == "failed"
    assert state.regression_test.exit_code == 7
    assert "unit test failed" in detail


def test_validate_stage_output_runs_baseline_for_test_plan(tmp_path):
    _write_entry(tmp_path, "echo ok")
    state = _state()

    class PassingStage:
        def code_validate(self, _project_root):
            return True, "测试计划结构通过"

    passed, detail = validate_stage_output(
        str(tmp_path),
        state,
        "test_plan",
        PassingStage(),
    )

    assert passed is True
    assert "修改前全量测试完成" in detail
    assert state.test_baseline.status == "passed"
