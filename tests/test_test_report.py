import hashlib
from pathlib import Path

import pytest

from workflow_loop import test_report


VITEST_ENTRY = "tests/widget.test.ts::shows saved widget"
PYTEST_ENTRY = "tests/test_widget.py::test_saved_widget"


def _write(path: Path, content: str) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path.relative_to(path.parents[2]).as_posix()


def _vitest_xml(*, outcome: str = "", tests: int = 1, skipped: int = 0) -> str:
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<testsuites name="vitest tests" tests="{tests}" failures="0" errors="0" time="0.1">
  <testsuite name="tests/widget.test.ts" tests="{tests}" failures="0" errors="0" skipped="{skipped}" time="0.1">
    {f'<testcase classname="tests/widget.test.ts" name="Widget suite &gt; shows saved widget" time="0.1">{outcome}</testcase>' if tests else ''}
  </testsuite>
</testsuites>
"""


def _pytest_xml(property_xml: str) -> str:
    return f"""<?xml version="1.0" encoding="utf-8"?>
<testsuites name="pytest tests">
  <testsuite name="pytest" tests="1" failures="0" errors="0" skipped="0" time="0.1">
    <testcase classname="tests.test_widget" name="test_saved_widget" time="0.1">
      <properties>{property_xml}</properties>
    </testcase>
  </testsuite>
</testsuites>
"""


def test_vitest_report_recomputes_counts_and_matches_exact_entry(tmp_path):
    """Workflow-Test
    主题：正式测试只在真实目标完整执行后通过
    测试项：TC-03 结构化报告精确证明登记目标
    验收条件：AC-03 结构化报告精确证明登记目标在当前代码上完整执行
    测试方式：自动化测试
    测试层级：单元测试
    测试目标：Vitest 报告按套件路径、类名和固定名称分隔符唯一匹配登记入口
    测试入口：tests/test_test_report.py::test_vitest_report_recomputes_counts_and_matches_exact_entry
    代码入口：workflow_loop.test_report.parse_test_report
    """
    report = tmp_path / ".workflow_loop" / "test_reports" / "result.xml"
    relative = _write(report, _vitest_xml())

    facts = test_report.parse_test_report(
        str(tmp_path), relative, "vitest-junit", [VITEST_ENTRY]
    )

    data = report.read_bytes()
    assert facts.report_hash == hashlib.sha256(data).hexdigest()
    assert facts.report_size == len(data)
    assert facts.discovered_count == 1
    assert facts.executed_count == 1
    assert facts.skipped_count == facts.failed_count == facts.error_count == 0
    assert facts.matched_test_entries == (VITEST_ENTRY,)


def test_vitest_discovered_but_skipped_is_not_counted_as_executed(tmp_path):
    report = tmp_path / ".workflow_loop" / "test_reports" / "result.xml"
    relative = _write(report, _vitest_xml(outcome="<skipped />", skipped=1))

    facts = test_report.parse_test_report(
        str(tmp_path), relative, "vitest-junit", [VITEST_ENTRY]
    )

    assert facts.discovered_count == 1
    assert facts.executed_count == 0
    assert facts.skipped_count == 1


@pytest.mark.parametrize(
    ("outcome", "field", "expected"),
    [
        ("<failure />", "failed_count", 1),
        ("<error />", "error_count", 1),
    ],
)
def test_report_recomputes_failure_and_error_from_testcases(
    tmp_path,
    outcome,
    field,
    expected,
):
    xml = _vitest_xml(outcome=outcome)
    if field == "failed_count":
        xml = xml.replace('failures="0"', 'failures="1"')
    else:
        xml = xml.replace('errors="0"', 'errors="1"')
    report = tmp_path / ".workflow_loop" / "test_reports" / "result.xml"
    relative = _write(report, xml)

    facts = test_report.parse_test_report(
        str(tmp_path), relative, "vitest-junit", [VITEST_ENTRY]
    )

    assert facts.executed_count == 1
    assert getattr(facts, field) == expected


@pytest.mark.parametrize(
    "entries,name,detail",
    [
        (["tests/other.test.ts::shows saved widget"], "Widget suite > shows saved widget", "唯一匹配"),
        ([VITEST_ENTRY, "tests/widget.test.ts::Widget suite > shows saved widget"], "Widget suite > shows saved widget", "唯一匹配"),
    ],
)
def test_vitest_rejects_missing_or_ambiguous_target(tmp_path, entries, name, detail):
    xml = _vitest_xml().replace("Widget suite &gt; shows saved widget", name.replace(">", "&gt;"))
    report = tmp_path / ".workflow_loop" / "test_reports" / "result.xml"
    relative = _write(report, xml)

    with pytest.raises(test_report.TestReportError, match=detail):
        test_report.parse_test_report(str(tmp_path), relative, "vitest-junit", entries)


def test_pytest_matches_only_dedicated_original_nodeid_property(tmp_path):
    report = tmp_path / ".workflow_loop" / "test_reports" / "result.xml"
    relative = _write(
        report,
        _pytest_xml(
            f'<property name="{test_report.PYTEST_NODEID_PROPERTY}" value="{PYTEST_ENTRY}" />'
        ),
    )

    facts = test_report.parse_test_report(
        str(tmp_path), relative, "pytest-junitxml", [PYTEST_ENTRY]
    )

    assert facts.executed_count == 1
    assert facts.matched_test_entries == (PYTEST_ENTRY,)


def test_pytest_does_not_guess_target_from_classname_or_name(tmp_path):
    report = tmp_path / ".workflow_loop" / "test_reports" / "result.xml"
    relative = _write(report, _pytest_xml(""))

    with pytest.raises(test_report.TestReportError, match="workflow_loop_nodeid"):
        test_report.parse_test_report(
            str(tmp_path), relative, "pytest-junitxml", [PYTEST_ENTRY]
        )


@pytest.mark.parametrize(
    "xml,detail",
    [
        (_vitest_xml().replace('tests="1" failures="0"', 'tests="2" failures="0"', 1), "汇总"),
        (_vitest_xml().replace(' skipped="0"', ""), "缺少 skipped"),
        ("<report />", "根节点"),
        ("<!DOCTYPE testsuites><testsuites tests=\"0\" failures=\"0\" errors=\"0\" />", "DTD"),
        ("<!ENTITY x \"value\"><testsuites tests=\"0\" failures=\"0\" errors=\"0\" />", "ENTITY"),
    ],
)
def test_report_rejects_untrusted_or_inconsistent_xml(tmp_path, xml, detail):
    report = tmp_path / ".workflow_loop" / "test_reports" / "result.xml"
    relative = _write(report, xml)

    with pytest.raises(test_report.TestReportError, match=detail):
        test_report.parse_test_report(
            str(tmp_path), relative, "vitest-junit", [VITEST_ENTRY]
        )


def test_report_rejects_symlink_outside_path_and_oversize(tmp_path, monkeypatch):
    outside = tmp_path.parent / "outside-report.xml"
    outside.write_text(_vitest_xml(), encoding="utf-8")
    report_dir = tmp_path / ".workflow_loop" / "test_reports"
    report_dir.mkdir(parents=True)
    link = report_dir / "linked.xml"
    link.symlink_to(outside)

    with pytest.raises(test_report.TestReportError, match="符号链接"):
        test_report.parse_test_report(
            str(tmp_path), ".workflow_loop/test_reports/linked.xml", "vitest-junit", [VITEST_ENTRY]
        )
    with pytest.raises(test_report.TestReportError, match="越出项目"):
        test_report.parse_test_report(
            str(tmp_path), "../outside-report.xml", "vitest-junit", [VITEST_ENTRY]
        )

    regular = report_dir / "regular.xml"
    regular.write_text(_vitest_xml(), encoding="utf-8")
    monkeypatch.setattr(test_report, "MAX_REPORT_BYTES", 8)
    with pytest.raises(test_report.TestReportError, match="大小限制"):
        test_report.parse_test_report(
            str(tmp_path), ".workflow_loop/test_reports/regular.xml", "vitest-junit", [VITEST_ENTRY]
        )


def test_report_rejects_utf16_before_dtd_scan(tmp_path):
    report = tmp_path / ".workflow_loop" / "test_reports" / "result.xml"
    report.parent.mkdir(parents=True)
    report.write_bytes("<!DOCTYPE testsuites><testsuites />".encode("utf-16"))

    with pytest.raises(test_report.TestReportError, match="UTF-8 XML"):
        test_report.parse_test_report(
            str(tmp_path),
            ".workflow_loop/test_reports/result.xml",
            "vitest-junit",
            [VITEST_ENTRY],
        )


def test_append_report_arguments_is_unique_and_adapter_specific():
    vitest = test_report.append_report_arguments(
        ["npx", "vitest", "run", "tests/widget.test.ts"],
        "vitest-junit",
        ".workflow_loop/test_reports/vitest.xml",
    )
    pytest_command = test_report.append_report_arguments(
        ["pytest", PYTEST_ENTRY],
        "pytest-junitxml",
        ".workflow_loop/test_reports/pytest.xml",
    )

    assert vitest[-2:] == [
        "--reporter=junit",
        "--outputFile.junit=.workflow_loop/test_reports/vitest.xml",
    ]
    assert pytest_command[-3:] == [
        "-p",
        "workflow_loop.test_report",
        "--junitxml=.workflow_loop/test_reports/pytest.xml",
    ]
    with pytest.raises(test_report.TestReportError, match="已经包含"):
        test_report.append_report_arguments(
            ["vitest", "run", "--reporter=default"],
            "vitest-junit",
            "result.xml",
        )
    with pytest.raises(test_report.TestReportError, match="不支持"):
        test_report.append_report_arguments(["jest"], "jest-junit", "result.xml")


def test_pytest_plugin_writes_exact_nodeid_once():
    class Item:
        nodeid = PYTEST_ENTRY
        user_properties = [(test_report.PYTEST_NODEID_PROPERTY, "stale"), ("other", "kept")]

    item = Item()
    test_report.pytest_collection_modifyitems([item])

    assert item.user_properties == [
        ("other", "kept"),
        (test_report.PYTEST_NODEID_PROPERTY, PYTEST_ENTRY),
    ]
