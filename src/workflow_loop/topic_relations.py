"""读取各阶段索引中的验收主题关系。"""

from __future__ import annotations

from dataclasses import dataclass
import os
import re


BASE_INDEX_HEADERS = ["展示顺序", "验收主题", "前置主题"]


@dataclass(frozen=True)
class TopicRelation:
    """一个验收主题及其前置主题。"""

    order: int
    topic: str
    prerequisites: tuple[str, ...]
    links: dict[str, str]


def _workflow_section(content: str, workflow_id: str) -> str:
    match = re.search(
        rf"^##\s+{re.escape(workflow_id)}\s*$\n(.*?)(?=^##\s+|\Z)",
        content,
        re.MULTILINE | re.DOTALL,
    )
    if match is None:
        raise ValueError(f"索引缺少当前工作流章节: {workflow_id}")
    return match.group(1)


def _table_cells(line: str) -> list[str] | None:
    stripped = line.strip()
    if not stripped.startswith("|") or not stripped.endswith("|"):
        return None
    cells = [cell.strip() for cell in stripped.strip("|").split("|")]
    if not cells or all(re.fullmatch(r"[-:]+", cell) for cell in cells):
        return None
    return cells


def _link_path(cell: str, allowed_text: set[str] | None = None) -> str:
    if allowed_text is not None and cell.strip() in allowed_text:
        return cell.strip()
    match = re.fullmatch(r"\[[^\]]+\]\(([^)]+)\)", cell.strip())
    if match is None:
        raise ValueError(f"索引单元格不是单一 Markdown 链接: {cell}")
    return match.group(1).strip()


def _prerequisites(cell: str) -> tuple[str, ...]:
    value = cell.strip()
    if value == "无":
        return ()
    topics = tuple(part.strip() for part in re.split(r"[、,，]", value) if part.strip())
    if not topics:
        raise ValueError("前置主题不能为空；没有依赖时写“无”")
    return topics


def read_topic_index(
    project_root: str,
    relative_path: str,
    workflow_id: str,
    expected_headers: list[str] | None = None,
    allowed_text_values: dict[str, set[str]] | None = None,
) -> list[TopicRelation]:
    """读取一个主题索引，返回按展示顺序排列的关系。"""

    full_path = os.path.join(project_root, relative_path)
    if not os.path.isfile(full_path):
        raise ValueError(f"{relative_path} 不存在")
    with open(full_path, "r", encoding="utf-8") as stream:
        section = _workflow_section(stream.read(), workflow_id)

    lines = section.splitlines()
    header_index = next(
        (
            index
            for index, line in enumerate(lines)
            if _has_index_headers(_table_cells(line), expected_headers)
        ),
        None,
    )
    if header_index is None:
        raise ValueError(f"{relative_path} 缺少主题关系表")

    relations: list[TopicRelation] = []
    for line in lines[header_index + 1 :]:
        cells = _table_cells(line)
        if cells is None:
            continue
        headers = _table_cells(lines[header_index])
        if headers is None or len(cells) != len(headers):
            raise ValueError(f"{relative_path} 主题关系表列数与表头不一致")
        try:
            order = int(cells[0])
        except ValueError as exc:
            raise ValueError(f"{relative_path} 展示顺序必须是整数: {cells[0]}") from exc

        allowed_values = allowed_text_values or {}
        link_cells = {
            header: _link_path(cells[index], allowed_values.get(header))
            for index, header in enumerate(headers[3:], start=3)
        }
        plan_path = link_cells.get("验收计划")
        if plan_path is None:
            raise ValueError(f"{relative_path} 缺少验收计划链接列")
        plan_match = re.fullmatch(r"(?:.*/)?([^/]+)_plan\.md", plan_path)
        if plan_match is None:
            raise ValueError(f"{relative_path} 验收计划链接必须指向主题的 *_plan.md 文件")
        topic = plan_match.group(1)
        displayed_topic = cells[1].strip()
        if displayed_topic != topic:
            raise ValueError(
                f"{relative_path} 显示的验收主题“{displayed_topic}”与验收计划链接“{topic}”不一致"
            )
        relations.append(
            TopicRelation(
                order=order,
                topic=topic,
                prerequisites=_prerequisites(cells[2]),
                links=link_cells,
            )
        )

    if not relations:
        raise ValueError(f"{relative_path} 主题关系表没有数据行")

    topics = [relation.topic for relation in relations]
    if len(topics) != len(set(topics)):
        raise ValueError(f"{relative_path} 存在重复验收主题")
    orders = [relation.order for relation in relations]
    if len(orders) != len(set(orders)):
        raise ValueError(f"{relative_path} 展示顺序不能重复")

    known = set(topics)
    order_by_topic = {relation.topic: relation.order for relation in relations}
    dependencies = {relation.topic: relation.prerequisites for relation in relations}
    for relation in relations:
        for prerequisite in relation.prerequisites:
            if prerequisite not in known:
                raise ValueError(
                    f"{relative_path} 主题“{relation.topic}”引用了不存在的前置主题“{prerequisite}”"
                )
            if prerequisite == relation.topic:
                raise ValueError(f"{relative_path} 主题“{relation.topic}”不能依赖自己")
            if order_by_topic[prerequisite] >= relation.order:
                raise ValueError(
                    f"{relative_path} 主题“{relation.topic}”的前置主题“{prerequisite}”必须排在前面"
                )

    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(topic: str) -> None:
        if topic in visiting:
            raise ValueError(f"{relative_path} 的主题前置关系存在循环")
        if topic in visited:
            return
        visiting.add(topic)
        for prerequisite in dependencies[topic]:
            visit(prerequisite)
        visiting.remove(topic)
        visited.add(topic)

    for topic in topics:
        visit(topic)
    return relations


def _has_index_headers(
    cells: list[str] | None,
    expected_headers: list[str] | None,
) -> bool:
    if cells is None or len(cells) < len(BASE_INDEX_HEADERS) + 2:
        return False
    if cells[: len(BASE_INDEX_HEADERS)] != BASE_INDEX_HEADERS:
        return False
    return expected_headers is None or cells == expected_headers


def relation_signature(
    relations: list[TopicRelation],
) -> list[tuple[int, str, tuple[str, ...]]]:
    """返回用于比较不同阶段主题关系的稳定表示。"""

    return [
        (relation.order, relation.topic, relation.prerequisites)
        for relation in relations
    ]


def expand_dependents(
    relations: list[TopicRelation],
    topics: list[str],
) -> list[str]:
    """把受影响主题扩展为它们的全部直接和间接后置主题。"""
    affected = set(topics)
    changed = True
    while changed:
        changed = False
        for relation in relations:
            if relation.topic in affected:
                continue
            if any(prerequisite in affected for prerequisite in relation.prerequisites):
                affected.add(relation.topic)
                changed = True
    return [relation.topic for relation in relations if relation.topic in affected]
