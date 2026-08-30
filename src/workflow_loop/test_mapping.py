"""测试计划、测试代码标识和自动化范围的对应关系。"""

from __future__ import annotations

import ast
from dataclasses import dataclass, replace
import hashlib
import os
import re

from . import snapshots as snapshots_mod
from .state import load_state


def table_is_filled_marker(table: dict) -> bool:
    for key, value in table.items():
        if key in {"表版本", "工作流编号", "验收主题", "生成文档哈希", "生成文档路径", "填写说明", "未完成状态"}:
            continue
        if isinstance(value, list) and value:
            return True
    return False
from .topic import topic_paths


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
    "产品入口",
    "测试入口",
    "代码入口",
    "准备数据",
    "执行动作",
    "关键断言",
    "预期证据",
)
PLACEHOLDER_VALUES = {
    "待补充",
    "待确认",
    "实施后确认",
    "符合预期",
    "正常",
    "正确处理",
    "todo",
}


@dataclass(frozen=True)
class TestPlanItem:
    topic: str
    criterion_id: str
    criterion_name: str
    test_id: str
    test_name: str
    test_method: str
    dependencies: tuple[str, ...] = ()
    product_entry: str = ""
    code_entry: str = ""
    test_entry: str = ""
    preparation: str = ""
    action: str = ""
    observation: str = ""
    expected_result: str = ""
    failure_behavior: str = ""
    evidence_requirement: str = ""

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
    product_entry: str
    test_entry: str
    code_entry: str
    preparation: str
    action: str
    key_assertion: str
    expected_evidence: str
    definition_line: int = 0
    definition_end_line: int = 0
    definition_name: str = ""
    body_excerpt: str = ""
    body_sha256: str = ""


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


def _entry_parts(value: str, label: str) -> tuple[str, str]:
    """解析 ``项目相对文件::符号或测试标题``，不从自然语言猜路径。"""
    normalized = value.strip().strip("`")
    if normalized.count("::") != 1:
        raise ValueError(f"{label} 必须写成 `项目相对文件::可定位标识`: {value}")
    path, target = (part.strip() for part in normalized.split("::", 1))
    if not path or not target or any(character.isspace() for character in path):
        raise ValueError(f"{label} 必须同时写明确文件和可定位标识: {value}")
    return path.replace("\\", "/"), target


def _validate_plan_entry(
    project_root: str,
    value: str,
    relative_plan_path: str,
    test_id: str,
    label: str,
    *,
    allow_missing: bool,
    require_test_path: bool,
) -> str:
    """校验计划登记文件的项目边界、类型和当前存在状态。"""
    raw_path, _ = _entry_parts(value, label)
    try:
        normalized = snapshots_mod.normalize_registered_paths(project_root, [raw_path])[0]
    except ValueError as exc:
        raise ValueError(
            f"{relative_plan_path} 的测试项 {test_id} {label}无效: {exc}"
        ) from exc
    if require_test_path and not _is_test_source(normalized):
        raise ValueError(
            f"{relative_plan_path} 的测试项 {test_id} {label}必须指向明确测试文件: {normalized}"
        )
    full_path = os.path.join(project_root, *normalized.split("/"))
    if os.path.lexists(full_path):
        if os.path.islink(full_path) or not os.path.isfile(full_path):
            raise ValueError(
                f"{relative_plan_path} 的测试项 {test_id} {label}不是项目内普通文件: {normalized}"
            )
    elif not allow_missing:
        raise ValueError(
            f"{relative_plan_path} 的测试项 {test_id} {label}文件不存在: {normalized}"
        )
    return normalized


def _test_plan_items_from_table(project_root: str, topic: str) -> list[TestPlanItem] | None:
    """测试计划工作记录表启用且已填时，从表构造计划项；否则返回 None。"""
    from . import records as records_mod

    state = load_state(project_root)
    workflow_id = state.workflow_id if state is not None else ""
    relative = records_mod.table_relative_path(project_root, workflow_id, "test_plan", topic)
    if not records_mod.table_exists(project_root, relative):
        return None
    try:
        table = records_mod.load_table(os.path.join(project_root, relative))
    except records_mod.RecordsError:
        return None
    if not table.get("测试项"):
        # 纯人工主题：表已填写但没有任何自动化测试项
        if table_is_filled_marker(table):
            return []
        return None
    criterion_names = _criterion_names_from_table(project_root, topic)
    items: list[TestPlanItem] = []
    for row in table["测试项"]:
        if not isinstance(row, dict):
            continue
        test_id = str(row.get("测试项编号", "")).strip()
        if not test_id:
            continue
        dependencies = _parse_dependency_ids(row.get("前置测试项"))
        criterion_cell = str(row.get("对应验收条件", "")).strip()
        criterion_ids = re.findall(r"AC-\d+", criterion_cell) or [criterion_cell]
        for criterion_id in criterion_ids:
            items.append(
                TestPlanItem(
                    topic=topic,
                    criterion_id=criterion_id,
                    criterion_name=criterion_names.get(criterion_id.upper(), ""),
                    test_id=test_id,
                    test_name=str(row.get("直白测试名称", "")).strip(),
                    test_method=str(row.get("测试方式", "")).strip() or "自动化测试",
                    dependencies=tuple(dependencies),
                    product_entry=str(row.get("产品入口", "")).strip(),
                    code_entry=str(row.get("代码入口", "")).strip(),
                    test_entry=str(row.get("正式目标名称", "")).strip(),
                    preparation=str(row.get("准备数据", "")).strip(),
                    action=str(row.get("执行动作", "")).strip(),
                    observation=str(row.get("观察位置", "")).strip(),
                    expected_result=str(row.get("预期结果", "")).strip(),
                    failure_behavior=str(row.get("不通过表现", "")).strip(),
                    evidence_requirement=str(row.get("证据要求", "")).strip(),
                )
            )
    return items


def _criterion_names_from_table(project_root: str, topic: str) -> dict[str, str]:
    """从验收计划工作记录表读取 AC 编号到验收条件名称的映射。"""
    from . import records as records_mod

    state = load_state(project_root)
    workflow_id = state.workflow_id if state is not None else ""
    relative = records_mod.table_relative_path(
        project_root, workflow_id, "acceptance_plan", topic
    )
    if not records_mod.table_exists(project_root, relative):
        return {}
    try:
        table = records_mod.load_table(os.path.join(project_root, relative))
    except records_mod.RecordsError:
        return {}
    names: dict[str, str] = {}
    for row in table.get("验收条件", []) or []:
        if not isinstance(row, dict):
            continue
        criterion_id = str(row.get("验收条件编号", "")).strip().upper()
        name = str(row.get("验收条件名称", "")).strip()
        if criterion_id and name:
            names[criterion_id] = name
    return names


def _parse_dependency_ids(raw: object) -> list[str]:
    """把前置测试项单元格解析为当前主题内的直接 TC 编号清单。"""
    text = str(raw or "").strip()
    if not text or text in {"无", "暂无"}:
        return []
    return [part.strip() for part in re.split(r"[、,，;；\s]+", text) if part.strip()]


def parse_test_plan_items(project_root: str, topic: str) -> list[TestPlanItem]:
    """读取一个主题测试计划中的 AC、TC 和测试方式。

    测试计划工作记录表启用且已填时，表是真本，直接从表构造计划项。
    """
    table_items = _test_plan_items_from_table(project_root, topic)
    if table_items is not None:
        return table_items
    relative_path = topic_paths(project_root, topic)["test_plan"]
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
        "产品入口",
        "代码入口",
        "测试入口",
        "准备数据",
        "执行动作",
        "观察位置",
        "预期结果",
        "不通过表现",
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
        field_values = {
            "产品入口": cells[4],
            "代码入口": cells[5],
            "测试入口": cells[6],
            "准备数据": cells[7],
            "执行动作": cells[8],
            "观察位置": cells[9],
            "预期结果": cells[10],
            "不通过表现": cells[11],
            "证据要求": cells[12],
        }
        invalid_fields = [
            label
            for label, value in field_values.items()
            if not _has_real_text(value)
        ]
        if invalid_fields:
            raise ValueError(
                f"{relative_path} 的测试项 {test_id} 缺少可执行内容或仍使用占位值: {invalid_fields}"
            )
        _validate_plan_entry(
            project_root,
            field_values["代码入口"],
            relative_path,
            test_id,
            "代码入口",
            allow_missing=False,
            require_test_path=False,
        )
        if test_method in AUTOMATED_TEST_METHODS:
            _validate_plan_entry(
                project_root,
                field_values["测试入口"],
                relative_path,
                test_id,
                "测试入口",
                allow_missing=True,
                require_test_path=True,
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
                product_entry=field_values["产品入口"].strip(),
                code_entry=field_values["代码入口"].strip(),
                test_entry=field_values["测试入口"].strip(),
                preparation=field_values["准备数据"].strip(),
                action=field_values["执行动作"].strip(),
                observation=field_values["观察位置"].strip(),
                expected_result=field_values["预期结果"].strip(),
                failure_behavior=field_values["不通过表现"].strip(),
                evidence_requirement=field_values["证据要求"].strip(),
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


def planned_test_source_paths(project_root: str, topics: list[str]) -> list[str]:
    """只返回当前测试计划明确登记的测试文件；不遍历项目目录。"""
    paths: list[str] = []
    for item in automated_test_items(project_root, topics):
        plan_path = topic_paths(project_root, item.topic)["test_plan"]
        paths.append(
            _validate_plan_entry(
                project_root,
                item.test_entry,
                plan_path,
                item.test_id,
                "测试入口",
                allow_missing=True,
                require_test_path=True,
            )
        )
    return sorted(set(paths))


def all_test_source_paths(project_root: str) -> list[str]:
    """返回项目中可读的测试源码路径，用于实际改动归属，不是测试白名单。"""

    excluded = {
        ".git",
        ".workflow_loop",
        ".venv",
        "venv",
        "node_modules",
        "dist",
        "build",
        ".next",
        "__pycache__",
        ".pytest_cache",
    }
    paths: list[str] = []
    for root, directories, files in os.walk(project_root):
        directories[:] = [name for name in directories if name not in excluded]
        for filename in files:
            relative = os.path.relpath(os.path.join(root, filename), project_root).replace(
                os.sep, "/"
            )
            if _is_test_source(relative):
                paths.append(relative)
    return sorted(set(paths))


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


# 各语言真实测试定义的识别模式：非 Python 语言的 Workflow-Test 注释必须紧邻
# 其中之一，才算写在真实测试函数、测试类或测试场景上；游离注释一律拒绝。
TEST_DEFINITION_PATTERNS = [
    # C / C++ / Qt（GoogleTest、QtTest）
    re.compile(r"\bTEST(?:_[A-Z]+)?\s*\("),
    re.compile(r"\bvoid\s+(?:test|tst_)\w*\s*\("),
    re.compile(r"\bQTEST_(?:MAIN|APPLESS_MAIN|GUILESS_MAIN)\b"),
    # JavaScript / TypeScript（jest、vitest、mocha、playwright）
    re.compile(r"\b(?:it|test|describe)(?:\.\w+)?\s*\("),
    # Go
    re.compile(r"\bfunc\s+Test\w+\s*\("),
    # Rust
    re.compile(r"#\[(?:tokio::)?test\]"),
    # Java / Kotlin（JUnit）
    re.compile(r"@Test\b"),
    # Ruby（rspec / minitest）
    re.compile(r"\b(?:it|describe|def\s+test_)\b"),
    # Shell bats
    re.compile(r"^@test\s"),
]
# 标识注释块之后向下查找真实测试定义的行数上限
DEFINITION_LOOKAHEAD_LINES = 14


def _near_test_definition(lines: list[str], marker_index: int) -> bool:
    """判断标识注释块之后是否紧跟真实测试定义。"""
    for line in lines[marker_index : marker_index + DEFINITION_LOOKAHEAD_LINES]:
        for pattern in TEST_DEFINITION_PATTERNS:
            if pattern.search(line):
                return True
    return False


def _parse_marker_lines(
    lines: list[str],
    relative_path: str,
    *,
    line_offset: int = 0,
    require_comment: bool = False,
    require_definition: bool = False,
    errors: list[str] | None = None,
) -> list[WorkflowTestMarker]:
    markers: list[WorkflowTestMarker] = []
    for index, line in enumerate(lines):
        if "Workflow-Test" not in line:
            continue
        if require_comment and re.match(r"^\s*(?:#|/{2,}|/\*+|\*+|--|<!--)", line) is None:
            # 字符串或普通代码中的 Workflow-Test 字样不是追踪标识
            continue
        if require_definition and not _near_test_definition(lines, index + 1):
            if errors is not None:
                errors.append(
                    f"{relative_path}:{line_offset + index + 1} Workflow-Test 标识没有紧邻"
                    "真实测试函数、测试类或测试场景（游离注释不能作为正式登记入口）"
                )
            continue
        fields: dict[str, str] = {}
        for raw_line in lines[index + 1 : index + 18]:
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
            if errors is not None:
                errors.append(
                    f"{relative_path}:{line_offset + index + 1} Workflow-Test 标识缺少"
                    "完整的测试项（TC-xx 名称）或验收条件（AC-xx 名称）"
                )
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
                product_entry=fields.get("产品入口", ""),
                test_entry=fields.get("测试入口", ""),
                code_entry=fields.get("代码入口", ""),
                preparation=fields.get("准备数据", ""),
                action=fields.get("执行动作", ""),
                key_assertion=fields.get("关键断言", ""),
                expected_evidence=fields.get("预期证据", ""),
            )
        )
    return markers


def _parse_python_markers(
    content: str,
    relative_path: str,
    errors: list[str] | None = None,
) -> list[WorkflowTestMarker]:
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
            errors=errors,
        )
        if len(parsed) > 1:
            raise ValueError(
                f"{relative_path}:{first_statement.lineno} 一个 Python 测试函数或测试类只能写一个 Workflow-Test 标识"
            )
        body = node.body[1:]
        content_lines = content.splitlines(keepends=True)
        if body:
            body_start = body[0].lineno
            body_end = getattr(body[-1], "end_lineno", body[-1].lineno)
            body_source = "".join(content_lines[body_start - 1 : body_end])
        else:
            body_source = ""
        body_excerpt = body_source.strip()
        if len(body_excerpt) > 500:
            body_excerpt = body_excerpt[:497] + "..."
        definition_end = getattr(node, "end_lineno", node.lineno)
        markers.extend(
            replace(
                marker,
                definition_line=node.lineno,
                definition_end_line=definition_end,
                definition_name=node.name,
                body_excerpt=body_excerpt,
                body_sha256=hashlib.sha256(body_source.encode("utf-8")).hexdigest(),
            )
            for marker in parsed
        )
        noop_reason = _obvious_python_noop_reason(body)
        if parsed and noop_reason is not None and errors is not None:
            errors.append(
                f"{relative_path}:{node.lineno}-{definition_end} Python 测试 {node.name} "
                f"没有验证真实行为：文档字符串后{noop_reason}；"
                "请调用真实目标并断言操作后的可检查状态"
            )
    return markers


def _obvious_python_noop_reason(body: list[ast.stmt]) -> str | None:
    """只识别无需理解调用关系即可确定的空测试。"""
    if not body:
        return "没有测试代码"
    if len(body) == 1:
        statement = body[0]
        if isinstance(statement, ast.Pass):
            return "只有 pass 空语句"
        if (
            isinstance(statement, ast.Expr)
            and isinstance(statement.value, ast.Constant)
            and statement.value.value is Ellipsis
        ):
            return "只有 Ellipsis（...）空语句"
        if isinstance(statement, ast.Return):
            if statement.value is None:
                return "只返回固定常量"
            try:
                ast.literal_eval(statement.value)
            except (ValueError, TypeError, SyntaxError, MemoryError, RecursionError):
                pass
            else:
                return "只返回固定常量"
        if isinstance(statement, ast.Assert):
            try:
                literal_value = ast.literal_eval(statement.test)
            except (ValueError, TypeError, SyntaxError, MemoryError, RecursionError):
                pass
            else:
                if bool(literal_value):
                    return "只有恒真的字面量断言"
    if _assertions_only_repeat_direct_test_writes(body):
        return "只断言测试代码刚写入的常量或属性（自造结果）"
    return None


def _assertions_only_repeat_direct_test_writes(body: list[ast.stmt]) -> bool:
    """拒绝测试自己写值后原样断言；不猜函数调用产生的数据。"""
    direct_writes: dict[str, ast.expr] = {}
    assertions: list[ast.Assert] = []
    for statement in body:
        if isinstance(statement, ast.Assign) and _is_literal_expression(statement.value):
            for target in statement.targets:
                key = _reference_key(target)
                if key is not None:
                    direct_writes[key] = statement.value
        elif (
            isinstance(statement, ast.AnnAssign)
            and statement.value is not None
            and _is_literal_expression(statement.value)
        ):
            key = _reference_key(statement.target)
            if key is not None:
                direct_writes[key] = statement.value
        elif isinstance(statement, ast.Assert):
            assertions.append(statement)
    return bool(assertions) and all(
        _assertion_repeats_direct_write(statement.test, direct_writes)
        for statement in assertions
    )


def _reference_key(node: ast.AST) -> str | None:
    if isinstance(node, ast.Name):
        return f"name:{node.id}"
    if isinstance(node, ast.Attribute):
        owner = _reference_key(node.value)
        return f"{owner}.attr:{node.attr}" if owner is not None else None
    if isinstance(node, ast.Subscript):
        owner = _reference_key(node.value)
        if owner is None:
            return None
        return f"{owner}.item:{ast.dump(node.slice, include_attributes=False)}"
    return None


def _is_literal_expression(node: ast.AST) -> bool:
    try:
        ast.literal_eval(node)
    except (ValueError, TypeError, SyntaxError, MemoryError, RecursionError):
        return False
    return True


def _same_literal(first: ast.AST, second: ast.AST) -> bool:
    if not _is_literal_expression(first) or not _is_literal_expression(second):
        return False
    return ast.dump(first, include_attributes=False) == ast.dump(
        second,
        include_attributes=False,
    )


def _assertion_repeats_direct_write(
    expression: ast.expr,
    direct_writes: dict[str, ast.expr],
) -> bool:
    if isinstance(expression, ast.Compare) and len(expression.ops) == 1:
        if not isinstance(expression.ops[0], (ast.Eq, ast.Is)):
            return False
        left, right = expression.left, expression.comparators[0]
        left_key = _reference_key(left)
        right_key = _reference_key(right)
        return (
            left_key in direct_writes
            and _same_literal(direct_writes[left_key], right)
        ) or (
            right_key in direct_writes
            and _same_literal(direct_writes[right_key], left)
        )
    key = _reference_key(expression)
    if key not in direct_writes:
        return False
    try:
        return bool(ast.literal_eval(direct_writes[key]))
    except (ValueError, TypeError, SyntaxError, MemoryError, RecursionError):
        return False


def _parse_markers_from_file(
    project_root: str,
    relative_path: str,
    errors: list[str] | None = None,
) -> list[WorkflowTestMarker]:
    content = _read_text(project_root, relative_path)
    if relative_path.lower().endswith(".py"):
        return _parse_python_markers(content, relative_path, errors)
    return _parse_marker_lines(
        content.splitlines(),
        relative_path,
        require_comment=True,
        require_definition=True,
        errors=errors,
    )


def _has_real_text(value: str) -> bool:
    normalized = value.strip()
    return (
        bool(normalized)
        and "<" not in normalized
        and normalized.lower() not in PLACEHOLDER_VALUES
        and "todo" not in normalized.lower()
    )


def validate_workflow_test_markers(
    project_root: str,
    topics: list[str],
) -> tuple[bool, str]:
    expected_items = automated_test_items(project_root, topics)
    if not expected_items:
        return True, "当前工作流没有自动化测试项，无需 Workflow-Test 标识"

    markers: list[WorkflowTestMarker] = []
    failures: list[str] = []
    try:
        for relative_path in all_test_source_paths(project_root):
            markers.extend(
                _parse_markers_from_file(project_root, relative_path, failures)
            )
    except ValueError as exc:
        failures.append(str(exc))

    # 当前主题的每个标识都必须完整对应现有测试项；未知测试项和错误名称一律拒绝
    expected_by_key = {(item.topic, item.test_id): item for item in expected_items}
    for marker in markers:
        if marker.topic in topics and (marker.topic, marker.test_id) not in expected_by_key:
            failures.append(
                f"{marker.path}:{marker.line} 标识引用了当前测试计划中不存在的测试项: "
                f"{marker.topic} / {marker.test_id}"
            )

    for item in expected_items:
        candidates = [
            marker
            for marker in markers
            if marker.topic == item.topic and marker.test_id == item.test_id
        ]
        if not candidates:
            failures.append(
                f"测试代码缺少 Workflow-Test 标识: {item.topic} / {item.test_id} {item.test_name}",
            )
            continue
        if len(candidates) != 1:
            failures.append(
                f"{item.topic} / {item.test_id} 必须恰好有一个 Workflow-Test 标识，实际 {len(candidates)} 个"
            )
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
            try:
                actual_test_path, actual_test_target = _entry_parts(
                    marker.test_entry,
                    "测试入口",
                )
            except ValueError as exc:
                marker_errors.append(str(exc))
            else:
                if marker.path.replace("\\", "/") != actual_test_path:
                    marker_errors.append(
                        f"测试入口路径应指向标识所在文件“{marker.path}”"
                    )
                if marker.definition_name and actual_test_target != marker.definition_name:
                    marker_errors.append(
                        f"测试入口标识应为真实定义“{marker.definition_name}”"
                    )
            exact_fields = (
                ("产品入口", marker.product_entry, item.product_entry),
                ("代码入口", marker.code_entry, item.code_entry),
                ("准备数据", marker.preparation, item.preparation),
                ("执行动作", marker.action, item.action),
                ("关键断言", marker.key_assertion, item.expected_result),
                ("预期证据", marker.expected_evidence, item.evidence_requirement),
            )
            for label, actual, expected in exact_fields:
                if not _has_real_text(actual):
                    marker_errors.append(f"{label}缺少具体内容")
                elif actual != expected:
                    marker_errors.append(f"{label}应为“{expected}”")
            if marker_errors:
                errors.append(f"{marker.path}:{marker.line} " + "；".join(marker_errors))
        # 同一测试项的多个标识必须全部完整正确；部分有效的重复标识不能被忽略
        if errors:
            failures.append(f"{item.topic} / {item.test_id} 的标识不完整: {'；'.join(errors)}")

    if failures:
        unique = sorted(set(failures))
        return False, "\n".join(f"{index}. {failure}" for index, failure in enumerate(unique, 1))
    confirmation_facts: list[str] = []
    for marker in sorted(markers, key=lambda item: (item.topic, item.test_id, item.path, item.line)):
        if marker.topic not in topics:
            continue
        definition = (
            f"{marker.path}:{marker.definition_line}-{marker.definition_end_line}"
            if marker.definition_line > 0
            else f"{marker.path}:标识行 {marker.line}；测试入口 {marker.test_entry}"
        )
        body_excerpt = " ".join(marker.body_excerpt.split()) or "非 Python 测试由用户核对真实定义"
        body_hash = marker.body_sha256 or "非 Python 测试未生成正文哈希"
        confirmation_facts.append(
            f"{marker.topic}/{marker.test_id}：产品入口={marker.product_entry}；"
            f"测试定义={definition}；准备={marker.preparation}；动作={marker.action}；"
            f"关键断言={marker.key_assertion}；预期证据={marker.expected_evidence}；"
            f"正文 SHA-256={body_hash}；正文摘要={body_excerpt}"
        )
    return (
        True,
        f"{len(expected_items)} 个自动化测试项都有完整 Workflow-Test 标识；"
        "用户确认前逐项核对：\n" + "\n".join(confirmation_facts),
    )


def collect_workflow_test_markers(
    project_root: str,
    topics: list[str],
) -> list[WorkflowTestMarker]:
    """返回当前主题的全部 Workflow-Test 标识，供执行登记读取测试入口。"""
    return [
        marker
        for marker in collect_all_workflow_test_markers(project_root)
        if marker.topic in topics
    ]


def collect_all_workflow_test_markers(project_root: str) -> list[WorkflowTestMarker]:
    """读取所有测试源码中的追踪标识，用于把实际改动归属到主题。"""

    markers: list[WorkflowTestMarker] = []
    errors: list[str] = []
    for relative_path in all_test_source_paths(project_root):
        if os.path.isfile(os.path.join(project_root, *relative_path.split("/"))):
            markers.extend(_parse_markers_from_file(project_root, relative_path, errors))
    if errors:
        raise ValueError("\n".join(errors))
    return markers


def test_item_path_mapping(
    project_root: str,
    topics: list[str],
) -> dict[str, tuple[tuple[str, str], ...]]:
    """返回真实测试文件到 ``(主题, TC)`` 的直接归属。"""

    mapping: dict[str, set[tuple[str, str]]] = {}
    for marker in collect_workflow_test_markers(project_root, topics):
        mapping.setdefault(marker.path.replace("\\", "/"), set()).add(
            (marker.topic, marker.test_id)
        )
    return {
        path: tuple(sorted(items))
        for path, items in sorted(mapping.items())
    }


def describe_actual_test_change_links(
    project_root: str,
    topics: list[str],
    paths: list[str],
) -> list[str]:
    """把实际测试路径解释为直接测试项或共享支持文件。"""

    direct = test_item_path_mapping(project_root, topics)
    all_items = tuple(
        (item.topic, item.test_id, item.criterion_id)
        for item in automated_test_items(project_root, topics)
    )
    descriptions: list[str] = []
    for path in sorted(set(paths)):
        linked = direct.get(path.replace("\\", "/"), ())
        if linked:
            labels = [
                f"{topic}/{test_id}/"
                + next(
                    item.criterion_id
                    for item in automated_test_items(project_root, topics)
                    if item.topic == topic and item.test_id == test_id
                )
                for topic, test_id in linked
            ]
            descriptions.append(f"{path}：直接关联 {labels}")
        else:
            labels = [f"{topic}/{test_id}/{criterion_id}" for topic, test_id, criterion_id in all_items]
            descriptions.append(
                f"{path}：没有直接 Workflow-Test 标识，按共享测试支持文件关联 {labels}"
            )
    return descriptions
