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


def _append_impl_record_rows(
    root: Path,
    rows: list[tuple[str, str]],
    *,
    location_header: str = "类、函数或配置项",
) -> None:
    """写入指定的实施后位置，供行号范围核对场景复用。"""

    document = root / "impl" / "上传文件_实施记录.md"
    records = "\n".join(
        f"| {path} | {location} | 将该位置更新为实施后的真实内容 | "
        "读取文件可观察到该位置的当前输出 | AC-01 |"
        for path, location in rows
    )
    document.write_text(
        document.read_text(encoding="utf-8")
        + f"""

## 3. 实施后记录

### 3.1 实际代码修改

| 文件 | {location_header} | 实际修改的代码逻辑 | 数据、状态或输出的实际变化 | 对应验收条件 |
| --- | --- | --- | --- | --- |
{records}
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
    验收条件：AC-05 代码位置泛称指出最终文件行号范围规则
    测试方式：自动化测试
    测试层级：模块测试
    产品入口：`workflow gate impl` 的实施记录与真实代码核对
    测试入口：`tests/test_rollback.py::test_implementation_record_reports_every_invalid_row_fact_at_once`
    代码入口：`src/workflow_loop/rollback.py::validate_implementation_changes_report`
    准备数据：建立真实修改文件 `src/app.py`，实施后记录同一行写入位置泛称“组件”、逻辑占位值、输出占位值和不存在的 AC-99。
    执行动作：执行实施变化三方核对。
    关键断言：同一次输出定位实施记录文件和错误行，显示目标代码文件与“组件”原值，说明必须改为最终文件行号范围；同一行其它独立错误也全部出现。
    预期证据：结构化报告需精确匹配该测试入口，实际执行数为 1，跳过数、失败数和错误数均为 0；断言需包含记录位置、原值、行号范围规则、两个占位错误和 AC 错误。
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
    assert "使用占位内容：'组件'" in detail
    assert "实际修改的代码逻辑使用占位内容" in detail
    assert "数据、状态或输出的实际变化使用占位内容" in detail
    assert "AC-99" in detail
    assert "验收计划中不存在" in detail


def test_line_ranges_cover_tsx_css_and_destructuring_without_declaration_regex(tmp_path):
    """行号范围直接覆盖 TSX、CSS 和解构差异，不依赖声明语法。"""
    sidebar = tmp_path / "src" / "Sidebar.tsx"
    styles = tmp_path / "src" / "docs.css"
    search = tmp_path / "src" / "search.ts"
    _write(
        sidebar,
        "export default function Sidebar() {\n"
        "  return <aside />;\n"
        "}\n",
    )
    _write(
        styles,
        ":root {\n"
        "  --primary: #111;\n"
        "}\n"
        "\n"
        ".docs-layout {\n"
        "  color: var(--primary);\n"
        "}\n",
    )
    _write(search, "export const refresh = () => false;\n")
    paths = ["src/Sidebar.tsx", "src/docs.css", "src/search.ts"]
    state = _impl_state(tmp_path, paths)
    rollback.prepare_impl(str(tmp_path), state)

    _write(
        sidebar,
        "export default function Sidebar() {\n"
        "  const [documents, setDocuments] = useDocuments();\n"
        "  return <aside>{documents.length}</aside>;\n"
        "}\n",
    )
    _write(
        styles,
        ":root {\n"
        "  --primary: #111;\n"
        "  --gray-50: #f5f5f5;\n"
        "}\n"
        "\n"
        ".docs-layout {\n"
        "  display: grid;\n"
        "  color: var(--primary);\n"
        "}\n",
    )
    _write(
        search,
        "const [documents, setDocuments] = useDocuments();\n"
        "export const refresh = () => documents.length > 0;\n",
    )
    _append_impl_record_rows(
        tmp_path,
        [
            ("src/Sidebar.tsx", "`L2-L3`"),
            ("src/docs.css", "`L3-L7`"),
            ("src/search.ts", "`L1-L2`"),
        ],
    )

    valid, detail = rollback.validate_implementation_changes(str(tmp_path), state)

    assert valid is True, detail


def test_legacy_location_name_does_not_need_declaration_regex(tmp_path):
    """兼容期内，旧的具体符号名称不再因 default export 等语法失败。"""
    sidebar = tmp_path / "src" / "Sidebar.tsx"
    _write(
        sidebar,
        "export default function Sidebar() {\n"
        "  return <aside />;\n"
        "}\n",
    )
    state = _impl_state(tmp_path, ["src/Sidebar.tsx"])
    rollback.prepare_impl(str(tmp_path), state)
    _write(
        sidebar,
        "export default function Sidebar() {\n"
        "  return <aside aria-label=\"navigation\" />;\n"
        "}\n",
    )
    _append_impl_record_rows(tmp_path, [("src/Sidebar.tsx", "Sidebar")])

    valid, detail = rollback.validate_implementation_changes(str(tmp_path), state)

    assert valid is True, detail


def test_new_location_header_requires_and_accepts_a_final_line_range(tmp_path):
    """新模板使用公开行号格式，不再把代码符号名称交给正则猜测。"""
    app = tmp_path / "src" / "app.py"
    _write(app, "def run():\n    return 'before'\n")
    state = _impl_state(tmp_path, ["src/app.py"])
    rollback.prepare_impl(str(tmp_path), state)
    _write(app, "def run():\n    return 'after'\n")
    _append_impl_record_rows(
        tmp_path,
        [("src/app.py", "`L2-L2`")],
        location_header="代码位置（最终文件）",
    )

    valid, detail = rollback.validate_implementation_changes(str(tmp_path), state)

    assert valid is True, detail


def test_new_location_header_rejects_a_name_without_a_line_range(tmp_path):
    """旧名称仅为兼容保留；新表头必须给出可验证的最终行号范围。"""
    app = tmp_path / "src" / "app.py"
    _write(app, "def run():\n    return 'before'\n")
    state = _impl_state(tmp_path, ["src/app.py"])
    rollback.prepare_impl(str(tmp_path), state)
    _write(app, "def run():\n    return 'after'\n")
    _append_impl_record_rows(
        tmp_path,
        [("src/app.py", "run")],
        location_header="代码位置（最终文件）",
    )

    report = rollback.validate_implementation_changes_report(str(tmp_path), state)

    errors = [
        item
        for item in report.errors
        if item.check_id == "impl.implementation_record.location_range_required"
    ]
    assert len(errors) == 1
    assert "代码位置（最终文件）" in errors[0].location
    assert "L12-L34" in errors[0].next_action


def test_new_line_ranges_must_cover_every_changed_hunk(tmp_path):
    """一条有效范围不能掩盖同文件中另一处未记录的真实改动。"""
    app = tmp_path / "src" / "app.py"
    _write(app, "first = 1\nkeep_one = True\nsecond = 2\nkeep_two = True\n")
    state = _impl_state(tmp_path, ["src/app.py"])
    rollback.prepare_impl(str(tmp_path), state)
    _write(app, "first = 10\nkeep_one = True\nsecond = 20\nkeep_two = True\n")
    _append_impl_record_rows(
        tmp_path,
        [("src/app.py", "`L1-L1`")],
        location_header="代码位置（最终文件）",
    )

    report = rollback.validate_implementation_changes_report(str(tmp_path), state)

    errors = [
        item
        for item in report.errors
        if item.check_id == "impl.implementation_record.location_range_coverage_missing"
    ]
    assert len(errors) == 1
    assert "最终 L3-L3" in errors[0].actual


def test_one_new_line_range_can_cover_multiple_changed_hunks(tmp_path):
    """同一文件一行记录覆盖多个相邻或分散改动时可以使用更大的行范围。"""
    app = tmp_path / "src" / "app.py"
    _write(app, "first = 1\nkeep_one = True\nsecond = 2\nkeep_two = True\n")
    state = _impl_state(tmp_path, ["src/app.py"])
    rollback.prepare_impl(str(tmp_path), state)
    _write(app, "first = 10\nkeep_one = True\nsecond = 20\nkeep_two = True\n")
    _append_impl_record_rows(
        tmp_path,
        [("src/app.py", "`L1-L3`")],
        location_header="代码位置（最终文件）",
    )

    valid, detail = rollback.validate_implementation_changes(str(tmp_path), state)

    assert valid is True, detail


@pytest.mark.parametrize(
    ("location", "check_id"),
    [
        ("`L2`", "impl.implementation_record.location_range_invalid"),
        ("`L3-L1`", "impl.implementation_record.location_range_invalid"),
        ("`L99-L100`", "impl.implementation_record.location_range_out_of_bounds"),
    ],
)
def test_line_range_reports_malformed_and_out_of_bounds_values(
    tmp_path,
    location,
    check_id,
):
    """格式错误和越界范围直接给出可填写的行号格式。"""
    app = tmp_path / "src" / "app.py"
    _write(app, "def run():\n    return 'before'\n")
    state = _impl_state(tmp_path, ["src/app.py"])
    rollback.prepare_impl(str(tmp_path), state)
    _write(app, "def run():\n    return 'after'\n")
    _append_impl_record_rows(tmp_path, [("src/app.py", location)])

    report = rollback.validate_implementation_changes_report(str(tmp_path), state)

    errors = [item for item in report.errors if item.check_id == check_id]
    assert len(errors) == 1
    assert "impl/上传文件_实施记录.md:" in errors[0].location
    assert location in errors[0].actual or location in errors[0].evidence


def test_line_range_must_intersect_a_real_final_file_change(tmp_path):
    """合法但未修改的最终行不能冒充本轮代码位置。"""
    app = tmp_path / "src" / "app.py"
    _write(
        app,
        "def run():\n"
        "    return 'before'\n"
        "\n"
        "UNTOUCHED = True\n",
    )
    state = _impl_state(tmp_path, ["src/app.py"])
    rollback.prepare_impl(str(tmp_path), state)
    _write(
        app,
        "def run():\n"
        "    return 'after'\n"
        "\n"
        "UNTOUCHED = True\n",
    )
    _append_impl_record_rows(tmp_path, [("src/app.py", "`L4-L4`")])

    report = rollback.validate_implementation_changes_report(str(tmp_path), state)

    errors = [
        item
        for item in report.errors
        if item.check_id == "impl.implementation_record.location_range_unchanged"
    ]
    assert len(errors) == 1
    assert "最终文件真实差异范围=L2-L2" in errors[0].evidence


def test_line_ranges_support_new_files_and_whole_file_deletion(tmp_path):
    """新增文件使用最终行号，整文件删除保留专用明确标记。"""
    removed = tmp_path / "src" / "removed.py"
    _write(removed, "def obsolete():\n    return True\n")
    paths = ["src/new.ts", "src/removed.py"]
    state = _impl_state(tmp_path, paths)
    rollback.prepare_impl(str(tmp_path), state)

    _write(
        tmp_path / "src" / "new.ts",
        "export const name = 'new';\n"
        "export const enabled = true;\n",
    )
    removed.unlink()
    _append_impl_record_rows(
        tmp_path,
        [
            ("src/new.ts", "`L1-L2`"),
            ("src/removed.py", "删除整个文件"),
        ],
    )

    valid, detail = rollback.validate_implementation_changes(str(tmp_path), state)

    assert valid is True, detail


def test_baseline_line_range_supports_partial_line_deletion(tmp_path):
    """最终文件不存在的旧行可按实施前副本的行号记录。"""
    app = tmp_path / "src" / "app.py"
    _write(app, "first\nremoved\nlast\n")
    state = _impl_state(tmp_path, ["src/app.py"])
    rollback.prepare_impl(str(tmp_path), state)
    _write(app, "first\nlast\n")
    _append_impl_record_rows(tmp_path, [("src/app.py", "`基线 L2-L2`")])

    valid, detail = rollback.validate_implementation_changes(str(tmp_path), state)

    assert valid is True, detail


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


def test_planned_code_paths_and_plan_hash_read_from_impl_record_table(tmp_path: Path) -> None:
    """R14（断言十三）：表模式下计划文件清单和计划哈希从 impl_record 表取，不读生成 md。"""
    from workflow_loop import records as records_mod
    from workflow_loop import state as state_mod

    root = tmp_path / "proj"
    root.mkdir()
    (root / "src").mkdir(parents=True)
    _write(root / "src" / "a.py", "x = 1\n")
    _write(root / "src" / "b.py", "y = 2\n")
    state = state_mod.WorkflowState(
        workflow_id="wf-table", intent="product_change", topics=["主题A"]
    )
    state.current_stage = "impl"
    state.stages["impl"] = state_mod.StageState()
    state_mod.save_state(str(root), state)

    relative = records_mod.create_or_complete_table(
        str(root), "wf-table", "impl_record", "主题A"
    )
    table_path = root / relative
    table = json.loads(table_path.read_text(encoding="utf-8"))
    table["代码修改计划"] = [
        {"文件": "src/a.py", "计划修改内容": "修复", "对应验收条件": "AC-01"},
        {"文件": "src/b.py", "计划修改内容": "新增", "对应验收条件": "AC-02"},
    ]
    table_path.write_text(json.dumps(table, ensure_ascii=False, indent=2), encoding="utf-8")

    # 不创建生成的 impl/<主题>_实施记录.md；表模式下不应读它
    paths = rollback.planned_code_paths(str(root), ["主题A"])
    assert paths == ["src/a.py", "src/b.py"]

    plan_hash = rollback.compute_plan_hash(str(root), ["主题A"])
    assert isinstance(plan_hash, str) and plan_hash
    # 计划内容变化后哈希应变化（证明从表内容算，不读 md）
    table["代码修改计划"][0]["计划修改内容"] = "改了计划"
    table_path.write_text(json.dumps(table, ensure_ascii=False, indent=2), encoding="utf-8")
    assert rollback.compute_plan_hash(str(root), ["主题A"]) != plan_hash


def test_flow_only_marker_excluded_from_planned_paths(tmp_path: Path) -> None:
    """R19⑥/R33：表模式下"无代码修改（流程动作）"标记行不进计划文件集合，
    不再按路径解析报 path_invalid；真实行照常收集。"""
    from workflow_loop import records as records_mod
    from workflow_loop import state as state_mod

    root = tmp_path / "proj"
    root.mkdir()
    (root / "src").mkdir(parents=True)
    _write(root / "src" / "a.py", "x = 1\n")
    state = state_mod.WorkflowState(
        workflow_id="wf-table", intent="product_change", topics=["主题A", "主题B"]
    )
    state.current_stage = "impl"
    state.stages["impl"] = state_mod.StageState()
    state_mod.save_state(str(root), state)

    plan_columns = records_mod.KIND_SCHEMAS["impl_record"]["row_lists"]["代码修改计划"]["columns"]
    for topic, file_value in (("主题A", "src/a.py"), ("主题B", records_mod.FLOW_ONLY_MARKER)):
        relative = records_mod.create_or_complete_table(
            str(root), "wf-table", "impl_record", topic
        )
        table_path = root / relative
        table = json.loads(table_path.read_text(encoding="utf-8"))
        row = dict.fromkeys(plan_columns, "占位")
        row.update({
            "顺序": "1",
            "文件": file_value,
            "类、函数或配置项": "流程动作" if file_value == records_mod.FLOW_ONLY_MARKER else "status_hint",
            "当前逻辑": "已完成轮次仍提示执行 done",
            "计划修改内容": "在 status_hint 中删除已完成提示分支" if file_value != records_mod.FLOW_ONLY_MARKER else "执行验收重做流程并核对生成文档，本轮不修改代码",
            "数据、状态或输出变化": "完成输出不再提示旧命令",
            "对应验收条件": "AC-01",
            "前置步骤": "无",
        })
        row["顺序"] = "1"
        table["代码修改计划"] = [row]
        table_path.write_text(json.dumps(table, ensure_ascii=False, indent=2), encoding="utf-8")

    paths = rollback.planned_code_paths(str(root), ["主题A", "主题B"])
    assert paths == ["src/a.py"]

    changes, diagnostics = rollback._planned_code_changes(str(root), ["主题A", "主题B"])
    assert diagnostics == []
    assert {change.topic for change in changes} == {"主题A"}


def test_flow_only_topic_skips_recorded_empty_diagnostic(tmp_path: Path) -> None:
    """R19⑥/R33：纯流程主题的 impl_record 表实际代码修改为空时，
    三方核对不再报 table_empty，也不把标记当文件记录。

Workflow-Test
主题：门禁实质内容校验
测试项：TC-05 纯流程主题不触发实际修改为空错误
验收条件：AC-04 纯流程主题按标记豁免
测试方式：自动化测试
测试层级：单元测试
产品入口：workflow gate impl 对纯流程主题的三方核对
测试入口：tests/test_rollback.py::test_flow_only_topic_skips_recorded_empty_diagnostic
代码入口：src/workflow_loop/rollback.py::_recorded_code_changes_with_diagnostics
准备数据：构造纯流程标记主题与其实施记录表
执行动作：执行实际改动核对
关键断言：实际代码修改为空不产生实施记录清单为空类错误
预期证据：pytest 结构化 junit 报告与退出码 0
    """
    from workflow_loop import records as records_mod
    from workflow_loop import state as state_mod

    root = tmp_path / "proj"
    root.mkdir()
    state = state_mod.WorkflowState(
        workflow_id="wf-table", intent="product_change", topics=["主题B"]
    )
    state.current_stage = "impl"
    state.stages["impl"] = state_mod.StageState()
    state_mod.save_state(str(root), state)

    relative = records_mod.create_or_complete_table(
        str(root), "wf-table", "impl_record", "主题B"
    )
    table_path = root / relative
    table = json.loads(table_path.read_text(encoding="utf-8"))
    plan_columns = records_mod.KIND_SCHEMAS["impl_record"]["row_lists"]["代码修改计划"]["columns"]
    row = dict.fromkeys(plan_columns, "占位说明内容需要足够长以免误判")
    row.update({
        "顺序": "1",
        "文件": records_mod.FLOW_ONLY_MARKER,
        "类、函数或配置项": "workflow return 后重走环节",
        "当前逻辑": "验收文档由旧渲染器生成缺少新栏位",
        "计划修改内容": "实施完成后执行 return 用 v2 表重新生成验收文档并核对",
        "数据、状态或输出变化": "验收文档全部由 v2 表重新生成",
        "对应验收条件": "AC-01",
        "前置步骤": "无",
    })
    table["代码修改计划"] = [row]
    table["实施依据"] = [
        {
            "依据类型": "验收条件",
            "依据编号": "JU-01",
            "具体内容": "AC-01：验收文档按 v2 表重新生成并核对",
            "文档位置": "[AC-01](../acceptance/主题B_验收计划.md#ac-01)",
        }
    ]
    table["预期产品结果"] = ["用户看到按新表重新生成的验收文档，不再残留占位句"]
    table["未决问题"] = ["暂无"]
    table_path.write_text(json.dumps(table, ensure_ascii=False, indent=2), encoding="utf-8")

    changes, diagnostics = rollback._recorded_code_changes_with_diagnostics(
        str(root), ["主题B"]
    )
    assert changes == []
    assert not any(
        item.check_id == "impl.implementation_record.table_empty"
        for item in diagnostics
    ), diagnostics
    # 混合表（真实计划行 + 标记行）不享受豁免：实际代码修改为空仍报 table_empty
    real_row = dict(row)
    real_row.update({
        "顺序": "2",
        "文件": "src/a.py",
        "类、函数或配置项": "status_hint",
        "计划修改内容": "在 status_hint 中删除已完成轮次仍提示 done 的分支",
        "当前逻辑": "已完成轮次仍提示执行 done",
    })
    real_row["文件"] = "src/a.py"
    table["代码修改计划"].append(real_row)
    table_path.write_text(json.dumps(table, ensure_ascii=False, indent=2), encoding="utf-8")
    _changes, diagnostics = rollback._recorded_code_changes_with_diagnostics(
        str(root), ["主题B"]
    )
    assert any(
        item.check_id == "impl.implementation_record.table_empty"
        for item in diagnostics
    ), diagnostics
