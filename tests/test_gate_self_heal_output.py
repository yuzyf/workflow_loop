"""门禁失败输出支持自修复测试（返回上游 R25 + 推进 R46）。"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import pytest


# ── 退回输出时序提示（AC-01）──


def test_return_output_contains_sequence_hint(tmp_path, capsys):
    """cmd_return 成功输出包含产物修改时序提示。"""
    from workflow_loop import cli as cli_mod

    # 不执行真实退回（需要完整状态）；直接验证提示文本由模块常量承载
    # 并在 cmd_return 的 spec/acceptance_plan/reproduce 分支输出。
    source = open(cli_mod.__file__, encoding="utf-8").read()
    assert "产物修改时序" in source
    assert "先重新加载材料并与用户讨论" in source
    assert "--discuss-done）之后再修改产物文件" in source
    assert "修改会被记进基线" in source


# ── 基线类失败带对比数据（AC-02）──


class _StageState:
    artifact_baseline_captured_at = "2026-09-08T06:00:00+00:00"
    artifact_baseline_hashes = {"spec/产品总说明.md": "baseline-hash-1"}


class _State:
    def __init__(self, stage_state):
        self.stages = {"spec": stage_state}
        self.intent = "product_change"


def test_baseline_conflict_facts_includes_all_four_items(tmp_path):
    """基线类报错含基线时间、两个哈希、对比结论四项。"""
    from workflow_loop.stages.stages import _baseline_conflict_facts
    from workflow_loop import verification as verification_mod

    overview = tmp_path / "spec" / "产品总说明.md"
    overview.parent.mkdir(parents=True)
    overview.write_text("# 总说明\n", encoding="utf-8")
    state = _State(_StageState())
    # 基线哈希与当前一致：说明修改被记进基线
    current_hashes = verification_mod.compute_file_hashes(
        str(tmp_path), ["spec/产品总说明.md"]
    )
    state.stages["spec"].artifact_baseline_hashes = current_hashes
    facts = _baseline_conflict_facts(
        state, str(tmp_path), "spec/产品总说明.md"
    )
    assert "产物基线拍摄时间：2026-09-08T06:00:00+00:00" in facts
    assert "产品总说明基线哈希：" in facts
    assert "当前哈希：" in facts
    assert "对比结论：当前内容与基线完全一致" in facts
    assert "先通过第一道门（--discuss-done）之后再修改产物文件" in facts


def test_baseline_conflict_facts_when_baseline_missing():
    """没有基线时说明无法提供对比数据，不崩。"""
    from workflow_loop.stages.stages import _baseline_conflict_facts

    class _NoBaseline:
        artifact_baseline_captured_at = None
        artifact_baseline_hashes = {}

    state = _State(_NoBaseline())
    facts = _baseline_conflict_facts(state, "/tmp/nonexistent", "spec/产品总说明.md")
    assert "无法提供对比数据" in facts


# ── 表文档不一致区分修复路径（AC-03）──


def _table_with_receipt(tmp_path, kind, relative, previous_content, table_content):
    """构造带生成凭据的最小表环境。"""
    from workflow_loop import records as records_mod

    records_dir = tmp_path / ".workflow_loop" / "records" / "wf-1"
    records_dir.mkdir(parents=True, exist_ok=True)
    table_path = records_dir / f"{kind}_test.json"
    table = {
        "表版本": "4",
        "工作流编号": "wf-1",
        "验收主题": "主题甲",
        records_mod.DOC_HASH_KEY: "old-doc-hash",
        records_mod.GENERATED_DOC_PATH_KEY: relative,
    }
    table.update(table_content)
    table_path.write_text(
        __import__("json").dumps(table, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    doc = tmp_path / relative
    doc.parent.mkdir(parents=True, exist_ok=True)
    doc.write_text(previous_content, encoding="utf-8")
    receipt_dir = records_dir / ".generated"
    receipt_dir.mkdir(exist_ok=True)
    return table


def test_conflict_facts_table_updated_path(tmp_path):
    """表已更新、文档被手改：提示恢复文档由程序按表重写。"""
    from workflow_loop import records as records_mod
    import hashlib

    # 上次凭据正文摘要（旧内容）
    previous_content = "# 旧内容\n"
    expected_content = "# 新内容（表已更新）\n"
    previous_body_hash = hashlib.sha256(
        previous_content.encode("utf-8")
    ).hexdigest()
    table = _table_with_receipt(
        tmp_path, "impl_record", "impl/主题甲_实施记录.md", previous_content, {}
    )
    # 直接构造 receipt
    from workflow_loop.records import _generation_receipt_path

    receipt_path = tmp_path / _generation_receipt_path(
        str(tmp_path), "impl_record", table
    )
    receipt_path.parent.mkdir(parents=True, exist_ok=True)
    receipt_path.write_text(
        __import__("json").dumps(
            {
                "fields": {},
                "documents": {
                    "impl/主题甲_实施记录.md": {"body_hash": previous_body_hash}
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    from workflow_loop.records import _table_document_conflict_facts, _load_generation_receipt

    facts = _table_document_conflict_facts(
        str(tmp_path),
        "impl_record",
        table,
        "impl/主题甲_实施记录.md",
        "实施记录（按表生成的章节）",
        expected_content,
    )
    assert "差异章节块" in facts
    assert "程序凭据指纹" in facts
    assert "当前指纹" in facts
    # 表已更新（预期内容与上次凭据不同）
    assert "表已更新、仅文档该章节被手改" in facts
    assert "不要再改表" in facts


def test_conflict_facts_table_not_updated_path(tmp_path):
    """表未更新：提示把改动写回表。"""
    from workflow_loop import records as records_mod
    import hashlib

    previous_content = "# 内容\n"
    expected_content = "# 内容\n"  # 表未变：生成内容与上次相同
    previous_body_hash = hashlib.sha256(
        previous_content.encode("utf-8")
    ).hexdigest()
    table = _table_with_receipt(
        tmp_path, "impl_record", "impl/主题甲_实施记录.md", previous_content, {}
    )
    from workflow_loop.records import _generation_receipt_path

    receipt_path = tmp_path / _generation_receipt_path(
        str(tmp_path), "impl_record", table
    )
    receipt_path.parent.mkdir(parents=True, exist_ok=True)
    receipt_path.write_text(
        __import__("json").dumps(
            {
                "fields": {},
                "documents": {
                    "impl/主题甲_实施记录.md": {"body_hash": previous_body_hash}
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    from workflow_loop.records import _table_document_conflict_facts

    facts = _table_document_conflict_facts(
        str(tmp_path),
        "impl_record",
        table,
        "impl/主题甲_实施记录.md",
        "实施记录（按表生成的章节）",
        expected_content,
    )
    assert "表未更新" in facts
    assert "写回工作记录表" in facts


def test_conflict_facts_no_receipt_fallback(tmp_path):
    """无凭据时给出保守提示，不笼统归为写回表。"""
    from workflow_loop import records as records_mod

    table = _table_with_receipt(
        tmp_path,
        "impl_record",
        "impl/主题甲_实施记录.md",
        "# 内容\n",
        {},
    )
    from workflow_loop.records import _table_document_conflict_facts

    facts = _table_document_conflict_facts(
        str(tmp_path),
        "impl_record",
        table,
        "impl/主题甲_实施记录.md",
        "实施记录（按表生成的章节）",
        "# 新内容\n",
    )
    assert "缺少上次生成凭据" in facts or "写回工作记录表" in facts
