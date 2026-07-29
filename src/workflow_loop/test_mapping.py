"""测试计划、测试代码标识和自动化范围的对应关系。"""

from __future__ import annotations

import ast
from dataclasses import dataclass
import os
import re


TEST_METHODS = {
    "自动化测试",
    "人工验收",
    "自动化测试 + 人工验收",
}
AUTOMATED_TEST_METHODS = {
    "自动化测试",
    "自动化测试 + 人工验收",
}
TEST_LEVELS = {
    "单元测试",
    "模块测试",
    "集成测试",
    "命令测试",
    "接口测试",
    "端到端测试",
}
TEST_SOURCE_SUFFIXES = {
    ".c", ".cc", ".cpp", ".cxx", ".java", ".kt", ".kts",
    ".py", ".go", ".rs", ".swift", ".m", ".mm", ".js", ".jsx",
    ".ts", ".tsx", ".vue", ".svelte", ".rb", ".php", ".cs", ".fs",
    ".ets", ".qml", ".sh", ".bash", ".zsh", ".bats",
}
EXCLUDED_DIRS = {
    ".git", ".workflow_loop", ".venv", "node_modules", "__pycache__",
    ".pytest_cache", "dist", "build",
}
TEST_DIRECTORY_NAMES = {
    "tests", "test", "__tests__", "testdata", "test_data",
    "integration_tests", "e2e",
}

AC_LINK_RE = re.compile(r"\[(AC-\d{2,})[：:]\s*([^\]]+)\]\([^)]+\)")
TC_LINK_RE = re.compile(
    r"\[(TC-\d{2,})\s+([^\]]+)\]\(#(tc-\d{2,})\)"
)
ID_AND_NAME_RE = re.compile(r"^((?:AC|TC)-\d{2,})\s+(.+?)\s*$")
MARKER_FIELDS = (
    "主题",
    "测试项",
    "验收条件",
    "测试方式",
    "测试层级",
    "测试目标",
    "测试入口",
    "代码入口",
)


@dataclass(frozen=True)
class TestPlanItem:
    topic: str
    criterion_id: str
    criterion_name: str
    test_id: str
    test_name: str
    test_method: str
    dependencies: tuple[str, ...] = ()

    @property
    def requires_test_code(self) -> bool:
        return self.test_method in AUTOMATED_TEST_METHODS


@dataclass(frozen=True)
class WorkflowTestMarker:
    path: str
    line: int
    topic: str
    test_id: str
    test_name: str
    criterion_id: str
    criterion_name: str
    test_method: str
    test_level: str
    test_target: str
    test_entry: str
    code_entry: str


def _read_text(project_root: str, relative_path: str) -> str:
    with open(os.path.join(project_root, relative_path), "r", encoding="utf-8") as stream:
        return stream.read()


def _section(content: str, heading: str) -> str | None:
    match = re.search(
        rf"^##\s+{re.escape(heading)}\s*$\n(.*?)(?=^##\s+|\Z)",
        content,
        re.MULTILINE | re.DOTALL,
    )
    return match.group(1).strip() if match else None


def _table_rows(content: str) -> tuple[list[str], list[list[str]]]:
    lines = content.splitlines()
    for header_index, line in enumerate(lines):
        stripped = line.strip()
        if not stripped.startswith("|") or not stripped.endswith("|"):
            continue
        headers = [cell.strip() for cell in stripped.strip("|").split("|")]
        if "验收条件链接" not in headers or "测试项" not in headers:
            continue
        rows: list[list[str]] = []
        for row_line in lines[header_index + 1 :]:
            row_stripped = row_line.strip()
            if not row_stripped.startswith("|") or not row_stripped.endswith("|"):
                if rows:
                    break
                continue
            cells = [cell.strip() for cell in row_stripped.strip("|").split("|")]
            if all(re.fullmatch(r"[-:]+", cell) for cell in cells):
                continue
            if len(cells) != len(headers):
                raise ValueError("验收条件覆盖表的数据列数与表头不一致")
            rows.append(cells)
        return headers, rows
    raise ValueError("缺少验收条件覆盖表")


def parse_test_plan_items(project_root: str, topic: str) -> list[TestPlanItem]:
    """读取一个主题测试计划中的 AC、TC 和测试方式。"""

    relative_path = os.path.join("qa", f"{topic}_plan.md")
    full_path = os.path.join(project_root, relative_path)
    if not os.path.isfile(full_path):
        raise ValueError(f"缺少测试计划文档: {relative_path}")

    coverage = _section(_read_text(project_root, relative_path), "1. 验收条件覆盖")
    if coverage is None:
        raise ValueError(f"{relative_path} 缺少“1. 验收条件覆盖”")
    headers, rows = _table_rows(coverage)
    required_headers = [
        "验收条件链接",
        "测试项",
        "前置测试项",
        "测试方式",
        "验证方向",
        "预期观察结果",
        "证据要求",
    ]
    if headers != required_headers:
        raise ValueError(f"{relative_path} 的验收条件覆盖表头必须是 {required_headers}")

    items: list[TestPlanItem] = []
    seen_test_ids: set[str] = set()
    for cells in rows:
        criterion_match = AC_LINK_RE.search(cells[0])
        if criterion_match is None:
            raise ValueError(f"{relative_path} 的验收条件必须同时写编号、名称和链接")
        test_match = TC_LINK_RE.search(cells[1])
        if test_match is None:
            raise ValueError(f"{relative_path} 的测试项必须同时写编号、名称和锚点")
        test_id, test_name, anchor_id = test_match.groups()
        if test_id.lower() != anchor_id.lower():
            raise ValueError(f"{relative_path} 的测试项 {test_id} 锚点必须是 #{test_id.lower()}")
        if test_id in seen_test_ids:
            raise ValueError(f"{relative_path} 的测试项 {test_id} 只能对应一条主要验收条件")
        dependency_cell = cells[2].strip()
        dependencies = _parse_dependencies(dependency_cell, relative_path, test_id)
        test_method = cells[3].strip()
        if test_method not in TEST_METHODS:
            raise ValueError(
                f"{relative_path} 的测试项 {test_id} 测试方式必须是 {sorted(TEST_METHODS)}"
            )
        seen_test_ids.add(test_id)
        items.append(
            TestPlanItem(
                topic=topic,
                criterion_id=criterion_match.group(1),
                criterion_name=criterion_match.group(2).strip(),
                test_id=test_id,
                test_name=test_name.strip(),
                test_method=test_method,
                dependencies=dependencies,
            )
        )
    if not items:
        raise ValueError(f"{relative_path} 没有测试项")
    _validate_dependencies(items, relative_path)
    return items


def _parse_dependencies(value: str, relative_path: str, test_id: str) -> tuple[str, ...]:
    """解析同一主题内的直接前置测试项。"""
    if value in {"", "无", "暂无"}:
        return ()
    dependencies = tuple(
        part.strip()
        for part in re.split(r"[,，、\s]+", value)
        if part.strip()
    )
    if any(not re.fullmatch(r"TC-\d{2,}", dependency) for dependency in dependencies):
        raise ValueError(
            f"{relative_path} 的测试项 {test_id} 的前置测试项必须写 TC 编号，多个编号用逗号或顿号分隔"
        )
    if test_id in dependencies:
        raise ValueError(f"{relative_path} 的测试项 {test_id} 不能依赖自己")
    return dependencies


def _validate_dependencies(items: list[TestPlanItem], relative_path: str) -> None:
    """检查依赖引用存在且没有循环，避免执行顺序不确定。"""
    known = {item.test_id for item in items}
    item_by_id = {item.test_id: item for item in items}
    dependencies = {item.test_id: item.dependencies for item in items}
    for test_id, refs in dependencies.items():
        unknown = sorted(set(refs) - known)
        if unknown:
            raise ValueError(
                f"{relative_path} 的测试项 {test_id} 引用了不存在的前置测试项: {unknown}"
            )
        if item_by_id[test_id].requires_test_code:
            manual_dependencies = [
                dependency
                for dependency in refs
                if item_by_id[dependency].test_method == "人工验收"
            ]
            if manual_dependencies:
                raise ValueError(
                    f"{relative_path} 的自动化测试项 {test_id} 不能依赖人工验收项: "
                    f"{manual_dependencies}；人工验收发生在主题验收阶段"
                )

    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(test_id: str) -> None:
        if test_id in visiting:
            raise ValueError(f"{relative_path} 的测试项依赖存在循环")
        if test_id in visited:
            return
        visiting.add(test_id)
        for dependency in dependencies[test_id]:
            visit(dependency)
        visiting.remove(test_id)
        visited.add(test_id)

    for test_id in dependencies:
        visit(test_id)


def collect_test_plan_items(project_root: str, topics: list[str]) -> list[TestPlanItem]:
    items: list[TestPlanItem] = []
    for topic in topics:
        items.extend(parse_test_plan_items(project_root, topic))
    return items


def automated_test_items(project_root: str, topics: list[str]) -> list[TestPlanItem]:
    return [item for item in collect_test_plan_items(project_root, topics) if item.requires_test_code]


def automated_topics(project_root: str, topics: list[str]) -> list[str]:
    return [
        topic
        for topic in topics
        if any(item.requires_test_code for item in parse_test_plan_items(project_root, topic))
    ]


def topic_requires_test_code(project_root: str, topic: str) -> bool:
    return any(item.requires_test_code for item in parse_test_plan_items(project_root, topic))


def criterion_requires_test_code(
    project_root: str,
    topic: str,
    criterion_id: str,
) -> bool:
    """判断一条 AC 是否至少有一个自动化或混合测试项。"""
    return any(
        item.criterion_id == criterion_id and item.requires_test_code
        for item in parse_test_plan_items(project_root, topic)
    )


def _is_test_source(relative_path: str) -> bool:
    normalized = relative_path.replace(os.sep, "/")
    parts = normalized.split("/")
    filename = parts[-1].lower()
    suffix = os.path.splitext(filename)[1]
    if suffix not in TEST_SOURCE_SUFFIXES:
        return False
    stem = os.path.splitext(filename)[0]
    return (
        any(part.lower() in TEST_DIRECTORY_NAMES for part in parts[:-1])
        or filename.startswith(("test_", "tst_"))
        or stem.endswith(("_test", "_spec", ".test", ".spec"))
    )


def _test_source_paths(project_root: str) -> list[str]:
    paths: list[str] = []
    for root, dirs, files in os.walk(project_root):
        dirs[:] = [directory for directory in dirs if directory not in EXCLUDED_DIRS]
        for filename in files:
            relative_path = os.path.relpath(os.path.join(root, filename), project_root)
            if _is_test_source(relative_path):
                paths.append(relative_path)
    return sorted(paths)


def _clean_marker_line(line: str) -> str:
    value = line.strip()
    value = re.sub(r"^(?:#|/{2,}|/\*+|\*+)\s*", "", value)
    value = re.sub(r"(?:\*/|\"\"\"|''')\s*$", "", value).strip()
    return value


def _id_and_name(value: str, expected_prefix: str) -> tuple[str, str] | None:
    match = ID_AND_NAME_RE.match(value.strip())
    if match is None or not match.group(1).startswith(expected_prefix):
        return None
    return match.group(1), match.group(2).strip()


def _parse_marker_lines(
    lines: list[str],
    relative_path: str,
    *,
    line_offset: int = 0,
    require_comment: bool = False,
) -> list[WorkflowTestMarker]:
    markers: list[WorkflowTestMarker] = []
    for index, line in enumerate(lines):
        if "Workflow-Test" not in line:
            continue
        if require_comment and re.match(r"^\s*(?:#|/{2,}|/\*+|\*+)", line) is None:
            continue
        fields: dict[str, str] = {}
        for raw_line in lines[index + 1 : index + 12]:
            cleaned = _clean_marker_line(raw_line)
            if "Workflow-Test" in cleaned:
                break
            for label in MARKER_FIELDS:
                prefix = f"{label}："
                if cleaned.startswith(prefix):
                    fields[label] = cleaned[len(prefix) :].strip()
                    break
        test_value = _id_and_name(fields.get("测试项", ""), "TC-")
        criterion_value = _id_and_name(fields.get("验收条件", ""), "AC-")
        if test_value is None or criterion_value is None:
            continue
        markers.append(
            WorkflowTestMarker(
                path=relative_path,
                line=line_offset + index + 1,
                topic=fields.get("主题", ""),
                test_id=test_value[0],
                test_name=test_value[1],
                criterion_id=criterion_value[0],
                criterion_name=criterion_value[1],
                test_method=fields.get("测试方式", ""),
                test_level=fields.get("测试层级", ""),
                test_target=fields.get("测试目标", ""),
                test_entry=fields.get("测试入口", ""),
                code_entry=fields.get("代码入口", ""),
            )
        )
    return markers


def _parse_python_markers(content: str, relative_path: str) -> list[WorkflowTestMarker]:
    """Python 只接受真实测试函数或测试类的文档字符串。"""
    try:
        tree = ast.parse(content)
    except SyntaxError:
        return []
    markers: list[WorkflowTestMarker] = []
    for node in ast.walk(tree):
        is_test_node = (
            isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and node.name.startswith("test")
        ) or (
            isinstance(node, ast.ClassDef)
            and node.name.startswith("Test")
        )
        if not is_test_node or not node.body:
            continue
        first_statement = node.body[0]
        if not (
            isinstance(first_statement, ast.Expr)
            and isinstance(first_statement.value, ast.Constant)
            and isinstance(first_statement.value.value, str)
        ):
            continue
        docstring = first_statement.value.value
        if "Workflow-Test" not in docstring:
            continue
        parsed = _parse_marker_lines(
            docstring.splitlines(),
            relative_path,
            line_offset=first_statement.lineno - 1,
        )
        if len(parsed) > 1:
            raise ValueError(
                f"{relative_path}:{first_statement.lineno} 一个 Python 测试函数或测试类只能写一个 Workflow-Test 标识"
            )
        markers.extend(parsed)
    return markers


def _parse_markers_from_file(project_root: str, relative_path: str) -> list[WorkflowTestMarker]:
    content = _read_text(project_root, relative_path)
    if relative_path.lower().endswith(".py"):
        return _parse_python_markers(content, relative_path)
    return _parse_marker_lines(
        content.splitlines(),
        relative_path,
        require_comment=True,
    )


def _has_real_text(value: str) -> bool:
    normalized = value.strip()
    return bool(normalized) and "<" not in normalized and "todo" not in normalized.lower()


def validate_workflow_test_markers(
    project_root: str,
    topics: list[str],
) -> tuple[bool, str]:
    expected_items = automated_test_items(project_root, topics)
    if not expected_items:
        return True, "当前工作流没有自动化测试项，无需 Workflow-Test 标识"

    markers: list[WorkflowTestMarker] = []
    try:
        for relative_path in _test_source_paths(project_root):
            markers.extend(_parse_markers_from_file(project_root, relative_path))
    except ValueError as exc:
        return False, str(exc)

    for item in expected_items:
        candidates = [
            marker
            for marker in markers
            if marker.topic == item.topic and marker.test_id == item.test_id
        ]
        if not candidates:
            return (
                False,
                f"测试代码缺少 Workflow-Test 标识: {item.topic} / {item.test_id} {item.test_name}",
            )
        valid = []
        errors = []
        for marker in candidates:
            marker_errors = []
            if marker.test_name != item.test_name:
                marker_errors.append(f"测试项名称应为“{item.test_name}”")
            if marker.criterion_id != item.criterion_id:
                marker_errors.append(f"验收条件应为 {item.criterion_id}")
            if marker.criterion_name != item.criterion_name:
                marker_errors.append(f"验收条件名称应为“{item.criterion_name}”")
            if marker.test_method != item.test_method:
                marker_errors.append(f"测试方式应为“{item.test_method}”")
            if marker.test_level not in TEST_LEVELS:
                marker_errors.append(f"测试层级必须是 {sorted(TEST_LEVELS)}")
            if not _has_real_text(marker.test_target):
                marker_errors.append("测试目标缺少具体内容")
            if not _has_real_text(marker.test_entry):
                marker_errors.append("测试入口缺少具体内容")
            if not _has_real_text(marker.code_entry):
                marker_errors.append("代码入口缺少具体内容")
            if marker_errors:
                errors.append(f"{marker.path}:{marker.line} " + "；".join(marker_errors))
            else:
                valid.append(marker)
        if not valid:
            return False, f"{item.topic} / {item.test_id} 的标识不完整: {'；'.join(errors)}"

    return True, f"{len(expected_items)} 个自动化测试项都有完整 Workflow-Test 标识"


def collect_workflow_test_markers(
    project_root: str,
    topics: list[str],
) -> list[WorkflowTestMarker]:
    """返回当前主题的全部 Workflow-Test 标识，供执行登记读取测试入口。"""
    markers: list[WorkflowTestMarker] = []
    for relative_path in _test_source_paths(project_root):
        markers.extend(_parse_markers_from_file(project_root, relative_path))
    return [marker for marker in markers if marker.topic in topics]
