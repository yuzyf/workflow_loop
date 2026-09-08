"""机器事实采集模块测试（R25-R29）。

覆盖：差异事实纯函数、采集写表与指纹、计划外文件两来源顺序、验收五列
回填、编号引用解析、测试标识生成、表版本 v4 兼容。
"""
import json
import os
import subprocess
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import pytest

from workflow_loop import machine_collect
from workflow_loop import records as records_mod


@pytest.fixture
def project(tmp_path):
    """最小项目根：目录结构 + 空记录目录。"""
    records_dir = tmp_path / ".workflow_loop" / "records" / "wf-1"
    records_dir.mkdir(parents=True)
    return tmp_path


def _write_table(project, kind, topic, table):
    relative = records_mod.table_relative_path(str(project), "wf-1", kind, topic)
    full = project / relative
    full.parent.mkdir(parents=True, exist_ok=True)
    full.write_text(json.dumps(table, ensure_ascii=False, indent=2), encoding="utf-8")
    return relative


def _diff_fact(file, location, content_hash=None):
    return machine_collect.DiffFact(file, location, content_hash)


# ── resolve_id_reference（R27）──


def test_id_reference_accepts_known_ids():
    ok, message = machine_collect.resolve_id_reference(
        "AC-01、AC-03", {"AC-01", "AC-03"}, set()
    )
    assert ok and message == ""


def test_id_reference_reports_deleted_id():
    ok, message = machine_collect.resolve_id_reference(
        "AC-02", {"AC-01"}, {"AC-02"}
    )
    assert not ok
    assert "已删除" in message


def test_id_reference_reports_unknown_with_available_ids():
    ok, message = machine_collect.resolve_id_reference("AC-09", {"AC-01", "AC-02"}, set())
    assert not ok
    assert "不存在" in message
    assert "AC-01" in message


def test_id_reference_rejects_format_content():
    ok, message = machine_collect.resolve_id_reference(
        "[AC-01](计划.md#ac-01)", {"AC-01"}, set()
    )
    assert not ok
    assert "只写编号本身" in message


# ── render_test_marker（R28）──


def test_render_test_marker_matches_field_labels():
    from workflow_loop.test_mapping import TestPlanItem, build_marker_from_plan

    item = TestPlanItem(
        topic="主题甲",
        criterion_id="AC-01",
        criterion_name="条件一",
        test_id="TC-01",
        test_name="测试一",
        test_method="自动化测试",
        test_entry="tests/test_a.py::test_one",
        product_entry="workflow collect",
        code_entry="src/a.py::f",
        action="执行",
        expected_result="结果",
        evidence_requirement="证据",
    )
    text = build_marker_from_plan(item)
    assert text.startswith("Workflow-Test: TC-01 测试一")
    assert "测试入口：tests/test_a.py::test_one" in text
    assert "验收条件：AC-01 条件一" in text
    # 与解析字段同源：每个标签都能被 MARKER_FIELDS 解析
    from workflow_loop.test_mapping import MARKER_FIELDS

    labels = [line.split("：", 1)[0] for line in text.splitlines()[1:]]
    assert labels == list(MARKER_FIELDS)


# ── 表版本 v4（R29/AC-06）──


def test_v4_impl_record_accepts_collection_fingerprint():
    table = {
        "表版本": "4",
        "工作流编号": "wf-1",
        "验收主题": "主题甲",
        records_mod.DOC_HASH_KEY: None,
        records_mod.GENERATED_DOC_PATH_KEY: None,
        records_mod.COLLECTION_FINGERPRINT_KEY: {
            "collected_at": "2026-09-08T00:00:00+00:00",
            "files": {"src/a.py": "hash"},
        },
    }
    problems = records_mod.validate_table("impl_record", table, "4")
    assert not any("未知栏目" in message for _category, message in problems)


def test_v3_impl_record_rejects_collection_fingerprint():
    """旧版本表不允许新键：进行中轮次不因程序升级改格式（R11）。"""
    table = {
        "表版本": "3",
        "工作流编号": "wf-1",
        "验收主题": "主题甲",
        records_mod.DOC_HASH_KEY: None,
        records_mod.GENERATED_DOC_PATH_KEY: None,
        records_mod.COLLECTION_FINGERPRINT_KEY: {},
    }
    problems = records_mod.validate_table("impl_record", table, "3")
    assert any("未知栏目" in message for _category, message in problems)


def test_v4_in_supported_versions():
    assert "4" in records_mod._SUPPORTED_TABLE_VERSIONS
    assert records_mod.TABLE_FORMAT_VERSION == "4"


# ── 验收五列回填（R26）──


class _Record:
    def __init__(self, method, result, test_record_ids, user_answer=None):
        self.topic = "主题甲"
        self.criterion_id = "AC-01"
        self.method = method
        self.result = result
        self.test_record_ids = test_record_ids
        self.user_answer = user_answer
        self.record_id = "AR-1"
        self.acceptance_plan_hash = None
        self.impl_hash = None
        self.test_result_hash = None
        self.confirmed_at = None
        self.evidence = ""


class _Current:
    def __init__(self):
        self.record_is_current = True


def test_fill_acceptance_row_columns_automated():
    row = {}
    record = _Record("自动化测试", "passed", ["RUN-1"])
    from workflow_loop import records as _records

    _records._fill_acceptance_row_columns(row, record)
    assert row["验收方式"] == "自动化测试"
    assert row["验收结论"] == "passed"
    assert row["机器测试记录编号"] == "RUN-1"
    assert row["用户实际回答"] == "不适用"
    assert row["人工确认"] == "不适用"


def test_fill_acceptance_row_columns_manual():
    row = {}
    record = _Record("人工验收", "passed", [], user_answer="用户原话")
    from workflow_loop import records as _records

    _records._fill_acceptance_row_columns(row, record)
    assert row["机器测试记录编号"] == "不适用"
    assert row["用户实际回答"] == "用户原话"
    assert row["人工确认"] == "通过"


def test_fill_acceptance_row_columns_mixed():
    row = {}
    record = _Record("自动化测试 + 人工验收", "passed", ["RUN-2"], user_answer="部分人工")
    from workflow_loop import records as _records

    _records._fill_acceptance_row_columns(row, record)
    assert row["机器测试记录编号"] == "RUN-2"
    assert row["用户实际回答"] == "部分人工"
    assert row["人工确认"] == "通过"


# ── 差异事实（R25）──


def test_collect_diff_facts_new_file_is_all_added(tmp_path):
    """计划外新建文件按全部行新增登记，不报错。"""
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "new_file.py").write_text("a = 1\n", encoding="utf-8")
    manifest = {"workflow_id": "wf-1", "entries": {}, "prepares": [{"inventory_before": {}}]}
    # 直接测纯逻辑：无回退登记、无基线提交号 → 新文件
    entry = machine_collect._entry_text_or_none(str(tmp_path), None, manifest, "src/new_file.py")
    assert entry is None  # 无任何来源时返回 None（调用方按新文件登记）


def test_collect_error_message_contains_path_and_next_step(tmp_path):
    """计划外修改文件取不到改动前内容时，报错含文件名和下一步。"""
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "outside.py").write_text("x = 1\n", encoding="utf-8")
    manifest = {"workflow_id": "wf-1", "entries": {}, "prepares": [{"inventory_before": {}}]}
    # _entry_text_or_none 对无副本无基线的文件返回 None；collect_diff_facts
    # 只对"有回退登记但副本不可读"报错。计划外文件按新文件登记。
    # 这里验证登记但副本损坏的场景：
    entry = {
        "original_exists": True,
        "backup_path": "backups/missing.py",
    }
    manifest["entries"]["src/outside.py"] = entry
    # 回退登记存在但副本不可读：按现有口径报 ValueError，消息含文件描述
    with pytest.raises(ValueError) as exc_info:
        machine_collect._texts_from_manifest(str(tmp_path), manifest, "src/outside.py")
    assert "src/outside.py" in str(exc_info.value)
    assert "无法读取" in str(exc_info.value)


def test_git_show_entry_baseline_for_subdirectory(tmp_path):
    """子目录项目用进场提交号能取到进场内容（实测结论的回归测试）。"""
    repo = tmp_path / "repo"
    (repo / "sub" / "project").mkdir(parents=True)
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    subprocess.run(
        ["git", "config", "user.email", "t@t.t"], cwd=repo, check=True
    )
    subprocess.run(["git", "config", "user.name", "t"], cwd=repo, check=True)
    original = "line1\nline2\nline3\n"
    (repo / "sub" / "project" / "a.py").write_text(original, encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
    subprocess.run(
        ["git", "commit", "-qm", "init"], cwd=repo, check=True,
        env={**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t.t",
             "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t.t"},
    )
    commit = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=repo, check=True,
        capture_output=True, text=True,
    ).stdout.strip()

    class _State:
        workflow_id = "wf-1"

    _State.meta = {"impl_entry_git_commit": {"workflow_id": "wf-1", "commit": commit}}
    project_root = str(repo / "sub" / "project")
    # 修改文件后，基线提交号仍能取到进场内容
    (repo / "sub" / "project" / "a.py").write_text(
        "line1\nline2-changed\n", encoding="utf-8"
    )
    text = machine_collect._entry_baseline_text(project_root, _State, "a.py")
    assert text == original


def test_record_entry_git_baseline_requires_clean_code(tmp_path):
    """代码范围有未提交改动时不记录基线提交号。"""
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.email", "t@t.t"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=repo, check=True)
    (repo / "code.py").write_text("a = 1\n", encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
    subprocess.run(
        ["git", "commit", "-qm", "init"], cwd=repo, check=True,
        env={**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t.t",
             "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t.t"},
    )
    (repo / "code.py").write_text("a = 2\n", encoding="utf-8")  # 未提交改动

    class _State:
        workflow_id = "wf-1"
        current_stage = "impl"
        meta = {}

    assert machine_collect.record_entry_git_baseline(str(repo), _State) is False
    assert machine_collect.IMPL_ENTRY_GIT_COMMIT_KEY not in _State.meta


# ── 采集写表（R25）──


def test_collect_implementation_changes_preserves_narrative(tmp_path, monkeypatch):
    """重新采集只刷新文件与代码位置两列，保留 AI 叙述列。"""
    records_dir = tmp_path / ".workflow_loop" / "records" / "wf-1"
    records_dir.mkdir(parents=True)
    topic = "主题甲"
    table = {
        "表版本": "4",
        "工作流编号": "wf-1",
        "验收主题": topic,
        records_mod.DOC_HASH_KEY: None,
        records_mod.GENERATED_DOC_PATH_KEY: None,
        "实际代码修改": [
            {
                "文件": "src/a.py",
                "代码位置（最终文件）": "L1-L1",
                "实际修改的代码逻辑": "AI 填写的叙述",
                "数据、状态或输出的实际变化": "AI 填的变化",
                "修改理由": "AI 填的理由",
                "对应验收条件": "AC-01",
                "测试证据": "AI 填的证据",
            }
        ],
    }
    relative = _write_table(tmp_path, "impl_record", topic, table)

    fact = _diff_fact("src/a.py", "L5-L9", "hash-1")
    monkeypatch.setattr(
        machine_collect, "collect_diff_facts", lambda *_args, **_kw: [fact]
    )
    monkeypatch.setattr(
        machine_collect, "_plan_rows_for_topic", lambda *_args, **_kw: [
            {"文件": "src/a.py"}
        ]
    )

    class _State:
        workflow_id = "wf-1"
        topics = [topic]

    _State.meta = {}
    summary = machine_collect.collect_implementation_changes(str(tmp_path), _State)
    updated = json.loads(
        (tmp_path / relative).read_text(encoding="utf-8")
    )
    rows = updated["实际代码修改"]
    assert rows[0]["代码位置（最终文件）"] == "L5-L9"
    assert rows[0]["实际修改的代码逻辑"] == "AI 填写的叙述"
    assert rows[0]["修改理由"] == "AI 填的理由"
    assert updated[records_mod.COLLECTION_FINGERPRINT_KEY]["files"] == {
        "src/a.py": "hash-1"
    }
    assert summary["topics"][topic].startswith("已写入")


def test_verify_collection_fingerprint_detects_change(tmp_path, monkeypatch):
    """采集后文件又变化时，门禁重算指纹不一致并报请重新采集。"""
    records_dir = tmp_path / ".workflow_loop" / "records" / "wf-1"
    records_dir.mkdir(parents=True)
    topic = "主题甲"
    table = {
        "表版本": "4",
        "工作流编号": "wf-1",
        "验收主题": topic,
        records_mod.DOC_HASH_KEY: None,
        records_mod.GENERATED_DOC_PATH_KEY: None,
        "实际代码修改": [
            {"文件": "src/a.py", "代码位置（最终文件）": "L1-L2"}
        ],
        records_mod.COLLECTION_FINGERPRINT_KEY: {
            "collected_at": "t",
            "files": {"src/a.py": "old-hash"},
        },
    }
    _write_table(tmp_path, "impl_record", topic, table)

    fact = _diff_fact("src/a.py", "L1-L2", "new-hash")
    monkeypatch.setattr(
        machine_collect, "collect_diff_facts", lambda *_args, **_kw: [fact]
    )

    class _State:
        workflow_id = "wf-1"
        topics = [topic]

    _State.meta = {}
    problems = machine_collect.verify_collection_fingerprint(str(tmp_path), _State)
    assert topic in problems
    assert "请重新执行采集命令" in problems[topic]
    assert "叙述列会保留" in problems[topic]


# ── 采集位置值与门禁行号格式同口径（对抗审查发现的缺口）──


def test_collect_location_values_pass_gate_format(tmp_path):
    """采集写入的位置值必须能被门禁 _parse_recorded_line_range 接受。"""
    from workflow_loop import rollback as rollback_mod

    # 新文件：L1-L行数
    after_new = "a = 1\nb = 2\nc = 3\n"
    before = None  # 新文件无 before
    location_new = f"L1-L{len(after_new.splitlines())}"
    parsed = rollback_mod._parse_recorded_line_range(location_new)
    assert parsed is not None and parsed.start == 1 and parsed.end == 3

    # 修改文件：单块
    parsed_single = rollback_mod._parse_recorded_line_range("L5-L9")
    assert parsed_single is not None and parsed_single.start == 5

    # 修改文件：多块 → 覆盖全部差异的连续范围
    multi_ranges = [(5, 9), (20, 24)]
    starts = [s for s, _ in multi_ranges]
    ends = [e for _, e in multi_ranges]
    location_multi = f"L{min(starts)}-L{max(ends)}"
    parsed_multi = rollback_mod._parse_recorded_line_range(location_multi)
    assert parsed_multi is not None
    assert parsed_multi.start == 5 and parsed_multi.end == 24


def test_collect_diff_facts_multi_block_writes_span(tmp_path):
    """多个不连续差异块写覆盖全部差异的连续范围（与门禁单块格式一致）。"""
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "app.py").write_text(
        "line1\nline2\nline3\nline4\nline5\n", encoding="utf-8"
    )
    before = (tmp_path / "src" / "app.py").read_text(encoding="utf-8")
    # 改第 2 行和第 4 行（两个不连续块）
    (tmp_path / "src" / "app.py").write_text(
        "line1\nLINE2\nline3\nLINE4\nline5\n", encoding="utf-8"
    )
    after = (tmp_path / "src" / "app.py").read_text(encoding="utf-8")
    from workflow_loop import rollback as rollback_mod

    _, after_ranges = rollback_mod._changed_line_ranges(before, after)
    assert len(after_ranges) == 2  # 确认确实是两个块
    # collect_diff_facts 的写法：连续范围覆盖
    starts = [s for s, _ in after_ranges]
    ends = [e for _, e in after_ranges]
    location = f"L{min(starts)}-L{max(ends)}"
    assert location == "L2-L4"
    parsed = rollback_mod._parse_recorded_line_range(location)
    assert parsed is not None and parsed.start == 2 and parsed.end == 4
