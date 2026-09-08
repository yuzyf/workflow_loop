"""空 test_result 表必须被 qa 门禁拦下（R11），不能静默放行。

回归背景：2026-09-08 实际踩坑——qa 三道门全过，到整体验收才发现三份
测试结果文档不存在（test_result 表全空但 required_at_gate=False 让
空表静默跳过），补填又使结果哈希变化触发退回 qa 重走全流程。
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from workflow_loop import records as records_mod


def test_test_result_rows_required_at_gate():
    """test_result 的行清单必须在门禁时必填（R11）。"""
    schema = records_mod.KIND_SCHEMAS["test_result"]
    row_list = schema["row_lists"]["测试结果"]
    assert row_list["required_at_gate"] is True


def test_empty_test_result_table_reports_unfilled(tmp_path):
    """空 test_result 表触发"尚未填写"，不再静默跳过。"""
    # 构造最小项目与本轮表
    records_dir = tmp_path / ".workflow_loop" / "records" / "wf-1"
    records_dir.mkdir(parents=True)
    table = {
        "表版本": "3",
        "工作流编号": "wf-1",
        "验收主题": "示例主题",
        records_mod.DOC_HASH_KEY: None,
        records_mod.GENERATED_DOC_PATH_KEY: None,
        "测试结果": [],
        "结果说明": [],
    }
    relative = records_mod.table_relative_path(str(tmp_path), "wf-1", "test_result", "示例主题")
    full = tmp_path / relative
    full.parent.mkdir(parents=True, exist_ok=True)
    import json

    full.write_text(json.dumps(table, ensure_ascii=False, indent=2), encoding="utf-8")

    # sync_stage_tables 对空表应报"尚未填写"
    problems, _documents = records_mod.sync_stage_tables(
        str(tmp_path),
        _state(tmp_path),
    )
    messages = [message for _category, message in problems]
    assert any("尚未填写内容" in message for message in messages), messages


class _StageState:
    def __init__(self):
        self.gate = type("Gate", (), {"discussion_complete": True})()
        self.test_tasks = {}


class _State:
    def __init__(self, root):
        self.workflow_id = "wf-1"
        self.intent = "product_change"
        self.current_stage = "qa"
        self.topics = ["示例主题"]
        self.stages = {"qa": _StageState()}
        self.rollback = type("Rollback", (), {"manifest_path": None, "manifest_hash": None, "prepared_at": None, "plan_hash": None, "code_baseline_hash": None, "planned_paths": []})()
        self.meta = {}
        self.spike_skipped = True


def _state(root):
    return _State(root)
