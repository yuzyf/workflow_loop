"""受控测试执行使用的结构化报告适配与严格 XML 解析。"""

from __future__ import annotations

import hashlib
import os
import re
import stat
import xml.etree.ElementTree as ET
from collections import Counter
from dataclasses import dataclass


SUPPORTED_REPORT_ADAPTERS = frozenset({"vitest-junit", "pytest-junitxml"})
MAX_REPORT_BYTES = 8 * 1024 * 1024
PYTEST_NODEID_PROPERTY = "workflow_loop_nodeid"
_XML_FORBIDDEN_DECLARATIONS = re.compile(br"<!\s*(?:DOCTYPE|ENTITY)\b", re.IGNORECASE)
_SUMMARY_FIELDS = ("tests", "failures", "errors")
_OUTCOME_TAGS = {"skipped", "failure", "error"}


@dataclass(frozen=True)
class TestReportFacts:
    """从具体测试用例重算并与报告汇总交叉核对的机器事实。"""

    report_adapter: str
    report_hash: str
    report_size: int
    discovered_count: int
    executed_count: int
    skipped_count: int
    failed_count: int
    error_count: int
    matched_test_entries: tuple[str, ...]


class TestReportError(ValueError):
    """报告路径、XML 结构、计数或目标映射不可信。"""


def append_report_arguments(
    command: list[str],
    report_adapter: str,
    report_path: str,
) -> list[str]:
    """为受支持测试框架追加唯一报告参数，不修改调用方的参数数组。"""

    if report_adapter not in SUPPORTED_REPORT_ADAPTERS:
        raise TestReportError(f"不支持的结构化报告适配器: {report_adapter}")
    if not report_path or not report_path.endswith(".xml"):
        raise TestReportError("结构化测试报告路径必须是非空 .xml 路径")
    if not command or any(not isinstance(token, str) or not token for token in command):
        raise TestReportError("测试命令参数必须是非空字符串")

    if report_adapter == "vitest-junit":
        conflicts = (
            "--reporter",
            "--outputFile",
            "--output-file",
        )
        if _has_option(command, conflicts):
            raise TestReportError(
                "测试命令已经包含 Vitest 报告器或输出路径参数，程序不能保证只生成一份受控报告"
            )
        return [
            *command,
            "--reporter=junit",
            f"--outputFile.junit={report_path}",
        ]

    conflicts = ("--junitxml", "--junit-xml", "--junit-prefix")
    if _has_option(command, conflicts) or _loads_pytest_plugin(command):
        raise TestReportError(
            "测试命令已经包含 pytest JUnit 报告参数或报告属性插件，程序不能保证配置唯一"
        )
    return [
        *command,
        "-p",
        "workflow_loop.test_report",
        f"--junitxml={report_path}",
    ]


def _has_option(command: list[str], option_names: tuple[str, ...]) -> bool:
    for token in command:
        if any(token == name or token.startswith(name + "=") or token.startswith(name + ".") for name in option_names):
            return True
    return False


def _loads_pytest_plugin(command: list[str]) -> bool:
    for index, token in enumerate(command):
        if token == "-p" and index + 1 < len(command):
            if command[index + 1] == "workflow_loop.test_report":
                return True
        if token.startswith("-p=") and token[3:] == "workflow_loop.test_report":
            return True
    return False


def pytest_collection_modifyitems(items) -> None:
    """pytest 插件钩子：把原始 ``item.nodeid`` 写入每个 JUnit 用例属性。"""

    for item in items:
        properties = [
            (name, value)
            for name, value in item.user_properties
            if name != PYTEST_NODEID_PROPERTY
        ]
        properties.append((PYTEST_NODEID_PROPERTY, item.nodeid))
        item.user_properties = properties


def parse_test_report(
    project_root: str,
    report_path: str,
    report_adapter: str,
    expected_test_entries: list[str] | tuple[str, ...],
) -> TestReportFacts:
    """解析一个新生成的严格 JUnit XML，并精确匹配本任务登记入口。"""

    if report_adapter not in SUPPORTED_REPORT_ADAPTERS:
        raise TestReportError(f"不支持的结构化报告适配器: {report_adapter}")
    expected = _validate_expected_entries(expected_test_entries)
    data = _read_trusted_report(project_root, report_path)
    if data.startswith((b"\xff\xfe", b"\xfe\xff", b"\xff\xfe\x00\x00", b"\x00\x00\xfe\xff")):
        raise TestReportError("结构化测试报告只接受 UTF-8 XML，不能使用 UTF-16 或 UTF-32 绕过声明检查")
    if _XML_FORBIDDEN_DECLARATIONS.search(data):
        raise TestReportError("结构化测试报告不能包含 DTD 或 ENTITY 声明")
    try:
        root = ET.fromstring(data)
    except ET.ParseError as exc:
        raise TestReportError(f"结构化测试报告不是有效 XML: {exc}") from exc
    if root.tag not in {"testsuites", "testsuite"}:
        raise TestReportError(
            f"结构化测试报告根节点必须是 testsuites 或 testsuite，实际是 {root.tag!r}"
        )

    suites = _report_suites(root)
    cases_by_suite: list[tuple[ET.Element, list[ET.Element]]] = []
    total = Counter(tests=0, failures=0, errors=0, skipped=0)
    for suite_index, suite in enumerate(suites, start=1):
        unknown_children = [
            child.tag
            for child in suite
            if child.tag not in {"testcase", "properties", "system-out", "system-err"}
        ]
        if unknown_children:
            raise TestReportError(
                f"第 {suite_index} 个 testsuite 包含未知子节点: {sorted(set(unknown_children))}"
            )
        cases = list(suite.findall("testcase"))
        counts = _count_cases(cases, f"第 {suite_index} 个 testsuite")
        _validate_summary(suite, counts, f"第 {suite_index} 个 testsuite", require_skipped=True)
        total.update(counts)
        cases_by_suite.append((suite, cases))

    if root.tag == "testsuites" and any(
        field in root.attrib for field in (*_SUMMARY_FIELDS, "skipped")
    ):
        _validate_summary(root, total, "testsuites 根节点", require_skipped=False)
    cases = [case for _, suite_cases in cases_by_suite for case in suite_cases]
    if report_adapter == "vitest-junit":
        matched = _match_vitest_entries(cases_by_suite, expected)
    else:
        matched = _match_pytest_entries(cases, expected)

    return TestReportFacts(
        report_adapter=report_adapter,
        report_hash=hashlib.sha256(data).hexdigest(),
        report_size=len(data),
        discovered_count=total["tests"],
        executed_count=total["tests"] - total["skipped"],
        skipped_count=total["skipped"],
        failed_count=total["failures"],
        error_count=total["errors"],
        matched_test_entries=tuple(matched),
    )


def _validate_expected_entries(entries: list[str] | tuple[str, ...]) -> tuple[str, ...]:
    if not isinstance(entries, (list, tuple)) or not entries:
        raise TestReportError("必须登记至少一个精确测试入口")
    if any(not isinstance(entry, str) or not entry.strip() for entry in entries):
        raise TestReportError("登记测试入口必须是非空字符串")
    normalized = tuple(entry.strip() for entry in entries)
    duplicates = sorted(entry for entry, count in Counter(normalized).items() if count > 1)
    if duplicates:
        raise TestReportError(f"登记测试入口不能重复: {duplicates}")
    return normalized


def _read_trusted_report(project_root: str, report_path: str) -> bytes:
    if not isinstance(report_path, str) or not report_path:
        raise TestReportError("结构化测试报告路径不能为空")
    if os.path.isabs(report_path):
        raise TestReportError("结构化测试报告路径必须是项目相对路径")
    normalized = os.path.normpath(report_path)
    if normalized in {"", "."} or normalized == ".." or normalized.startswith(".." + os.sep):
        raise TestReportError(f"结构化测试报告路径越出项目: {report_path}")

    project_abs = os.path.abspath(project_root)
    candidate = os.path.abspath(os.path.join(project_abs, normalized))
    try:
        if os.path.commonpath([project_abs, candidate]) != project_abs:
            raise TestReportError(f"结构化测试报告路径越出项目: {report_path}")
    except ValueError as exc:
        raise TestReportError(f"结构化测试报告路径越出项目: {report_path}") from exc

    current = project_abs
    for component in normalized.split(os.sep):
        current = os.path.join(current, component)
        if os.path.islink(current):
            raise TestReportError(f"结构化测试报告路径不能经过符号链接: {report_path}")
    try:
        metadata = os.stat(candidate, follow_symlinks=False)
    except FileNotFoundError as exc:
        raise TestReportError(f"结构化测试报告不存在: {report_path}") from exc
    if not stat.S_ISREG(metadata.st_mode):
        raise TestReportError(f"结构化测试报告必须是普通文件: {report_path}")
    if metadata.st_size <= 0:
        raise TestReportError(f"结构化测试报告不能为空: {report_path}")
    if metadata.st_size > MAX_REPORT_BYTES:
        raise TestReportError(
            f"结构化测试报告超过大小限制: {metadata.st_size} > {MAX_REPORT_BYTES} 字节"
        )
    with open(candidate, "rb") as stream:
        data = stream.read(MAX_REPORT_BYTES + 1)
    if len(data) != metadata.st_size:
        raise TestReportError("结构化测试报告读取期间发生变化，不能作为本次执行证据")
    return data


def _report_suites(root: ET.Element) -> list[ET.Element]:
    if root.tag == "testsuite":
        return [root]
    suites = list(root.findall("testsuite"))
    unknown = [child.tag for child in root if child.tag != "testsuite"]
    if unknown:
        raise TestReportError(f"testsuites 根节点包含未知子节点: {sorted(set(unknown))}")
    if not suites:
        raise TestReportError("testsuites 根节点必须包含至少一个 testsuite 子节点")
    return suites


def _count_cases(cases: list[ET.Element], location: str) -> Counter:
    counts = Counter(tests=len(cases), failures=0, errors=0, skipped=0)
    for index, case in enumerate(cases, start=1):
        unknown = [
            child.tag
            for child in case
            if child.tag not in _OUTCOME_TAGS | {"properties", "system-out", "system-err"}
        ]
        if unknown:
            raise TestReportError(
                f"{location} 第 {index} 个 testcase 包含未知子节点: {sorted(set(unknown))}"
            )
        outcomes = [child.tag for child in case if child.tag in _OUTCOME_TAGS]
        if len(outcomes) > 1:
            raise TestReportError(f"{location} 第 {index} 个 testcase 同时包含多个结果: {outcomes}")
        if outcomes:
            outcome = outcomes[0]
            counts[{"failure": "failures", "error": "errors", "skipped": "skipped"}[outcome]] += 1
    return counts


def _validate_summary(
    element: ET.Element,
    actual: Counter,
    location: str,
    *,
    require_skipped: bool,
) -> None:
    required = (*_SUMMARY_FIELDS, "skipped") if require_skipped else _SUMMARY_FIELDS
    for field in required:
        declared = _integer_attribute(element, field, location)
        if declared != actual[field]:
            raise TestReportError(
                f"{location} 的 {field} 汇总与具体 testcase 冲突: 声明 {declared}，重算 {actual[field]}"
            )
    if not require_skipped and "skipped" in element.attrib:
        declared = _integer_attribute(element, "skipped", location)
        if declared != actual["skipped"]:
            raise TestReportError(
                f"{location} 的 skipped 汇总与具体 testcase 冲突: 声明 {declared}，重算 {actual['skipped']}"
            )


def _integer_attribute(element: ET.Element, field: str, location: str) -> int:
    value = element.get(field)
    if value is None:
        raise TestReportError(f"{location} 缺少 {field} 汇总字段")
    if not re.fullmatch(r"\d+", value):
        raise TestReportError(f"{location} 的 {field} 必须是非负整数，实际是 {value!r}")
    return int(value)


def _match_vitest_entries(
    cases_by_suite: list[tuple[ET.Element, list[ET.Element]]],
    expected: tuple[str, ...],
) -> list[str]:
    targets: list[tuple[str, str, str]] = []
    for entry in expected:
        if "::" not in entry:
            raise TestReportError(f"Vitest 登记入口必须是 <项目相对路径>::<测试标题>: {entry}")
        path, title = entry.split("::", 1)
        if not path or not title:
            raise TestReportError(f"Vitest 登记入口必须同时包含路径和标题: {entry}")
        targets.append((entry, path, title))

    matched: list[str] = []
    for suite, cases in cases_by_suite:
        suite_name = suite.get("name")
        if not suite_name:
            raise TestReportError("Vitest testsuite 缺少 name 路径字段")
        for case in cases:
            classname = case.get("classname")
            name = case.get("name")
            if not classname or not name:
                raise TestReportError("Vitest testcase 必须同时包含 classname 路径和 name 测试名称")
            candidates = [
                entry
                for entry, path, title in targets
                if suite_name == path
                and classname == path
                and (name == title or name.endswith(" > " + title))
            ]
            if len(candidates) != 1:
                raise TestReportError(
                    "Vitest testcase 必须唯一匹配一个登记入口: "
                    f"suite={suite_name!r}, classname={classname!r}, name={name!r}, 匹配={candidates}"
                )
            matched.append(candidates[0])
    return _require_exact_one_to_one(matched, expected, "Vitest")


def _match_pytest_entries(cases: list[ET.Element], expected: tuple[str, ...]) -> list[str]:
    matched: list[str] = []
    for index, case in enumerate(cases, start=1):
        values = [
            prop.get("value")
            for properties in case.findall("properties")
            for prop in properties.findall("property")
            if prop.get("name") == PYTEST_NODEID_PROPERTY
        ]
        if len(values) != 1 or not values[0]:
            raise TestReportError(
                f"pytest 第 {index} 个 testcase 必须有且只有一个 {PYTEST_NODEID_PROPERTY} 属性"
            )
        nodeid = values[0]
        if nodeid not in expected:
            raise TestReportError(f"pytest 报告包含未登记的原始测试入口: {nodeid}")
        matched.append(nodeid)
    return _require_exact_one_to_one(matched, expected, "pytest")


def _require_exact_one_to_one(
    matched: list[str],
    expected: tuple[str, ...],
    adapter_name: str,
) -> list[str]:
    actual_counts = Counter(matched)
    duplicates = sorted(entry for entry, count in actual_counts.items() if count > 1)
    missing = sorted(set(expected) - set(matched))
    extra = sorted(set(matched) - set(expected))
    if duplicates or missing or extra or len(matched) != len(expected):
        raise TestReportError(
            f"{adapter_name} 报告目标与登记入口不是双向一一对应: "
            f"缺少={missing}，多出={extra}，重复={duplicates}"
        )
    return [entry for entry in expected]
