import json
from pathlib import Path

import pytest

from workflow_loop import rollback as rollback_mod
from workflow_loop.state import GateState, StageState, WorkflowState, save_state
from workflow_loop.verification import compute_non_test_code_snapshot_hash


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _setup(tmp_path: Path, *, existing_code: bool = False) -> WorkflowState:
    topic = "上传文件"
    _write(
        tmp_path / "impl" / "index.md",
        """# 实施索引

## test

| 展示顺序 | 验收主题 | 前置主题 | 验收计划 | 测试计划 | 实施文档 |
|---|---|---|---|---|---|
| 1 | 上传文件 | 无 | [验收计划](../acceptance/上传文件_plan.md) | [测试计划](../qa/上传文件_plan.md) | [实施文档](./上传文件.md) |
""",
    )
    _write(
        tmp_path / "impl" / f"{topic}.md",
        """# 【实施】上传文件

- 工作流编号：test
- 验收主题：上传文件

## 2. 实施前计划

### 2.2 代码修改计划

| 顺序 | 文件 | 类、函数或配置项 | 当前逻辑 | 计划修改的具体逻辑 | 数据、状态或输出变化 | 对应验收条件和测试项 | 前置步骤 |
|---|---|---|---|---|---|---|---|
| 1 | src/app.py | run | 暂无 | 新增处理逻辑 | 输出改变 | AC-01；TC-01 | 无 |
""",
    )
    if existing_code:
        _write(tmp_path / "src" / "app.py", "return 'old'\n")
    state = WorkflowState(
        workflow_id="test",
        intent="from_scratch",
        current_stage="impl",
        topics=[topic],
        stages={
            "impl": StageState(
                gate=GateState(discussion_complete=True),
                code_baseline_hash=compute_non_test_code_snapshot_hash(str(tmp_path)),
            )
        },
    )
    save_state(str(tmp_path), state)
    return state


def test_prepare_and_restore_does_not_copy_the_whole_project(tmp_path):
    state = _setup(tmp_path)

    detail, paths = rollback_mod.prepare_impl(str(tmp_path), state)
    save_state(str(tmp_path), state)

    assert paths == ["src/app.py"]
    assert "回退清单和文件副本完整" in detail
    assert (tmp_path / ".workflow_loop" / "rollback" / "test" / "impl" / "manifest.json").is_file()
    assert not (tmp_path / ".workflow_loop" / "rollback" / "test.tar").exists()

    _write(tmp_path / "src" / "app.py", "return 'new'\n")
    ok, detail = rollback_mod.validate_implementation_changes(str(tmp_path), state)
    assert ok is True, detail

    restored = rollback_mod.restore(str(tmp_path), state)
    assert restored == ["src/app.py"]
    assert not (tmp_path / "src" / "app.py").exists()


def test_restore_preserves_original_existing_file(tmp_path):
    state = _setup(tmp_path, existing_code=True)
    rollback_mod.prepare_impl(str(tmp_path), state)

    _write(tmp_path / "src" / "app.py", "return 'new'\n")
    rollback_mod.restore(str(tmp_path), state)

    assert (tmp_path / "src" / "app.py").read_text(encoding="utf-8") == "return 'old'\n"


def test_impl_gate_rejects_unplanned_file_change(tmp_path):
    state = _setup(tmp_path)
    rollback_mod.prepare_impl(str(tmp_path), state)
    _write(tmp_path / "README.md", "unplanned change\n")

    ok, detail = rollback_mod.validate_implementation_changes(str(tmp_path), state)

    assert ok is False
    assert "实施计划外" in detail
    assert "README.md" in detail


def test_tampered_backup_blocks_restore(tmp_path):
    state = _setup(tmp_path, existing_code=True)
    rollback_mod.prepare_impl(str(tmp_path), state)
    manifest = tmp_path / ".workflow_loop" / "rollback" / "test" / "impl" / "manifest.json"
    data = json.loads(manifest.read_text(encoding="utf-8"))
    backup_path = manifest.parent / data["entries"]["src/app.py"]["backup_path"]
    backup_path.write_bytes(b"return 'wrong'\n")

    with pytest.raises(ValueError, match="哈希|副本"):
        rollback_mod.restore(str(tmp_path), state)


def test_new_test_file_is_removed_after_abort_restore(tmp_path):
    state = _setup(tmp_path)
    rollback_mod.prepare_impl(str(tmp_path), state)
    rollback_mod.prepare_test_code_baseline(str(tmp_path), state)
    _write(tmp_path / "tests" / "test_app.py", "def test_app(): pass\n")
    rollback_mod.finalize_test_code_changes(str(tmp_path), state)

    rollback_mod.restore(str(tmp_path), state)

    assert not (tmp_path / "tests" / "test_app.py").exists()


def test_restore_rejects_parent_directory_replaced_by_symlink(tmp_path):
    state = _setup(tmp_path, existing_code=True)
    rollback_mod.prepare_impl(str(tmp_path), state)

    original_src = tmp_path / "src"
    original_src.rename(tmp_path / "src_original")
    outside = tmp_path / "outside"
    outside.mkdir()
    original_src.symlink_to(outside, target_is_directory=True)

    with pytest.raises(ValueError, match="符号链接"):
        rollback_mod.restore(str(tmp_path), state)

    assert not (outside / "app.py").exists()
