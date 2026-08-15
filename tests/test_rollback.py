import hashlib
import json
import os
import subprocess
from pathlib import Path

import pytest

from workflow_loop import project as project_mod
from workflow_loop import rollback
from workflow_loop.state import GateState, StageState, WorkflowState
from workflow_loop.verification import (
    compute_complete_implementation_file_snapshot,
    compute_non_test_code_snapshot_hash,
)


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


def _append_impl_record(root: Path, paths: list[str]) -> None:
    document = root / "impl" / "上传文件_实施记录.md"
    rows = []
    for path in paths:
        content = (root / path).read_text(encoding="utf-8")
        location = next(
            (
                line.removeprefix("def ").split("(", 1)[0].strip()
                for line in content.splitlines()
                if line.startswith("def ")
            ),
            None,
        )
        if location is None:
            location = next(
                (line.strip() for line in content.splitlines() if line.strip()),
                path,
            )
        rows.append(
            f"| {path} | `{location}` | 将该位置更新为实施后的真实内容 | "
            "读取文件可观察到该位置的当前输出 | AC-01 |"
        )
    document.write_text(
        document.read_text(encoding="utf-8")
        + f"""

## 3. 实施后记录

### 3.1 实际代码修改

| 文件 | 类、函数或配置项 | 实际修改的代码逻辑 | 数据、状态或输出的实际变化 | 对应验收条件 |
| --- | --- | --- | --- | --- |
{"\n".join(rows)}
""",
        encoding="utf-8",
    )


def _impl_state(root: Path, paths: list[str]) -> WorkflowState:
    project_mod.create_project(str(root))
    _impl_document(root, paths)
    _write(
        root / "acceptance" / "上传文件_验收计划.md",
        """# 【验收主题】上传文件

<a id="ac-01"></a>
### AC-01：上传后可读取结果
""",
    )
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


def _freeze_complete_impl_inventory(root: Path, state: WorkflowState) -> None:
    state.meta[rollback.IMPL_COMPLETE_BASELINE_SNAPSHOT_KEY] = (
        compute_complete_implementation_file_snapshot(str(root), scope="all")
    )


def _git(root: Path, *arguments: str) -> None:
    completed = subprocess.run(
        ["git", *arguments],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr


def _commit_code_baseline(root: Path, *paths: str) -> None:
    _git(root, "init")
    _git(root, "config", "user.name", "Workflow Loop Test")
    _git(root, "config", "user.email", "workflow-loop@example.invalid")
    _git(root, "add", "--", *paths)
    _git(root, "commit", "-m", "code baseline")


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


def test_adjusted_plan_rejects_path_without_an_original_snapshot(tmp_path):
    """Workflow-Test
    主题：项目修改可恢复且正式测试结果来自真实执行
    测试项：TC-02 实施计划调整不覆盖最初副本
    验收条件：AC-02 实施始终受当前确认计划约束
    测试方式：自动化测试
    测试层级：集成测试
    测试目标：计划调整后旧路径首次副本不变且拒绝没有实施前快照的新路径
    测试入口：tests/test_rollback.py::test_adjusted_plan_rejects_path_without_an_original_snapshot
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
    with pytest.raises(ValueError, match="没有可信的实施前原内容：src/helper.py"):
        rollback.prepare_impl(str(tmp_path), state)
    second = json.loads(manifest_path.read_text(encoding="utf-8"))

    assert _sha256(first_backup) == first_hash
    assert set(second["entries"]) == {"src/app.py"}
    assert helper.read_text(encoding="utf-8") == "old helper\n"


def test_adjusted_plan_accepts_unsampled_file_equal_to_clean_git_head(tmp_path):
    """首次清单漏采样的既有文件只从完全一致的 Git HEAD 补可信副本。"""
    app = tmp_path / "src" / "app.py"
    helper = tmp_path / "src" / "helper.py"
    _write(app, "old app\n")
    _write(helper, "old helper\n")
    _commit_code_baseline(tmp_path, "src/app.py", "src/helper.py")
    state = _impl_state(tmp_path, ["src/app.py"])
    rollback.prepare_impl(str(tmp_path), state)

    app.write_text("implemented\n", encoding="utf-8")
    _impl_document(tmp_path, ["src/app.py", "src/helper.py"])
    detail, paths = rollback.prepare_impl(str(tmp_path), state)
    manifest_path = tmp_path / state.rollback.manifest_path
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    helper_entry = manifest["entries"]["src/helper.py"]
    helper_backup = manifest_path.parent / helper_entry["backup_path"]

    assert "完整" in detail
    assert paths == ["src/app.py", "src/helper.py"]
    assert helper_backup.read_bytes() == b"old helper\n"
    assert manifest["initial_inventory"]["src/helper.py"] == _sha256(helper)
    assert "src/helper.py" in manifest["core_registered_paths"]


def test_adjusted_plan_recovers_changed_sampled_file_from_matching_git_head(tmp_path):
    """旧清单已有原始哈希时，可从哈希一致的 HEAD 补回修改前副本。"""
    app = tmp_path / "src" / "app.py"
    helper = tmp_path / "src" / "helper.py"
    _write(app, "old app\n")
    _write(helper, "old helper\n")
    _commit_code_baseline(tmp_path, "src/app.py", "src/helper.py")
    state = _impl_state(tmp_path, ["src/app.py"])
    _write(
        tmp_path / "spec" / "代码架构设计.md",
        """## 6. 各产品功能的代码设计

| 图中步骤 | 代码位置 |
|---|---|
| 辅助逻辑 | `src/helper.py::run` |
""",
    )
    rollback.prepare_impl(str(tmp_path), state)
    manifest_path = tmp_path / state.rollback.manifest_path
    first = json.loads(manifest_path.read_text(encoding="utf-8"))

    assert first["initial_inventory"]["src/helper.py"] == _sha256(helper)
    assert "src/helper.py" not in first["entries"]

    helper.write_text("implemented helper\n", encoding="utf-8")
    _impl_document(tmp_path, ["src/app.py", "src/helper.py"])
    detail, paths = rollback.prepare_impl(str(tmp_path), state)
    second = json.loads(manifest_path.read_text(encoding="utf-8"))
    helper_entry = second["entries"]["src/helper.py"]
    helper_backup = manifest_path.parent / helper_entry["backup_path"]

    assert "完整" in detail
    assert paths == ["src/app.py", "src/helper.py"]
    assert helper_backup.read_bytes() == b"old helper\n"
    assert helper_entry["content_hash"] == first["initial_inventory"]["src/helper.py"]
    assert helper.read_text(encoding="utf-8") == "implemented helper\n"

    restored = rollback.restore(str(tmp_path), state)

    assert "src/helper.py" in restored
    assert helper.read_text(encoding="utf-8") == "old helper\n"


def test_adjusted_plan_reports_initial_and_head_hash_when_they_differ(tmp_path):
    """HEAD 已变化时，失败原因必须同时给出首次清单和 HEAD 的真实哈希。"""
    app = tmp_path / "src" / "app.py"
    helper = tmp_path / "src" / "helper.py"
    _write(app, "old app\n")
    _write(helper, "old helper\n")
    _commit_code_baseline(tmp_path, "src/app.py", "src/helper.py")
    state = _impl_state(tmp_path, ["src/app.py"])
    _write(
        tmp_path / "spec" / "代码架构设计.md",
        """## 6. 各产品功能的代码设计

| 图中步骤 | 代码位置 |
|---|---|
| 辅助逻辑 | `src/helper.py::run` |
""",
    )
    rollback.prepare_impl(str(tmp_path), state)
    initial_hash = json.loads(
        (tmp_path / state.rollback.manifest_path).read_text(encoding="utf-8")
    )["initial_inventory"]["src/helper.py"]

    helper.write_text("new committed helper\n", encoding="utf-8")
    _git(tmp_path, "add", "--", "src/helper.py")
    _git(tmp_path, "commit", "-m", "move helper head")
    head_hash = _sha256(helper)
    helper.write_text("implemented helper\n", encoding="utf-8")
    _impl_document(tmp_path, ["src/app.py", "src/helper.py"])

    with pytest.raises(ValueError) as error:
        rollback.prepare_impl(str(tmp_path), state)

    detail = str(error.value)
    assert f"首次清单 SHA-256={initial_hash}" in detail
    assert f"Git HEAD SHA-256={head_hash}" in detail
    assert "两个哈希不一致" in detail
    assert "没有未提交差异且当前字节与 HEAD 完全一致" not in detail


def test_reprepare_rejects_a_manifest_changed_without_state_hash_update(tmp_path):
    """补副本前必须先验证旧清单原始字节仍与状态中的清单哈希一致。"""
    app = tmp_path / "src" / "app.py"
    _write(app, "old app\n")
    state = _impl_state(tmp_path, ["src/app.py"])
    rollback.prepare_impl(str(tmp_path), state)
    manifest_path = tmp_path / state.rollback.manifest_path
    manifest_path.write_bytes(manifest_path.read_bytes() + b"\n")

    with pytest.raises(ValueError, match="清单哈希与 state.json 不一致"):
        rollback.prepare_impl(str(tmp_path), state)


def test_reprepare_reports_invalid_initial_inventory_structure(tmp_path):
    """哈希已同步但结构损坏时，应给字段原因而不是泄漏 Python 类型异常。"""
    app = tmp_path / "src" / "app.py"
    _write(app, "old app\n")
    state = _impl_state(tmp_path, ["src/app.py"])
    rollback.prepare_impl(str(tmp_path), state)
    manifest_path = tmp_path / state.rollback.manifest_path
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["initial_inventory"] = []
    rollback._write_manifest(str(tmp_path), state, manifest)

    with pytest.raises(
        ValueError,
        match=r"initial_inventory（初始文件哈希表）必须是对象",
    ):
        rollback.prepare_impl(str(tmp_path), state)


@pytest.mark.skipif(os.name == "nt", reason="Windows Git 不保留 POSIX 可执行位")
def test_adjusted_plan_preserves_clean_executable_mode_from_git_head(tmp_path):
    """Git 普通可执行文件可补副本，并保留 HEAD 的 100755 模式。"""
    app = tmp_path / "src" / "app.py"
    helper = tmp_path / "scripts" / "helper.sh"
    _write(app, "old app\n")
    _write(helper, "#!/bin/sh\nexit 0\n")
    helper.chmod(0o755)
    _commit_code_baseline(tmp_path, "src/app.py", "scripts/helper.sh")
    state = _impl_state(tmp_path, ["src/app.py"])
    rollback.prepare_impl(str(tmp_path), state)

    _impl_document(tmp_path, ["src/app.py", "scripts/helper.sh"])
    rollback.prepare_impl(str(tmp_path), state)
    manifest = json.loads(
        (tmp_path / state.rollback.manifest_path).read_text(encoding="utf-8")
    )

    assert manifest["entries"]["scripts/helper.sh"]["mode"] == 0o755


@pytest.mark.skipif(os.name == "nt", reason="Windows 创建 Git 符号链接需要额外权限")
def test_adjusted_plan_rejects_git_head_symlink_blob_as_a_file_baseline(tmp_path):
    """HEAD 的 120000 链接对象不能被当作普通文件原文写入回退副本。"""
    app = tmp_path / "src" / "app.py"
    target = tmp_path / "src" / "target.py"
    helper = tmp_path / "src" / "helper.py"
    _write(app, "old app\n")
    _write(target, "target\n")
    helper.symlink_to("target.py")
    _commit_code_baseline(tmp_path, "src/app.py", "src/helper.py", "src/target.py")
    state = _impl_state(tmp_path, ["src/app.py"])
    rollback.prepare_impl(str(tmp_path), state)

    helper.unlink()
    helper.write_text("target.py", encoding="utf-8")
    _impl_document(tmp_path, ["src/app.py", "src/helper.py"])

    with pytest.raises(ValueError) as error:
        rollback.prepare_impl(str(tmp_path), state)

    detail = str(error.value)
    assert "Git HEAD 文件模式=120000（符号链接）" in detail
    assert "不能把链接目标文字当作文件原文" in detail


def test_adjusted_plan_rejects_unsampled_untracked_file_even_inside_git_repo(tmp_path):
    """Git 仓库中的未跟踪文件也不能被倒推成实施前原内容。"""
    app = tmp_path / "src" / "app.py"
    helper = tmp_path / "src" / "helper.py"
    _write(app, "old app\n")
    _commit_code_baseline(tmp_path, "src/app.py")
    _write(helper, "untracked helper\n")
    state = _impl_state(tmp_path, ["src/app.py"])
    rollback.prepare_impl(str(tmp_path), state)

    _impl_document(tmp_path, ["src/app.py", "src/helper.py"])
    with pytest.raises(ValueError, match="没有可信的实施前原内容：src/helper.py"):
        rollback.prepare_impl(str(tmp_path), state)


def test_adjusted_plan_rejects_unsampled_file_with_staged_git_difference(tmp_path):
    """即使工作区字节恢复为 HEAD，索引中的未提交差异也必须拒绝。"""
    app = tmp_path / "src" / "app.py"
    helper = tmp_path / "src" / "helper.py"
    _write(app, "old app\n")
    _write(helper, "old helper\n")
    _commit_code_baseline(tmp_path, "src/app.py", "src/helper.py")
    state = _impl_state(tmp_path, ["src/app.py"])
    rollback.prepare_impl(str(tmp_path), state)

    helper.write_text("staged helper\n", encoding="utf-8")
    _git(tmp_path, "add", "--", "src/helper.py")
    helper.write_text("old helper\n", encoding="utf-8")
    _impl_document(tmp_path, ["src/app.py", "src/helper.py"])

    with pytest.raises(ValueError, match="没有可信的实施前原内容：src/helper.py"):
        rollback.prepare_impl(str(tmp_path), state)


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

    app.write_text("def run():\n    return 'implemented'\n", encoding="utf-8")
    test_file.write_text("confirmed test\n", encoding="utf-8")
    _append_impl_record(tmp_path, ["src/app.py"])
    rollback.finalize_test_code_changes(str(tmp_path), state)
    rollback.accept_test_code_inventory(str(tmp_path), state)

    valid, detail = rollback.validate_implementation_changes(str(tmp_path), state)
    assert valid is True, detail
    assert "tests/test_app.py" in detail
    assert "测试代码阶段登记且未再变化的非实施计划文件" in detail
    assert rollback.implementation_changed_paths_since_prepare(
        str(tmp_path),
        json.loads(
            (tmp_path / state.rollback.manifest_path).read_text(encoding="utf-8")
        ),
    ) == ["src/app.py"]

    test_file.write_text("changed after return\n", encoding="utf-8")
    valid, detail = rollback.validate_implementation_changes(str(tmp_path), state)

    assert valid is False
    assert "实际修改但不在实施计划" in detail
    assert "tests/test_app.py" in detail


def test_impl_reentry_ignores_unchanged_unplanned_test_baseline_before_confirmation(
    tmp_path,
):
    """测试代码尚未确认时，未变的非实施入口文件不能被倒算成实施新增。"""
    app = tmp_path / "src" / "app.py"
    test_entry = tmp_path / "scripts" / "test_all.sh"
    _write(app, "old app\n")
    _write(test_entry, "#!/bin/sh\nexit 0\n")
    state = _impl_state(tmp_path, ["src/app.py"])
    project_mod.register_test_entry(
        str(tmp_path),
        {"default": ["scripts/test_all.sh"]},
    )
    rollback.prepare_impl(str(tmp_path), state)
    rollback.prepare_test_code_baseline(str(tmp_path), state)
    manifest_path = tmp_path / state.rollback.manifest_path
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest.pop("core_registered_paths")
    rollback._write_manifest(str(tmp_path), state, manifest)

    app.write_text("def run():\n    return 'implemented'\n", encoding="utf-8")
    _append_impl_record(tmp_path, ["src/app.py"])

    valid, detail = rollback.validate_implementation_changes(str(tmp_path), state)

    assert valid is True, detail
    assert "scripts/test_all.sh" in detail
    assert "测试代码阶段登记且未再变化的非实施计划文件" in detail

    test_entry.write_text("#!/bin/sh\nexit 1\n", encoding="utf-8")
    valid, detail = rollback.validate_implementation_changes(str(tmp_path), state)

    assert valid is False
    assert "实际修改但不在实施计划" in detail
    assert "scripts/test_all.sh" in detail


def test_planned_actual_and_recorded_implementation_paths_must_match(tmp_path):
    """计划、真实差异和实施记录的四类不一致必须一次全部报告。"""
    planned_only = tmp_path / "src" / "planned_only.py"
    actual_unrecorded = tmp_path / "src" / "actual_unrecorded.py"
    recorded_without_change = tmp_path / "src" / "recorded_without_change.py"
    outside_plan = tmp_path / "src" / "outside_plan.py"
    for path in (planned_only, actual_unrecorded, recorded_without_change, outside_plan):
        _write(path, "before\n")
    state = _impl_state(
        tmp_path,
        [
            "src/planned_only.py",
            "src/actual_unrecorded.py",
            "src/recorded_without_change.py",
        ],
    )
    _write(
        tmp_path / "spec" / "代码架构设计.md",
        """## 6. 各产品功能的代码设计

| 图中步骤 | 代码位置 |
|---|---|
| 计划外核心路径 | `src/outside_plan.py::run` |
""",
    )
    rollback.prepare_impl(str(tmp_path), state)
    actual_unrecorded.write_text("after\n", encoding="utf-8")
    outside_plan.write_text("after\n", encoding="utf-8")
    _append_impl_record(
        tmp_path,
        ["src/recorded_without_change.py", "src/outside_plan.py"],
    )

    valid, detail = rollback.validate_implementation_changes(str(tmp_path), state)

    assert valid is False
    assert "计划列出但实际未修改" in detail
    assert "实际修改但不在实施计划" in detail
    assert "实际修改但实施后记录未列出" in detail
    assert "实施后记录列出但没有真实差异" in detail


def test_implementation_change_report_keeps_each_path_and_record_location(tmp_path):
    """三方核对报告逐文件给出可处理事实，不能把路径列表塞回一条错误文字。"""
    planned_only = tmp_path / "src" / "planned_only.py"
    actual_unrecorded = tmp_path / "src" / "actual_unrecorded.py"
    recorded_without_change = tmp_path / "src" / "recorded_without_change.py"
    outside_plan = tmp_path / "src" / "outside_plan.py"
    for path in (planned_only, actual_unrecorded, recorded_without_change, outside_plan):
        _write(path, "before\n")
    state = _impl_state(
        tmp_path,
        [
            "src/planned_only.py",
            "src/actual_unrecorded.py",
            "src/recorded_without_change.py",
        ],
    )
    _write(
        tmp_path / "spec" / "代码架构设计.md",
        """## 6. 各产品功能的代码设计

| 图中步骤 | 代码位置 |
|---|---|
| 计划外核心路径 | `src/outside_plan.py::run` |
""",
    )
    rollback.prepare_impl(str(tmp_path), state)
    actual_unrecorded.write_text("after\n", encoding="utf-8")
    outside_plan.write_text("after\n", encoding="utf-8")
    _append_impl_record(
        tmp_path,
        ["src/recorded_without_change.py", "src/outside_plan.py"],
    )

    report = rollback.validate_implementation_changes_report(str(tmp_path), state)

    assert report.passed is False
    facts = {(item.check_id, item.location, item.actual) for item in report.errors}
    assert any(
        check_id == "impl.implementation_relation.planned_but_unchanged"
        and "src/planned_only.py" in actual
        and "impl/上传文件_实施记录.md:" in location
        for check_id, location, actual in facts
    )
    assert any(
        check_id == "impl.implementation_relation.actual_outside_plan"
        and location.startswith("src/outside_plan.py")
        and "src/outside_plan.py" in actual
        for check_id, location, actual in facts
    )
    assert any(
        check_id == "impl.implementation_relation.actual_unrecorded"
        and location.startswith("src/actual_unrecorded.py")
        and "src/actual_unrecorded.py" in actual
        for check_id, location, actual in facts
    )
    assert any(
        check_id == "impl.implementation_relation.recorded_without_change"
        and "impl/上传文件_实施记录.md:" in location
        and "src/recorded_without_change.py" in actual
        for check_id, location, actual in facts
    )
    assert all("['src/" not in item.actual for item in report.errors)


def test_invalid_record_path_blocks_only_the_dependent_set_comparison(tmp_path):
    """记录文件列无效时保留真实行列，三方集合只能明确标为未检查。"""
    app = tmp_path / "src" / "app.py"
    _write(app, "def run():\n    return 'before'\n")
    state = _impl_state(tmp_path, ["src/app.py"])
    rollback.prepare_impl(str(tmp_path), state)
    app.write_text("def run():\n    return 'after'\n", encoding="utf-8")
    document = tmp_path / "impl" / "上传文件_实施记录.md"
    document.write_text(
        document.read_text(encoding="utf-8")
        + """

## 3. 实施后记录

### 3.1 实际代码修改

| 文件 | 类、函数或配置项 | 实际修改的代码逻辑 | 数据、状态或输出的实际变化 | 对应验收条件 |
| --- | --- | --- | --- | --- |
| 暂无 | 暂无 | 暂无 | 暂无 | 暂无 |
""",
        encoding="utf-8",
    )

    report = rollback.validate_implementation_changes_report(str(tmp_path), state)

    assert report.passed is False
    assert len(report.errors) == 1
    path_error = report.errors[0]
    assert path_error.check_id == "impl.implementation_record.path_invalid"
    assert path_error.location.endswith("，“文件”列")
    assert "实施后记录的“文件”列" in path_error.actual
    assert "代码修改计划包含" not in path_error.actual
    assert len(report.not_checked) == 1
    relation = report.not_checked[0]
    assert relation.check_id == "impl.implementation_relation.not_checked"
    assert relation.depends_on == (path_error.check_id,)
    assert "实际差异文件=['src/app.py']" in relation.evidence


def test_complete_inventory_reports_unregistered_modified_and_new_files(tmp_path):
    """观察全集独立于计划集合，未登记旧文件和新测试文件都必须被发现。"""
    app = tmp_path / "src" / "app.py"
    hidden = tmp_path / "src" / "hidden.py"
    new_test = tmp_path / "tests" / "test_new.py"
    _write(app, "def run():\n    return 'before'\n")
    _write(hidden, "def hidden():\n    return 'before'\n")
    state = _impl_state(tmp_path, ["src/app.py"])
    _freeze_complete_impl_inventory(tmp_path, state)
    rollback.prepare_impl(str(tmp_path), state)

    app.write_text("def run():\n    return 'after'\n", encoding="utf-8")
    hidden.write_text("def hidden():\n    return 'after'\n", encoding="utf-8")
    _write(new_test, "def test_new():\n    assert True\n")
    _append_impl_record(
        tmp_path,
        ["src/app.py", "src/hidden.py", "tests/test_new.py"],
    )

    report = rollback.validate_implementation_changes_report(str(tmp_path), state)

    assert report.passed is False
    outside_plan = [
        item
        for item in report.errors
        if item.check_id == "impl.implementation_relation.actual_outside_plan"
    ]
    assert [item.location.split("（", 1)[0] for item in outside_plan] == [
        "src/hidden.py",
        "tests/test_new.py",
    ]
    assert all("恢复该文件到实施前内容" in item.next_action for item in outside_plan)


def test_complete_inventory_detects_deleted_unregistered_file_and_blocks_restore(
    tmp_path,
):
    """完整基线中的未登记文件被删除时，中止不能假装已安全恢复。"""
    app = tmp_path / "src" / "app.py"
    hidden = tmp_path / "src" / "hidden.py"
    _write(app, "def run():\n    return 'before'\n")
    _write(hidden, "def hidden():\n    return 'before'\n")
    state = _impl_state(tmp_path, ["src/app.py"])
    _freeze_complete_impl_inventory(tmp_path, state)
    rollback.prepare_impl(str(tmp_path), state)
    hidden.unlink()

    manifest = json.loads(
        (tmp_path / state.rollback.manifest_path).read_text(encoding="utf-8")
    )
    assert rollback.changed_paths_since_prepare(str(tmp_path), manifest) == [
        "src/hidden.py"
    ]
    with pytest.raises(ValueError, match="src/hidden.py"):
        rollback.restore(str(tmp_path), state)


def test_prepare_rejects_unregistered_change_after_impl_entry(tmp_path):
    """入场到保存副本之间修改未登记文件，不能把修改后内容当成原内容。"""
    app = tmp_path / "src" / "app.py"
    hidden = tmp_path / "src" / "hidden.py"
    _write(app, "def run():\n    return 'before'\n")
    _write(hidden, "def hidden():\n    return 'before'\n")
    state = _impl_state(tmp_path, ["src/app.py"])
    _freeze_complete_impl_inventory(tmp_path, state)
    hidden.write_text("def hidden():\n    return 'changed too early'\n", encoding="utf-8")

    with pytest.raises(ValueError, match=r"修改=\['src/hidden.py'\]"):
        rollback.prepare_impl(str(tmp_path), state)


def test_legacy_manifest_does_not_invent_changes_for_unrecorded_core_paths(tmp_path):
    """旧清单没有采样的路径不得因新版登记范围扩大而被倒推成新增。"""
    app = tmp_path / "src" / "app.py"
    architecture_only = tmp_path / "src" / "architecture_only.py"
    _write(app, "before\n")
    _write(architecture_only, "unchanged\n")
    state = _impl_state(tmp_path, ["src/app.py"])
    _write(
        tmp_path / "spec" / "代码架构设计.md",
        """## 6. 各产品功能的代码设计

| 图中步骤 | 代码位置 |
|---|---|
| 已登记但不在本轮计划 | `src/architecture_only.py::run` |
""",
    )
    rollback.prepare_impl(str(tmp_path), state)
    manifest_path = tmp_path / state.rollback.manifest_path
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    assert "src/architecture_only.py" in manifest["core_registered_paths"]

    legacy_manifest = json.loads(json.dumps(manifest))
    legacy_manifest.pop("core_registered_paths")
    legacy_manifest["initial_inventory"].pop("src/architecture_only.py")

    assert rollback.changed_paths_since_prepare(str(tmp_path), legacy_manifest) == []

    app.write_text("after\n", encoding="utf-8")
    assert rollback.changed_paths_since_prepare(str(tmp_path), legacy_manifest) == [
        "src/app.py"
    ]


def test_existing_implementation_checks_plan_record_and_real_files(tmp_path):
    """既有代码例外只核对计划、记录和当前文件，不声称比较基线差异。"""
    app = tmp_path / "src" / "app.py"
    _write(app, "def run():\n    return 'already implemented'\n")
    state = _impl_state(tmp_path, ["src/app.py"])
    _append_impl_record(tmp_path, ["src/app.py"])

    valid, detail = rollback.validate_existing_implementation_paths(str(tmp_path), state)

    assert valid is True, detail
    assert "没有声称验证基线后的真实差异" in detail

    app.unlink()
    valid, detail = rollback.validate_existing_implementation_paths(str(tmp_path), state)
    assert valid is False
    assert "不是当前项目内普通文件" in detail


def test_implementation_record_reports_every_invalid_row_fact_at_once(tmp_path):
    """Workflow-Test
    主题：所有阶段门禁失败时一次指出全部真实原因和改法
    测试项：TC-08 实施记录一行的全部真实错误一次说清
    验收条件：AC-05 代码位置泛称指出文件内可定位名称规则
    测试方式：自动化测试
    测试层级：模块测试
    产品入口：`workflow gate impl` 的实施记录与真实代码核对
    测试入口：`tests/test_rollback.py::test_implementation_record_reports_every_invalid_row_fact_at_once`
    代码入口：`src/workflow_loop/rollback.py::validate_implementation_changes_report`
    准备数据：建立真实修改文件 `src/app.py`，实施后记录同一行写入位置泛称“组件”、逻辑占位值、输出占位值和不存在的 AC-99。
    执行动作：执行实施变化三方核对。
    关键断言：同一次输出定位实施记录文件和错误行，显示目标代码文件与“组件”原值，说明必须改为文件内真实函数名、类名或配置项；同一行其它独立错误也全部出现。
    预期证据：结构化报告需精确匹配该测试入口，实际执行数为 1，跳过数、失败数和错误数均为 0；断言需包含记录位置、原值、真实名称规则、两个占位错误和 AC 错误。
    """
    app = tmp_path / "src" / "app.py"
    _write(app, "# 组件不是代码符号\ndef run():\n    return 'before'\n")
    state = _impl_state(tmp_path, ["src/app.py"])
    rollback.prepare_impl(str(tmp_path), state)
    _write(app, "# 组件不是代码符号\ndef run():\n    return 'after'\n")
    document = tmp_path / "impl" / "上传文件_实施记录.md"
    document.write_text(
        document.read_text(encoding="utf-8")
        + """

## 3. 实施后记录

### 3.1 实际代码修改

| 文件 | 类、函数或配置项 | 实际修改的代码逻辑 | 数据、状态或输出的实际变化 | 对应验收条件 |
| --- | --- | --- | --- | --- |
| src/app.py | 组件 | TODO | 符合预期 | AC-99 |
""",
        encoding="utf-8",
    )

    valid, detail = rollback.validate_implementation_changes(str(tmp_path), state)

    assert valid is False
    assert "impl/上传文件_实施记录.md" in detail
    assert "记录位置='组件'" in detail
    assert "代码位置无法在当前文件中定位" in detail
    assert "必须填写目标文件内可定位的真实函数名、类名或配置项" in detail
    assert "“组件”等泛称无效" in detail
    assert "实际修改的代码逻辑使用占位内容" in detail
    assert "数据、状态或输出的实际变化使用占位内容" in detail
    assert "AC-99" in detail
    assert "验收计划中不存在" in detail


def test_code_location_requires_a_real_declaration_not_a_comment(tmp_path):
    """位置列中的真实函数名可以通过，注释里的同名泛称不能通过。"""
    app = tmp_path / "src" / "app.py"
    _write(app, "# component is only a comment\ndef run():\n    return True\n")

    assert rollback._location_exists(str(tmp_path), "src/app.py", "run") is True
    assert rollback._location_exists(str(tmp_path), "src/app.py", "component") is False


def test_document_location_requires_an_exact_markdown_heading(tmp_path):
    """模板和规范文件可用真实标题定位，普通段落里的同词不能通过。"""
    document = tmp_path / "docs" / "rules.md"
    _write(document, "# 工作规范\n\n## 门禁失败信息\n\n诊断只是普通段落文字。\n")

    assert rollback._location_exists(
        str(tmp_path), "docs/rules.md", "门禁失败信息"
    ) is True
    assert rollback._location_exists(str(tmp_path), "docs/rules.md", "诊断") is False


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
