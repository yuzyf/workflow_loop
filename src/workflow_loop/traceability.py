"""需求交付追踪表的读取和阶段更新。

追踪表是项目根下的 ``traceability.md``。本模块只更新当前工作流中
当前阶段负责的列，不重写旧工作流，也不修改验收计划文件本身。
"""

from __future__ import annotations

import re
from pathlib import Path


TRACEABILITY_PATH = "traceability.md"
TRACEABILITY_HEADERS = [
    "需求来源与设计依据",
    "验收主题",
    "验收条件",
    "测试项",
    "实施计划与任务",
    "实施记录与代码",
    "测试结果",
    "验收结果",
    "更新后的代码设计",
]

_INITIAL_VALUES = {"待制定", "待执行", "待更新"}
_TEST_ITEM_LINK_RE = re.compile(
    r"\[(TC-\d{2,})\s+([^\]]+)\]\(#(tc-\d{2,})\)"
)


def _workflow_heading_pattern(workflow_id: str) -> re.Pattern[str]:
    return re.compile(
        rf"^##\s+{re.escape(workflow_id)}\s*$\n(.*?)(?=^##\s+|\Z)",
        re.MULTILINE | re.DOTALL,
    )


def _split_table_line(line: str) -> list[str] | None:
    stripped = line.strip()
    if not stripped.startswith("|") or not stripped.endswith("|"):
        return None
    cells = [cell.strip() for cell in stripped.strip("|").split("|")]
    if not cells or all(re.fullmatch(r"[-:]+", cell) for cell in cells):
        return None
    return cells


def _format_table_line(cells: list[str]) -> str:
    return "| " + " | ".join(cells) + " |"


def _read_traceability(project_root: str) -> str:
    path = Path(project_root) / TRACEABILITY_PATH
    if not path.is_file():
        raise ValueError(f"{TRACEABILITY_PATH} 不存在")
    return path.read_text(encoding="utf-8")


def _workflow_match(content: str, workflow_id: str) -> re.Match[str]:
    match = _workflow_heading_pattern(workflow_id).search(content)
    if match is None:
        raise ValueError(f"{TRACEABILITY_PATH} 缺少当前工作流章节: {workflow_id}")
    return match


def _topic_rows(section: str, topic: str) -> list[tuple[int, list[str]]]:
    marker = f"acceptance/{topic}_plan.md"
    rows: list[tuple[int, list[str]]] = []
    for index, line in enumerate(section.splitlines()):
        cells = _split_table_line(line)
        if cells is not None and len(cells) == 9 and marker in cells[1]:
            rows.append((index, cells))
    return rows


def _replace_workflow_section(content: str, workflow_id: str, section: str) -> str:
    match = _workflow_match(content, workflow_id)
    return content[: match.start(1)] + section + content[match.end(1) :]


def _section_lines(content: str, workflow_id: str) -> list[str]:
    match = _workflow_match(content, workflow_id)
    return match.group(1).splitlines()


def _set_or_append_link(current: str, label: str, path: str) -> str:
    """把阶段链接写入单元格；已经存在时不重复添加。"""
    link = f"[{label}]({path})"
    if link in current:
        return current
    if current in _INITIAL_VALUES:
        return link
    return f"{current}<br>{link}"


def _set_or_append_text(current: str, value: str) -> str:
    if value in current:
        return current
    if current in _INITIAL_VALUES:
        return value
    return f"{current}<br>{value}"


def _link_files(
    project_root: str,
    directory: str,
    label: str,
    *,
    exclude: set[str] | None = None,
) -> str:
    excluded = exclude or set()
    directory_path = Path(project_root) / directory
    files = sorted(
        path.name
        for path in directory_path.glob("*.md")
        if path.name not in excluded
    ) if directory_path.is_dir() else []
    if not files:
        raise ValueError(f"{directory}/ 下没有可写入追踪表的 .md 文件")
    links = [f"[{name}](./{directory}/{name})" for name in files]
    return f"{label}：" + "<br>".join(links)


def _test_plan_links(project_root: str, topic: str) -> str:
    """读取主题测试计划中的 TC，生成追踪表中的直接链接。"""
    path = Path(project_root) / "qa" / f"{topic}_plan.md"
    if not path.is_file():
        raise ValueError(f"{path.relative_to(project_root)} 不存在")
    content = path.read_text(encoding="utf-8")
    section_match = re.search(
        r"^##\s+1\.\s+验收条件覆盖\s*$\n(.*?)(?=^##\s+2\.|\Z)",
        content,
        re.MULTILINE | re.DOTALL,
    )
    if section_match is None:
        raise ValueError(f"qa/{topic}_plan.md 缺少验收条件覆盖章节")
    items = _TEST_ITEM_LINK_RE.findall(section_match.group(1))
    if not items:
        raise ValueError(f"qa/{topic}_plan.md 没有可写入追踪表的测试项")
    links = [f"[测试计划](./qa/{topic}_plan.md)"]
    links.extend(
        f"[{test_id} {name}](./qa/{topic}_plan.md#{anchor_id.lower()})"
        for test_id, name, anchor_id in items
    )
    return "<br>".join(links)


def validate_structure(
    project_root: str,
    workflow_id: str,
    topics: list[str] | None = None,
    *,
    require_initial_statuses: bool = False,
    require_completed_updates: bool = False,
) -> tuple[bool, str]:
    """校验当前工作流章节、九列表格和主题行。"""
    try:
        content = _read_traceability(project_root)
        match = _workflow_match(content, workflow_id)
    except ValueError as exc:
        return False, str(exc)

    lines = match.group(1).splitlines()
    header_found = False
    rows: list[list[str]] = []
    for line in lines:
        cells = _split_table_line(line)
        if cells is None:
            continue
        if cells == TRACEABILITY_HEADERS:
            header_found = True
            continue
        if len(cells) == 9 and cells[0] != "需求来源与设计依据":
            rows.append(cells)

    if not header_found:
        return False, f"{TRACEABILITY_PATH} 当前工作流章节缺少九列表头"
    if not rows:
        return False, f"{TRACEABILITY_PATH} 当前工作流章节没有九列交付记录"

    expected_topics = topics or []
    for topic in expected_topics:
        topic_rows = [row for row in rows if f"acceptance/{topic}_plan.md" in row[1]]
        if not topic_rows:
            return False, f"{TRACEABILITY_PATH} 缺少主题“{topic}”的交付记录"
        if any(not all(cell.strip() for cell in row) for row in topic_rows):
            return False, f"{TRACEABILITY_PATH} 主题“{topic}”存在空单元格"
        if require_initial_statuses:
            expected = ["待制定", "待制定", "待执行", "待执行", "待执行", "待更新"]
            for row in topic_rows:
                if row[3:] != expected:
                    return False, f"{TRACEABILITY_PATH} 主题“{topic}”尚未保持初始状态: {expected}"
        if require_completed_updates:
            for row in topic_rows:
                if any(value in _INITIAL_VALUES for value in row[3:]):
                    return False, f"{TRACEABILITY_PATH} 主题“{topic}”仍有未更新的阶段列"

    return True, f"{TRACEABILITY_PATH} 当前工作流包含 {len(rows)} 条九列交付记录"


def _update_stage_rows(
    project_root: str,
    workflow_id: str,
    topics: list[str],
    column_index: int,
    value_factory,
) -> str:
    content = _read_traceability(project_root)
    match = _workflow_match(content, workflow_id)
    section_lines = match.group(1).splitlines()
    changed = 0

    for topic in topics:
        rows = _topic_rows("\n".join(section_lines), topic)
        if not rows:
            raise ValueError(f"{TRACEABILITY_PATH} 缺少主题“{topic}”的九列记录")
        for line_index, cells in rows:
            cells[column_index] = value_factory(topic, cells[column_index])
            section_lines[line_index] = _format_table_line(cells)
            changed += 1

    updated_section = "\n".join(section_lines)
    updated = _replace_workflow_section(content, workflow_id, updated_section)
    if updated != content:
        Path(project_root, TRACEABILITY_PATH).write_text(updated, encoding="utf-8")
    return f"已更新 {TRACEABILITY_PATH} 当前工作流 {changed} 条记录"


def update_for_stage(
    project_root: str,
    workflow_id: str,
    topics: list[str],
    stage_name: str,
) -> str:
    """更新一个阶段负责的追踪列。"""
    if not topics:
        raise ValueError("当前工作流没有验收主题，不能更新需求交付追踪表")

    if stage_name == "test_plan":
        return _update_stage_rows(
            project_root,
            workflow_id,
            topics,
            3,
            lambda topic, current: _set_or_append_text(
                current,
                _test_plan_links(project_root, topic),
            ),
        )

    if stage_name in {"plan", "fix_plan"}:
        return _update_stage_rows(
            project_root,
            workflow_id,
            topics,
            4,
            lambda _topic, current: _set_or_append_link(
                current,
                "实施计划索引",
                "./plan/index.md",
            ),
        )

    if stage_name == "topic_execution":
        implementation = _link_files(project_root, "impl", "实施记录")
        return _update_stage_rows(
            project_root,
            workflow_id,
            topics,
            5,
            lambda _topic, current: _set_or_append_text(current, implementation),
        ) + "；" + _update_stage_rows(
            project_root,
            workflow_id,
            topics,
            6,
            lambda topic, current: _set_or_append_link(
                current,
                "测试结果",
                f"./qa/{topic}_result.md",
            ),
        ) + "；" + _update_stage_rows(
            project_root,
            workflow_id,
            topics,
            7,
            lambda topic, current: _set_or_append_link(
                current,
                "主题验收结果",
                f"./acceptance/{topic}_result.md",
            ),
        )

    if stage_name == "regression_test":
        return _update_stage_rows(
            project_root,
            workflow_id,
            topics,
            6,
            lambda _topic, current: _set_or_append_link(
                current,
                "最终全量回归",
                "./qa/final_regression_result.md",
            ),
        )

    if stage_name == "overall_acceptance":
        return _update_stage_rows(
            project_root,
            workflow_id,
            topics,
            7,
            lambda _topic, current: _set_or_append_text(
                current,
                "整体验收：用户已确认",
            ),
        )

    if stage_name == "update_code_design":
        return _update_stage_rows(
            project_root,
            workflow_id,
            topics,
            8,
            lambda _topic, current: _set_or_append_link(
                current,
                "最终代码设计",
                "./spec/architecture_code_design.md",
            ),
        )

    raise ValueError(f"阶段 {stage_name} 没有追踪表更新规则")
