import hashlib
import json
from pathlib import Path

import pytest

from workflow_loop import project as project_mod
from workflow_loop import rollback
from workflow_loop.state import GateState, StageState, WorkflowState
from workflow_loop.verification import compute_non_test_code_snapshot_hash


BACKUP_TOPIC = "项目修改可恢复且正式测试结果来自真实执行"
ABORT_TOPIC = "返回上游或整轮作废后状态与项目内容正确恢复"


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _impl_document(root: Path, paths: list[str]) -> None:
    rows = "\n".join(f"| {path} | run | 当前逻辑 | 修改逻辑 |" for path in paths)
    _write(
        root / "impl" / "上传文件_实施记录.md",
        f"""# 【实施】上传文件

## 2. 实施前计划

### 2.2 代码修改计划

| 文件 | 类、函数或配置项 | 当前逻辑 | 计划修改的具体逻辑 |
| --- | --- | --- | --- |
{rows}
""",
    )


def _impl_state(root: Path, paths: list[str]) -> WorkflowState:
    project_mod.create_project(str(root))
    _impl_document(root, paths)
    state = WorkflowState(
        workflow_id="impl-workflow",
        intent="product_change",
        run_status="active",
        current_stage="impl",
        topics=["上传文件"],
        stage_path=["impl"],
        stages={
            "impl": StageState(
                status="in_progress",
                gate=GateState(discussion_complete=True),
                code_baseline_hash=compute_non_test_code_snapshot_hash(str(root)),
            )
        },
    )
    return state


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_impl_backup_records_existing_and_originally_missing_files(tmp_path):
    """Workflow-Test
    主题：项目修改可恢复且正式测试结果来自真实执行
    测试项：TC-01 回退清单保存真实原内容和不存在记录
    验收条件：AC-01 修改前保存真实恢复依据
    测试方式：自动化测试
    测试层级：集成测试
    测试目标：计划内旧文件保存内容副本而新文件明确记录原本不存在并可准确恢复
    测试入口：tests/test_rollback.py::test_impl_backup_records_existing_and_originally_missing_files
    代码入口：workflow_loop.rollback.prepare_impl
    """
    existing = tmp_path / "src" / "app.py"
    _write(existing, "old\n")
    state = _impl_state(tmp_path, ["src/app.py", "src/new.py"])

    detail, paths = rollback.prepare_impl(str(tmp_path), state)
    existing.write_text("new\n", encoding="utf-8")
    _write(tmp_path / "src" / "new.py", "created\n")
    restored = rollback.restore(str(tmp_path), state)

    assert paths == ["src/app.py", "src/new.py"]
    assert "完整" in detail
    assert restored == ["src/app.py", "src/new.py"]
    assert existing.read_text(encoding="utf-8") == "old\n"
    assert not (tmp_path / "src" / "new.py").exists()


def test_adjusted_plan_keeps_first_backup_and_only_adds_trustworthy_paths(tmp_path):
    """Workflow-Test
    主题：项目修改可恢复且正式测试结果来自真实执行
    测试项：TC-02 实施计划调整不覆盖最初副本
    验收条件：AC-02 实施始终受当前确认计划约束
    测试方式：自动化测试
    测试层级：集成测试
    测试目标：计划调整后旧路径首次副本不变且只补尚未修改的新路径
    测试入口：tests/test_rollback.py::test_adjusted_plan_keeps_first_backup_and_only_adds_trustworthy_paths
    代码入口：workflow_loop.rollback.prepare_impl
    """
    app = tmp_path / "src" / "app.py"
    helper = tmp_path / "src" / "helper.py"
    _write(app, "old app\n")
    _write(helper, "old helper\n")
    state = _impl_state(tmp_path, ["src/app.py"])
    rollback.prepare_impl(str(tmp_path), state)
    manifest_path = tmp_path / state.rollback.manifest_path
    first = json.loads(manifest_path.read_text(encoding="utf-8"))
    first_backup = manifest_path.parent / first["entries"]["src/app.py"]["backup_path"]
    first_hash = _sha256(first_backup)

    app.write_text("implemented\n", encoding="utf-8")
    _impl_document(tmp_path, ["src/app.py", "src/helper.py"])
    rollback.prepare_impl(str(tmp_path), state)
    second = json.loads(manifest_path.read_text(encoding="utf-8"))

    assert _sha256(first_backup) == first_hash
    assert set(second["entries"]) == {"src/app.py", "src/helper.py"}
    helper_backup = manifest_path.parent / second["entries"]["src/helper.py"]["backup_path"]
    assert helper_backup.read_text(encoding="utf-8") == "old helper\n"


def test_confirmed_test_inventory_keeps_first_backup(tmp_path):
    """Workflow-Test
    主题：项目修改可恢复且正式测试结果来自真实执行
    测试项：TC-01 回退清单保存真实原内容和不存在记录
    验收条件：AC-01 修改前保存真实恢复依据
    测试方式：自动化测试
    测试层级：集成测试
    测试目标：另存已确认测试状态时不覆盖整轮作废所需的首次副本
    测试入口：tests/test_rollback.py::test_confirmed_test_inventory_keeps_first_backup
    代码入口：workflow_loop.rollback.accept_test_code_inventory
    """
    app = tmp_path / "src" / "app.py"
    test_file = tmp_path / "tests" / "test_app.py"
    _write(app, "old app\n")
    _write(test_file, "old test\n")
    state = _impl_state(tmp_path, ["src/app.py"])
    rollback.prepare_impl(str(tmp_path), state)
    rollback.prepare_test_code_baseline(str(tmp_path), state)
    manifest_path = tmp_path / state.rollback.manifest_path
    before = json.loads(manifest_path.read_text(encoding="utf-8"))
    entry_before = before["entries"]["tests/test_app.py"].copy()
    backup = manifest_path.parent / entry_before["backup_path"]
    backup_hash = _sha256(backup)

    test_file.write_text("confirmed test\n", encoding="utf-8")
    rollback.finalize_test_code_changes(str(tmp_path), state)
    rollback.accept_test_code_inventory(str(tmp_path), state)
    after = json.loads(manifest_path.read_text(encoding="utf-8"))

    assert after["entries"]["tests/test_app.py"] == entry_before
    assert _sha256(backup) == backup_hash
    assert backup.read_text(encoding="utf-8") == "old test\n"
    assert after["test_code_inventory_after"]["tests/test_app.py"] == _sha256(
        test_file
    )


def test_impl_reentry_allows_only_unchanged_confirmed_test_files(tmp_path):
    """Workflow-Test
    主题：项目修改可恢复且正式测试结果来自真实执行
    测试项：TC-02 实施计划调整不覆盖最初副本
    验收条件：AC-02 实施始终受当前确认计划约束
    测试方式：自动化测试
    测试层级：集成测试
    测试目标：返回实施后保留未再变的已确认测试文件并拦截之后的新变化
    测试入口：tests/test_rollback.py::test_impl_reentry_allows_only_unchanged_confirmed_test_files
    代码入口：workflow_loop.rollback.validate_implementation_changes
    """
    app = tmp_path / "src" / "app.py"
    test_file = tmp_path / "tests" / "test_app.py"
    _write(app, "old app\n")
    _write(test_file, "old test\n")
    state = _impl_state(tmp_path, ["src/app.py"])
    rollback.prepare_impl(str(tmp_path), state)
    rollback.prepare_test_code_baseline(str(tmp_path), state)

    app.write_text("implemented\n", encoding="utf-8")
    test_file.write_text("confirmed test\n", encoding="utf-8")
    rollback.finalize_test_code_changes(str(tmp_path), state)
    rollback.accept_test_code_inventory(str(tmp_path), state)

    valid, detail = rollback.validate_implementation_changes(str(tmp_path), state)
    assert valid is True, detail
    assert "tests/test_app.py" in detail
    assert "已确认且返回实施后未再变" in detail

    test_file.write_text("changed after return\n", encoding="utf-8")
    valid, detail = rollback.validate_implementation_changes(str(tmp_path), state)

    assert valid is False
    assert "实施计划外的文件变化" in detail
    assert "tests/test_app.py" in detail


def test_tampered_backup_blocks_restore_before_project_change(tmp_path):
    """Workflow-Test
    主题：项目修改可恢复且正式测试结果来自真实执行
    测试项：TC-01 回退清单保存真实原内容和不存在记录
    验收条件：AC-01 修改前保存真实恢复依据
    测试方式：自动化测试
    测试层级：集成测试
    测试目标：副本内容哈希不一致时拒绝用不可信内容覆盖项目
    测试入口：tests/test_rollback.py::test_tampered_backup_blocks_restore_before_project_change
    代码入口：workflow_loop.rollback.restore
    """
    app = tmp_path / "src" / "app.py"
    _write(app, "old\n")
    state = _impl_state(tmp_path, ["src/app.py"])
    rollback.prepare_impl(str(tmp_path), state)
    manifest_path = tmp_path / state.rollback.manifest_path
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    backup = manifest_path.parent / manifest["entries"]["src/app.py"]["backup_path"]
    backup.write_text("tampered\n", encoding="utf-8")
    app.write_text("current\n", encoding="utf-8")

    with pytest.raises(ValueError, match="副本内容已损坏"):
        rollback.restore(str(tmp_path), state)

    assert app.read_text(encoding="utf-8") == "current\n"


def _abort_state(root: Path, workflow_id: str = "abort-workflow") -> WorkflowState:
    return WorkflowState(
        workflow_id=workflow_id,
        intent="product_change",
        run_status="active",
        current_stage="impl",
        topics=[],
        stage_path=["impl"],
        stages={"impl": StageState(status="in_progress")},
    )


def _prepare_abort_project(root: Path) -> tuple[WorkflowState, dict]:
    project_mod.create_project(str(root))
    overview = root / "spec" / "产品总说明.md"
    _write(overview, "before\n")
    fields = project_mod.snapshot_managed_fields(str(root))
    state = _abort_state(root)
    rollback.prepare_start_baseline(str(root), state.workflow_id, fields, None)
    overview.write_text("during\n", encoding="utf-8")
    _write(root / "spec" / "功能_本轮新增.md", "new\n")
    project_mod.set_project_design_initialized(str(root), True)
    return state, fields


def test_full_abort_restores_managed_content_and_project_fields_only(tmp_path):
    """Workflow-Test
    主题：返回上游或整轮作废后状态与项目内容正确恢复
    测试项：TC-05 整轮作废恢复全部受管内容且不归档
    验收条件：AC-05 整轮作废真正恢复项目
    测试方式：自动化测试
    测试层级：集成测试
    测试目标：整轮作废恢复旧正式文档、删除本轮新文档和恢复受管字段且不碰第三方文件
    测试入口：tests/test_rollback.py::test_full_abort_restores_managed_content_and_project_fields_only
    代码入口：workflow_loop.rollback.restore_full_run
    """
    state, fields = _prepare_abort_project(tmp_path)
    third_party = tmp_path / "notes.txt"
    third_party.write_text("keep\n", encoding="utf-8")

    ok, problems, _ = rollback.preflight_abort(str(tmp_path), state)
    restored, failures = rollback.restore_full_run(str(tmp_path), state)

    assert ok is True, problems
    assert failures == []
    assert "spec/产品总说明.md" in restored
    assert (tmp_path / "spec" / "产品总说明.md").read_text(encoding="utf-8") == "before\n"
    assert not (tmp_path / "spec" / "功能_本轮新增.md").exists()
    assert third_party.read_text(encoding="utf-8") == "keep\n"
    assert project_mod.snapshot_managed_fields(str(tmp_path)) == fields


def test_abort_retry_detects_change_after_restore_progress_write_failure(tmp_path, monkeypatch):
    """Workflow-Test
    主题：返回上游或整轮作废后状态与项目内容正确恢复
    测试项：TC-06 部分恢复失败后只继续未完成项目
    验收条件：AC-06 恢复不完整不能标记成功
    测试方式：自动化测试
    测试层级：集成测试
    测试目标：文件已恢复但完成进度未落盘时重试识别目标状态且不覆盖期间的新修改
    测试入口：tests/test_rollback.py::test_abort_retry_detects_change_after_restore_progress_write_failure
    代码入口：workflow_loop.rollback.restore_full_run
    """
    state, _fields = _prepare_abort_project(tmp_path)
    ok, problems, _ = rollback.preflight_abort(str(tmp_path), state)
    assert ok is True, problems
    original_write = rollback._write_abort_manifest
    failed_writes = 0

    def fail_after_overview_restore(project_root, workflow_id, manifest):
        nonlocal failed_writes
        item = next(
            candidate
            for candidate in manifest["items"]
            if candidate.get("path") == "spec/产品总说明.md"
        )
        if item.get("status") == "restored" and failed_writes < 2:
            failed_writes += 1
            raise OSError("injected progress failure")
        return original_write(project_root, workflow_id, manifest)

    monkeypatch.setattr(rollback, "_write_abort_manifest", fail_after_overview_restore)
    _restored, failures = rollback.restore_full_run(str(tmp_path), state)
    assert failures
    overview = tmp_path / "spec" / "产品总说明.md"
    assert overview.read_text(encoding="utf-8") == "before\n"

    monkeypatch.setattr(rollback, "_write_abort_manifest", original_write)
    overview.write_text("user changed after interruption\n", encoding="utf-8")
    _restored, failures = rollback.restore_full_run(str(tmp_path), state)
    assert any("发生了新的修改" in failure for failure in failures), failures
    assert overview.read_text(encoding="utf-8") == "user changed after interruption\n"

    overview.write_text("before\n", encoding="utf-8")
    _restored, failures = rollback.restore_full_run(str(tmp_path), state)
    assert failures == []
    assert overview.read_text(encoding="utf-8") == "before\n"
