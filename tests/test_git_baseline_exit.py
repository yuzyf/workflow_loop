"""先改代码后准备基线的 Git 自证出口测试。

覆盖：进场后修改文件用 Git HEAD 自证放行、新文件直接放行、
无法自证（快照≠HEAD）保持拒绝、主题合并（死循环修复）。
"""
import json
import os
import subprocess
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import pytest

GIT_ENV = {
    "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t.t",
    "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t.t",
}


def _git(repo, *args):
    return subprocess.run(
        ["git", *args], cwd=repo, check=True, capture_output=True, text=True,
        env={**os.environ, **GIT_ENV},
    )


@pytest.fixture
def repo(tmp_path):
    """git 仓库 + 最小项目结构与状态。"""
    _git(str(tmp_path), "init", "-q")
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "app.py").write_text("def run():\n    return 'before'\n", encoding="utf-8")
    _git(str(tmp_path), "add", "-A")
    _git(str(tmp_path), "commit", "-qm", "init")
    return tmp_path


def _state_with_snapshot(repo, snapshot):
    from workflow_loop.state import WorkflowState, StageState, GateState

    names = ["spec", "spike", "acceptance_plan", "impl", "qa",
             "topic_acceptance", "regression_test", "overall_acceptance", "update_code_design"]
    state = WorkflowState(
        workflow_id="2026-09-08-0000-product_change",
        intent="product_change",
        run_status="active",
        current_stage="impl",
        stage_path=names,
        stages={n: StageState(artifact_paths=[], gate=GateState(), internal_step="") for n in names},
    )
    state.stages["impl"].gate.discussion_complete = True
    state.meta["impl_complete_baseline_snapshot"] = snapshot
    return state


def _snapshot_of(repo):
    """按真实快照结构记录当前文件状态。"""
    files = []
    for relative in ["src/app.py", "src/new_thing.py"]:
        full = repo / relative
        files.append({
            "path": relative,
            "exists": full.is_file(),
            "type": "file" if full.is_file() else "missing",
            "content_hash": _sha(full) if full.is_file() else None,
        })
    return {"files": files}


def _sha(path):
    import hashlib
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_prepare_allows_changed_file_matching_head(repo):
    """进场后修改的文件：进场快照=HEAD 时用 HEAD 字节自证放行（AC-01）。"""
    from workflow_loop import rollback

    # 进场快照：app.py = HEAD 版本
    snapshot = _snapshot_of(repo)
    state = _state_with_snapshot(repo, snapshot)
    state.stages["impl"].code_baseline_hash = "entry-hash"
    # 进场后修改文件（当前 ≠ HEAD ≠ 快照）
    (repo / "src" / "app.py").write_text("def run():\n    return 'after'\n", encoding="utf-8")
    # 快照里 app.py 的哈希 = HEAD 哈希 → 可自证
    manifest_rel = rollback._manifest_rel_path(state.workflow_id)
    try:
        rollback.prepare_impl(str(repo), state)  # 快照=HEAD 自证放行（AC-01）
    except ValueError as exc:
        pytest.fail(f"应自证放行却拒绝: {exc}")
    manifest, _ = rollback._read_manifest(str(repo), manifest_rel)
    assert manifest.get("workflow_id") == state.workflow_id


def test_prepare_allows_new_file_not_in_snapshot(repo):
    """进场快照不存在的新文件：直接放行，原状态为没有（AC-01）。"""
    from workflow_loop import rollback

    snapshot = _snapshot_of(repo)  # src/new_thing.py 记录 exists=False
    state = _state_with_snapshot(repo, snapshot)
    state.stages["impl"].code_baseline_hash = "entry-hash"
    # 进场后新建文件
    (repo / "src" / "new_thing.py").write_text("x = 1\n", encoding="utf-8")
    manifest_rel = rollback._manifest_rel_path(state.workflow_id)
    rollback.prepare_impl(str(repo), state)  # 新文件不阻塞，准备成功（AC-01）
    manifest, _ = rollback._read_manifest(str(repo), manifest_rel)
    assert manifest.get("workflow_id") == state.workflow_id


def test_prepare_rejects_unverifiable_change(repo):
    """进场快照≠HEAD 的修改：无法自证，保持拒绝（AC-02）。"""
    from workflow_loop import rollback

    # 先做一个额外提交使 HEAD ≠ 进场内容
    (repo / "src" / "app.py").write_text("def run():\n    return 'head-ver'\n", encoding="utf-8")
    _git(str(repo), "add", "-A")
    _git(str(repo), "commit", "-qm", "head version")
    # 进场快照记录的是旧版本（不等于 HEAD）
    snapshot = {
        "files": [{
            "path": "src/app.py", "exists": True, "type": "file",
            "content_hash": _sha_of_bytes(b"def run():\n    return 'before'\n"),
        }],
    }
    state = _state_with_snapshot(repo, snapshot)
    state.stages["impl"].code_baseline_hash = "entry-hash"
    # 进场后又修改
    (repo / "src" / "app.py").write_text("def run():\n    return 'after'\n", encoding="utf-8")
    with pytest.raises(ValueError) as exc_info:
        rollback.prepare_impl(str(repo), state)
    assert "不能用 Git 证明进场时内容" in str(exc_info.value)


def _sha_of_bytes(data: bytes) -> str:
    import hashlib
    return hashlib.sha256(data).hexdigest()


def test_current_workflow_topics_merges_table(tmp_path):
    """state.topics 非空时合并 topic_relations 表新主题（死循环修复，AC-03）。"""
    records_dir = tmp_path / ".workflow_loop" / "records" / "wf-1"
    records_dir.mkdir(parents=True)
    table = {
        "表版本": "4", "工作流编号": "wf-1", "验收主题": "",
        "主题关系": [
            {"验收主题": "旧主题A", "前置主题": "无"},
            {"验收主题": "中途新主题B", "前置主题": "无"},
        ],
    }
    (records_dir / "topic_relations_topic_relations.json").write_text(
        json.dumps(table, ensure_ascii=False), encoding="utf-8"
    )
    # 模拟 state：topics 只有旧主题
    import workflow_loop.topic as topic_mod
    original_load = topic_mod.load_state

    class _State:
        workflow_id = "wf-1"
        topics = ["旧主题A"]
        topic = None

    def fake_load_state(_root):
        return _State()

    topic_mod.load_state = fake_load_state
    try:
        result = topic_mod.current_workflow_topics(str(tmp_path))
    finally:
        topic_mod.load_state = original_load
    assert result == ["旧主题A", "中途新主题B"]
