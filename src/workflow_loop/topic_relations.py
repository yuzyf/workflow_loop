"""读取各阶段索引中的验收主题关系。"""

from __future__ import annotations

from dataclasses import dataclass
import os
import re

from . import artifact_paths as artifact_paths_mod
from .project import load_project
from .state import load_state


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


PENDING_HEADERS = {"主题验收结果", "验收结果", "测试计划", "测试结果"}


def _link_path(
    cell: str,
    allowed_text: set[str] | None = None,
    *,
    allow_pending: bool = False,
) -> tuple[str, bool]:
    if allowed_text is not None and cell.strip() in allowed_text:
        return cell.strip(), False
    match = re.fullmatch(r"\[[^\]]+\]\(([^)]+)\)", cell.strip())
    if match is not None:
        return match.group(1).strip(), False
    pending = re.fullmatch(r"`([^`]+)`\s*[（(]待生成[）)]", cell.strip())
    if pending is not None and allow_pending:
        return pending.group(1).strip(), True
    raise ValueError(
        "索引单元格必须是单一真实 Markdown 链接"
        + ("，或“`路径`（待生成）”" if allow_pending else "")
        + f"：{cell}"
    )


def _expected_topic_path(relative_path: str, header: str, file_key: str) -> str | None:
    builders = {
        "验收计划": artifact_paths_mod.topic_acceptance_plan,
        "主题验收结果": artifact_paths_mod.topic_acceptance_result,
        "验收结果": artifact_paths_mod.topic_acceptance_result,
        "测试计划": artifact_paths_mod.topic_test_plan,
        "测试结果": artifact_paths_mod.topic_test_result,
        "实施文档": artifact_paths_mod.topic_impl_doc,
        "实施记录": artifact_paths_mod.topic_impl_doc,
    }
    builder = builders.get(header)
    if builder is None:
        return None
    source_dir = os.path.dirname(relative_path) or "."
    target = builder(file_key)
    value = os.path.relpath(target, source_dir).replace(os.sep, "/")
    return value if value.startswith("../") else f"./{value}"


def _prerequisites(cell: str, known_topics: set[str] | None = None) -> tuple[str, ...]:
    value = cell.strip()
    if value == "无":
        return ()
    # 主题名称可能自身含顿号（例如“代码实施按计划、实施、结果……”）。
    # 已知当前主题时先按完整名称匹配，再把名称之间的顿号当分隔符，避免误拆。
    if known_topics:
        matches: list[tuple[int, str]] = []
        for topic in sorted(known_topics, key=len, reverse=True):
            for match in re.finditer(re.escape(topic), value):
                if any(start <= match.start() < start + len(existing) for start, existing in matches):
                    continue
                matches.append((match.start(), topic))
                break
        if matches:
            matches.sort()
            cursor = 0
            valid = True
            for start, topic in matches:
                separator = value[cursor:start].strip()
                if separator and separator not in {"、", ",", "，", ";", "；"}:
                    valid = False
                    break
                cursor = start + len(topic)
            if value[cursor:].strip() not in {"", "、", ",", "，", ";", "；"}:
                valid = False
            if valid:
                return tuple(topic for _, topic in matches)
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

    headers = _table_cells(lines[header_index])
    if headers is None:
        raise ValueError(f"{relative_path} 缺少可读取的主题关系表头")

    relations: list[TopicRelation] = []
    row_errors: list[str] = []
    project = load_project(project_root)
    workflow_state = load_state(project_root)
    known_topics = set(workflow_state.topics) if workflow_state is not None else set()
    for source_line, line in enumerate(
        lines[header_index + 1 :],
        start=header_index + 2,
    ):
        cells = _table_cells(line)
        if cells is None:
            continue
        location = f"{relative_path} 当前工作流章节第 {source_line} 行"
        if len(cells) != len(headers):
            row_errors.append(
                f"{location}列数与表头不一致：预期 {len(headers)} 列，实际 {len(cells)} 列"
            )
            continue

        order: int | None = None
        try:
            order = int(cells[0])
        except ValueError:
            row_errors.append(f"{location}展示顺序必须是整数：{cells[0]}")

        topic = cells[1].strip()
        if not topic:
            row_errors.append(f"{location}验收主题不能为空")

        prerequisites: tuple[str, ...] | None = None
        try:
            prerequisites = _prerequisites(cells[2], known_topics)
        except ValueError as exc:
            row_errors.append(f"{location}{exc}")

        allowed_values = allowed_text_values or {}
        parsed_cells: dict[str, tuple[str, bool]] = {}
        for index, header in enumerate(headers[3:], start=3):
            try:
                parsed_cells[header] = _link_path(
                    cells[index],
                    allowed_values.get(header),
                    allow_pending=header in PENDING_HEADERS,
                )
            except ValueError as exc:
                row_errors.append(f"{location}“{header}”列：{exc}")
        link_cells = {header: parsed[0] for header, parsed in parsed_cells.items()}
        plan_path = link_cells.get("验收计划")
        if plan_path is None:
            row_errors.append(f"{location}缺少可解析的验收计划链接")
        # 验收主题以显示名称列为准；文件标识只用于核对链接路径，
        # 不再从文件名反推业务名称（显示名称与文件标识分离）。
        if topic:
            expected_key = artifact_paths_mod.resolve_key_for(project, "topic", topic)
            for header, (actual_path, is_pending) in parsed_cells.items():
                if actual_path in allowed_values.get(header, set()):
                    continue
                expected_path = _expected_topic_path(relative_path, header, expected_key)
                if expected_path is not None and actual_path != expected_path:
                    row_errors.append(
                        f"{location}主题“{topic}”的“{header}”应指向 {expected_path}，"
                        f"实际是 {actual_path}"
                    )
                if header in PENDING_HEADERS and expected_path is not None:
                    target = os.path.normpath(
                        os.path.join(os.path.dirname(full_path), actual_path)
                    )
                    if is_pending and os.path.isfile(target):
                        row_errors.append(
                            f"{location}主题“{topic}”的“{header}”目标已经存在，不能标记待生成"
                        )

        if (
            order is not None
            and topic
            and prerequisites is not None
            and len(parsed_cells) == len(headers[3:])
        ):
            relations.append(
                TopicRelation(
                    order=order,
                    topic=topic,
                    prerequisites=prerequisites,
                    links=link_cells,
                )
            )

    if row_errors:
        row_errors.append("主题关系图：未检查：存在无法完整解析的数据行")
        raise ValueError(
            "\n".join(
                f"{index}. {error}"
                for index, error in enumerate(dict.fromkeys(row_errors), start=1)
            )
        )

    if not relations:
        raise ValueError(f"{relative_path} 主题关系表没有数据行")

    errors: list[str] = []
    topics = [relation.topic for relation in relations]
    if len(topics) != len(set(topics)):
        duplicates = sorted({topic for topic in topics if topics.count(topic) > 1})
        errors.append(f"{relative_path} 存在重复验收主题：{duplicates}")
    orders = [relation.order for relation in relations]
    if len(orders) != len(set(orders)):
        duplicates = sorted({order for order in orders if orders.count(order) > 1})
        errors.append(f"{relative_path} 展示顺序不能重复：{duplicates}")

    known = set(topics)
    order_by_topic = {relation.topic: relation.order for relation in relations}
    dependencies = {relation.topic: relation.prerequisites for relation in relations}
    for relation in relations:
        for prerequisite in relation.prerequisites:
            if prerequisite not in known:
                errors.append(
                    f"{relative_path} 主题“{relation.topic}”引用了不存在的前置主题“{prerequisite}”"
                )
                continue
            if prerequisite == relation.topic:
                errors.append(f"{relative_path} 主题“{relation.topic}”不能依赖自己")
            if order_by_topic[prerequisite] >= relation.order:
                errors.append(
                    f"{relative_path} 主题“{relation.topic}”的前置主题“{prerequisite}”必须排在前面"
                )

    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(topic: str) -> bool:
        if topic in visiting:
            return False
        if topic in visited:
            return True
        visiting.add(topic)
        for prerequisite in dependencies[topic]:
            if prerequisite in dependencies and not visit(prerequisite):
                return False
        visiting.remove(topic)
        visited.add(topic)
        return True

    if not all(visit(topic) for topic in topics):
        errors.append(f"{relative_path} 的主题前置关系存在循环")
    if errors:
        raise ValueError(
            "\n".join(
                f"{index}. {error}"
                for index, error in enumerate(dict.fromkeys(errors), start=1)
            )
        )
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
