"""无代码改动轮次跳过全量回归测试（R9/R9a）。

覆盖：差异全空跳过并留依据、仅测试代码变化不跳过、文档变化不影响判定、
清单缺失时一律运行、跳过后状态与确认门。
"""
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import pytest

from workflow_loop import test_runner


def _make_project(tmp_path, changed_paths=None):
    """最小项目：回退清单 + 差异文件。changed_paths 为相对路径清单。"""
    manifest_dir = tmp_path / ".workflow_loop" / "rollback" / "wf-1"
    manifest_dir.mkdir(parents=True, exist_ok=True)
    for relative in changed_paths or []:
        full = tmp_path / relative
        full.parent.mkdir(parents=True, exist_ok=True)
        full.write_text("content\n", encoding="utf-8")
    manifest = {
        "workflow_id": "wf-1",
        "entries": {},
        "prepares": [{"inventory_before": {}}],
    }
    manifest_path = manifest_dir / "impl_manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False), encoding="utf-8"
    )
    return str(manifest_path)


class _State:
    workflow_id = "wf-1"

    def __init__(self):
        self.meta = {}


def _manifest_rel(_state):
    from workflow_loop import rollback as rollback_mod

    return rollback_mod._manifest_rel_path("wf-1")


def test_skip_when_no_code_changes(tmp_path, monkeypatch):
    """差异为空：跳过并返回依据。"""
    _make_project(tmp_path)
    state = _State()
    # 回退清单按 workflow_id 命名：_manifest_rel_path 决定路径
    from workflow_loop import rollback as rollback_mod

    manifest_relative = rollback_mod._manifest_rel_path("wf-1")
    (tmp_path / manifest_relative).parent.mkdir(parents=True, exist_ok=True)
    (tmp_path / manifest_relative).write_text(
        json.dumps(
            {"workflow_id": "wf-1", "entries": {}, "prepares": [{"inventory_before": {}}]},
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    # managed_document_paths 返回空（无正式文档登记）
    monkeypatch.setattr(
        "workflow_loop.rollback.managed_document_paths", lambda _root: []
    )
    skip, reason = test_runner.should_skip_final_regression(str(tmp_path), state)
    assert skip is True
    assert "产品代码差异与测试代码差异均为空" in reason
    assert "判定时间" in reason


def test_no_skip_when_test_code_changed(tmp_path, monkeypatch):
    """仅测试代码变化：不跳过。"""
    from workflow_loop import rollback as rollback_mod

    manifest_relative = rollback_mod._manifest_rel_path("wf-1")
    (tmp_path / manifest_relative).parent.mkdir(parents=True, exist_ok=True)
    test_file = tmp_path / "tests" / "test_new.py"
    test_file.parent.mkdir(parents=True, exist_ok=True)
    test_file.write_text("def test_x():\n    pass\n", encoding="utf-8")
    manifest = {
        "workflow_id": "wf-1",
        "entries": {"tests/test_new.py": {"original_exists": False, "backup_path": None, "content_hash": None}},
        "prepares": [{"inventory_before": {}}],
        # complete inventory 让 changed_paths_since_prepare 走快照比对；
        # 简化：直接用 entries 的 original_exists=False + 文件已建 → 计划外新文件
    }
    (tmp_path / manifest_relative).write_text(
        json.dumps(manifest, ensure_ascii=False), encoding="utf-8"
    )
    monkeypatch.setattr(
        "workflow_loop.rollback.managed_document_paths", lambda _root: []
    )
    skip, reason = test_runner.should_skip_final_regression(str(tmp_path), _State())
    assert skip is False
    assert "照常运行" in reason


def test_no_skip_when_manifest_missing(tmp_path):
    """回退清单缺失：差异无法确认，一律运行。"""
    (tmp_path / ".workflow_loop").mkdir(exist_ok=True)
    skip, reason = test_runner.should_skip_final_regression(str(tmp_path), _State())
    assert skip is False
    assert "差异无法确认" in reason
    assert "一律运行" in reason


def test_managed_document_changes_do_not_affect_judgement(tmp_path, monkeypatch):
    """受管文档变化不影响判定：managed 路径被排除后差异为空 → 跳过。"""
    from workflow_loop import rollback as rollback_mod

    manifest_relative = rollback_mod._manifest_rel_path("wf-1")
    (tmp_path / manifest_relative).parent.mkdir(parents=True, exist_ok=True)
    doc_file = tmp_path / "spec" / "功能_示例.md"
    doc_file.parent.mkdir(parents=True, exist_ok=True)
    doc_file.write_text("# 内容\n", encoding="utf-8")
    manifest = {
        "workflow_id": "wf-1",
        "entries": {"spec/功能_示例.md": {"original_exists": False, "backup_path": None, "content_hash": None}},
        "prepares": [{"inventory_before": {}}],
    }
    (tmp_path / manifest_relative).write_text(
        json.dumps(manifest, ensure_ascii=False), encoding="utf-8"
    )
    # spec/ 全目录是受管文档
    monkeypatch.setattr(
        "workflow_loop.rollback.managed_document_paths",
        lambda _root: ["spec/功能_示例.md"],
    )
    skip, reason = test_runner.should_skip_final_regression(str(tmp_path), _State())
    assert skip is True


def test_regression_state_serialization_roundtrip(tmp_path):
    """跳过字段序列化往返兼容。"""
    from workflow_loop.state import RegressionTestState, _regression_state_from_dict

    state = RegressionTestState(
        status="skipped-by-no-change",
        skip_reason="差异为空",
        skipped_at="2026-09-08T00:00:00+00:00",
    )
    from dataclasses import asdict

    restored = _regression_state_from_dict(asdict(state))
    assert restored.skip_reason == "差异为空"
    assert restored.skipped_at == "2026-09-08T00:00:00+00:00"


def test_skipped_regression_passes_state_validation(tmp_path):
    """跳过状态通过最终回归状态校验（依据齐全时）。"""
    from workflow_loop.state import RegressionTestState, WorkflowState
    from workflow_loop import artifact_validation

    wf_state = WorkflowState(workflow_id="wf-1", intent="product_change")
    wf_state.regression_test = RegressionTestState(
        status="skipped-by-no-change",
        skip_reason="产品代码差异与测试代码差异均为空",
        skipped_at="2026-09-08T00:00:00+00:00",
    )
    # validate_final_regression_state 读磁盘 state；直接构造不适用。
    # 这里测的是：跳过状态有依据时函数放行。
    import workflow_loop.artifact_validation as av
    from unittest.mock import patch

    with patch.object(av, "load_state", return_value=wf_state):
        ok, detail = av.validate_final_regression_state(str(tmp_path), "wf-1")
    assert ok is True
    assert "无代码改动跳过" in detail


def test_skipped_regression_without_reason_fails(tmp_path):
    """跳过状态缺依据时校验失败。"""
    from workflow_loop.state import RegressionTestState, WorkflowState
    import workflow_loop.artifact_validation as av
    from unittest.mock import patch

    wf_state = WorkflowState(workflow_id="wf-1", intent="product_change")
    wf_state.regression_test = RegressionTestState(
        status="skipped-by-no-change",
    )
    with patch.object(av, "load_state", return_value=wf_state):
        ok, detail = av.validate_final_regression_state(str(tmp_path), "wf-1")
    assert ok is False
    assert "缺少跳过依据" in detail
