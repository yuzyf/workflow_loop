"""需求交付追踪表的读取和阶段更新。

追踪表是项目根下的 ``需求交付追踪表.md``。本模块只更新当前工作流中
当前阶段负责的列，不重写旧工作流，也不修改验收计划文件本身。
通过已登记的主题文件标识识别当前工作流的每一行，不从文件名反推主题。
"""

from __future__ import annotations

import re
from pathlib import Path

from . import artifact_paths as artifact_paths_mod
from .state import load_state
from .test_mapping import criterion_requires_test_code, parse_test_plan_items
from .topic import topic_paths


TRACEABILITY_PATH = artifact_paths_mod.TRACEABILITY_DOC
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
_REGRESSION_CONCLUSION_RE = re.compile(
    r"最终全量回归：通过(?:（机器记录 [^）]+）)?"
)
_OVERALL_ACCEPTANCE_CONCLUSION_RE = re.compile(r"整体验收：用户已确认")


def _trace_relative_path(project_root: str) -> str:
    """返回唯一受支持的中文需求交付追踪表路径。"""
    return TRACEABILITY_PATH


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


def _read_traceability(project_root: str) -> tuple[str, str]:
    relative_path = _trace_relative_path(project_root)
    path = Path(project_root) / relative_path
    if not path.is_file():
        raise ValueError(f"{TRACEABILITY_PATH} 不存在")
    return path.read_text(encoding="utf-8"), relative_path


def _workflow_match(content: str, workflow_id: str) -> re.Match[str]:
    match = _workflow_heading_pattern(workflow_id).search(content)
    if match is None:
        raise ValueError(f"{TRACEABILITY_PATH} 缺少当前工作流章节: {workflow_id}")
    return match


def _topic_markers(project_root: str, topic: str) -> list[str]:
    """使用当前登记的中文验收计划路径识别主题行。"""
    plan_path = topic_paths(project_root, topic)["acceptance_plan"]
    return [plan_path]


def _topic_rows(
    project_root: str,
    section: str,
    topic: str,
) -> list[tuple[int, list[str]]]:
    markers = _topic_markers(project_root, topic)
    rows: list[tuple[int, list[str]]] = []
    for index, line in enumerate(section.splitlines()):
        cells = _split_table_line(line)
        if cells is not None and len(cells) == 9 and any(
            marker in cells[1] for marker in markers
        ):
            rows.append((index, cells))
    return rows


def _replace_workflow_section(content: str, workflow_id: str, section: str) -> str:
    match = _workflow_match(content, workflow_id)
    return content[: match.start(1)] + section + content[match.end(1) :]


def _write_traceability(project_root: str, relative_path: str, content: str) -> None:
    Path(project_root, relative_path).write_text(content, encoding="utf-8")


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


def _remove_appended_text(current: str, pattern: re.Pattern[str], fallback: str) -> str:
    """只删除匹配的阶段追加结论，保留同一单元格中的正式结果链接。"""
    retained = [
        part
        for part in current.split("<br>")
        if pattern.fullmatch(part.strip()) is None
    ]
    return "<br>".join(retained) if retained else fallback


def _criterion_id_from_cell(topic: str, criterion_cell: str) -> str:
    match = _CRITERION_ID_RE.search(criterion_cell)
    if match is None:
        raise ValueError(f"{TRACEABILITY_PATH} 主题“{topic}”的验收条件列缺少 AC 编号")
    return match.group(1)


def _test_plan_links(project_root: str, topic: str, criterion_id: str) -> str:
    """只生成当前 AC 对应的测试计划和 TC 链接。"""
    test_plan_path = topic_paths(project_root, topic)["test_plan"]
    items = [
        item
        for item in parse_test_plan_items(project_root, topic)
        if item.criterion_id == criterion_id
    ]
    if not items:
        raise ValueError(f"{test_plan_path} 没有覆盖 {criterion_id} 的测试项")
    links = [f"[测试计划](./{test_plan_path})"]
    links.extend(
        f"[{item.test_id} {item.test_name}](./{test_plan_path}#{item.test_id.lower()})"
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
        content, _relative_path = _read_traceability(project_root)
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
        markers = _topic_markers(project_root, topic)
        topic_rows = [
            row for row in rows if any(marker in row[1] for marker in markers)
        ]
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
    content, relative_path = _read_traceability(project_root)
    match = _workflow_match(content, workflow_id)
    section_lines = match.group(1).splitlines()
    changed = 0

    for topic in topics:
        rows = _topic_rows(project_root, "\n".join(section_lines), topic)
        if not rows:
            raise ValueError(f"{TRACEABILITY_PATH} 缺少主题“{topic}”的九列记录")
        for line_index, cells in rows:
            cells[column_index] = value_factory(topic, cells)
            section_lines[line_index] = _format_table_line(cells)
            changed += 1

    updated_section = "\n".join(section_lines)
    updated = _replace_workflow_section(content, workflow_id, updated_section)
    if updated != content:
        _write_traceability(project_root, relative_path, updated)
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

    if not (Path(project_root) / _trace_relative_path(project_root)).is_file():
        return f"{TRACEABILITY_PATH} 不存在，无需重置阶段 {stage_name} 的下游列"

    content, relative_path = _read_traceability(project_root)
    match = _workflow_match(content, workflow_id)
    section_lines = match.group(1).splitlines()
    changed = 0

    for topic in topics:
        rows = _topic_rows(project_root, "\n".join(section_lines), topic)
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
        _write_traceability(project_root, relative_path, updated)
    return f"已重置 {TRACEABILITY_PATH} 当前工作流 {changed} 条失效下游记录"


# 各返回目标只重置确实失效的后续列。
_RETURN_RESET_COLUMNS: dict[str, dict[int, str]] = {
    "spec": {3: "待制定", 4: "待制定", 5: "待执行", 6: "待执行", 7: "待执行", 8: "待更新"},
    "code_design": {3: "待制定", 4: "待制定", 5: "待执行", 6: "待执行", 7: "待执行", 8: "待更新"},
    "revise_code_design": {3: "待制定", 4: "待制定", 5: "待执行", 6: "待执行", 7: "待执行", 8: "待更新"},
    "project_design_init": {3: "待制定", 4: "待制定", 5: "待执行", 6: "待执行", 7: "待执行", 8: "待更新"},
    "reproduce": {3: "待制定", 4: "待制定", 5: "待执行", 6: "待执行", 7: "待执行", 8: "待更新"},
    "spike": {3: "待制定", 4: "待制定", 5: "待执行", 6: "待执行", 7: "待执行", 8: "待更新"},
    "acceptance_plan": {3: "待制定", 4: "待制定", 5: "待执行", 6: "待执行", 7: "待执行", 8: "待更新"},
    "test_plan": {3: "待制定", 4: "待制定", 5: "待执行", 6: "待执行", 7: "待执行", 8: "待更新"},
    "impl": {4: "待制定", 5: "待执行", 6: "待执行", 7: "待执行", 8: "待更新"},
    "test_code": {6: "待执行", 7: "待执行", 8: "待更新"},
    "test_execution": {6: "待执行", 7: "待执行", 8: "待更新"},
    "topic_acceptance": {7: "待执行", 8: "待更新"},
    "regression_test": {},
    "overall_acceptance": {},
    "update_code_design": {8: "待更新"},
}
_RETURN_REMOVE_CONCLUSIONS: dict[str, tuple[tuple[int, re.Pattern[str], str], ...]] = {
    "regression_test": (
        (6, _REGRESSION_CONCLUSION_RE, "待执行"),
        (7, _OVERALL_ACCEPTANCE_CONCLUSION_RE, "待执行"),
    ),
    "overall_acceptance": (
        (7, _OVERALL_ACCEPTANCE_CONCLUSION_RE, "待执行"),
    ),
}


def reset_topics_for_return(
    project_root: str,
    workflow_id: str,
    topics: list[str],
    target_stage: str,
) -> str:
    """流程退回时，只清理受影响主题从目标阶段开始的当前交付状态。

    支持当前路径中的任意真实上游；独立主题的行保持不变。
    """
    columns = _RETURN_RESET_COLUMNS.get(target_stage)
    if columns is None:
        raise ValueError(f"不支持从追踪表退回阶段: {target_stage}")
    conclusion_rules = _RETURN_REMOVE_CONCLUSIONS.get(target_stage, ())
    if not columns and not conclusion_rules:
        return f"{TRACEABILITY_PATH} 阶段 {target_stage} 没有需要重置的追踪列"
    content, relative_path = _read_traceability(project_root)
    match = _workflow_match(content, workflow_id)
    section_lines = match.group(1).splitlines()
    changed_lines: set[int] = set()
    for topic in topics:
        rows = _topic_rows(project_root, "\n".join(section_lines), topic)
        if not rows:
            raise ValueError(f"{TRACEABILITY_PATH} 缺少主题“{topic}”的九列记录")
        for line_index, cells in rows:
            original_cells = list(cells)
            for column_index, value in columns.items():
                cells[column_index] = value
            if cells != original_cells:
                section_lines[line_index] = _format_table_line(cells)
                changed_lines.add(line_index)

    # 最终回归和整体验收是整轮唯一的全局结论。状态失效时必须从当前工作流
    # 每一行删除该结论，不能只删用户列出的直接受影响主题；主题自身的结果链接保留。
    if conclusion_rules:
        for line_index, line in enumerate(section_lines):
            cells = _split_table_line(line)
            if cells is None or len(cells) != 9 or cells == TRACEABILITY_HEADERS:
                continue
            original_cells = list(cells)
            for column_index, pattern, fallback in conclusion_rules:
                cells[column_index] = _remove_appended_text(
                    cells[column_index],
                    pattern,
                    fallback,
                )
            if cells != original_cells:
                section_lines[line_index] = _format_table_line(cells)
                changed_lines.add(line_index)
    updated = _replace_workflow_section(content, workflow_id, "\n".join(section_lines))
    if updated != content:
        _write_traceability(project_root, relative_path, updated)
    return f"已重置 {TRACEABILITY_PATH} 中 {len(changed_lines)} 条失效记录"


def reset_topic_test_results(
    project_root: str,
    workflow_id: str,
    topics: list[str],
) -> str:
    """主题测试重新执行前，只把受影响主题的测试结果列恢复为待执行。"""
    trace_path = Path(project_root) / _trace_relative_path(project_root)
    if not trace_path.is_file() or not topics:
        return f"{TRACEABILITY_PATH} 不存在或没有受影响主题，无需重置测试结果"

    content, relative_path = _read_traceability(project_root)
    match = _workflow_match(content, workflow_id)
    section_lines = match.group(1).splitlines()
    changed = 0
    for topic in topics:
        rows = _topic_rows(project_root, "\n".join(section_lines), topic)
        if not rows:
            raise ValueError(f"{TRACEABILITY_PATH} 缺少主题“{topic}”的九列记录")
        for line_index, cells in rows:
            cells[6] = "待执行"
            section_lines[line_index] = _format_table_line(cells)
            changed += 1

    updated = _replace_workflow_section(content, workflow_id, "\n".join(section_lines))
    if updated != content:
        _write_traceability(project_root, relative_path, updated)
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
                f"./{topic_paths(project_root, topic)['impl_doc']}#2-实施前计划",
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
                f"./{topic_paths(project_root, topic)['impl_doc']}#3-实施后记录",
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
                    f"./{topic_paths(project_root, topic)['test_result']}",
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
                f"./{topic_paths(project_root, topic)['acceptance_result']}",
            ),
        )

    if stage_name == "regression_test":
        # 最终回归写当前机器记录编号和通过结论，可以逐字段回查 state.json
        state = load_state(project_root)
        record_id = getattr(state.regression_test, "record_id", None) if state else None
        conclusion = (
            f"最终全量回归：通过（机器记录 {record_id}）" if record_id else "最终全量回归：通过"
        )
        return _update_stage_rows(
            project_root,
            workflow_id,
            topics,
            6,
            lambda _topic, cells: _set_or_append_text(cells[6], conclusion),
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
                f"./{artifact_paths_mod.CODE_DESIGN_DOC}",
            ),
        )

    raise ValueError(f"阶段 {stage_name} 没有追踪表更新规则")
