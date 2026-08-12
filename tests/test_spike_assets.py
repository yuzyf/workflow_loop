import json
import shlex
import sys
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest

from workflow_loop import cli as cli_mod
from workflow_loop import project as project_mod
from workflow_loop import rollback
from workflow_loop import spike_reuse
from workflow_loop import state as state_mod
from workflow_loop import traceability as traceability_mod
from workflow_loop.stages.base import clean_spike_tmp, plan_spike_tmp_cleanup


WORKFLOW_ID = "2026-08-11-1200-product_change"
HISTORICAL_WORKFLOW_ID = "2026-08-10-0900-product_change"


def _write(path: Path, content: str = "content\n") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _asset(
    workflow_id: str,
    item_key: str,
    *,
    status: str = "registered",
) -> state_mod.SpikeAssetRegistration:
    return state_mod.SpikeAssetRegistration(
        workflow_id=workflow_id,
        spike_id=f"SP-{item_key}",
        relative_path=f".workflow_loop/spike_tmp/{workflow_id}/{item_key}",
        conclusion_document=f"spec/穿刺_{item_key}.md",
        acceptance_conditions=[],
        purpose=f"复用 {item_key} 重新取得结论",
        run_method="python rerun.py",
        status=status,
    )


def _state(
    *,
    workflow_id: str = WORKFLOW_ID,
    current_stage: str = "spike",
    spike_assets: list[state_mod.SpikeAssetRegistration] | None = None,
) -> state_mod.WorkflowState:
    return state_mod.WorkflowState(
        workflow_id=workflow_id,
        intent="product_change",
        run_status="active",
        current_stage=current_stage,
        stage_path=["spike", "acceptance_plan"],
        stages={
            "spike": state_mod.StageState(status="in_progress"),
            "acceptance_plan": state_mod.StageState(status="pending"),
        },
        spike_assets=list(spike_assets or []),
    )


def test_spike_cleanup_removes_only_current_unregistered_entries(tmp_path):
    """已登记、待修订和历史资产都保留，只删当前工作流未登记内容。"""
    registered = _asset(WORKFLOW_ID, "registered")
    needs_revision = _asset(WORKFLOW_ID, "needs-revision", status="needs_revision")
    historical = _asset(HISTORICAL_WORKFLOW_ID, "registered")
    state = _state(spike_assets=[registered, needs_revision, historical])

    registered_file = tmp_path / registered.relative_path / "rerun.py"
    revision_file = tmp_path / needs_revision.relative_path / "rerun.py"
    historical_file = tmp_path / historical.relative_path / "rerun.py"
    scratch_file = (
        tmp_path
        / ".workflow_loop"
        / "spike_tmp"
        / WORKFLOW_ID
        / "unfinished"
        / "notes.txt"
    )
    loose_file = (
        tmp_path / ".workflow_loop" / "spike_tmp" / WORKFLOW_ID / "debug.log"
    )
    _write(registered_file, "registered\n")
    _write(revision_file, "needs revision\n")
    _write(historical_file, "historical\n")
    _write(scratch_file, "unfinished\n")
    _write(loose_file, "debug\n")

    plan = plan_spike_tmp_cleanup(str(tmp_path), state)
    cleaned = clean_spike_tmp(str(tmp_path), state, cleanup_plan=plan)

    assert plan == {
        "preserved": sorted([registered.relative_path, needs_revision.relative_path]),
        "remove": sorted(
            [
                f".workflow_loop/spike_tmp/{WORKFLOW_ID}/debug.log",
                f".workflow_loop/spike_tmp/{WORKFLOW_ID}/unfinished",
            ]
        ),
    }
    assert cleaned == plan["remove"]
    assert registered_file.read_text(encoding="utf-8") == "registered\n"
    assert revision_file.read_text(encoding="utf-8") == "needs revision\n"
    assert historical_file.read_text(encoding="utf-8") == "historical\n"
    assert not scratch_file.exists()
    assert not loose_file.exists()


def test_frozen_spike_cleanup_plan_rejects_new_unregistered_content(tmp_path):
    """作废预检后的新半成品不能被静默遗漏，也不能扩大原冻结删除范围。"""
    state = _state()
    original = (
        tmp_path
        / ".workflow_loop"
        / "spike_tmp"
        / WORKFLOW_ID
        / "original"
        / "notes.txt"
    )
    added_later = (
        tmp_path
        / ".workflow_loop"
        / "spike_tmp"
        / WORKFLOW_ID
        / "added-later"
        / "notes.txt"
    )
    _write(original)
    plan = plan_spike_tmp_cleanup(str(tmp_path), state)
    _write(added_later)

    with pytest.raises(ValueError, match="冻结后出现新的未登记内容"):
        clean_spike_tmp(str(tmp_path), state, cleanup_plan=plan)

    assert original.is_file()
    assert added_later.is_file()


def _prepare_abort_project(root: Path) -> state_mod.WorkflowState:
    project_mod.create_project(str(root))
    overview = root / "spec" / "产品总说明.md"
    _write(overview, "before\n")
    state = _state(current_stage="impl", spike_assets=[_asset(WORKFLOW_ID, "registered")])
    state.stage_path = ["impl"]
    state.stages = {"impl": state_mod.StageState(status="in_progress")}
    rollback.prepare_start_baseline(
        str(root),
        state.workflow_id,
        project_mod.snapshot_managed_fields(str(root)),
        None,
    )
    overview.write_text("during\n", encoding="utf-8")
    state_mod.save_state(str(root), state)
    return state


def test_abort_preflight_freezes_spike_plan_and_restore_failure_keeps_contents(
    tmp_path,
    monkeypatch,
    capsys,
):
    """作废先保存穿刺清理计划，项目恢复未完成时绝不提前清理。"""
    state = _prepare_abort_project(tmp_path)
    registered_file = tmp_path / state.spike_assets[0].relative_path / "rerun.py"
    scratch_file = (
        tmp_path
        / ".workflow_loop"
        / "spike_tmp"
        / WORKFLOW_ID
        / "unfinished"
        / "notes.txt"
    )
    _write(registered_file, "registered\n")
    _write(scratch_file, "unfinished\n")

    monkeypatch.setattr(cli_mod, "resolve_project_root", lambda: str(tmp_path))
    monkeypatch.setattr(
        cli_mod.rollback_mod,
        "restore_full_run",
        lambda _root, _state: (["spec/产品总说明.md"], ["injected restore failure"]),
    )
    cleanup_called = False

    def unexpected_cleanup(*_args, **_kwargs):
        nonlocal cleanup_called
        cleanup_called = True
        return []

    monkeypatch.setattr(cli_mod, "clean_spike_tmp", unexpected_cleanup)

    cli_mod.cmd_abort(SimpleNamespace(summary=None))
    output = capsys.readouterr().out

    manifest_path = (
        tmp_path
        / ".workflow_loop"
        / "rollback"
        / WORKFLOW_ID
        / "abort"
        / "manifest.json"
    )
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["spike_cleanup_plan"] == {
        "preserved": [state.spike_assets[0].relative_path],
        "remove": [f".workflow_loop/spike_tmp/{WORKFLOW_ID}/unfinished"],
    }
    assert cleanup_called is False
    assert registered_file.read_text(encoding="utf-8") == "registered\n"
    assert scratch_file.read_text(encoding="utf-8") == "unfinished\n"
    saved = state_mod.load_state(str(tmp_path))
    assert saved is not None and saved.run_status == "active"
    assert saved.rollback.restore_started_at is not None
    assert saved.rollback.restored_at is None
    assert "当前轮次仍是 active" in output


def _prepare_confirmed_spike_state(root: Path) -> state_mod.WorkflowState:
    state = _state()
    stage = state.stages["spike"]
    stage.gate = state_mod.GateState(
        discussion_complete=True,
        code_validated=True,
        user_confirmed=False,
    )
    stage.discussion_material_hash = "materials"
    stage.validation_credential = state_mod.ValidationCredential(
        workflow_id=WORKFLOW_ID,
        stage="spike",
        result=True,
    )
    state.meta[cli_mod.PENDING_SPIKE_ASSETS_META_KEY] = {
        "workflow_id": WORKFLOW_ID,
        "prepared_at": "2026-08-11T04:00:00+00:00",
        "items": [
            {
                "workflow_id": WORKFLOW_ID,
                "spike_id": "SP-01",
                "relative_path": (
                    f".workflow_loop/spike_tmp/{WORKFLOW_ID}/confirmed"
                ),
                "conclusion_document": "spec/穿刺_确认真实接口.md",
                "acceptance_conditions": [],
                "purpose": "重新取得真实接口结论",
                "run_method": "python rerun.py",
                "status": "registered",
                "registered_at": None,
                "last_rerun_at": None,
                "last_rerun_status": None,
            }
        ],
    }
    state_mod.save_state(str(root), state)
    _write(
        root
        / ".workflow_loop"
        / "spike_tmp"
        / WORKFLOW_ID
        / "confirmed"
        / "rerun.py",
        "print('confirmed')\n",
    )
    _write(
        root
        / ".workflow_loop"
        / "spike_tmp"
        / WORKFLOW_ID
        / "unfinished"
        / "notes.txt",
        "unfinished\n",
    )
    return state


def _patch_spike_confirmation_dependencies(monkeypatch, root: Path) -> None:
    monkeypatch.setattr(cli_mod, "resolve_project_root", lambda: str(root))
    monkeypatch.setattr(cli_mod, "refuse_if_pending_start_transaction", lambda _root: None)
    monkeypatch.setattr(
        cli_mod,
        "_ensure_stage_path_current_for_command",
        lambda _root, _state: None,
    )
    monkeypatch.setattr(
        cli_mod,
        "restore_recovery_context_from_journal",
        lambda _root, _state: False,
    )
    monkeypatch.setattr(
        cli_mod,
        "clear_completed_material_recovery",
        lambda _root, _state: None,
    )
    monkeypatch.setattr(cli_mod, "ensure_impl_recovery_baseline", lambda _root, _state: False)
    monkeypatch.setattr(cli_mod, "build_stage_path", lambda _intent, _root: [object()])
    monkeypatch.setattr(
        cli_mod,
        "get_stage_strategy",
        lambda _name, _state, _instances: object(),
    )
    monkeypatch.setattr(cli_mod, "compute_stage_material_hash", lambda _root, _stage: "materials")
    monkeypatch.setattr(
        cli_mod.verification_mod,
        "compare_validation_credential",
        lambda _root, _state, _stage: (True, "凭据有效"),
    )
    monkeypatch.setattr(cli_mod, "_register_stage_artifact_keys", lambda *_args: {})
    monkeypatch.setattr(cli_mod, "apply_stage_completion_updates", lambda *_args: [])
    monkeypatch.setattr(cli_mod.journal_mod, "append_entry", lambda *_args, **_kwargs: None)


def _confirmed_gate_args() -> SimpleNamespace:
    return SimpleNamespace(
        stage="spike",
        rebaseline=False,
        prepare_code=False,
        accept_existing_code=False,
        accept_existing_test_code=False,
        skip=False,
        discuss_done=False,
        confirmed=True,
    )


def test_spike_third_gate_registers_asset_then_cleans_unregistered_content(
    tmp_path,
    monkeypatch,
):
    """第三道门只有在资产登记和定向清理都成功后才推进。"""
    _prepare_confirmed_spike_state(tmp_path)
    _patch_spike_confirmation_dependencies(monkeypatch, tmp_path)

    cli_mod.cmd_gate(_confirmed_gate_args())

    saved = state_mod.load_state(str(tmp_path))
    assert saved is not None
    assert saved.current_stage == "acceptance_plan"
    assert saved.stages["spike"].status == "done"
    assert saved.stages["spike"].gate.user_confirmed is True
    assert cli_mod.PENDING_SPIKE_ASSETS_META_KEY not in saved.meta
    assert [asset.relative_path for asset in saved.spike_assets] == [
        f".workflow_loop/spike_tmp/{WORKFLOW_ID}/confirmed"
    ]
    assert (
        tmp_path
        / ".workflow_loop"
        / "spike_tmp"
        / WORKFLOW_ID
        / "confirmed"
        / "rerun.py"
    ).is_file()
    assert not (
        tmp_path
        / ".workflow_loop"
        / "spike_tmp"
        / WORKFLOW_ID
        / "unfinished"
    ).exists()


def test_spike_third_gate_cleanup_failure_keeps_pending_registration_and_stage(
    tmp_path,
    monkeypatch,
):
    """定向清理失败时不提交登记、不推进阶段，原待确认事实可重试。"""
    original = _prepare_confirmed_spike_state(tmp_path)
    pending = json.loads(json.dumps(original.meta[cli_mod.PENDING_SPIKE_ASSETS_META_KEY]))
    _patch_spike_confirmation_dependencies(monkeypatch, tmp_path)
    monkeypatch.setattr(
        cli_mod,
        "clean_spike_tmp",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("injected cleanup failure")),
    )

    cli_mod.cmd_gate(_confirmed_gate_args())

    saved = state_mod.load_state(str(tmp_path))
    assert saved is not None
    assert saved.current_stage == "spike"
    assert saved.stages["spike"].status == "in_progress"
    assert saved.stages["spike"].gate.code_validated is True
    assert saved.stages["spike"].gate.user_confirmed is False
    assert saved.spike_assets == []
    assert saved.meta[cli_mod.PENDING_SPIKE_ASSETS_META_KEY] == pending
    assert (
        tmp_path
        / ".workflow_loop"
        / "spike_tmp"
        / WORKFLOW_ID
        / "unfinished"
        / "notes.txt"
    ).is_file()


def test_same_minute_workflow_id_and_historical_assets_are_preserved(
    tmp_path,
    monkeypatch,
):
    """同一分钟开新轮次追加序号，并把历史资产登记完整继承到新状态。"""
    historical = _asset(WORKFLOW_ID, "confirmed")
    previous = _state(spike_assets=[historical])
    previous.run_status = "completed"
    previous.current_stage = "completed"
    state_mod.save_state(str(tmp_path), previous)
    project_mod.create_project(str(tmp_path))

    monkeypatch.setattr(cli_mod, "resolve_project_root", lambda: str(tmp_path))
    monkeypatch.setattr(cli_mod.project_mod, "is_installed", lambda _root: True)
    monkeypatch.setattr(
        cli_mod.state_mod,
        "now_iso",
        lambda: "2026-08-11T12:00:00+00:00",
    )
    monkeypatch.setattr(
        cli_mod.rollback_mod,
        "prepare_start_baseline",
        lambda *_args, **_kwargs: {"entries": {}},
    )
    monkeypatch.setattr(cli_mod.journal_mod, "append_entry", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        cli_mod,
        "build_stage_path",
        lambda _intent, _root: [
            SimpleNamespace(
                name=lambda: "spike",
                artifact_paths=lambda: ["spec/穿刺清单.md"],
            ),
            SimpleNamespace(
                name=lambda: "acceptance_plan",
                artifact_paths=lambda: ["acceptance/索引.md"],
            ),
        ],
    )

    cli_mod.cmd_start(SimpleNamespace(intent="product_change", confirm_clean=False))

    started = state_mod.load_state(str(tmp_path))
    assert started is not None
    assert started.workflow_id == f"{WORKFLOW_ID}-2"
    assert started.spike_assets == [historical]


def _historical_rerun_state(root: Path, script_body: str) -> tuple[state_mod.WorkflowState, Path]:
    source_workflow_id = HISTORICAL_WORKFLOW_ID
    asset = _asset(source_workflow_id, "rerun")
    script = root / asset.relative_path / "rerun.py"
    _write(script, script_body)
    asset.run_method = shlex.join([sys.executable, "rerun.py"])
    state = _state(spike_assets=[asset])
    return state, script


def test_historical_spike_asset_rerun_records_current_success_only_after_execution(
    tmp_path,
):
    """历史结论只有真实命令成功后才成为当前工作流事实。"""
    state, script = _historical_rerun_state(
        tmp_path,
        "print('current environment supports the interface')\n",
    )
    asset = state.spike_assets[0]
    assert asset.last_rerun_at is None

    attempt = spike_reuse.rerun_historical_asset(
        str(tmp_path),
        state,
        asset.relative_path,
        "当前环境返回稳定接口响应，可继续制定本轮代码计划",
        timeout_seconds=10,
    )

    assert attempt.status == "passed"
    assert attempt.result.exit_code == 0
    assert "current environment supports" in attempt.result.output_tail
    assert asset.last_rerun_workflow_id == WORKFLOW_ID
    assert asset.last_rerun_at == attempt.result.finished_at
    assert asset.last_rerun_status == "passed"
    assert asset.last_rerun_conclusion == "当前环境返回稳定接口响应，可继续制定本轮代码计划"
    assert asset.status == "registered"
    assert script.is_file()


def test_historical_spike_asset_failed_rerun_marks_revision_and_preserves_asset(
    tmp_path,
):
    """重跑失败写入当前失败事实并阻止沿用历史结论，但不删除资产。"""
    state, script = _historical_rerun_state(
        tmp_path,
        "import sys\nprint('dependency missing')\nsys.exit(3)\n",
    )
    asset = state.spike_assets[0]

    attempt = spike_reuse.rerun_historical_asset(
        str(tmp_path),
        state,
        asset.relative_path,
        "旧结论只有命令成功时才允许沿用",
        timeout_seconds=10,
    )

    assert attempt.status == "failed"
    assert attempt.result.exit_code == 3
    assert asset.last_rerun_workflow_id == WORKFLOW_ID
    assert asset.last_rerun_status == "failed"
    assert "历史结论不可沿用" in (asset.last_rerun_conclusion or "")
    assert asset.status == "needs_revision"
    assert script.is_file()


def test_historical_spike_asset_rerun_preflight_failure_writes_no_false_fact(
    tmp_path,
    monkeypatch,
):
    """结论含糊或范围无效时命令不启动，也不写任何当前重跑状态。"""
    state, _script = _historical_rerun_state(tmp_path, "print('not executed')\n")
    asset = state.spike_assets[0]
    executed = False

    def unexpected_execution(_request):
        nonlocal executed
        executed = True
        raise AssertionError("process must not run")

    monkeypatch.setattr(spike_reuse.process_runner_mod, "run_process", unexpected_execution)

    with pytest.raises(ValueError, match="具体技术结论"):
        spike_reuse.rerun_historical_asset(
            str(tmp_path),
            state,
            asset.relative_path,
            "运行成功",
            timeout_seconds=10,
        )

    assert executed is False
    assert asset.last_rerun_workflow_id is None
    assert asset.last_rerun_at is None
    assert asset.last_rerun_status is None
    assert asset.last_rerun_conclusion is None


def test_spike_rerun_cli_executes_registered_method_and_persists_machine_fact(
    tmp_path,
    monkeypatch,
    capsys,
):
    """CLI 入口调用登记方法，成功后才把当前工作流、状态和结论写入状态与流水。"""
    state, _script = _historical_rerun_state(tmp_path, "print('cli rerun passed')\n")
    state_mod.save_state(str(tmp_path), state)
    entries: list[tuple[tuple, dict]] = []
    monkeypatch.setattr(cli_mod, "resolve_project_root", lambda: str(tmp_path))
    monkeypatch.setattr(
        cli_mod,
        "_load_active_workflow_for_command",
        lambda _root: state_mod.load_state(str(tmp_path)),
    )
    monkeypatch.setattr(
        cli_mod.journal_mod,
        "append_entry",
        lambda *args, **kwargs: entries.append((args, kwargs)),
    )
    plan = spike_reuse.plan_historical_asset_rerun(
        str(tmp_path),
        state,
        state.spike_assets[0].relative_path,
        timeout_seconds=10,
    )

    cli_mod.cmd_spike_rerun(
        SimpleNamespace(
            asset=state.spike_assets[0].relative_path,
            conclusion="CLI 当前环境重跑得到明确支持结论",
            timeout=10,
            plan_id=plan.plan_id,
            confirmed=True,
        )
    )
    output = capsys.readouterr().out

    saved = state_mod.load_state(str(tmp_path))
    assert saved is not None
    asset = saved.spike_assets[0]
    assert asset.last_rerun_workflow_id == WORKFLOW_ID
    assert asset.last_rerun_status == "passed"
    assert asset.last_rerun_conclusion == "CLI 当前环境重跑得到明确支持结论"
    assert "历史穿刺资产重跑成功" in output
    assert "cli rerun passed" in output
    assert len(entries) == 1
    assert entries[0][0][1] == "历史穿刺资产重跑"
    assert entries[0][1]["status"] == "passed"
    assert "output_tail" not in entries[0][1]


def test_spike_rerun_cli_blocks_unknown_asset_without_state_or_journal_write(
    tmp_path,
    monkeypatch,
    capsys,
):
    """CLI 找不到继承登记时明确阻塞，不执行任意目录命令，也不伪造重跑流水。"""
    state, _script = _historical_rerun_state(tmp_path, "print('must not execute')\n")
    state_mod.save_state(str(tmp_path), state)
    before = (tmp_path / ".workflow_loop" / "state.json").read_bytes()
    entries: list[tuple[tuple, dict]] = []
    monkeypatch.setattr(cli_mod, "resolve_project_root", lambda: str(tmp_path))
    monkeypatch.setattr(
        cli_mod,
        "_load_active_workflow_for_command",
        lambda _root: state_mod.load_state(str(tmp_path)),
    )
    monkeypatch.setattr(
        cli_mod.journal_mod,
        "append_entry",
        lambda *args, **kwargs: entries.append((args, kwargs)),
    )

    cli_mod.cmd_spike_rerun(
        SimpleNamespace(
            asset=f".workflow_loop/spike_tmp/{HISTORICAL_WORKFLOW_ID}/unknown",
            conclusion=None,
            timeout=10,
            confirmed=False,
        )
    )
    output = capsys.readouterr().out

    assert "历史穿刺资产重跑未开始" in output
    assert "本次没有写入重跑事实" in output
    assert (tmp_path / ".workflow_loop" / "state.json").read_bytes() == before
    assert entries == []


def _write_historical_asset_traceability(
    root: Path,
    state: state_mod.WorkflowState,
) -> None:
    topic = "复用历史穿刺"
    state.topics = [topic]
    state.topic = topic
    state.spike_skipped = False
    state_mod.save_state(str(root), state)
    _write(
        root / "spec" / "穿刺清单.md",
        f"""# 【穿刺】穿刺清单

- 工作流编号：{state.workflow_id}

## SP-001 复用历史结论

- 真实场景：当前环境重新运行历史资产
- 要验证的不确定性：历史结论是否仍成立
- 验证结果用于决定什么：是否作为当前验收依据
- 结论文档：[复用历史结论](./穿刺_rerun.md)
- 穿刺状态：已确认
- 是否阻塞后续：否
- 产品设计影响：无需修改
- 代码设计影响：无需修改
- 后续处理阶段：acceptance_plan
""",
    )
    _write(root / "acceptance" / f"{topic}_验收计划.md", f"# 【验收主题】{topic}\n")
    asset = state.spike_assets[0]
    spike_value = (
        f"[{asset.spike_id} 结论](./{asset.conclusion_document})<br>"
        f"{asset.relative_path}<br>用途：{asset.purpose}<br>"
        f"运行方法：{asset.run_method}<br>"
        f"当前重跑结论：{asset.last_rerun_conclusion or '待重跑'}"
    )
    _write(
        root / "需求交付追踪表.md",
        f"""# 需求交付追踪表

## {state.workflow_id}

| 需求来源与设计依据 | 验收主题 | 验收条件 | 穿刺结论与可复用内容 | 测试项 | 实施计划与任务 | 实施记录与代码 | 测试结果 | 验收结果 | 更新后的代码设计 |
|---|---|---|---|---|---|---|---|---|---|
| [产品设计](./spec/功能.md) | [{topic}](./acceptance/{topic}_验收计划.md) | AC-01：当前环境仍支持 | {spike_value} | 待制定 | 待制定 | 待执行 | 待执行 | 待执行 | 待更新 |
""",
    )


def test_historical_asset_success_from_an_older_run_still_blocks_current_traceability(
    tmp_path,
):
    """继承到下一轮的旧成功不能冒充本轮重跑，追踪门禁必须要求当前工作流编号。"""
    state, _script = _historical_rerun_state(tmp_path, "print('ok')\n")
    asset = state.spike_assets[0]
    attempt = spike_reuse.rerun_historical_asset(
        str(tmp_path),
        state,
        asset.relative_path,
        "当前环境仍支持",
        timeout_seconds=10,
    )
    asset.last_rerun_workflow_id = "2026-08-10-1000-product_change"
    asset.last_rerun_at = attempt.record.finished_at
    asset.last_rerun_status = "passed"
    asset.last_rerun_conclusion = "上一轮环境支持"
    asset.last_rerun_record = replace(
        attempt.record,
        current_workflow_id="2026-08-10-1000-product_change",
        conclusion="上一轮环境支持",
    )
    asset.last_rerun_record = replace(
        asset.last_rerun_record,
        record_id=spike_reuse.compute_spike_rerun_record_id(asset.last_rerun_record),
    )
    _write_historical_asset_traceability(tmp_path, state)

    with pytest.raises(ValueError, match="必须在当前环境重新运行成功"):
        traceability_mod.collect_spike_asset_acceptance_links(
            str(tmp_path),
            state.workflow_id,
            state.topics,
        )

    asset.last_rerun_workflow_id = state.workflow_id
    asset.last_rerun_at = attempt.record.finished_at
    asset.last_rerun_status = "passed"
    asset.last_rerun_conclusion = attempt.record.conclusion
    asset.last_rerun_record = attempt.record
    state_mod.save_state(str(tmp_path), state)
    _write_historical_asset_traceability(tmp_path, state)
    links = traceability_mod.collect_spike_asset_acceptance_links(
        str(tmp_path),
        state.workflow_id,
        state.topics,
    )
    assert links == {asset.relative_path: ["复用历史穿刺/AC-01"]}


def test_spike_rerun_record_survives_save_load_and_binds_current_directory(tmp_path):
    """完整重跑记录保存后仍可被追踪门禁重新核验。"""
    state, _script = _historical_rerun_state(tmp_path, "print('recorded')\n")
    asset = state.spike_assets[0]

    attempt = spike_reuse.rerun_historical_asset(
        str(tmp_path),
        state,
        asset.relative_path,
        "当前环境仍能稳定得到记录中的接口响应",
        timeout_seconds=10,
    )
    state_mod.save_state(str(tmp_path), state)
    loaded = state_mod.load_state(str(tmp_path))

    assert loaded is not None
    loaded_asset = loaded.spike_assets[0]
    assert loaded_asset.last_rerun_record == attempt.record
    assert spike_reuse.historical_asset_has_current_success(
        str(tmp_path),
        loaded_asset,
        state.workflow_id,
    ) is True


def test_spike_rerun_success_invalidates_when_asset_changes_after_execution(tmp_path):
    """重跑成功后只要资产内容变化，旧机器证据立即失效。"""
    state, script = _historical_rerun_state(tmp_path, "print('before')\n")
    asset = state.spike_assets[0]
    spike_reuse.rerun_historical_asset(
        str(tmp_path),
        state,
        asset.relative_path,
        "当前环境仍支持",
        timeout_seconds=10,
    )
    script.write_text("print('after')\n", encoding="utf-8")

    problems = spike_reuse.historical_asset_success_problems(
        str(tmp_path),
        asset,
        state.workflow_id,
    )
    assert spike_reuse.historical_asset_has_current_success(
        str(tmp_path), asset, state.workflow_id
    ) is False
    assert any("目录哈希" in problem for problem in problems)


def test_spike_rerun_success_invalidates_when_run_method_changes(tmp_path):
    """登记的运行方法变化后，不能继续冒充原成功记录。"""
    state, _script = _historical_rerun_state(tmp_path, "print('stable')\n")
    asset = state.spike_assets[0]
    spike_reuse.rerun_historical_asset(
        str(tmp_path),
        state,
        asset.relative_path,
        "当前环境仍支持",
        timeout_seconds=10,
    )
    asset.run_method = shlex.join([sys.executable, "different.py"])

    problems = spike_reuse.historical_asset_success_problems(
        str(tmp_path), asset, state.workflow_id
    )
    assert any("运行方法已经变化" in problem for problem in problems)
    assert spike_reuse.historical_asset_has_current_success(
        str(tmp_path), asset, state.workflow_id
    ) is False


def test_spike_rerun_marks_asset_blocked_when_command_modifies_asset_directory(tmp_path):
    """命令成功但改写资产目录时也不能通过，资产保留并标待修订。"""
    state, script = _historical_rerun_state(
        tmp_path,
        "from pathlib import Path\nPath('changed.txt').write_text('changed')\n",
    )
    asset = state.spike_assets[0]
    attempt = spike_reuse.rerun_historical_asset(
        str(tmp_path),
        state,
        asset.relative_path,
        "不应被接受的结论",
        timeout_seconds=10,
    )

    assert attempt.result.status == "passed"
    assert attempt.status == "blocked"
    assert asset.status == "needs_revision"
    assert asset.last_rerun_record is not None
    assert asset.last_rerun_record.asset_hash_before != asset.last_rerun_record.asset_hash_after
    assert (script.parent / "changed.txt").is_file()


@pytest.mark.parametrize("intent", ["light_task"])
def test_spike_rerun_rejects_non_research_workflow(tmp_path, intent):
    """无需开发流程不允许借用完整研发流程的穿刺重跑命令。"""
    state, _script = _historical_rerun_state(tmp_path, "print('no')\n")
    state.intent = intent
    with pytest.raises(ValueError, match="light_task"):
        spike_reuse.rerun_historical_asset(
            str(tmp_path),
            state,
            state.spike_assets[0].relative_path,
            "不应执行",
            timeout_seconds=10,
        )


@pytest.mark.parametrize("stage", ["spike", "acceptance_plan"])
def test_spike_rerun_rejects_stage_after_second_gate(tmp_path, stage):
    """穿刺或验收计划第二道门通过后，必须退回再重跑，不能绕过凭据。"""
    state, _script = _historical_rerun_state(tmp_path, "print('no')\n")
    state.current_stage = stage
    state.stages[stage].gate.code_validated = True
    with pytest.raises(ValueError, match="第二道门"):
        spike_reuse.rerun_historical_asset(
            str(tmp_path),
            state,
            state.spike_assets[0].relative_path,
            "不应执行",
            timeout_seconds=10,
        )


def test_spike_rerun_preview_does_not_execute_or_write_state(tmp_path, monkeypatch, capsys):
    """不带 --confirmed 只预览命令，不运行进程也不改状态文件。"""
    state, _script = _historical_rerun_state(tmp_path, "print('preview only')\n")
    state_mod.save_state(str(tmp_path), state)
    before = (tmp_path / ".workflow_loop" / "state.json").read_bytes()
    monkeypatch.setattr(cli_mod, "resolve_project_root", lambda: str(tmp_path))
    monkeypatch.setattr(
        cli_mod,
        "_load_active_workflow_for_command",
        lambda _root: state_mod.load_state(str(tmp_path)),
    )
    monkeypatch.setattr(
        spike_reuse.process_runner_mod,
        "run_process",
        lambda _request: (_ for _ in ()).throw(AssertionError("preview must not execute")),
    )

    cli_mod.cmd_spike_rerun(
        SimpleNamespace(
            asset=state.spike_assets[0].relative_path,
            conclusion=None,
            timeout=10,
            confirmed=False,
        )
    )
    output = capsys.readouterr().out
    assert "历史穿刺资产重跑预览" in output
    assert "本次预览没有写入重跑事实" in output
    assert (tmp_path / ".workflow_loop" / "state.json").read_bytes() == before


def test_traceability_allows_historical_reuse_after_skipping_new_spike(tmp_path):
    """跳过新穿刺不等于禁止本轮真实复用并重跑历史资产。"""
    state, _script = _historical_rerun_state(tmp_path, "print('reused')\n")
    asset = state.spike_assets[0]
    spike_reuse.rerun_historical_asset(
        str(tmp_path),
        state,
        asset.relative_path,
        "跳过新穿刺后，本轮重跑历史资产仍得到稳定响应",
        timeout_seconds=10,
    )
    _write_historical_asset_traceability(tmp_path, state)
    state.spike_skipped = True
    state_mod.save_state(str(tmp_path), state)

    links = traceability_mod.collect_spike_asset_acceptance_links(
        str(tmp_path), state.workflow_id, state.topics
    )
    assert links == {asset.relative_path: ["复用历史穿刺/AC-01"]}


def test_abort_manifest_version_one_without_cleanup_plan_migrates_before_restore(
    tmp_path,
):
    """旧作废清单尚未开始恢复时，先补冻结计划再升级，不能因沿用版本号漏校验。"""
    state = _prepare_abort_project(tmp_path)
    registered_file = tmp_path / state.spike_assets[0].relative_path / "rerun.py"
    scratch_file = (
        tmp_path
        / ".workflow_loop"
        / "spike_tmp"
        / WORKFLOW_ID
        / "unfinished"
        / "notes.txt"
    )
    _write(registered_file)
    _write(scratch_file)

    ok, problems, manifest = rollback.preflight_abort(str(tmp_path), state)
    assert ok is True, problems
    assert manifest is not None
    manifest.pop("spike_cleanup_plan")
    manifest["version"] = 1
    manifest_path = (
        tmp_path
        / ".workflow_loop"
        / "rollback"
        / WORKFLOW_ID
        / "abort"
        / "manifest.json"
    )
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    ok, problems, migrated = rollback.preflight_abort(str(tmp_path), state)

    assert ok is True, problems
    assert migrated is not None
    assert migrated["version"] == rollback.ABORT_MANIFEST_VERSION
    assert migrated["spike_cleanup_plan"] == {
        "preserved": [state.spike_assets[0].relative_path],
        "remove": [f".workflow_loop/spike_tmp/{WORKFLOW_ID}/unfinished"],
    }


def test_abort_manifest_without_cleanup_plan_cannot_migrate_after_restore_started(
    tmp_path,
):
    """旧清单已有恢复进度时不能事后补造清理边界，必须保留现场并明确失败。"""
    state = _prepare_abort_project(tmp_path)
    _write(tmp_path / state.spike_assets[0].relative_path / "rerun.py")
    ok, problems, manifest = rollback.preflight_abort(str(tmp_path), state)
    assert ok is True, problems
    assert manifest is not None
    manifest.pop("spike_cleanup_plan")
    manifest["version"] = 1
    manifest["items"][0]["status"] = "restoring"
    manifest["items"][0]["attempts"] = 1
    manifest["items"][0]["observed_before_restore"] = {
        "kind": "file",
        "exists": True,
        "content_hash": "0" * 64,
        "mode": 420,
    }
    manifest_path = (
        tmp_path
        / ".workflow_loop"
        / "rollback"
        / WORKFLOW_ID
        / "abort"
        / "manifest.json"
    )
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    ok, problems, migrated = rollback.preflight_abort(str(tmp_path), state)

    assert ok is False
    assert migrated is None
    assert any(
        "已经开始恢复" in problem and "不能事后补造" in problem
        for problem in problems
    ), problems
