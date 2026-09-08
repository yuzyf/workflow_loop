"""填表、文档再生与链接修复的真实入口回归。"""

from argparse import Namespace
from collections import Counter
from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path

from markdown_it import MarkdownIt
import pytest

from workflow_loop import artifact_validation as av
from workflow_loop import cli
from workflow_loop import markdown_links as links
from workflow_loop import project as project_mod
from workflow_loop import records
from workflow_loop import state as state_mod
from workflow_loop import verification
from test_architecture_validation import _write_complete_final_architecture


TOPIC = "填写结果保持真实"
WORKFLOW_ID = "guidance-regression"


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _save(path: Path, table: dict) -> None:
    _write(path, json.dumps(table, ensure_ascii=False, indent=2))


def _project(root: Path, version: str = "3", stage: str = "reproduce"):
    root.mkdir(parents=True, exist_ok=True)
    project_mod.create_project(str(root))
    state = state_mod.WorkflowState(
        workflow_id=WORKFLOW_ID, intent="bugfix", current_stage=stage,
        topics=[TOPIC], table_format_version=version,
        stage_path=["reproduce", "acceptance_plan", "impl", "qa"],
        stages={name: state_mod.StageState() for name in
                ("reproduce", "acceptance_plan", "impl", "qa")},
    )
    state_mod.save_state(str(root), state)
    return state


def _table(root: Path, kind: str) -> tuple[Path, dict]:
    topic = "" if kind in records.WORKFLOW_LEVEL_KINDS else TOPIC
    relative = records.create_or_complete_table(
        str(root), WORKFLOW_ID, kind, topic,
    )
    path = root / relative
    return path, records.load_table(str(path))


def _filled_table(root: Path, kind: str, version: str = "3") -> tuple[Path, dict]:
    path, table = _table(root, kind)
    schema = records._schema(kind, version)
    values = {
        "顺序": "1", "实施顺序": "1", "对应计划步骤": "1", "展示顺序": "1",
        "前置步骤": "无", "前置测试项": "无", "前置主题": "无",
        "验收主题": TOPIC, "验收条件编号": "AC-01", "对应验收条件": "AC-01",
        "测试项编号": "TC-01", "缺陷编号": "BUG-01", "穿刺项编号": "SP-001",
        "依据编号": "JU-01", "依据类型": "验收条件", "状态": "已完成",
        "命令参数数组": ["python", "-m", "pytest", "tests/test_sample.py::test_sample"],
        "正式目标名称": "tests/test_sample.py::test_sample", "超时秒数": 600,
        "工作目录": ".", "报告适配器": "pytest-junitxml", "测试方式": "自动化测试",
        "测试入口": "tests/test_sample.py::test_sample",
        "代码入口": "src/sample.py::sample", "代码位置（最终文件）": "L1-L1",
        "文件": "src/sample.py", "执行结论": "passed", "验收结论": "passed",
        "验收方式": "自动化测试", "是否需要继续修改": "否",
        "产品设计依据": "[定义 R1](../spec/功能_定义.md#r-1)",
        "功能文档路径": "./功能_定义.md",
    }
    for key, definition in schema["row_lists"].items():
        table[key] = [{
            column: values.get(column, f"{column}根据真实输入核对文件内容和返回结果。")
            for column in definition["columns"]
        }]
    for key in schema["narrative"]:
        table[key] = [f"{key}根据真实输入核对文件内容和返回结果。"]
    for key in records._NARRATIVE_ALLOW_NO_CONTENT.get(kind, set()):
        if key in schema["narrative"]:
            table[key] = ["暂无"]
    if kind == "bug_record":
        table["验收主题"] = TOPIC
    _save(path, table)
    return path, table


def _bug_table(root: Path, version: str = "3") -> tuple[Path, dict]:
    path, table = _filled_table(root, "bug_record", version)
    row = table["缺陷信息"][0]
    if version == "3":
        row["根因说明"] = "正文中引用“根因证据：”并不表示新字段。\n这个换行也是原事实的一部分。"
        row["根因位置"] = "src/workflow_loop/records.py 的缺陷生成函数"
        row["根因证据"] = "独立字段原文不应再按引号中的标签文字进行切分。"
        table["运行环境"] = ["macOS 与 Python 3.13，独立临时项目。"]
        table["真实输入"] = ["程序实际创建的缺陷表以及包含换行和标签引用的事实文字。"]
    else:
        row["根因"] = "根因说明：旧表根因保持完整。根因位置：真实生成函数。根因证据：实际输出与原表比对。"
        if version == "2":
            table["真实复现条件"] = ["运行环境：隔离临时目录与实际解释器。", "真实输入：程序创建的旧表与已填事实。"]
    _save(path, table)
    return path, table


def _markdown_snapshot(root: Path) -> dict[str, bytes]:
    return {path.relative_to(root).as_posix(): path.read_bytes() for path in root.rglob("*.md")}


def test_bug_facts_are_separate_and_literal(tmp_path):
    """Workflow-Test
    主题：按程序指引填表和修链接都能一次过关，修复结果不被程序自己抹掉
    测试项：TC-01 缺陷五类事实分栏生成且缺项明确拒绝
    验收条件：AC-01 缺陷五类事实分栏生成且缺项明确拒绝
    测试方式：自动化测试
    测试层级：集成测试
    产品入口：调用缺陷记录表生成与复现校验入口
    测试入口：tests/test_workflow_guidance.py::test_bug_facts_are_separate_and_literal
    代码入口：src/workflow_loop/records.py::sync_stage_tables
    准备数据：版本 3 缺陷表填入真实类型事实，并在根因中包含换行和类似固定标签的引用文字。
    执行动作：按表生成缺陷文档并校验，再分别移除五类必需事实。
    关键断言：五类事实完整保留，缺少任一必需事实均指出具体栏目，不要求重复根因证据叙述栏。
    预期证据：当前执行的结构化测试报告中入口精确匹配，执行数大于零，跳过失败错误均为零且退出码为零。
    """
    root = tmp_path / "project"
    state = _project(root)
    path, table = _bug_table(root)
    assert "根因证据" not in table
    assert "根因" not in table["缺陷信息"][0]
    assert records.validate_table("bug_record", table, "3", project_root=str(root)) == []
    problems, _ = records.sync_stage_tables(str(root), state)
    assert not problems, problems
    ok, detail = av.validate_reproduce_documents(str(root), [], WORKFLOW_ID)
    assert ok, detail
    content = (root / f"bug/缺陷_{TOPIC}.md").read_text(encoding="utf-8")
    for column in ("根因说明", "根因位置", "根因证据"):
        assert table["缺陷信息"][0][column] in content
    for column in ("运行环境", "真实输入"):
        assert table[column][0] in content
    current = records.load_table(str(path))
    for column in ("根因说明", "根因位置", "根因证据", "运行环境", "真实输入"):
        missing = deepcopy(current)
        if column in ("运行环境", "真实输入"):
            missing[column] = []
        else:
            missing["缺陷信息"][0][column] = ""
        issues = records.validate_table("bug_record", missing, "3", project_root=str(root))
        assert any(column in message for _, message in issues), column


def test_program_fields_reject_tampering_before_writes(tmp_path):
    """Workflow-Test
    主题：按程序指引填表和修链接都能一次过关，修复结果不被程序自己抹掉
    测试项：TC-02 所有记录表拒绝篡改程序字段且零写入
    验收条件：AC-02 所有记录表拒绝篡改程序字段且零写入
    测试方式：自动化测试
    测试层级：集成测试
    产品入口：调用工作记录表的文档同步入口
    测试入口：tests/test_workflow_guidance.py::test_program_fields_reject_tampering_before_writes
    代码入口：src/workflow_loop/records.py::sync_documents
    准备数据：分别建立全部表类型，准备合法程序回填、已有正式文档以及三项专用字段的篡改输入。
    执行动作：逐项改动专用字段并同步，核对正式文件原文，再用合法程序值连续同步。
    关键断言：三项专用字段在所有表类型中均拒绝非程序值，拒绝时正式文件不变，合法回填可连续同步。
    预期证据：当前执行的结构化测试报告中入口精确匹配，执行数大于零，跳过失败错误均为零且退出码为零。
    """
    for kind in records.KIND_SCHEMAS:
        root = tmp_path / kind
        _project(root)
        _write(root / "spec/产品总说明.md", "# 产品\n\n## 7. 产品功能\n\n原清单\n\n## 8. 相关文档\n")
        _write(root / "spec/功能_定义.md", "# 定义\n")
        if kind == "acceptance_result":
            from workflow_repair_support import prepared_project, run_project_evidence

            state = prepared_project(root, [TOPIC], workflow_id=WORKFLOW_ID)
            run_project_evidence(root, state)
            path = root / records.table_relative_path(str(root), WORKFLOW_ID, kind, TOPIC)
            table = records.load_table(str(path))
        else:
            path, table = _filled_table(root, kind)
        topic = "" if kind in records.WORKFLOW_LEVEL_KINDS else TOPIC
        if kind == "product_features":
            problems, _ = records._sync_product_features(str(root), WORKFLOW_ID)
        else:
            problems, _ = records.sync_documents(str(root), WORKFLOW_ID, kind, [topic])
        assert not problems, (kind, problems)
        table = records.load_table(str(path))
        if kind == "bug_record":
            assert records._write_bug_documents(str(root), table) == []
            _save(path, table)
        assert records.validate_table(kind, table, "3", project_root=str(root)) == []
        before = _markdown_snapshot(root)
        replacements = [
            (records.GENERATED_DOC_PATH_KEY, "spec/产品总说明.md"),
            (records.DOC_HASH_KEY, "0" * 64),
            (records.BUG_DOC_HASHES_KEY, {"bug/索引.md": "0" * 64}),
            (records.DOC_HASH_KEY, None),
        ]
        if kind == "product_features":
            replacements[0] = (records.GENERATED_DOC_PATH_KEY, "spec/错误出口.md")
        for field, value in replacements:
            changed = deepcopy(table)
            changed[field] = value
            _save(path, changed)
            problems, _ = records.sync_documents(str(root), WORKFLOW_ID, kind, [topic])
            assert any(field in message for _, message in problems), (kind, field, problems)
            assert _markdown_snapshot(root) == before, (kind, field)
            if kind in {"impl_record", "acceptance_plan", "test_plan"}:
                assert records._refresh_stage_document(str(root), WORKFLOW_ID, kind, topic) == []
            if kind == "bug_record":
                assert records._write_bug_documents(str(root), changed)
            assert _markdown_snapshot(root) == before
        _save(path, table)
        for _ in range(2):
            if kind == "product_features":
                problems, _ = records._sync_product_features(str(root), WORKFLOW_ID)
            else:
                problems, _ = records.sync_documents(str(root), WORKFLOW_ID, kind, [topic])
            assert not problems, (kind, problems)


def test_link_scans_reuse_unchanged_documents(tmp_path, monkeypatch, capsys):
    """Workflow-Test
    主题：按程序指引填表和修链接都能一次过关，修复结果不被程序自己抹掉
    测试项：TC-03 链接修复复用未变化文档的读取和解析
    验收条件：AC-03 链接修复复用未变化文档的读取和解析
    测试方式：自动化测试
    测试层级：集成测试
    产品入口：通过受控链接修复命令预览并执行
    测试入口：tests/test_workflow_guidance.py::test_link_scans_reuse_unchanged_documents
    代码入口：src/workflow_loop/cli.py::cmd_repair_links
    准备数据：受管来源文档重复引用同一目标，目标包含待修复标题；对真实文件读取与解析调用计数。
    执行动作：运行扫描和修复预览，再通过命令入口执行预览；记录每份内容被读取和解析的次数。
    关键断言：单次扫描每份文档只读取解析一次；修复执行只重新解析变化内容，结果与独立扫描一致。
    预期证据：当前执行的结构化测试报告中入口精确匹配，执行数大于零，跳过失败错误均为零且退出码为零。
    """
    root = tmp_path / "project"
    _project(root)
    source = root / "spec/产品总说明.md"
    target = root / "spec/功能_目标.md"
    source_text = "# 来源\n" + "[规则](./功能_目标.md#ac-01)\n" * 40
    target_text = "### AC-01：规则\n\n原文。\n"
    _write(source, source_text)
    _write(target, target_text)
    reads, parses = Counter(), Counter()
    read_bytes, parse = Path.read_bytes, MarkdownIt.parse

    def counted_read(path):
        if path in (source, target):
            reads[path] += 1
        return read_bytes(path)

    def counted_parse(parser, content, *args, **kwargs):
        parses[content] += 1
        return parse(parser, content, *args, **kwargs)

    monkeypatch.setattr(Path, "read_bytes", counted_read)
    monkeypatch.setattr(MarkdownIt, "parse", counted_parse)
    baseline = links.scan_managed_markdown_links(str(root))
    assert baseline.issues
    assert reads == Counter({source: 1, target: 1})
    assert parses == Counter({source_text: 1, target_text: 1})
    reads.clear()
    parses.clear()
    preview = links.plan_legacy_anchor_repairs(str(root))
    assert reads == Counter({source: 1, target: 1})
    assert parses == Counter({source_text: 1, target_text: 1})
    reads.clear()
    parses.clear()
    monkeypatch.chdir(root)
    cli.cmd_repair_links(Namespace(apply_hash=preview.preview_hash))
    assert parses[source_text] == 1
    assert parses[target_text] == 1
    assert sum(parses.values()) == 3
    assert "修复完成" in capsys.readouterr().out
    assert links.scan_managed_markdown_links(str(root)).ok
    assert links.plan_legacy_anchor_repairs(str(root)).repairs == ()


def test_regeneration_preserves_anchors_and_manual_edits(tmp_path):
    """Workflow-Test
    主题：按程序指引填表和修链接都能一次过关，修复结果不被程序自己抹掉
    测试项：TC-04 修复定位经重新生成和回补仍有效
    验收条件：AC-04 修复定位经重新生成和回补仍有效
    测试方式：自动化测试
    测试层级：集成测试
    产品入口：更新表后重新生成并回补正式文档
    测试入口：tests/test_workflow_guidance.py::test_regeneration_preserves_anchors_and_manual_edits
    代码入口：src/workflow_loop/records.py::_refresh_stage_document
    准备数据：由表生成验收计划并补齐大写历史定位，另准备包含代码块定位文字和正文手改的文档。
    执行动作：修改表中事实后连续生成和回补，扫描链接；再手改正文并尝试生成。
    关键断言：合法历史定位保持唯一可导航；代码块和未知定位不被忽略；正文手改被报告并原样保留。
    预期证据：当前执行的结构化测试报告中入口精确匹配，执行数大于零，跳过失败错误均为零且退出码为零。
    """
    root = tmp_path / "project"
    _project(root, stage="acceptance_plan")
    path, table = _filled_table(root, "acceptance_plan")
    _write(root / "spec/功能_定义.md", '<a id="r-1"></a>\n## 定义\n')
    _write(root / "需求交付追踪表.md", "# 交付关系\n")
    _write(root / "spec/产品总说明.md", f"[验收](../acceptance/{TOPIC}_验收计划.md#AC-01)\n")
    assert records.sync_documents(str(root), WORKFLOW_ID, "acceptance_plan", [TOPIC])[0] == []
    preview = links.plan_legacy_anchor_repairs(str(root))
    assert any(repair.fragment == "AC-01" for repair in preview.repairs)
    assert links.apply_legacy_anchor_repairs(str(root), preview).success
    table = records.load_table(str(path))
    table["验收目标说明"] = ["修改表中的真实目标说明后，已经修复的同一验收定位仍须保持有效。"]
    _save(path, table)
    assert records.sync_documents(str(root), WORKFLOW_ID, "acceptance_plan", [TOPIC])[0] == []
    assert records._refresh_stage_document(str(root), WORKFLOW_ID, "acceptance_plan", TOPIC)
    document = root / f"acceptance/{TOPIC}_验收计划.md"
    content = document.read_text(encoding="utf-8")
    assert content.count('<a id="AC-01"></a>') == 1
    assert links.scan_managed_markdown_links(str(root)).ok
    protected = content + '\n人工补充正文。\n\x60\x60\x60html\n<a id="ac-01"></a>\n\x60\x60\x60\n'
    _write(document, protected)
    records.create_or_complete_table(str(root), WORKFLOW_ID, "acceptance_plan", TOPIC)
    assert records._refresh_stage_document(str(root), WORKFLOW_ID, "acceptance_plan", TOPIC) == []
    problems, _ = records.sync_documents(str(root), WORKFLOW_ID, "acceptance_plan", [TOPIC])
    assert any("与工作记录表不一致" in message for _, message in problems)
    assert document.read_text(encoding="utf-8") == protected
    example = '## Intro\n\n\x60\x60\x60html\n<a id="intro"></a>\n\x60\x60\x60\n'
    assert links.without_generated_anchors(links.with_heading_anchors(example)) == example
    unknown = '<a id="unknown"></a>\n## Intro\n'
    assert links.without_generated_anchors(unknown) == unknown
    duplicate = '<a id="intro"></a>\n<a id="intro"></a>\n## Intro\n'
    assert links.without_generated_anchors(duplicate) == duplicate


def test_final_sync_explains_obsolete_record_ids(tmp_path):
    """Workflow-Test
    主题：按程序指引填表和修链接都能一次过关，修复结果不被程序自己抹掉
    测试项：TC-05 旧机器编号提示当前依据且集合严格匹配
    验收条件：AC-05 旧机器编号提示当前依据且集合严格匹配
    测试方式：自动化测试
    测试层级：集成测试
    产品入口：提交最终设计文档进行编号集合检查
    测试入口：tests/test_workflow_guidance.py::test_final_sync_explains_obsolete_record_ids
    代码入口：src/workflow_loop/artifact_validation.py::validate_final_code_design_document
    准备数据：完整最终设计文档引用旧记录，当前状态保存新的有效回归记录编号。
    执行动作：检查旧编号、缺少编号、多出编号与拼接错误，再填写当前完整集合重新检查。
    关键断言：旧编号被拒绝且提示重跑后重新取得当前集合；仅精确匹配当前有效集合时通过。
    预期证据：当前执行的结构化测试报告中入口精确匹配，执行数大于零，跳过失败错误均为零且退出码为零。
    """
    _write_complete_final_architecture(tmp_path)
    state = state_mod.load_state(str(tmp_path))
    state.regression_test.record_id = "REG-current-2"
    state_mod.save_state(str(tmp_path), state)
    architecture = tmp_path / "spec/代码架构设计.md"
    original = architecture.read_text(encoding="utf-8")
    ok, detail = av.validate_final_code_design_document(str(tmp_path), "test")
    assert not ok
    assert "REG-test-1" in detail and "REG-current-2" in detail
    assert "重跑" in detail and "重新取得" in detail and "当前有效集合" in detail
    valid = original.replace("REG-test-1", "REG-current-2")
    for invalid in ("", "REG-unused-3", "REG-current-2、REG-unused-3", "REG-current-2REG-unused-3"):
        _write(architecture, valid.replace("REG-current-2", invalid))
        assert not av.validate_final_code_design_document(str(tmp_path), "test")[0], invalid
    _write(architecture, valid)
    ok, detail = av.validate_final_code_design_document(str(tmp_path), "test")
    assert ok, detail


def test_no_uncertainty_is_explicit_and_strict(tmp_path):
    """Workflow-Test
    主题：按程序指引填表和修链接都能一次过关，修复结果不被程序自己抹掉
    测试项：TC-06 整栏暂无可通过且必需事实不放宽
    验收条件：AC-06 整栏暂无可通过且必需事实不放宽
    测试方式：自动化测试
    测试层级：集成测试
    产品入口：提交已确认根因的缺陷工作记录表
    测试入口：tests/test_workflow_guidance.py::test_no_uncertainty_is_explicit_and_strict
    代码入口：src/workflow_loop/records.py::validate_table
    准备数据：填全版本 2 和 3 的缺陷事实，分别准备整栏暂无、空栏、混合占位词及缺失必需事实。
    执行动作：对每组输入执行真实表校验，比较不确定性栏和其他必需栏的具体问题。
    关键断言：仅整栏一条暂无表示确无不确定性；空栏、混合占位和事实栏中的占位词均被拒绝。
    预期证据：当前执行的结构化测试报告中入口精确匹配，执行数大于零，跳过失败错误均为零且退出码为零。
    """
    for version in ("2", "3"):
        root = tmp_path / version
        state = _project(root, version)
        path, table = _bug_table(root, version)
        table["修复仍存在的不确定性"] = ["暂无"]
        assert records.validate_table("bug_record", table, version, project_root=str(root)) == []
        problems, _ = records.sync_stage_tables(str(root), state)
        assert not problems, problems
        ok, detail = av.validate_reproduce_documents(str(root), [], WORKFLOW_ID)
        assert ok, detail
        table = records.load_table(str(path))
        for invalid in ([], ["暂无", ""], ["暂无", "待补充"], ["暂无", "仍需核实实际环境中的未决技术问题。"]):
            changed = deepcopy(table)
            changed["修复仍存在的不确定性"] = invalid
            problems = records.validate_table("bug_record", changed, version, project_root=str(root))
            assert any("修复仍存在的不确定性" in message for _, message in problems), invalid
        changed = deepcopy(table)
        changed["缺陷信息"][0]["根因说明" if version == "3" else "根因"] = "暂无"
        if version == "2":
            # 旧版合并根因栏在生成后的文档检查中校验，不能只检查前半段。
            _save(path, changed)
            problems, _ = records.sync_stage_tables(str(root), state)
            assert not problems, problems
            ok, detail = av.validate_reproduce_documents(str(root), [], WORKFLOW_ID)
            assert not ok and "根因说明" in detail, detail
        else:
            assert records.validate_table("bug_record", changed, version, project_root=str(root))
        if version == "3":
            for column in ("运行环境", "真实输入"):
                changed = deepcopy(table)
                changed[column] = ["暂无"]
                assert records.validate_table("bug_record", changed, version, project_root=str(root))


def test_hints_refresh_without_invalidating_facts(tmp_path):
    """Workflow-Test
    主题：按程序指引填表和修链接都能一次过关，修复结果不被程序自己抹掉
    测试项：TC-07 重新加载刷新说明但保留业务事实
    验收条件：AC-07 重新加载刷新说明但保留业务事实
    测试方式：自动化测试
    测试层级：集成测试
    产品入口：重新加载验收计划实施记录和最终同步表
    测试入口：tests/test_workflow_guidance.py::test_hints_refresh_without_invalidating_facts
    代码入口：src/workflow_loop/records.py::create_or_complete_table
    准备数据：三类表含过时填写说明和已填事实，保存更新前业务内容摘要。
    执行动作：重新加载表并比较事实及说明，刷新程序字段后比较摘要，再修改真实事实。
    关键断言：说明写明链接和章节、起止行号及当前编号；刷新不改事实或摘要，真实事实变化仍改变摘要。
    预期证据：当前执行的结构化测试报告中入口精确匹配，执行数大于零，跳过失败错误均为零且退出码为零。
    """
    root = tmp_path / "project"
    state = _project(root, "2")
    for kind in ("acceptance_plan", "impl_record", "design_sync"):
        path, table = _filled_table(root, kind, "2")
        topic = "" if kind in records.WORKFLOW_LEVEL_KINDS else TOPIC
        table["填写说明"] = {"过时说明": "只写一个例子，没有硬性格式。"}
        _save(path, table)
        before = records.load_table(str(path))
        digest = verification._table_document_hash(str(root), WORKFLOW_ID, kind, [topic])
        records.create_or_complete_table(str(root), WORKFLOW_ID, kind, topic)
        updated = records.load_table(str(path))
        assert {k: v for k, v in before.items() if k != "填写说明"} == {
            k: v for k, v in updated.items() if k != "填写说明"
        }
        hints = json.dumps(updated["填写说明"], ensure_ascii=False)
        if kind == "acceptance_plan":
            assert "同时包含" in hints and "章节号或规则编号" in hints
        elif kind == "impl_record":
            assert "起止行号" in hints and "不能只写 L12" in hints
        else:
            assert "当前有效" in hints and "重新取得" in hints
        assert digest == verification._table_document_hash(str(root), WORKFLOW_ID, kind, [topic])
        updated[records.DOC_HASH_KEY] = "a" * 64
        updated[records.BUG_DOC_HASHES_KEY] = {"bug/索引.md": "b" * 64}
        _save(path, updated)
        assert digest == verification._table_document_hash(str(root), WORKFLOW_ID, kind, [topic])
        narrative = records._schema(kind, "2")["narrative"][0]
        updated[narrative].append("这一段是填写事实的真实改变，不能被程序摘要忽略。")
        _save(path, updated)
        assert digest != verification._table_document_hash(str(root), WORKFLOW_ID, kind, [topic])
    path, table = _bug_table(root, "2")
    before = verification._stage_records_content_hash(str(root), state, "reproduce")
    table["填写说明"] = {"已刷新": "新的事实填写说明"}
    table[records.BUG_DOC_HASHES_KEY] = {"bug/索引.md": "c" * 64}
    _save(path, table)
    assert verification._stage_records_content_hash(str(root), state, "reproduce") == before
    table["缺陷说明"].append("新增缺陷事实，必须使已保存的业务内容摘要改变。")
    _save(path, table)
    assert verification._stage_records_content_hash(str(root), state, "reproduce") != before


def test_legacy_tables_keep_frozen_fields(tmp_path):
    """Workflow-Test
    主题：按程序指引填表和修链接都能一次过关，修复结果不被程序自己抹掉
    测试项：TC-08 旧版冻结结构与生成凭据继续兼容
    验收条件：AC-08 旧版冻结结构与生成凭据继续兼容
    测试方式：自动化测试
    测试层级：集成测试
    产品入口：继续冻结旧版本的工作记录表
    测试入口：tests/test_workflow_guidance.py::test_legacy_tables_keep_frozen_fields
    代码入口：src/workflow_loop/records.py::generate_document
    准备数据：分别建立冻结为版本 1 和 2 的旧表及无独立凭据的合法旧生成文档，并建立新轮次表。
    执行动作：继续加载生成旧表并核对事实，更新事实后再次同步；比较新轮次缺陷表的独立栏目。
    关键断言：旧版本与事实不迁移，新轮次才用独立栏目；可核实旧文档建立凭据后仍可正常更新。
    预期证据：当前执行的结构化测试报告中入口精确匹配，执行数大于零，跳过失败错误均为零且退出码为零。
    """
    for version in ("1", "2"):
        root = tmp_path / version
        _project(root, version)
        path, table = _bug_table(root, version)
        facts = deepcopy(table["缺陷信息"])
        assert records.validate_table("bug_record", table, version, project_root=str(root)) == []
        problems, _ = records.sync_documents(str(root), WORKFLOW_ID, "bug_record", [""])
        assert not problems, problems
        current = records.load_table(str(path))
        assert current["表版本"] == version
        document = root / current[records.GENERATED_DOC_PATH_KEY]
        renderer = records._generate_document_v1 if version == "1" else records._generate_document_v2
        legacy_content = renderer("bug_record", current, project_root=str(root))
        _write(document, legacy_content)
        current[records.DOC_HASH_KEY] = sha256(legacy_content.encode("utf-8")).hexdigest()
        _save(path, current)
        Path(records._generation_receipt_path(str(root), "bug_record", current)).unlink()
        records.create_or_complete_table(str(root), WORKFLOW_ID, "bug_record", "")
        reloaded = records.load_table(str(path))
        assert reloaded["表版本"] == version and reloaded["缺陷信息"] == facts
        assert "根因说明" not in reloaded["缺陷信息"][0]
        assert records.validate_table("bug_record", reloaded, version, project_root=str(root)) == []
        reloaded["缺陷说明"].append("旧轮次继续补充事实，程序仍可按冻结结构生成。")
        _save(path, reloaded)
        assert records.sync_documents(str(root), WORKFLOW_ID, "bug_record", [""])[0] == []
        assert reloaded["缺陷说明"][-1] in document.read_text(encoding="utf-8")
    root = tmp_path / "new"
    _project(root)
    _, new_table = _table(root, "bug_record")
    assert new_table["表版本"] == "3"
    assert "运行环境" in new_table and "真实输入" in new_table
    assert "根因证据" not in new_table
    assert set(new_table["填写说明"]["缺陷信息"]) >= {"根因说明", "根因位置", "根因证据"}


def test_link_repair_keeps_transaction_guards(tmp_path):
    """Workflow-Test
    主题：按程序指引填表和修链接都能一次过关，修复结果不被程序自己抹掉
    测试项：TC-09 链接修复保留漂移拒绝与整批恢复
    验收条件：AC-09 链接修复保留漂移拒绝与整批恢复
    测试方式：自动化测试
    测试层级：集成测试
    产品入口：按预览执行存在异常的受控链接修复
    测试入口：tests/test_workflow_guidance.py::test_link_repair_keeps_transaction_guards
    代码入口：src/workflow_loop/markdown_links.py::apply_legacy_anchor_repairs
    准备数据：准备来源和目标漂移、歧义标题、越界或符号链接，以及写入失败和写后来源变化场景。
    执行动作：先预览核对零写入，再逐场景执行修复并检查异常和所有文件原文。
    关键断言：漂移和不安全目标不能误修，歧义只报告；失败恢复全部修复目标，额外来源修改不被覆盖。
    预期证据：当前执行的结构化测试报告中入口精确匹配，执行数大于零，跳过失败错误均为零且退出码为零。
    """
    root = tmp_path / "project"
    _project(root)
    source = root / "spec/产品总说明.md"
    first = root / "spec/功能_一.md"
    second = root / "spec/功能_二.md"
    _write(source, "[一](./功能_一.md#ac-01)\n[二](./功能_二.md#ac-02)\n")
    _write(first, "### AC-01：一\n")
    _write(second, "### AC-02：二\n")
    before = _markdown_snapshot(root)
    preview = links.plan_legacy_anchor_repairs(str(root))
    assert _markdown_snapshot(root) == before
    for changed_path in (source, first):
        original = changed_path.read_text(encoding="utf-8")
        _write(changed_path, original + "\n外部改动。\n")
        drifted = _markdown_snapshot(root)
        with pytest.raises(links.LinkRepairError, match="漂移"):
            links.apply_legacy_anchor_repairs(str(root), preview)
        assert _markdown_snapshot(root) == drifted
        _write(changed_path, original)
    calls = []

    def fail_second(path, content):
        calls.append(path)
        if len(calls) == 2:
            raise OSError("测试注入的磁盘写入失败")
        path.write_bytes(content)

    with pytest.raises(links.LinkRepairError, match="恢复全部原文"):
        links.apply_legacy_anchor_repairs(str(root), preview, replace_file=fail_second)
    assert _markdown_snapshot(root) == before
    assert not (root / links.TRANSACTION_DIR).exists()

    def change_source(path, content):
        path.write_bytes(content)
        _write(source, source.read_text(encoding="utf-8") + "\n并发编辑必须保留。\n")

    with pytest.raises(links.LinkRepairError, match="复查时发生变化"):
        links.apply_legacy_anchor_repairs(str(root), preview, replace_file=change_source)
    assert first.read_bytes() == before["spec/功能_一.md"]
    assert second.read_bytes() == before["spec/功能_二.md"]
    assert "并发编辑必须保留" in source.read_text(encoding="utf-8")
    _write(first, "### AC-01：重复一\n### AC-01：重复二\n")
    outside = tmp_path / "outside.md"
    _write(outside, "# 外部\n")
    (root / "spec/功能_链接.md").symlink_to(outside)
    _write(source, "[歧义](./功能_一.md#ac-01)\n[越界](../../outside.md)\n[链接](./功能_链接.md)\n")
    ambiguous = links.plan_legacy_anchor_repairs(str(root))
    assert not ambiguous.repairs and len(ambiguous.unresolved) == 3
    unchanged = _markdown_snapshot(root)
    result = links.apply_legacy_anchor_repairs(str(root), ambiguous)
    assert result.success and len(result.unresolved) == 3
    assert _markdown_snapshot(root) == unchanged
