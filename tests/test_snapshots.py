import os

import pytest

from workflow_loop.snapshots import (
    collect_snapshot,
    compare_snapshots,
    normalize_registered_paths,
    snapshot_from_dict,
)


def test_snapshot_reads_only_registered_files(tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "core.py").write_text("before\n", encoding="utf-8")
    (tmp_path / ".next").mkdir()
    generated = tmp_path / ".next" / "bundle.js"
    generated.write_text("one\n", encoding="utf-8")
    (tmp_path / "node_modules").mkdir()
    dependency = tmp_path / "node_modules" / "pkg.js"
    dependency.write_text("one\n", encoding="utf-8")

    before = collect_snapshot(str(tmp_path), ["src/core.py"])
    generated.write_text("two\n", encoding="utf-8")
    dependency.write_text("two\n", encoding="utf-8")
    after = collect_snapshot(str(tmp_path), ["src/core.py"])

    assert before.aggregate_hash == after.aggregate_hash
    assert compare_snapshots(before, after) == {
        "added": [],
        "modified": [],
        "deleted": [],
        "type_changed": [],
        "not_checked": [],
    }


def test_snapshot_reports_added_modified_deleted_and_type_changed(tmp_path):
    for name, content in {
        "modified.py": "old",
        "deleted.py": "old",
        "type.py": "old",
    }.items():
        (tmp_path / name).write_text(content, encoding="utf-8")
    paths = ["added.py", "modified.py", "deleted.py", "type.py"]
    before = collect_snapshot(str(tmp_path), paths)

    (tmp_path / "added.py").write_text("new", encoding="utf-8")
    (tmp_path / "modified.py").write_text("new", encoding="utf-8")
    (tmp_path / "deleted.py").unlink()
    (tmp_path / "type.py").unlink()
    (tmp_path / "type.py").mkdir()
    after = collect_snapshot(str(tmp_path), paths)

    assert compare_snapshots(before, after) == {
        "added": ["added.py"],
        "modified": ["modified.py"],
        "deleted": ["deleted.py"],
        "type_changed": ["type.py"],
        "not_checked": [],
    }


def test_snapshot_without_baseline_marks_every_path_not_checked(tmp_path):
    (tmp_path / "core.py").write_text("x", encoding="utf-8")
    current = collect_snapshot(str(tmp_path), ["core.py", "future.py"])
    assert compare_snapshots(None, current)["not_checked"] == ["core.py", "future.py"]


def test_registered_paths_reject_escape_and_symlink(tmp_path):
    with pytest.raises(ValueError, match="项目内相对路径"):
        normalize_registered_paths(str(tmp_path), ["../outside.py"])
    target = tmp_path / "target.py"
    target.write_text("x", encoding="utf-8")
    link = tmp_path / "link.py"
    try:
        os.symlink(target, link)
    except (OSError, NotImplementedError):
        pytest.skip("当前平台不能创建符号链接")
    with pytest.raises(ValueError, match="符号链接"):
        collect_snapshot(str(tmp_path), ["link.py"])


@pytest.mark.parametrize(
    "relative_path",
    [
        ".next/server/app.js",
        "node_modules/package/index.js",
        "build/generated.py",
        ".pytest_cache/v/cache.json",
    ],
)
def test_registered_paths_reject_generated_dependency_and_cache_directories(
    tmp_path,
    relative_path,
):
    with pytest.raises(ValueError, match="不能作为核心代码"):
        collect_snapshot(str(tmp_path), [relative_path])


def test_snapshot_machine_record_rejects_duplicate_and_hash_drift(tmp_path):
    (tmp_path / "a.py").write_text("a", encoding="utf-8")
    snapshot = collect_snapshot(str(tmp_path), ["a.py"])
    data = snapshot.to_dict()
    assert snapshot_from_dict(data) == snapshot
    data["aggregate_hash"] = "0" * 64
    with pytest.raises(ValueError, match="聚合哈希"):
        snapshot_from_dict(data)
