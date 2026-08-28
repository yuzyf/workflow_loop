import json
import re
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from workflow_loop import PRODUCT_NAME, __version__
from workflow_loop import cli as cli_mod
from workflow_loop import installer as installer_mod
from workflow_loop.state import WorkflowState, load_state, save_state


WORKFLOW_CMD = [sys.executable, "-m", "workflow_loop.cli"]
START_TOPIC = "用户提出需求后工作流正确开始或继续并逐环节确认"
RETURN_TOPIC = "返回上游或整轮作废后状态与项目内容正确恢复"
DONE_TOPIC = "主题验收_全量回归和最终同步完成后正式收工"


def _run(args: list[str], cwd: Path):
    result = subprocess.run(
        WORKFLOW_CMD + args,
        cwd=cwd,
        capture_output=True,
        text=True,
        timeout=30,
    )
    return result.returncode, result.stdout, result.stderr


def _install_project(root: Path) -> None:
    token_path = root / ".install-token.json"
    token_path.write_text(
        json.dumps(
            {
                "product": PRODUCT_NAME,
                "version": __version__,
                "project_root": str(root.resolve()),
                "allowed_paths": sorted(installer_mod.PROJECT_WRITE_PATHS),
                "used": False,
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    code, out, err = _run(
        ["_install-project", "--transaction", str(token_path)], root
    )
    assert code == 0, f"installation failed: {out} {err}"


def test_start_without_intent_is_read_only(tmp_path):
    """Workflow-Test
    主题：用户提出需求后工作流正确开始或继续并逐环节确认
    测试项：TC-01 无工作意图的状态检查保持只读
    验收条件：AC-01 用户不用操作内部命令
    测试方式：自动化测试
    测试层级：命令测试
    测试目标：没有工作意图时只说明状态和下一步且不创建本轮状态
    测试入口：tests/test_commands.py::test_start_without_intent_is_read_only
    代码入口：workflow_loop.cli.cmd_start
    """
    _install_project(tmp_path)
    state_path = tmp_path / ".workflow_loop" / "state.json"

    code, out, err = _run(["start"], tmp_path)

    assert code == 0, err
    assert "当前没有进行中的工作轮次" in out
    assert "from_scratch" in out and "product_change" in out and "bugfix" in out
    assert "用户不需要" not in out or "AI" in out
    assert not state_path.exists()


def test_start_creates_one_run_and_refuses_to_overwrite_active_run(tmp_path):
    """Workflow-Test
    主题：用户提出需求后工作流正确开始或继续并逐环节确认
    测试项：TC-02 正确继续旧轮次或开始新轮次
    验收条件：AC-02 正确继续或开始轮次
    测试方式：自动化测试
    测试层级：命令测试
    测试目标：首次工作意图创建轮次而再次开工不覆盖进行中状态
    测试入口：tests/test_commands.py::test_start_creates_one_run_and_refuses_to_overwrite_active_run
    代码入口：workflow_loop.cli.cmd_start
    """
    _install_project(tmp_path)
    assert _run(["start", "--intent", "product_change"], tmp_path)[0] == 0
    first = load_state(str(tmp_path))

    code, out, _ = _run(["start", "--intent", "bugfix"], tmp_path)
    after = load_state(str(tmp_path))

    assert code == 1
    assert "有进行中 Run" in out
    assert after.workflow_id == first.workflow_id
    assert after.intent == "product_change"


def test_three_intents_produce_complete_project_specific_paths(tmp_path):
    """Workflow-Test
    主题：用户提出需求后工作流正确开始或继续并逐环节确认
    测试项：TC-03 三种工作意图生成完整路线
    验收条件：AC-03 环节路线符合目标和项目现状
    测试方式：自动化测试
    测试层级：集成测试
    测试目标：三种工作意图都包含计划实施测试验收和最终同步且按项目状态选择设计入口
    测试入口：tests/test_commands.py::test_three_intents_produce_complete_project_specific_paths
    代码入口：workflow_loop.path_composer.build_stage_path
    """
    expected_tail = [
        "acceptance_plan",
        "impl",
        "qa",
        "topic_acceptance",
        "regression_test",
        "overall_acceptance",
        "update_code_design",
    ]
    for intent in ("from_scratch", "product_change", "bugfix"):
        root = tmp_path / intent
        root.mkdir()
        _install_project(root)
        code, out, err = _run(["start", "--intent", intent], root)
        assert code == 0, f"{intent}: {out} {err}"
        state = load_state(str(root))
        assert state.stage_path[-len(expected_tail) :] == expected_tail
        assert state.intent == intent


def test_from_scratch_preflight_lists_scope_without_modifying_files(tmp_path):
    """Workflow-Test
    主题：用户提出需求后工作流正确开始或继续并逐环节确认
    测试项：TC-04 从零清场取消成功和失败恢复
    验收条件：AC-04 从零清场可恢复
    测试方式：自动化测试
    测试层级：命令测试
    测试目标：未确认清场时完整披露目录范围且不删除文件不创建状态
    测试入口：tests/test_commands.py::test_from_scratch_preflight_lists_scope_without_modifying_files
    代码入口：workflow_loop.cli.cmd_start
    """
    _install_project(tmp_path)
    custom = tmp_path / "spec" / "user.txt"
    custom.parent.mkdir()
    custom.write_text("keep", encoding="utf-8")

    code, out, err = _run(["start", "--intent", "from_scratch"], tmp_path)

    assert code == 0, err
    assert "删除命中的整个目录及其中全部内容" in out
    assert "本次尚未删除任何内容" in out
    assert custom.read_text(encoding="utf-8") == "keep"
    assert not (tmp_path / ".workflow_loop" / "state.json").exists()


def test_from_scratch_confirmation_cleans_declared_scope_and_starts(tmp_path):
    """Workflow-Test
    主题：用户提出需求后工作流正确开始或继续并逐环节确认
    测试项：TC-04 从零清场取消成功和失败恢复
    验收条件：AC-04 从零清场可恢复
    测试方式：自动化测试
    测试层级：命令测试
    测试目标：用户确认后只清理已披露过程产物并成功建立新轮次
    测试入口：tests/test_commands.py::test_from_scratch_confirmation_cleans_declared_scope_and_starts
    代码入口：workflow_loop.cli.cmd_start
    """
    _install_project(tmp_path)
    (tmp_path / "spec").mkdir()
    (tmp_path / "spec" / "old.md").write_text("old", encoding="utf-8")
    outside = tmp_path / "user.txt"
    outside.write_text("keep", encoding="utf-8")

    code, out, err = _run(
        ["start", "--intent", "from_scratch", "--confirm-clean"], tmp_path
    )

    assert code == 0, f"{out} {err}"
    assert "工作流启动" in out and "已清场" in out
    assert not (tmp_path / "spec").exists()
    assert outside.read_text(encoding="utf-8") == "keep"
    assert load_state(str(tmp_path)).run_status == "active"


def test_discuss_prints_ordered_material_paths_without_document_bodies(tmp_path):
    """Workflow-Test
    主题：用户提出需求后工作流正确开始或继续并逐环节确认
    测试项：TC-05 材料清单和变化失效
    验收条件：AC-05 每个环节先取得正确材料
    测试方式：自动化测试
    测试层级：命令测试
    测试目标：讨论命令只给出按顺序验证过的绝对路径和用途而不复制材料正文
    测试入口：tests/test_commands.py::test_discuss_prints_ordered_material_paths_without_document_bodies
    代码入口：workflow_loop.cli.cmd_discuss
    """
    _install_project(tmp_path)
    _run(["start", "--intent", "from_scratch"], tmp_path)

    code, out, err = _run(["discuss"], tmp_path)

    assert code == 0, err
    writing = str(
        tmp_path
        / ".workflow_loop"
        / "Standardized_Repository"
        / "global"
        / "document_writing.md"
    )
    lifecycle = str(
        tmp_path
        / ".workflow_loop"
        / "Standardized_Repository"
        / "global"
        / "workflow_lifecycle.md"
    )
    assert writing in out and lifecycle in out
    assert out.index(writing) < out.index(lifecycle)
    assert "按下列顺序用文件读取工具逐份读取全文" in out


def test_discuss_announces_impl_baseline_frozen_before_first_material_read(
    tmp_path,
    monkeypatch,
    capsys,
):
    """Workflow-Test
    主题：所有阶段门禁失败时一次指出全部真实原因和改法
    测试项：TC-06 首次实施讨论先说明基线已经冻结
    验收条件：AC-04 实施基线差异说清冻结时机、变化文件和处理方法
    测试方式：自动化测试
    测试层级：命令测试
    产品入口：`workflow discuss` 进入实施环节
    测试入口：`tests/test_commands.py::test_discuss_announces_impl_baseline_frozen_before_first_material_read`
    代码入口：`src/workflow_loop/cli.py::cmd_discuss`
    准备数据：建立首次进入实施环节且已经保存登记快照和完整实施范围快照的工作流状态。
    执行动作：执行实施环节讨论命令。
    关键断言：在第一份材料被读取前只提示一次“实施前基线已冻结”，并说明基线不会被 `workflow discuss` 或 Git 提交重写；重复讨论不重复提示。
    预期证据：结构化报告需精确匹配该测试入口，实际执行数为 1，跳过数、失败数和错误数均为 0；断言需保留提示顺序、含义和只展示一次的事实。
    """
    stage_state = cli_mod.state_mod.StageState(
        status="in_progress",
    )
    workflow_state = WorkflowState(
        workflow_id="impl-entry-baseline",
        intent="product_change",
        run_status="active",
        current_stage="impl",
        stage_path=["impl"],
        stages={"impl": stage_state},
    )

    class ImplStrategy:
        def name(self):
            return "impl"

        def instruction(self):
            return "先核对实施计划"

        def materials(self):
            return []

        def artifact_paths(self):
            return []

        def prompt_doc_path(self):
            return None

        def standard_doc_path(self):
            return None

        def additional_standard_doc_paths(self):
            return []

    checklist = SimpleNamespace(
        fingerprint="impl-materials",
        role_title="",
        role_description="",
        task_text="先核对实施计划",
        materials=[],
        placeholders=[],
    )
    saved_states: list[WorkflowState] = []

    monkeypatch.setattr(cli_mod, "resolve_project_root", lambda: str(tmp_path))
    monkeypatch.setattr(
        cli_mod.state_mod,
        "load_state",
        lambda _root: workflow_state,
    )
    monkeypatch.setattr(
        cli_mod.state_mod,
        "save_state",
        lambda _root, state: saved_states.append(state),
    )
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
    monkeypatch.setattr(cli_mod, "clear_completed_material_recovery", lambda _root, _state: False)
    monkeypatch.setattr(cli_mod, "_stage_role_doc", lambda _stage: None)
    monkeypatch.setattr(
        cli_mod,
        "build_stage_path",
        lambda _intent, _root: [ImplStrategy()],
    )
    monkeypatch.setattr(
        cli_mod,
        "get_stage_strategy",
        lambda _name, _state, _instances: ImplStrategy(),
    )
    monkeypatch.setattr(
        cli_mod.stage_materials_mod,
        "build_checklist",
        lambda *_args: checklist,
    )
    monkeypatch.setattr(
        cli_mod.verification_mod,
        "compute_registered_file_snapshot",
        lambda _root, *, scope: {"scope": scope, "files": []},
    )
    monkeypatch.setattr(
        cli_mod,
        "compute_non_test_code_snapshot_hash",
        lambda _root: "impl-entry-code-hash",
    )
    monkeypatch.setattr(cli_mod.journal_mod, "append_entry", lambda *_args, **_kwargs: None)

    # 这一步模拟上游第三道门推进到 impl 时同步冻结的事实。
    assert cli_mod.ensure_impl_recovery_baseline(str(tmp_path), workflow_state) is True
    assert stage_state.code_baseline_hash == "impl-entry-code-hash"

    cli_mod.cmd_discuss(SimpleNamespace())
    first_output = capsys.readouterr().out

    assert "【代码门禁过程】" in first_output
    assert "impl-entry-code-hash" in first_output
    assert "不是允许修改的文件白名单" in first_output
    assert "额外文件可以直接修改" in first_output
    assert cli_mod.IMPL_CODE_BASELINE_NOTICE_PENDING_KEY not in workflow_state.meta
    assert saved_states

    cli_mod.cmd_discuss(SimpleNamespace())
    second_output = capsys.readouterr().out

    assert "【实施前代码基线】" not in second_output


def test_confirmed_gate_reports_unreadable_credential_comparison_without_clearing_it(
    tmp_path,
    monkeypatch,
    capsys,
):
    """第三道门无法读取凭据时，保留原凭据并给出可重试的确认命令。"""
    stage_state = cli_mod.state_mod.StageState(
        status="in_progress",
        discussion_material_hash="materials",
    )
    stage_state.gate.discussion_complete = True
    stage_state.gate.code_validated = True
    original_credential = object()
    stage_state.validation_credential = original_credential
    workflow_state = WorkflowState(
        workflow_id="credential-io-error",
        intent="product_change",
        run_status="active",
        current_stage="spec",
        stage_path=["spec"],
        stages={"spec": stage_state},
    )
    saved_states: list[WorkflowState] = []
    journal_entries: list[tuple[tuple, dict]] = []

    monkeypatch.setattr(cli_mod, "resolve_project_root", lambda: str(tmp_path))
    monkeypatch.setattr(
        cli_mod.state_mod,
        "load_state",
        lambda _root: workflow_state,
    )
    monkeypatch.setattr(
        cli_mod.state_mod,
        "save_state",
        lambda _root, state: saved_states.append(state),
    )
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
    monkeypatch.setattr(cli_mod, "clear_completed_material_recovery", lambda _root, _state: False)
    monkeypatch.setattr(cli_mod, "build_stage_path", lambda _intent, _root: [object()])
    monkeypatch.setattr(
        cli_mod,
        "get_stage_strategy",
        lambda _name, _state, _instances: object(),
    )
    monkeypatch.setattr(cli_mod, "compute_stage_material_hash", lambda _root, _stage: "materials")
    monkeypatch.setattr(
        cli_mod.verification_mod,
        "compare_validation_credential_report",
        lambda *_args: (_ for _ in ()).throw(OSError("凭据关联文件不可读取")),
    )
    monkeypatch.setattr(
        cli_mod.journal_mod,
        "append_entry",
        lambda *args, **kwargs: journal_entries.append((args, kwargs)),
    )

    cli_mod.cmd_gate(
        SimpleNamespace(
            stage="spec",
            rebaseline=False,
            prepare_code=False,
            accept_existing_code=False,
            accept_existing_test_code=False,
            skip=False,
            discuss_done=False,
            confirmed=True,
        )
    )
    output = capsys.readouterr().out

    assert "用户确认前凭据比较失败" in output
    assert "无法比较第二道门校验凭据：凭据关联文件不可读取" in output
    assert output.count("下一步命令: workflow gate spec --confirmed") == 1
    assert "Traceback" not in output
    assert stage_state.gate.code_validated is True
    assert stage_state.validation_credential is original_credential
    assert saved_states == []
    assert journal_entries == []


def test_three_gates_advance_in_the_required_order(tmp_path):
    """Workflow-Test
    主题：用户提出需求后工作流正确开始或继续并逐环节确认
    测试项：TC-06 三道门顺序和中文说明
    验收条件：AC-06 三道门按含义和顺序推进
    测试方式：自动化测试 + 人工验收
    测试层级：命令测试
    测试目标：按读取材料、确认讨论、校验产物、用户确认的顺序进入下一阶段
    测试入口：tests/test_commands.py::test_three_gates_advance_in_the_required_order
    代码入口：workflow_loop.cli.cmd_gate
    """
    _install_project(tmp_path)
    _run(["start", "--intent", "from_scratch"], tmp_path)

    code, out, err = _run(["discuss"], tmp_path)
    assert code == 0, err
    assert "按下列顺序用文件读取工具逐份读取全文" in out

    code, out, err = _run(["gate", "spec", "--discuss-done"], tmp_path)
    assert code == 0, err
    assert "讨论完毕" in out
    assert "下一步" in out

    spec_dir = tmp_path / "spec"
    spec_dir.mkdir(exist_ok=True)
    (spec_dir / "产品总说明.md").write_text(
        "# 产品总说明\n\n[一次安装](./功能_一次安装.md)\n",
        encoding="utf-8",
    )
    (spec_dir / "功能_一次安装.md").write_text(
        "# 【功能】一次安装\n",
        encoding="utf-8",
    )

    code, out, err = _run(["gate", "spec"], tmp_path)
    assert code == 0, err
    assert "代码校验通过" in out
    assert "用户" in out and "确认" in out

    code, out, err = _run(["gate", "spec", "--confirmed"], tmp_path)
    assert code == 0, err
    assert "进入 spike" in out


def _state_at_impl(root: Path) -> WorkflowState:
    _install_project(root)
    _run(["start", "--intent", "product_change"], root)
    state = load_state(str(root))
    state.current_stage = "impl"
    state.topics = ["安装"]
    for name in state.stage_path:
        state.stages[name].status = "pending"
    state.stages["impl"].status = "in_progress"
    save_state(str(root), state)
    return state


def test_return_requires_explicit_directly_affected_topic_scope(tmp_path):
    """Workflow-Test
    主题：返回上游或整轮作废后状态与项目内容正确恢复
    测试项：TC-01 返回前明确问题目标和影响范围
    验收条件：AC-01 先调查并确认返回目标
    测试方式：自动化测试 + 人工验收
    测试层级：命令测试
    测试目标：已有主题时缺少明确主题范围的返回请求保持状态不变
    测试入口：tests/test_commands.py::test_return_requires_explicit_directly_affected_topic_scope
    代码入口：workflow_loop.cli.cmd_return
    """
    before = _state_at_impl(tmp_path)

    code, out, err = _run(
        ["return", "--to", "acceptance_plan", "--reason", "验收计划需修正"],
        tmp_path,
    )
    after = load_state(str(tmp_path))

    assert code == 0, err
    assert "必须明确写出直接受影响的主题" in out
    assert "门禁: 退回请求检查" in out
    assert out.count("下一步命令: workflow status") == 1
    assert after.current_stage == before.current_stage
    assert after.recovery.return_target is None


def test_return_invalid_target_reports_structured_reason_and_one_safe_next_command(tmp_path):
    """退回目标不在真实路径时，AI 能看到原因并先读取当前路径。"""
    _state_at_impl(tmp_path)

    code, out, err = _run(
        ["return", "--to", "not-a-stage", "--topic", "安装", "--reason", "原因"],
        tmp_path,
    )

    assert code == 0, err
    assert "目标阶段不在当前工作流的实际路径中: not-a-stage" in out
    assert "本轮路径:" in out
    assert "门禁: 退回请求检查" in out
    assert out.count("下一步命令: workflow status") == 1


def test_return_accepts_only_real_earlier_stage(tmp_path):
    """Workflow-Test
    主题：返回上游或整轮作废后状态与项目内容正确恢复
    测试项：TC-02 只允许返回本轮真实上游
    验收条件：AC-02 返回目标必须真实有效
    测试方式：自动化测试
    测试层级：命令测试
    测试目标：当前环节、后续环节和不存在环节都不能成为返回目标
    测试入口：tests/test_commands.py::test_return_accepts_only_real_earlier_stage
    代码入口：workflow_loop.cli.cmd_return
    """
    _state_at_impl(tmp_path)

    current = _run(
        ["return", "--to", "impl", "--topic", "安装", "--reason", "原因"], tmp_path
    )
    future = _run(
        [
            "return",
            "--to",
            "qa",
            "--topic",
            "安装",
            "--reason",
            "原因",
        ],
        tmp_path,
    )
    missing = _run(
        ["return", "--to", "not-a-stage", "--topic", "安装", "--reason", "原因"],
        tmp_path,
    )

    assert "只能退回当前阶段之前的阶段" in current[1]
    assert "只能退回当前阶段之前的阶段" in future[1]
    assert "不在当前工作流的实际路径" in missing[1]
    assert load_state(str(tmp_path)).current_stage == "impl"


def test_done_refuses_incomplete_run(tmp_path):
    """Workflow-Test
    主题：主题验收、全量回归和最终同步完成后正式收工
    测试项：TC-07 正式收工不重复确认且保留正式产物
    验收条件：AC-07 正式收工不重复确认
    测试方式：自动化测试
    测试层级：命令测试
    测试目标：最终阶段尚未确认时正式收工保持轮次进行中
    测试入口：tests/test_commands.py::test_done_refuses_incomplete_run
    代码入口：workflow_loop.cli.cmd_done
    """
    _install_project(tmp_path)
    _run(["start", "--intent", "product_change"], tmp_path)

    code, out, err = _run(["done"], tmp_path)

    assert code == 1, err
    assert "还有未完成的 stage" in out
    assert load_state(str(tmp_path)).run_status == "active"


def _prepare_accept_existing_command(
    tmp_path,
    monkeypatch,
    *,
    actual_result: tuple[bool, str] = (True, "实际改动和实施记录已核对"),
):
    stage_state = cli_mod.state_mod.StageState(
        status="in_progress",
        discussion_material_hash="materials",
        code_baseline_hash="original-baseline",
    )
    stage_state.gate.discussion_complete = True
    workflow_state = WorkflowState(
        workflow_id="wf",
        intent="product_change",
        run_status="active",
        current_stage="impl",
        stage_path=["impl"],
        topics=["上传文件"],
        stages={"impl": stage_state},
    )

    class ImplStrategy:
        def validate_implementation_records(self, _root, _state):
            return True, "实施文档和追踪关系完整", ["上传文件"]

    saved_states: list[WorkflowState] = []
    journal_entries: list[tuple[object, ...]] = []
    monkeypatch.setattr(cli_mod, "resolve_project_root", lambda: str(tmp_path))
    monkeypatch.setattr(cli_mod.state_mod, "load_state", lambda _root: workflow_state)
    monkeypatch.setattr(
        cli_mod.state_mod,
        "save_state",
        lambda _root, state: saved_states.append(state),
    )
    monkeypatch.setattr(cli_mod, "refuse_if_pending_start_transaction", lambda _root: None)
    monkeypatch.setattr(cli_mod, "ensure_stage_path_current", lambda _root, _state: False)
    monkeypatch.setattr(
        cli_mod,
        "restore_recovery_context_from_journal",
        lambda _root, _state: False,
    )
    monkeypatch.setattr(cli_mod, "clear_completed_material_recovery", lambda _root, _state: None)
    monkeypatch.setattr(cli_mod, "ensure_impl_recovery_baseline", lambda _root, _state: False)
    monkeypatch.setattr(cli_mod, "build_stage_path", lambda _intent, _root: [])
    monkeypatch.setattr(
        cli_mod,
        "get_stage_strategy",
        lambda _name, _state, _instances: ImplStrategy(),
    )
    monkeypatch.setattr(cli_mod, "compute_stage_material_hash", lambda _root, _stage: "materials")
    monkeypatch.setattr(
        cli_mod.rollback_mod,
        "validate_actual_implementation_changes",
        lambda _root, _state: actual_result,
    )
    monkeypatch.setattr(
        cli_mod,
        "compute_non_test_code_snapshot_hash",
        lambda _root: "current-code-hash",
    )
    monkeypatch.setattr(
        cli_mod.journal_mod,
        "append_entry",
        lambda *args, **kwargs: journal_entries.append((args, kwargs)),
    )
    args = SimpleNamespace(
        stage="impl",
        rebaseline=False,
        prepare_code=False,
        accept_existing_code=True,
        accept_existing_test_code=False,
        skip=False,
        discuss_done=False,
        confirmed=False,
    )
    return workflow_state, stage_state, saved_states, journal_entries, args


def test_accept_existing_code_accepts_actual_changes_with_complete_evidence(
    tmp_path,
    monkeypatch,
    capsys,
):
    """既有代码确认不再因为实际文件变化而要求重设基线。"""
    _, stage_state, saved_states, journal_entries, args = _prepare_accept_existing_command(
        tmp_path,
        monkeypatch,
        actual_result=(True, "实际改动包含 src/upload.py 和 tests/test_upload.py，记录完整"),
    )

    cli_mod.cmd_gate(args)
    output = capsys.readouterr().out

    assert "既有实施代码已确认" in output
    assert stage_state.existing_code_accepted_hash == "current-code-hash"
    assert len(saved_states) == 1
    assert len(journal_entries) == 1


def test_accept_existing_code_rejects_missing_actual_evidence_without_state_change(
    tmp_path,
    monkeypatch,
    capsys,
):
    """实际改动缺少理由或验收关联时，既有代码确认保持原样。"""
    _, stage_state, saved_states, journal_entries, args = _prepare_accept_existing_command(
        tmp_path,
        monkeypatch,
        actual_result=(
            False,
            "1. 实际改动文件尚未在实施记录中说明：src/missing.py；请补充修改理由、对应 AC 编号和测试证据\n"
            "2. 实施记录列出但未检测到进入 impl 后的实际变化：src/stale.py",
        ),
    )

    cli_mod.cmd_gate(args)
    output = capsys.readouterr().out

    assert "实际改动文件尚未在实施记录中说明" in output
    assert "实施记录列出但未检测到" in output
    assert stage_state.code_baseline_hash == "original-baseline"
    assert stage_state.existing_code_accepted_hash is None
    assert saved_states == []
    assert journal_entries == []


def test_accept_existing_code_preserves_observation_snapshot(
    tmp_path,
    monkeypatch,
    capsys,
):
    """合法既有代码确认只写确认哈希，不覆盖原有观察快照。"""
    _, stage_state, saved_states, journal_entries, args = _prepare_accept_existing_command(
        tmp_path,
        monkeypatch,
    )

    cli_mod.cmd_gate(args)
    output = capsys.readouterr().out

    assert "既有实施代码已确认" in output
    assert stage_state.code_baseline_hash == "original-baseline"
    assert stage_state.existing_code_accepted_hash == "current-code-hash"
    assert len(saved_states) == 1
    assert len(journal_entries) == 1


def test_material_change_reconfirms_the_new_gate_state(
    tmp_path,
    monkeypatch,
    capsys,
):
    """材料变化清门后必须更新新 GateState，不能继续写已经失效的旧对象。"""

    stage_state = cli_mod.state_mod.StageState(
        status="in_progress",
        discussion_material_hash="old-materials",
        plan_confirmed_hash="old-plan",
        code_baseline_hash="old-code",
    )
    stage_state.gate.discussion_complete = True
    workflow_state = WorkflowState(
        workflow_id="wf",
        intent="product_change",
        run_status="active",
        current_stage="impl",
        stage_path=["impl"],
        stage_path_version=2,
        topics=["上传文件"],
        stages={"impl": stage_state},
    )

    class ImplStrategy:
        def discussion_validate(self, _root, _state):
            return True, "代码计划完整"

    journal_entries: list[tuple[tuple, dict]] = []
    monkeypatch.setattr(cli_mod, "resolve_project_root", lambda: str(tmp_path))
    monkeypatch.setattr(cli_mod.state_mod, "load_state", lambda _root: workflow_state)
    monkeypatch.setattr(cli_mod.state_mod, "save_state", lambda _root, _state: None)
    monkeypatch.setattr(cli_mod, "refuse_if_pending_start_transaction", lambda _root: None)
    monkeypatch.setattr(cli_mod, "ensure_stage_path_current", lambda _root, _state: False)
    monkeypatch.setattr(
        cli_mod,
        "restore_recovery_context_from_journal",
        lambda _root, _state: False,
    )
    monkeypatch.setattr(cli_mod, "clear_completed_material_recovery", lambda _root, _state: None)
    monkeypatch.setattr(cli_mod, "ensure_impl_recovery_baseline", lambda _root, _state: False)
    monkeypatch.setattr(cli_mod, "build_stage_path", lambda _intent, _root: [])
    monkeypatch.setattr(
        cli_mod,
        "get_stage_strategy",
        lambda _name, _state, _instances: ImplStrategy(),
    )
    monkeypatch.setattr(cli_mod, "compute_stage_material_hash", lambda _root, _stage: "new-materials")
    monkeypatch.setattr(cli_mod, "_has_loaded_stage_materials", lambda _root, _state, _stage: True)
    monkeypatch.setattr(cli_mod, "ensure_stage_artifact_baseline", lambda _root, _state, _stage: False)
    monkeypatch.setattr(cli_mod.rollback_mod, "compute_plan_hash", lambda _root, _topics: "new-plan")
    monkeypatch.setattr(cli_mod, "compute_non_test_code_snapshot_hash", lambda _root: "new-code")
    monkeypatch.setattr(
        cli_mod.journal_mod,
        "append_entry",
        lambda *args, **kwargs: journal_entries.append((args, kwargs)),
    )
    args = SimpleNamespace(
        stage="impl",
        rebaseline=False,
        prepare_code=False,
        accept_existing_code=False,
        accept_existing_test_code=False,
        skip=False,
        discuss_done=True,
        confirmed=False,
    )

    cli_mod.cmd_gate(args)
    output = capsys.readouterr().out

    assert stage_state.gate.discussion_complete is True
    assert stage_state.discussion_material_hash == "new-materials"
    assert stage_state.plan_confirmed_hash == "new-plan"
    assert stage_state.code_baseline_hash is None
    assert "impl 讨论完毕" in output
    assert "实施计划已重新确认" not in output
    assert any(entry[0][1] == "门禁讨论完毕" for entry in journal_entries)


def test_done_marks_completed_and_preserves_formal_documents(tmp_path):
    """Workflow-Test
    主题：主题验收、全量回归和最终同步完成后正式收工
    测试项：TC-07 正式收工不重复确认且保留正式产物
    验收条件：AC-07 正式收工不重复确认
    测试方式：自动化测试
    测试层级：命令测试
    测试目标：全部阶段完成后直接结束轮次并只清理临时回退副本
    测试入口：tests/test_commands.py::test_done_marks_completed_and_preserves_formal_documents
    代码入口：workflow_loop.cli.cmd_done
    """
    _install_project(tmp_path)
    formal = tmp_path / "spec" / "产品总说明.md"
    formal.parent.mkdir()
    formal.write_text("formal", encoding="utf-8")
    start_code, start_out, start_err = _run(
        ["start", "--intent", "product_change"], tmp_path
    )
    assert start_code == 0, start_out + start_err
    state = load_state(str(tmp_path))
    state.current_stage = "completed"
    for stage_state in state.stages.values():
        stage_state.status = "done"
        stage_state.gate.discussion_complete = True
        stage_state.gate.code_validated = True
        stage_state.gate.user_confirmed = True
    save_state(str(tmp_path), state)

    code, out, err = _run(["done"], tmp_path)

    assert code == 0, err
    completed = load_state(str(tmp_path))
    assert completed.run_status == "completed"
    assert completed.ended_at
    assert formal.read_text(encoding="utf-8") == "formal"
    assert "工作流完成" in out


def _write_legacy_order_run(root: Path):
    """建立含旧测试和验收事实的旧顺序活动轮次。"""
    _install_project(root)
    code, out, err = _run(["start", "--intent", "product_change"], root)
    assert code == 0, out + err
    state = load_state(str(root))
    topic = "旧顺序迁移主题"
    state.topics = [topic]
    legacy_path: list[str] = []
    for stage_name in state.stage_path:
        if stage_name == "spike":
            legacy_path.append("revise_code_design")
        if stage_name == "qa":
            legacy_path.extend(("test_plan", "test_code", "test_execution"))
            continue
        legacy_path.append(stage_name)
    state.stage_path = legacy_path
    state.stage_path_version = 0
    for stage_name in ("revise_code_design", "test_plan", "test_code", "test_execution"):
        state.stages.setdefault(stage_name, cli_mod.state_mod.StageState())
    state.stages.pop("qa", None)
    state.stage_path.remove("test_plan")
    state.stage_path.insert(state.stage_path.index("impl"), "test_plan")
    state.current_stage = "impl"
    for stage_name, stage_state in state.stages.items():
        stage_state.status = "pending"
        stage_state.gate = cli_mod.state_mod.GateState()
    for stage_name in state.stage_path[: state.stage_path.index("impl")]:
        state.stages[stage_name].status = "done"
        state.stages[stage_name].gate = cli_mod.state_mod.GateState(True, True, True)
    state.stages["impl"].status = "in_progress"
    state.stages["impl"].gate.discussion_complete = True
    state.stages["test_execution"].test_tasks = {
        topic: {
            "TC-01": cli_mod.state_mod.TestTaskState(
                command=["pytest", "tests/test_old.py"],
                status="passed",
            )
        }
    }
    state.stages["topic_acceptance"].acceptance_records = {
        topic: {
            "AC-01": cli_mod.state_mod.AcceptanceCriterionRecord(
                topic=topic,
                criterion_id="AC-01",
                method="自动化测试",
                result="passed",
            )
        }
    }
    state.regression_test = cli_mod.state_mod.RegressionTestState(
        entry=["pytest"],
        command=["pytest"],
        status="passed",
        exit_code=0,
        record_id="REG-old",
    )
    state.verification.impl_hash = "impl-old"
    state.verification.test_plan_hash = "plan-old"
    state.verification.test_code_hash = "test-code-old"
    state.verification.test_result_hash = "test-result-old"
    state.verification.acceptance_result_hash = "acceptance-result-old"
    state.verification.regression_test_result_hash = "regression-old"
    save_state(str(root), state)
    cli_mod.journal_mod.append_entry(
        str(root),
        "旧轮次测试完成",
        "workflow.py",
        workflow_id=state.workflow_id,
    )

    paths = cli_mod.topic_mod.topic_paths(str(root), topic)
    for key in ("test_result", "acceptance_result"):
        result_path = root / paths[key]
        result_path.parent.mkdir(parents=True, exist_ok=True)
        result_path.write_text(f"old {key}\n", encoding="utf-8")

    trace_path = root / cli_mod.artifact_paths_mod.TRACEABILITY_DOC
    headers = cli_mod.traceability_mod.TRACEABILITY_HEADERS
    row = [
        "[需求](./spec/产品总说明.md)",
        f"[{topic}](./{paths['acceptance_plan']})",
        f"[AC-01](./{paths['acceptance_plan']}#ac-01)",
        "本轮未执行穿刺，无可复用资产",
        f"[TC-01](./{paths['test_plan']}#tc-01)",
        f"[实施计划](./{paths['impl_doc']})",
        f"[实施记录](./{paths['impl_doc']})",
        f"[测试结果](./{paths['test_result']})<br>最终全量回归：通过（机器记录 REG-old）",
        f"[验收结果](./{paths['acceptance_result']})<br>整体验收：用户已确认",
        "[代码设计](./spec/代码架构设计.md)",
    ]
    trace_path.write_text(
        "# 需求交付追踪表\n\n"
        f"## {state.workflow_id}\n\n"
        + "| " + " | ".join(headers) + " |\n"
        + "| " + " | ".join(["---"] * len(headers)) + " |\n"
        + "| " + " | ".join(row) + " |\n",
        encoding="utf-8",
    )
    return state, paths


def _migration_bytes(root: Path, paths: dict[str, str]) -> dict[str, bytes | None]:
    relative_paths = [
        ".workflow_loop/state.json",
        ".workflow_loop/journal.jsonl",
        cli_mod.artifact_paths_mod.TRACEABILITY_DOC,
        paths["test_result"],
        paths["acceptance_result"],
    ]
    return {
        relative_path: (
            (root / relative_path).read_bytes()
            if (root / relative_path).is_file()
            else None
        )
        for relative_path in relative_paths
    }


def test_legacy_order_status_preview_is_zero_write(tmp_path):
    _state, paths = _write_legacy_order_run(tmp_path)
    before = _migration_bytes(tmp_path, paths)

    code, out, err = _run(["status"], tmp_path)

    assert code == 0, out + err
    assert "旧顺序迁移预览" in out
    assert "本次只读，写入 0 个文件" in out
    assert "保留：已确认产品设计、验收计划、实施事实和所有正式文件" in out
    assert _migration_bytes(tmp_path, paths) == before


def test_legacy_order_migration_clears_old_facts_and_is_idempotent(tmp_path):
    state, paths = _write_legacy_order_run(tmp_path)

    assert cli_mod.ensure_stage_path_current(str(tmp_path), state) is True

    migrated = load_state(str(tmp_path))
    assert migrated.current_stage == "impl"
    assert migrated.stage_path.index("impl") < migrated.stage_path.index("qa")
    assert migrated.stages["qa"].test_tasks == {}
    assert migrated.stages["topic_acceptance"].acceptance_records == {}
    assert {"test_plan", "test_code", "test_execution"} <= set(
        migrated.legacy_stage_facts
    )
    assert migrated.regression_test == cli_mod.state_mod.RegressionTestState()
    assert migrated.verification.test_plan_hash is None
    assert migrated.verification.test_result_hash is None
    assert migrated.verification.acceptance_result_hash is None
    assert migrated.verification.regression_test_result_hash is None
    assert not (tmp_path / paths["test_result"]).exists()
    assert not (tmp_path / paths["acceptance_result"]).exists()
    trace = (tmp_path / cli_mod.artifact_paths_mod.TRACEABILITY_DOC).read_text(
        encoding="utf-8"
    )
    assert "待制定 | 待制定 | 待执行 | 待执行 | 待执行 | 待更新" in trace
    assert sum(
        entry.get("action") == "阶段路径迁移"
        for entry in cli_mod.journal_mod.read_all(str(tmp_path))
    ) == 1

    before_second_call = _migration_bytes(tmp_path, paths)
    assert cli_mod.ensure_stage_path_current(str(tmp_path), migrated) is False
    assert _migration_bytes(tmp_path, paths) == before_second_call


@pytest.mark.parametrize("failed_step", ["save_state", "journal"])
def test_legacy_order_migration_failure_restores_every_original_byte(
    tmp_path,
    monkeypatch,
    failed_step,
):
    state, paths = _write_legacy_order_run(tmp_path)
    original_path = list(state.stage_path)
    before = _migration_bytes(tmp_path, paths)

    if failed_step == "save_state":
        original_save = cli_mod.state_mod.save_state

        def fail_after_save(project_root, workflow_state):
            original_save(project_root, workflow_state)
            raise OSError("injected save failure")

        monkeypatch.setattr(cli_mod.state_mod, "save_state", fail_after_save)
    else:
        original_append = cli_mod.journal_mod.append_entry

        def fail_after_append(project_root, action, actor, **kwargs):
            original_append(project_root, action, actor, **kwargs)
            raise OSError("injected journal failure")

        monkeypatch.setattr(cli_mod.journal_mod, "append_entry", fail_after_append)

    with pytest.raises(cli_mod.StagePathMigrationError, match="迁移失败"):
        cli_mod.ensure_stage_path_current(str(tmp_path), state)

    assert state.stage_path == original_path
    assert _migration_bytes(tmp_path, paths) == before


def _write_link_repair_fixture(root: Path, *, unresolved: bool = False) -> Path:
    _install_project(root)
    spec_dir = root / "spec"
    spec_dir.mkdir(exist_ok=True)
    missing_link = "\n[缺失](./功能_缺失.md)\n" if unresolved else ""
    (spec_dir / "产品总说明.md").write_text(
        f"[规则](./功能_目标.md#ac-01)\n{missing_link}",
        encoding="utf-8",
    )
    target = spec_dir / "功能_目标.md"
    target.write_text("### AC-01：可检查规则\n正文\n", encoding="utf-8")
    return target


def test_repair_links_preview_is_zero_write_and_lists_every_unresolved_issue(tmp_path):
    target = _write_link_repair_fixture(tmp_path, unresolved=True)
    target_before = target.read_bytes()
    project_path = tmp_path / ".workflow_loop" / "project.json"
    project_before = project_path.read_bytes()

    code, out, err = _run(["repair-links"], tmp_path)

    assert code == 0, out + err
    assert re.search(r"预览哈希: [0-9a-f]{64}", out)
    assert "可自动修复: 1 个定位，涉及 1 个文件" in out
    assert "不可自动修复: 1 个" in out
    assert "链接 './功能_缺失.md'" in out
    assert "目标不是现有普通文件" in out
    assert "预览写入: 0 个正式文档" in out
    assert target.read_bytes() == target_before
    assert project_path.read_bytes() == project_before
    assert not (tmp_path / ".workflow_loop" / "state.json").exists()
    assert not (tmp_path / ".workflow_loop" / "link_repair").exists()


def test_repair_links_wrong_hash_fails_without_writing(tmp_path):
    target = _write_link_repair_fixture(tmp_path)
    target_before = target.read_bytes()
    project_path = tmp_path / ".workflow_loop" / "project.json"
    project_before = project_path.read_bytes()

    code, out, err = _run(
        ["repair-links", "--apply", "0" * 64],
        tmp_path,
    )

    assert code == 1, out + err
    assert "预览已经漂移" in out
    assert "整批零写入" in out
    assert "下一步命令: workflow repair-links" in out
    assert target.read_bytes() == target_before
    assert project_path.read_bytes() == project_before
    assert not (tmp_path / ".workflow_loop" / "state.json").exists()
    assert not (tmp_path / ".workflow_loop" / "link_repair").exists()


def test_repair_links_matching_hash_applies_only_confirmed_anchor(tmp_path):
    target = _write_link_repair_fixture(tmp_path)
    project_path = tmp_path / ".workflow_loop" / "project.json"
    start_code, start_out, start_err = _run(
        ["start", "--intent", "product_change"], tmp_path
    )
    assert start_code == 0, start_out + start_err
    project_before = project_path.read_bytes()
    workflow_state = load_state(str(tmp_path))
    state_path = tmp_path / ".workflow_loop" / "state.json"
    state_before = state_path.read_bytes()
    preview_code, preview_out, preview_err = _run(["repair-links"], tmp_path)
    assert preview_code == 0, preview_out + preview_err
    preview_hash = re.search(r"预览哈希: ([0-9a-f]{64})", preview_out)
    assert preview_hash is not None

    code, out, err = _run(
        ["repair-links", "--apply", preview_hash.group(1)],
        tmp_path,
    )

    assert code == 0, out + err
    assert "实际修改文件: 1 个" in out
    assert "spec/功能_目标.md" in out
    assert "剩余不可自动修复: 0 个" in out
    assert target.read_text(encoding="utf-8").startswith(
        '<a id="ac-01"></a>\n### AC-01：可检查规则'
    )
    assert project_path.read_bytes() == project_before
    assert state_path.read_bytes() == state_before
    assert f"`workflow gate {workflow_state.current_stage}`" in out
    assert not (tmp_path / ".workflow_loop" / "link_repair").exists()


def test_gate_reports_link_and_stage_errors_without_running_regression(
    tmp_path,
    monkeypatch,
):
    calls = {"stage": 0, "regression": 0}

    class StageWithIndependentError:
        def code_validate(self, project_root):
            calls["stage"] += 1
            return (
                False,
                "spec/代码架构设计.md 第 20 行；代码位置列；"
                "原值为中文说明；预期项目内真实代码文件",
            )

    def run_regression(project_root, workflow_state):
        calls["regression"] += 1
        return True, "不应执行"

    monkeypatch.setattr(
        cli_mod.markdown_links_mod,
        "validate_managed_markdown_links",
        lambda project_root: (
            False,
            "受管正式文档存在 2 个链接问题：\n"
            "1. 来源 spec/产品总说明.md:3；链接 './功能_一.md#ac-01'；"
            "目标 spec/功能_一.md；原因：缺少完全一致的显式 HTML id\n"
            "2. 来源 spec/产品总说明.md:4；链接 './功能_缺失.md'；"
            "目标 spec/功能_缺失.md；原因：目标不是现有普通文件",
        ),
    )
    monkeypatch.setattr(cli_mod.test_runner_mod, "run_final_regression", run_regression)
    workflow_state = WorkflowState(
        workflow_id="link-gate-order",
        intent="product_change",
        run_status="active",
    )

    passed, detail = cli_mod.validate_stage_output(
        str(tmp_path),
        workflow_state,
        "regression_test",
        StageWithIndependentError(),
    )

    assert not passed
    assert calls == {"stage": 1, "regression": 0}
    assert "门禁: 代码校验（链接、阶段事实和依赖动作）" in detail
    assert "错误 3 项，未检查 1 项" in detail
    assert "位置: spec/产品总说明.md:3" in detail
    assert "位置: spec/产品总说明.md:4" in detail
    assert "spec/代码架构设计.md 第 20 行；代码位置列；原值为中文说明；预期项目内真实代码文件" in detail
    assert "前置检查失败，本次没有启动最终全量测试进程" in detail
    assert "下一步命令: workflow repair-links" in detail


def test_gate_splits_nested_legacy_numbered_errors_into_independent_diagnostics(
    tmp_path,
    monkeypatch,
):
    """旧阶段把编号错误包进外层条目时，顶层仍须逐项报告。"""

    class LegacyImplStage:
        def code_validate(self, _project_root):
            return (
                False,
                "- 实施代码变化和计划范围：1. impl/上传文件_实施记录.md:87，文件列："
                "代码修改计划包含无法定位的文件路径：'暂无'\n"
                "2. 实际修改但实施后记录未列出：['src/upload.py']",
            )

    monkeypatch.setattr(
        cli_mod.markdown_links_mod,
        "validate_managed_markdown_links",
        lambda _project_root, **_kwargs: (True, "链接完整"),
    )
    workflow_state = WorkflowState(
        workflow_id="nested-legacy-details",
        intent="product_change",
        run_status="active",
    )

    passed, detail = cli_mod.validate_stage_output(
        str(tmp_path),
        workflow_state,
        "impl",
        LegacyImplStage(),
    )

    assert passed is False
    assert "错误 2 项，未检查 0 项" in detail
    assert "代码修改计划包含无法定位的文件路径：'暂无'" in detail
    assert "实际修改但实施后记录未列出：['src/upload.py']" in detail


def test_impl_gate_replaces_covered_legacy_text_with_structured_file_facts(
    tmp_path,
    monkeypatch,
):
    """Workflow-Test
    主题：所有阶段门禁失败时一次指出全部真实原因和改法
    测试项：TC-02 上层汇总不覆盖底层逐文件事实
    验收条件：AC-02 每项诊断保留真实事实并能直接修改
    测试方式：自动化测试
    测试层级：模块测试
    产品入口：`workflow gate impl` 的阶段产物校验
    测试入口：`tests/test_commands.py::test_impl_gate_replaces_covered_legacy_text_with_structured_file_facts`
    代码入口：`src/workflow_loop/cli.py::validate_stage_output`
    准备数据：建立同时返回两个逐文件结构化错误、对应旧路径列表文字和一个未被结构化报告覆盖的基线错误的实施阶段替身。
    执行动作：调用实施阶段产物校验，合并结构化诊断、仍有效的旧错误和当前门禁动作。
    关键断言：两个文件分别保留检查项、位置、预期、实际、证据、影响和改法；已覆盖的旧路径列表被去除；未覆盖的基线错误仍保留。
    预期证据：结构化报告需精确匹配该测试入口，实际执行数为 1，跳过数、失败数和错误数均为 0；断言需证明逐文件事实和未覆盖错误同时存在。
    """

    class StructuredImplStage:
        def code_validate(self, _project_root):
            return (
                False,
                "- 实施代码变化和计划范围：实际修改但实施后记录未列出："
                "['src/a.py', 'src/b.py']\n"
                "- 实施代码基线：缺少进入 impl 时的代码基线",
            )

        def code_validation_report(self, _project_root, _workflow_state):
            report = cli_mod.diagnostics_mod.ValidationReport(
                stage="impl",
                gate="实施代码变化和三方核对",
            )
            for path in ("src/a.py", "src/b.py"):
                report.add_error(
                    check_id="impl.implementation_relation.actual_unrecorded",
                    location=f"{path}（实施前基线后的真实文件差异）",
                    expected="每个真实修改文件都有一条实施后记录",
                    actual=f"实际修改但实施后记录未列出：{path}",
                    evidence=f"真实差异文件={path}；实施记录文件=[]",
                    impact="后续测试无法知道该文件改了什么",
                    next_action="为该文件补充真实实施记录",
                )
            return report

        @staticmethod
        def legacy_diagnostic_prefixes_covered_by_report():
            return ("实施代码变化和计划范围：",)

    monkeypatch.setattr(
        cli_mod.markdown_links_mod,
        "validate_managed_markdown_links",
        lambda _project_root, **_kwargs: (True, "链接完整"),
    )
    workflow_state = WorkflowState(
        workflow_id="structured-impl-report",
        intent="product_change",
        run_status="active",
    )

    passed, detail = cli_mod.validate_stage_output(
        str(tmp_path),
        workflow_state,
        "impl",
        StructuredImplStage(),
    )

    assert passed is False
    assert "错误 3 项，未检查 0 项" in detail
    assert detail.count("impl.implementation_relation.actual_unrecorded") == 2
    assert "位置: src/a.py（实施前基线后的真实文件差异）" in detail
    assert "位置: src/b.py（实施前基线后的真实文件差异）" in detail
    assert "['src/a.py', 'src/b.py']" not in detail
    assert "实施代码基线：缺少进入 impl 时的代码基线" in detail
    assert detail.count("下一步命令: workflow gate impl") == 1


def test_test_code_unchanged_failure_reports_exact_existing_code_command(
    tmp_path,
    monkeypatch,
):
    class UnchangedTestCodeStage:
        def code_validate(self, project_root):
            return (
                False,
                "存在自动化测试项，但测试代码没有变化；如果当前测试代码已经覆盖最新测试计划，"
                "请由用户执行 workflow gate test_code --accept-existing-test-code 明确确认",
            )

    monkeypatch.setattr(
        cli_mod.markdown_links_mod,
        "validate_managed_markdown_links",
        lambda project_root: (True, "链接完整"),
    )
    workflow_state = WorkflowState(
        workflow_id="reuse-test-code-command",
        intent="product_change",
        run_status="active",
    )

    passed, detail = cli_mod.validate_stage_output(
        str(tmp_path),
        workflow_state,
        "test_code",
        UnchangedTestCodeStage(),
    )

    assert not passed
    assert (
        "下一步命令: workflow gate test_code --accept-existing-test-code"
        in detail
    )
    assert "自动动作: 记录用户确认复用当前测试代码" in detail
    assert (
        "下一动作: 确认现有测试代码是否仍覆盖最新测试计划；未覆盖时先修改测试代码，"
        "然后执行报告末尾唯一的下一步命令"
        in detail
    )
    assert (
        detail.count(
            "下一步命令: workflow gate test_code --accept-existing-test-code"
        )
        == 1
    )
    assert "请按上述每项“下一动作”处理" in detail


def test_test_code_multiple_failures_do_not_bypass_required_fixes(
    tmp_path,
    monkeypatch,
):
    class TestCodeStageWithIndependentErrors:
        def code_validate(self, project_root):
            return (
                False,
                "- 存在自动化测试项，但测试代码没有变化；如果当前测试代码已经覆盖最新测试计划，"
                "请由用户执行 workflow gate test_code --accept-existing-test-code 明确确认\n"
                "- tests/test_feature.py:12 的 Workflow-Test 标识缺少关键断言",
            )

    monkeypatch.setattr(
        cli_mod.markdown_links_mod,
        "validate_managed_markdown_links",
        lambda project_root: (True, "链接完整"),
    )
    workflow_state = WorkflowState(
        workflow_id="reuse-test-code-with-errors",
        intent="product_change",
        run_status="active",
    )

    passed, detail = cli_mod.validate_stage_output(
        str(tmp_path),
        workflow_state,
        "test_code",
        TestCodeStageWithIndependentErrors(),
    )

    assert not passed
    assert "错误 2 项" in detail
    assert "下一步命令: workflow gate test_code\n" in detail
    assert (
        "下一步命令: workflow gate test_code --accept-existing-test-code"
        not in detail
    )
