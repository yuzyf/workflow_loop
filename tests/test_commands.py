import json
import subprocess
import sys
from pathlib import Path

from workflow_loop import PRODUCT_NAME, __version__
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
        "test_plan",
        "impl",
        "test_code",
        "test_execution",
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
    assert "进入 code_design" in out


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
        ["return", "--to", "test_plan", "--reason", "测试计划需修正"], tmp_path
    )
    after = load_state(str(tmp_path))

    assert code == 0, err
    assert "必须明确写出直接受影响的主题" in out
    assert after.current_stage == before.current_stage
    assert after.recovery.return_target is None


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
            "test_execution",
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
    state = WorkflowState(
        workflow_id="done-workflow",
        intent="product_change",
        run_status="active",
        current_stage="completed",
        stage_path=[],
        stages={},
    )
    save_state(str(tmp_path), state)

    code, out, err = _run(["done"], tmp_path)

    assert code == 0, err
    completed = load_state(str(tmp_path))
    assert completed.run_status == "completed"
    assert completed.ended_at
    assert formal.read_text(encoding="utf-8") == "formal"
    assert "工作流完成" in out
