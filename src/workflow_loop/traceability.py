"""需求交付追踪表的读取和阶段更新。

追踪表是项目根下的 ``traceability.md``。本模块只更新当前工作流中
当前阶段负责的列，不重写旧工作流，也不修改验收计划文件本身。
"""

from __future__ import annotations

import re
from pathlib import Path

from .test_mapping import criterion_requires_test_code, parse_test_plan_items


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
_INITIAL_ROW_VALUES = ["待制定", "待制定", "待执行", "待执行", "待执行", "待更新"]
_CRITERION_ID_RE = re.compile(r"\b(AC-\d{2,})\b")


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


def _criterion_id_from_cell(topic: str, criterion_cell: str) -> str:
    match = _CRITERION_ID_RE.search(criterion_cell)
    if match is None:
        raise ValueError(f"{TRACEABILITY_PATH} 主题“{topic}”的验收条件列缺少 AC 编号")
    return match.group(1)


def _test_plan_links(project_root: str, topic: str, criterion_id: str) -> str:
    """只生成当前 AC 对应的测试计划和 TC 链接。"""
    items = [
        item
        for item in parse_test_plan_items(project_root, topic)
        if item.criterion_id == criterion_id
    ]
    if not items:
        raise ValueError(f"qa/{topic}_plan.md 没有覆盖 {criterion_id} 的测试项")
    links = [f"[测试计划](./qa/{topic}_plan.md)"]
    links.extend(
        f"[{item.test_id} {item.test_name}](./qa/{topic}_plan.md#{item.test_id.lower()})"
        for item in items
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
            cells[column_index] = value_factory(topic, cells)
            section_lines[line_index] = _format_table_line(cells)
            changed += 1

    updated_section = "\n".join(section_lines)
    updated = _replace_workflow_section(content, workflow_id, updated_section)
    if updated != content:
        Path(project_root, TRACEABILITY_PATH).write_text(updated, encoding="utf-8")
    return f"已更新 {TRACEABILITY_PATH} 当前工作流 {changed} 条记录"


def reset_after_upstream_invalidation(
    project_root: str,
    workflow_id: str,
    topics: list[str],
    stage_name: str,
) -> str:
    """清理当前工作流中已经失效的下游追踪列。

    验收计划或测试计划变化后，原来的下游链接不能继续表示有效结果。
    这里只改当前工作流，不改旧工作流；后续阶段重新确认时会再写回自己的列。
    """

    reset_from = {
        "acceptance_plan": 0,
        "test_plan": 0,
    }.get(stage_name)
    if reset_from is None or not topics:
        return f"{TRACEABILITY_PATH} 无需重置阶段 {stage_name} 的下游列"

    if not (Path(project_root) / TRACEABILITY_PATH).is_file():
        return f"{TRACEABILITY_PATH} 不存在，无需重置阶段 {stage_name} 的下游列"

    content = _read_traceability(project_root)
    match = _workflow_match(content, workflow_id)
    section_lines = match.group(1).splitlines()
    changed = 0

    for topic in topics:
        rows = _topic_rows("\n".join(section_lines), topic)
        for line_index, cells in rows:
            for column_index in range(3 + reset_from, 9):
                cells[column_index] = _INITIAL_ROW_VALUES[column_index - 3]
            section_lines[line_index] = _format_table_line(cells)
            changed += 1

    if changed == 0:
        return f"{TRACEABILITY_PATH} 当前工作流没有可重置的主题记录"

    updated_section = "\n".join(section_lines)
    updated = _replace_workflow_section(content, workflow_id, updated_section)
    if updated != content:
        Path(project_root, TRACEABILITY_PATH).write_text(updated, encoding="utf-8")
    return f"已重置 {TRACEABILITY_PATH} 当前工作流 {changed} 条失效下游记录"


def reset_topics_for_return(
    project_root: str,
    workflow_id: str,
    topics: list[str],
    target_stage: str,
) -> str:
    """流程退回时，只清理受影响主题从目标阶段开始的当前交付状态。"""
    reset_columns = {
        "spec": {3: "待制定", 4: "待制定", 5: "待执行", 6: "待执行", 7: "待执行", 8: "待更新"},
        "acceptance_plan": {3: "待制定", 4: "待制定", 5: "待执行", 6: "待执行", 7: "待执行", 8: "待更新"},
        "test_plan": {3: "待制定", 4: "待制定", 5: "待执行", 6: "待执行", 7: "待执行", 8: "待更新"},
        "impl": {4: "待制定", 5: "待执行", 6: "待执行", 7: "待执行", 8: "待更新"},
        "test_code": {6: "待执行", 7: "待执行", 8: "待更新"},
    }
    columns = reset_columns.get(target_stage)
    if columns is None:
        raise ValueError(f"不支持从追踪表退回阶段: {target_stage}")
    content = _read_traceability(project_root)
    match = _workflow_match(content, workflow_id)
    section_lines = match.group(1).splitlines()
    changed = 0
    for topic in topics:
        rows = _topic_rows("\n".join(section_lines), topic)
        if not rows:
            raise ValueError(f"{TRACEABILITY_PATH} 缺少主题“{topic}”的九列记录")
        for line_index, cells in rows:
            for column_index, value in columns.items():
                cells[column_index] = value
            section_lines[line_index] = _format_table_line(cells)
            changed += 1
    updated = _replace_workflow_section(content, workflow_id, "\n".join(section_lines))
    if updated != content:
        Path(project_root, TRACEABILITY_PATH).write_text(updated, encoding="utf-8")
    return f"已重置 {TRACEABILITY_PATH} 中 {changed} 条受影响主题记录"


def reset_topic_test_results(
    project_root: str,
    workflow_id: str,
    topics: list[str],
) -> str:
    """主题测试重新执行前，只把受影响主题的测试结果列恢复为待执行。"""
    trace_path = Path(project_root) / TRACEABILITY_PATH
    if not trace_path.is_file() or not topics:
        return f"{TRACEABILITY_PATH} 不存在或没有受影响主题，无需重置测试结果"

    content = _read_traceability(project_root)
    match = _workflow_match(content, workflow_id)
    section_lines = match.group(1).splitlines()
    changed = 0
    for topic in topics:
        rows = _topic_rows("\n".join(section_lines), topic)
        if not rows:
            raise ValueError(f"{TRACEABILITY_PATH} 缺少主题“{topic}”的九列记录")
        for line_index, cells in rows:
            cells[6] = "待执行"
            section_lines[line_index] = _format_table_line(cells)
            changed += 1

    updated = _replace_workflow_section(content, workflow_id, "\n".join(section_lines))
    if updated != content:
        trace_path.write_text(updated, encoding="utf-8")
    return f"已重置 {TRACEABILITY_PATH} 中 {changed} 条主题测试结果"


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
            lambda topic, cells: _set_or_append_text(
                cells[3],
                _test_plan_links(
                    project_root,
                    topic,
                    _criterion_id_from_cell(topic, cells[2]),
                ),
            ),
        )

    if stage_name == "impl":
        plan_update = _update_stage_rows(
            project_root,
            workflow_id,
            topics,
            4,
            lambda topic, cells: _set_or_append_link(
                cells[4],
                "实施前计划",
                f"./impl/{topic}.md#2-实施前计划",
            ),
        )
        record_update = _update_stage_rows(
            project_root,
            workflow_id,
            topics,
            5,
            lambda topic, cells: _set_or_append_link(
                cells[5],
                "实施后记录",
                f"./impl/{topic}.md#3-实施后记录",
            ),
        )
        return plan_update + "；" + record_update

    if stage_name == "test_execution":
        return _update_stage_rows(
            project_root,
            workflow_id,
            topics,
            6,
            lambda topic, cells: (
                _set_or_append_link(
                    cells[6],
                    "测试结果",
                    f"./qa/{topic}_result.md",
                )
                if criterion_requires_test_code(
                    project_root,
                    topic,
                    _criterion_id_from_cell(topic, cells[2]),
                )
                else _set_or_append_text(cells[6], "无自动化测试项，转主题验收")
            ),
        )

    if stage_name == "topic_acceptance":
        return _update_stage_rows(
            project_root,
            workflow_id,
            topics,
            7,
            lambda topic, cells: _set_or_append_link(
                cells[7],
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
            lambda _topic, cells: _set_or_append_text(
                cells[6],
                "最终全量回归：通过",
            ),
        )

    if stage_name == "overall_acceptance":
        return _update_stage_rows(
            project_root,
            workflow_id,
            topics,
            7,
            lambda _topic, cells: _set_or_append_text(
                cells[7],
                "整体验收：用户已确认",
            ),
        )

    if stage_name == "update_code_design":
        return _update_stage_rows(
            project_root,
            workflow_id,
            topics,
            8,
            lambda _topic, cells: _set_or_append_link(
                cells[8],
                "最终代码设计",
                "./spec/architecture_code_design.md",
            ),
        )

    raise ValueError(f"阶段 {stage_name} 没有追踪表更新规则")
