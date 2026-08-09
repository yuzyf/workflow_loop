import json
import subprocess
import sys
from pathlib import Path

import pytest

from workflow_loop import PRODUCT_NAME, __version__
from workflow_loop import installer as installer_mod
from workflow_loop import journal as journal_mod
from workflow_loop.path_composer import build_stage_path
from workflow_loop.state import load_state


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW_CMD = [sys.executable, "-m", "workflow_loop.cli"]
TOPIC = "无需开发任务按确认流程完成并保持边界"


def _run(args: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        WORKFLOW_CMD + args,
        cwd=cwd,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )


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
    result = _run(["_install-project", "--transaction", str(token_path)], root)
    assert result.returncode == 0, result.stdout + result.stderr


def _start_light(root: Path) -> subprocess.CompletedProcess[str]:
    result = _run(["start", "--intent", "light_task"], root)
    assert result.returncode == 0, result.stdout + result.stderr
    return result


def _enter_execution(
    root: Path,
    *,
    task: str = "更新说明文档",
    verification: str = "核对文档差异",
) -> subprocess.CompletedProcess[str]:
    result = _run(
        [
            "light",
            "--discuss-done",
            "--task",
            task,
            "--verification",
            verification,
        ],
        root,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    return result


def _entries(root: Path, action: str) -> list[dict]:
    return [
        entry
        for entry in journal_mod.read_all(str(root))
        if entry.get("action") == action
    ]


def test_light_task_route_requires_explicit_start_and_keeps_one_active_run(tmp_path: Path):
    """Workflow-Test
    主题：无需开发任务按确认流程完成并保持边界
    测试项：TC-01 确认四种路线并只开始一个轮次
    验收条件：AC-01 路线确认后才开始无需开发任务
    测试方式：自动化测试 + 人工验收
    测试层级：命令测试
    测试目标：状态检查只展示四种路线且不启动，明确选择简单路线后只建立一个进行中轮次
    测试入口：tests/test_light_task.py::test_light_task_route_requires_explicit_start_and_keeps_one_active_run
    代码入口：workflow_loop.cli.cmd_start；workflow_loop.state.WorkflowState
    """
    _install_project(tmp_path)
    state_path = tmp_path / ".workflow_loop" / "state.json"

    inspection = _run(["start"], tmp_path)

    assert inspection.returncode == 0, inspection.stderr
    for intent in ("from_scratch", "product_change", "bugfix", "light_task"):
        assert intent in inspection.stdout
    assert "用户明确确认" in inspection.stdout
    assert not state_path.exists()

    started = _start_light(tmp_path)
    first_state = load_state(str(tmp_path))
    assert first_state is not None
    assert first_state.intent == "light_task"
    assert first_state.run_status == "active"
    assert first_state.current_stage == ""
    assert first_state.stage_path == []
    assert first_state.light_task is not None
    assert first_state.light_task.phase == "discussion"
    assert "不会自动执行任务" in started.stdout
    assert len(_entries(tmp_path, "工作流启动")) == 1

    duplicate = _run(["start", "--intent", "bugfix"], tmp_path)
    unchanged = load_state(str(tmp_path))

    assert duplicate.returncode == 1
    assert "有进行中 Run" in duplicate.stdout
    assert unchanged is not None
    assert unchanged.workflow_id == first_state.workflow_id
    assert unchanged.intent == "light_task"
    assert len(_entries(tmp_path, "工作流启动")) == 1


def test_light_task_discussion_must_finish_before_execution(tmp_path: Path):
    """Workflow-Test
    主题：无需开发任务按确认流程完成并保持边界
    测试项：TC-02 讨论完成前禁止执行
    验收条件：AC-02 讨论完成前不执行任务
    测试方式：自动化测试 + 人工验收
    测试层级：命令测试
    测试目标：文档修改、文档生成和调查任务都必须先确认任务摘要与核对方法才能进入执行
    测试入口：tests/test_light_task.py::test_light_task_discussion_must_finish_before_execution
    代码入口：workflow_loop.cli.cmd_light；workflow_loop.cli.cmd_done
    """
    cases = (
        ("document-edit", "修改现有说明文档", "查看现有文档差异", True),
        ("document-create", "生成一份发布说明", "读取生成文档全文", False),
        ("research", "调查当前版本准备状态", "逐项核对调查依据", False),
    )
    for dirname, task, verification, target_exists in cases:
        root = tmp_path / dirname
        root.mkdir()
        _install_project(root)
        target = root / "task-output.md"
        if target_exists:
            target.write_text("before\n", encoding="utf-8")
        before = target.read_bytes() if target_exists else None

        started = _start_light(root)
        assert "每次只问用户一个问题并给出建议" in started.stdout

        premature_result = _run(
            ["light", "--confirmed", "--result", "尚未执行却声称完成"],
            root,
        )
        premature_done = _run(["done"], root)
        missing_method = _run(
            ["light", "--discuss-done", "--task", task],
            root,
        )
        discussion_state = load_state(str(root))

        assert premature_result.returncode == 1
        assert premature_done.returncode == 1
        assert missing_method.returncode == 1
        assert discussion_state is not None and discussion_state.light_task is not None
        assert discussion_state.light_task.phase == "discussion"
        assert discussion_state.light_task.result_summary == ""
        assert not _entries(root, "无需开发任务讨论完成")
        if before is None:
            assert not target.exists()
        else:
            assert target.read_bytes() == before

        _enter_execution(root, task=task, verification=verification)
        execution_state = load_state(str(root))

        assert execution_state is not None and execution_state.light_task is not None
        assert execution_state.light_task.phase == "execution"
        assert execution_state.light_task.task_summary == task
        assert execution_state.light_task.verification_method == verification
        discussion_entries = _entries(root, "无需开发任务讨论完成")
        assert len(discussion_entries) == 1
        assert discussion_entries[0]["task_summary"] == task
        assert discussion_entries[0]["verification_method"] == verification


def test_light_task_records_each_exact_irreversible_action_approval(tmp_path: Path):
    """Workflow-Test
    主题：无需开发任务按确认流程完成并保持边界
    测试项：TC-03 难撤销操作按准确范围批准
    验收条件：AC-03 难以撤销的操作单独取得准确批准
    测试方式：自动化测试 + 人工验收
    测试层级：命令测试
    测试目标：本地提交、远程推送、发布和删除的批准分别准确记录且不会互相扩大范围
    测试入口：tests/test_light_task.py::test_light_task_records_each_exact_irreversible_action_approval
    代码入口：workflow_loop.cli.cmd_light；workflow_loop.journal.append_entry
    """
    _install_project(tmp_path)
    _start_light(tmp_path)

    too_early = _run(
        ["light", "--approve-action", "创建本地 Git commit"],
        tmp_path,
    )
    assert too_early.returncode == 1
    assert not _entries(tmp_path, "无需开发任务操作已批准")

    _enter_execution(tmp_path)
    empty = _run(["light", "--approve-action", ""], tmp_path)
    mixed_steps = _run(
        ["light", "--approve-action", "删除旧标签", "--task", "额外任务"],
        tmp_path,
    )
    assert empty.returncode == 1
    assert mixed_steps.returncode == 1

    approvals = [
        "在本地仓库创建只包含 README.md 的 Git commit",
        "把分支 release-docs push 到 origin 远程仓库",
        "把版本 v0.2.0 发布到正式发布平台",
        "删除远程仓库中的 release-docs 分支",
    ]
    assert "push" not in approvals[0]
    for approval in approvals:
        result = _run(["light", "--approve-action", approval], tmp_path)
        assert result.returncode == 0, result.stdout + result.stderr
        assert "只记录批准，不会自动执行" in result.stdout

    approval_entries = _entries(tmp_path, "无需开发任务操作已批准")
    final_state = load_state(str(tmp_path))

    assert [entry["approved_action"] for entry in approval_entries] == approvals
    assert final_state is not None and final_state.light_task is not None
    assert final_state.light_task.last_approved_action == approvals[-1]


def test_light_task_bypasses_full_flow_while_three_existing_routes_stay_intact(tmp_path: Path):
    """Workflow-Test
    主题：无需开发任务按确认流程完成并保持边界
    测试项：TC-04 简单流程绕过研发阶段且旧流程不变
    验收条件：AC-04 无需开发任务不继承完整研发负担
    测试方式：自动化测试
    测试层级：集成测试
    测试目标：简单轮次没有研发阶段、过程产物、固定测试和回退副本，完整研发命令被拒绝且原三种路线不变
    测试入口：tests/test_light_task.py::test_light_task_bypasses_full_flow_while_three_existing_routes_stay_intact
    代码入口：workflow_loop.cli.cmd_start；workflow_loop.cli.cmd_discuss；workflow_loop.cli.cmd_gate；workflow_loop.path_composer.build_stage_path
    """
    light_root = tmp_path / "light"
    light_root.mkdir()
    _install_project(light_root)
    _start_light(light_root)
    state_path = light_root / ".workflow_loop" / "state.json"
    before_state = state_path.read_text(encoding="utf-8")

    full_flow_commands = (
        ["discuss"],
        ["gate", "spec"],
        ["return", "--to", "spec", "--reason", "不应进入研发阶段"],
        ["test", "entry", "--default", sys.executable],
        [
            "acceptance",
            "record",
            "--topic",
            TOPIC,
            "--criterion",
            "AC-01",
            "--result",
            "passed",
            "--actual-result",
            "不应记录",
            "--answer",
            "不应记录",
        ],
    )
    for command in full_flow_commands:
        rejected = _run(command, light_root)
        assert rejected.returncode == 1
        assert "简单流程" in rejected.stdout

    light_state = load_state(str(light_root))
    assert light_state is not None
    assert state_path.read_text(encoding="utf-8") == before_state
    assert light_state.stage_path == []
    assert light_state.stages == {}
    assert light_state.regression_test.status == "not_run"
    assert not any(vars(light_state.verification).values())
    assert light_state.rollback.manifest_path is None
    assert not (light_root / ".workflow_loop" / "rollback").exists()
    for process_path in ("spec", "acceptance", "qa", "impl", "bug"):
        assert not (light_root / process_path).exists()
    with pytest.raises(ValueError, match="不使用研发 stage 路径"):
        build_stage_path("light_task", str(light_root))

    expected_paths = {
        "from_scratch": [
            "spec", "code_design", "spike", "acceptance_plan", "impl", "test_plan",
            "test_code", "test_execution", "topic_acceptance", "regression_test",
            "overall_acceptance", "update_code_design",
        ],
        "product_change": [
            "project_design_init", "spec", "revise_code_design", "spike",
            "acceptance_plan", "impl", "test_plan", "test_code", "test_execution",
            "topic_acceptance", "regression_test", "overall_acceptance", "update_code_design",
        ],
        "bugfix": [
            "project_design_init", "reproduce", "spike", "acceptance_plan", "impl",
            "test_plan", "test_code", "test_execution", "topic_acceptance", "regression_test",
            "overall_acceptance", "update_code_design",
        ],
    }
    for intent, expected_path in expected_paths.items():
        root = tmp_path / intent
        root.mkdir()
        _install_project(root)
        started = _run(["start", "--intent", intent], root)
        full_state = load_state(str(root))

        assert started.returncode == 0, started.stdout + started.stderr
        assert full_state is not None
        assert full_state.stage_path == expected_path
        assert full_state.light_task is None
        assert (root / ".workflow_loop" / "rollback").is_dir()


def test_light_task_finishes_once_only_after_result_confirmation(tmp_path: Path):
    """Workflow-Test
    主题：无需开发任务按确认流程完成并保持边界
    测试项：TC-05 核对结果后只收工一次
    验收条件：AC-05 结果确认后只正式收工一次
    测试方式：自动化测试 + 人工验收
    测试层级：命令测试
    测试目标：没有确认实际结果时不能收工，确认后只生成一次完成记录且结果说明不冒充研发验收
    测试入口：tests/test_light_task.py::test_light_task_finishes_once_only_after_result_confirmation
    代码入口：workflow_loop.cli.cmd_light；workflow_loop.cli.cmd_done
    """
    _install_project(tmp_path)
    _start_light(tmp_path)
    _enter_execution(tmp_path)

    no_result = _run(["light", "--confirmed"], tmp_path)
    premature_done = _run(["done"], tmp_path)
    assert no_result.returncode == 1
    assert premature_done.returncode == 1
    assert not _entries(tmp_path, "Run 完成")

    result_summary = "README 已更新，实际差异只包含约定的简单流程说明"
    confirmed = _run(
        ["light", "--confirmed", "--result", result_summary],
        tmp_path,
    )
    awaiting_done = load_state(str(tmp_path))

    assert confirmed.returncode == 0, confirmed.stdout + confirmed.stderr
    assert awaiting_done is not None and awaiting_done.light_task is not None
    assert awaiting_done.run_status == "active"
    assert awaiting_done.light_task.phase == "result_confirmed"
    assert awaiting_done.light_task.result_summary == result_summary
    assert "测试通过" not in confirmed.stdout
    assert "研发验收通过" not in confirmed.stdout

    finished = _run(["done"], tmp_path)
    repeated = _run(["done"], tmp_path)
    final_state = load_state(str(tmp_path))

    assert finished.returncode == 0, finished.stdout + finished.stderr
    assert repeated.returncode == 1
    assert final_state is not None
    assert final_state.run_status == "completed"
    assert final_state.ended_at is not None
    completed_entries = _entries(tmp_path, "Run 完成")
    assert len(completed_entries) == 1
    assert completed_entries[0]["result_summary"] == result_summary


def test_light_task_abort_preserves_reality_and_allows_confirmed_reclassification(tmp_path: Path):
    """Workflow-Test
    主题：无需开发任务按确认流程完成并保持边界
    测试项：TC-06 异常结束保留真实状态并重新分类
    验收条件：AC-06 失败、作废和重新分类保留真实状态
    测试方式：自动化测试
    测试层级：集成测试
    测试目标：部分完成、失败、用户作废和发现需要开发都保留现场并记录真实摘要，之后才能明确选择完整研发路线
    测试入口：tests/test_light_task.py::test_light_task_abort_preserves_reality_and_allows_confirmed_reclassification
    代码入口：workflow_loop.cli.cmd_abort；workflow_loop.cli.cmd_start
    """
    cases = (
        ("partial", "已修改一半文档，剩余段落未执行"),
        ("failed", "文档生成失败，已创建的草稿保留"),
        ("cancelled", "用户决定作废，已完成的调查记录保留"),
        ("needs-development", "发现需要修改产品代码，简单任务停止"),
    )
    for dirname, summary in cases:
        root = tmp_path / dirname
        root.mkdir()
        _install_project(root)
        _start_light(root)
        _enter_execution(root, task="处理当前任务", verification="核对真实现场")
        sentinel = root / "actual-state.txt"
        sentinel_content = f"{dirname}: already happened\n"
        sentinel.write_text(sentinel_content, encoding="utf-8")

        missing_summary = _run(["abort"], root)
        active_state = load_state(str(root))
        assert missing_summary.returncode == 1
        assert active_state is not None and active_state.run_status == "active"
        assert sentinel.read_text(encoding="utf-8") == sentinel_content

        aborted = _run(["abort", "--summary", summary], root)
        aborted_state = load_state(str(root))

        assert aborted.returncode == 0, aborted.stdout + aborted.stderr
        assert "程序没有创建或执行回滚" in aborted.stdout
        assert aborted_state is not None and aborted_state.light_task is not None
        assert aborted_state.run_status == "aborted"
        assert aborted_state.light_task.result_summary == summary
        assert sentinel.read_text(encoding="utf-8") == sentinel_content
        assert not (root / ".workflow_loop" / "rollback").exists()
        abort_entries = _entries(root, "无需开发任务已作废")
        assert len(abort_entries) == 1
        assert abort_entries[0]["actual_state_summary"] == summary

        if dirname == "needs-development":
            route_check = _run(["start"], root)
            still_aborted = load_state(str(root))
            assert route_check.returncode == 0
            assert "用户明确确认" in route_check.stdout
            assert still_aborted is not None and still_aborted.run_status == "aborted"

            reclassified = _run(["start", "--intent", "product_change"], root)
            full_state = load_state(str(root))
            assert reclassified.returncode == 0, reclassified.stdout + reclassified.stderr
            assert full_state is not None
            assert full_state.intent == "product_change"
            assert full_state.run_status == "active"
            assert full_state.light_task is None
            assert full_state.stage_path


def test_installed_contract_and_readme_describe_the_light_task_rules(tmp_path: Path):
    """Workflow-Test
    主题：无需开发任务按确认流程完成并保持边界
    测试项：TC-07 AI 契约和公开说明写明简单流程
    验收条件：AC-07 安装后的 AI 契约和公开说明包含简单流程
    测试方式：自动化测试 + 人工验收
    测试层级：集成测试
    测试目标：安装后的 AI 契约和公开 README 都完整说明四种路线、逐题讨论、额外批准及 AI 执行边界
    测试入口：tests/test_light_task.py::test_installed_contract_and_readme_describe_the_light_task_rules
    代码入口：workflow_loop.installer.AGENTS_MD_CONTENT；README.md
    """
    _install_project(tmp_path)
    contract = (tmp_path / "AGENTS.md").read_text(encoding="utf-8")
    readme = (ROOT / "README.md").read_text(encoding="utf-8")

    assert contract == installer_mod.AGENTS_MD_CONTENT
    for text in (contract, readme):
        for intent in ("from_scratch", "product_change", "bugfix", "light_task"):
            assert intent in text
        assert "每次只问一个问题" in text
        assert "确认讨论完毕" in text
        assert "commit" in text and "push" in text
        assert "发布" in text and "删除" in text
        assert "难撤销" in text
        assert "AI" in text and "用户" in text
    assert "不限于改文档、生成文档、Git 提交或发布版本" in contract
    assert "不是“改文档、提交、发布”三个固定选项" in readme
    assert "不需要知道或手动执行任何 `workflow` 命令" in contract
    assert "用户不需要手工执行日常" in readme
