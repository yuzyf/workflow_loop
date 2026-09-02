"""需求交付追踪表的读取和阶段更新。

追踪表是项目根下的 ``需求交付追踪表.md``。本模块只更新当前工作流中
当前阶段负责的列，不重写旧工作流，也不修改验收计划文件本身。
通过已登记的主题文件标识识别当前工作流的每一行，不从文件名反推主题。
"""

from __future__ import annotations

import os
import re
from pathlib import Path

from . import artifact_paths as artifact_paths_mod
from .state import load_state
from .test_mapping import criterion_requires_test_code, parse_test_plan_items
from .topic import topic_paths


TRACEABILITY_PATH = artifact_paths_mod.TRACEABILITY_DOC
LEGACY_TRACEABILITY_HEADERS = [
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
TRACEABILITY_HEADERS = [
    "需求来源与设计依据",
    "验收主题",
    "验收条件",
    "穿刺结论与可复用内容",
    "测试项",
    "实施计划与任务",
    "实施记录与代码",
    "测试结果",
    "验收结果",
    "更新后的代码设计",
]
SPIKE_SKIPPED_TEXT = "本轮未执行穿刺，无可复用资产"
SPIKE_RECHECK_TEXT = "待重新确认；已登记资产保留"
SPIKE_NO_SUPPORT_TEXT = "本验收条件没有直接支撑的穿刺结论或可复用资产"
SUPPORTED_HEADERS = (TRACEABILITY_HEADERS, LEGACY_TRACEABILITY_HEADERS)

_INITIAL_VALUES = {"待制定", "待执行", "待更新"}
_INITIAL_VALUES_BY_HEADER = {
    "测试项": "待制定",
    "实施计划与任务": "待制定",
    "实施记录与代码": "待执行",
    "测试结果": "待执行",
    "验收结果": "待执行",
    "更新后的代码设计": "待更新",
}
_CRITERION_ID_RE = re.compile(r"\b(AC-\d{2,})\b")
_SPIKE_ASSET_PATH_RE = re.compile(
    r"\.workflow_loop/spike_tmp/[A-Za-z0-9][A-Za-z0-9._-]*/"
    r"[A-Za-z0-9_\-一-鿿㐀-䶿]+"
)
_REGRESSION_CONCLUSION_RE = re.compile(
    r"最终全量回归：通过(?:（机器记录 [^）]+）)?"
)
_OVERALL_ACCEPTANCE_CONCLUSION_RE = re.compile(r"整体验收：用户已确认")
_EXPLICIT_ANCHOR_LINE_PATTERN = (
    r"<a\s+id=(?:\"[^\"]+\"|'[^']+')\s*>\s*</a>[ \t]*\r?\n"
)


def _trace_relative_path(project_root: str) -> str:
    """返回唯一受支持的中文需求交付追踪表路径。"""
    return TRACEABILITY_PATH


def _workflow_heading_pattern(workflow_id: str) -> re.Pattern[str]:
    return re.compile(
        rf"^##[ \t]+{re.escape(workflow_id)}[ \t]*\r?\n"
        rf"(.*?)(?=^(?:{_EXPLICIT_ANCHOR_LINE_PATTERN})?##[ \t]+|\Z)",
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


def _column_count_label(count: int) -> str:
    return {9: "九列", 10: "十列"}.get(count, f"{count} 列")


def _headers_for_row(cells: list[str]) -> list[str]:
    if len(cells) == len(TRACEABILITY_HEADERS):
        return TRACEABILITY_HEADERS
    if len(cells) == len(LEGACY_TRACEABILITY_HEADERS):
        return LEGACY_TRACEABILITY_HEADERS
    raise ValueError(f"追踪表行列数无效：{len(cells)}")


def _column_index(cells: list[str], header: str) -> int:
    headers = _headers_for_row(cells)
    if header not in headers:
        raise ValueError(f"当前追踪表格式缺少列：{header}")
    return headers.index(header)


def _initial_value_for_header(header: str) -> str:
    return _INITIAL_VALUES_BY_HEADER[header]


def _cell(cells: list[str], header: str) -> str:
    return cells[_column_index(cells, header)]


def _set_cell(cells: list[str], header: str, value: str) -> None:
    cells[_column_index(cells, header)] = value


def _reset_cells(cells: list[str], headers: set[str] | tuple[str, ...]) -> None:
    row_headers = _headers_for_row(cells)
    for header in headers:
        if header in row_headers:
            _set_cell(cells, header, _initial_value_for_header(header))


def _required_headers_for_workflow(
    project_root: str,
    workflow_id: str,
) -> list[str] | None:
    """新路径的当前轮次必须使用十列；历史轮次继续接受九列。"""
    state = load_state(project_root)
    if (
        state is not None
        and state.workflow_id == workflow_id
        and state.stage_path_version >= 2
    ):
        return TRACEABILITY_HEADERS
    return None


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
    active_headers: list[str] | None = None
    for index, line in enumerate(section.splitlines()):
        cells = _split_table_line(line)
        if cells is None:
            continue
        if cells in SUPPORTED_HEADERS:
            active_headers = cells
            continue
        if active_headers is None or len(cells) != len(active_headers):
            continue
        try:
            topic_cell = _cell(cells, "验收主题")
        except ValueError:
            continue
        if any(marker in topic_cell for marker in markers):
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
    """只生成当前 AC 对应的测试计划和 TC 链接。

    测试工作记录表为空的纯人工主题：不生成自动化链接，写明由最终全量回归
    和主题验收人工核对。
    """
    from . import records as records_mod
    from .state import load_state

    state = load_state(project_root)
    if state is not None:
        relative = records_mod.table_relative_path(
            project_root, state.workflow_id, "test_plan", topic
        )
        if records_mod.table_exists(project_root, relative):
            try:
                table = records_mod.load_table(os.path.join(project_root, relative))
            except records_mod.RecordsError:
                table = None
            if table is not None and table.get("测试范围说明") and not table.get("测试项"):
                return "无自动化测试项，转主题验收人工核对；自动化验证由最终全量回归承担"
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


def _current_spike_conclusion_documents(
    project_root: str,
    workflow_id: str,
) -> list[str]:
    """读取当前穿刺清单中的结论文档路径，不从目录扫描猜测。"""

    from .spike_validation import parse_spike_index

    index_path = Path(project_root) / artifact_paths_mod.SPIKE_INDEX_DOC
    if not index_path.is_file():
        raise ValueError(f"{artifact_paths_mod.SPIKE_INDEX_DOC} 不存在")
    parsed_workflow_id, items, errors = parse_spike_index(str(index_path))
    if parsed_workflow_id != workflow_id:
        errors.append(
            f"{artifact_paths_mod.SPIKE_INDEX_DOC} 工作流编号与当前状态不一致"
        )
    documents: list[str] = []
    for item in items:
        link = item.fields.get("结论文档", "")
        match = re.search(r"\[[^\]]+\]\(([^)#]+)", link)
        if match is None:
            errors.append(f"穿刺项 {item.item_id} 的结论文档链接无效")
            continue
        target = match.group(1).strip().replace("\\", "/")
        if target.startswith("./"):
            target = target[2:]
        if not target.startswith("spec/"):
            target = f"spec/{target}"
        documents.append(target)
    if errors:
        raise ValueError("；".join(dict.fromkeys(errors)))
    return list(dict.fromkeys(documents))


def collect_spike_asset_acceptance_links(
    project_root: str,
    workflow_id: str,
    topics: list[str],
) -> dict[str, list[str]]:
    """校验十列表中的穿刺列，并返回资产路径到“主题/AC”的真实关联。"""

    state = load_state(project_root)
    if state is None or state.workflow_id != workflow_id:
        raise ValueError("找不到当前工作流状态，不能核对穿刺资产与验收条件的关联")

    content, _relative_path = _read_traceability(project_root)
    match = _workflow_match(content, workflow_id)
    section = match.group(1)
    errors: list[str] = []
    associations: dict[str, list[str]] = {}
    assets_by_path = {
        asset.relative_path.replace("\\", "/").rstrip("/"): asset
        for asset in state.spike_assets
    }
    current_assets = {
        path: asset
        for path, asset in assets_by_path.items()
        if asset.workflow_id == workflow_id
    }

    if state.spike_skipped:
        conclusion_documents: list[str] = []
    else:
        conclusion_documents = _current_spike_conclusion_documents(
            project_root,
            workflow_id,
        )
    referenced_conclusions: set[str] = set()

    # 延迟导入，避免 spike_reuse -> test_execution -> traceability 的模块循环。
    from . import spike_reuse as spike_reuse_mod

    for topic in topics:
        rows = _topic_rows(project_root, section, topic)
        if not rows:
            errors.append(f"{TRACEABILITY_PATH} 缺少主题“{topic}”的交付记录")
            continue
        for _line_index, cells in rows:
            headers = _headers_for_row(cells)
            if "穿刺结论与可复用内容" not in headers:
                errors.append(f"{TRACEABILITY_PATH} 主题“{topic}”仍是九列表，无法登记穿刺关联")
                continue
            criterion_id = _criterion_id_from_cell(topic, _cell(cells, "验收条件"))
            reference = f"{topic}/{criterion_id}"
            spike_value = _cell(cells, "穿刺结论与可复用内容").strip()

            mentioned_paths = set(_SPIKE_ASSET_PATH_RE.findall(spike_value))
            if state.spike_skipped and not mentioned_paths:
                if spike_value != SPIKE_SKIPPED_TEXT:
                    errors.append(
                        f"{TRACEABILITY_PATH} 主题“{topic}”{criterion_id} 穿刺列："
                        f"本轮已跳过新穿刺且没有复用历史资产，必须精确写“{SPIKE_SKIPPED_TEXT}”"
                    )
                continue

            unknown_paths = sorted(mentioned_paths - set(assets_by_path))
            if unknown_paths:
                errors.append(
                    f"{TRACEABILITY_PATH} 主题“{topic}”{criterion_id} 引用了未登记穿刺资产："
                    f"{unknown_paths}"
                )
            for relative_path in sorted(mentioned_paths & set(assets_by_path)):
                asset = assets_by_path[relative_path]
                if state.spike_skipped and asset.workflow_id == workflow_id:
                    errors.append(
                        f"{TRACEABILITY_PATH} 主题“{topic}”{criterion_id}："
                        "本轮已跳过新穿刺，不能引用当前工作流新登记的穿刺资产"
                    )
                if asset.workflow_id != workflow_id:
                    rerun_problems = spike_reuse_mod.historical_asset_success_problems(
                        project_root,
                        asset,
                        workflow_id,
                    )
                    if rerun_problems:
                        errors.append(
                            f"{TRACEABILITY_PATH} 主题“{topic}”{criterion_id} 引用历史资产 "
                            f"{relative_path} 前，必须在当前环境重新运行成功并保留完整机器证据："
                            f"{rerun_problems}"
                        )
                missing_facts = []
                if asset.conclusion_document not in spike_value:
                    missing_facts.append(f"结论文档 {asset.conclusion_document}")
                if f"用途：{asset.purpose}" not in spike_value:
                    missing_facts.append(f"用途：{asset.purpose}")
                if f"运行方法：{asset.run_method}" not in spike_value:
                    missing_facts.append(f"运行方法：{asset.run_method}")
                if missing_facts:
                    errors.append(
                        f"{TRACEABILITY_PATH} 主题“{topic}”{criterion_id} 的资产 {relative_path} "
                        f"缺少登记事实：{missing_facts}"
                    )
                if asset.workflow_id != workflow_id:
                    current_conclusion = asset.last_rerun_conclusion or ""
                    if (
                        not current_conclusion
                        or f"当前重跑结论：{current_conclusion}" not in spike_value
                    ):
                        errors.append(
                            f"{TRACEABILITY_PATH} 主题“{topic}”{criterion_id} 引用历史资产 "
                            f"{relative_path} 时，必须记录本轮实际重跑结论"
                        )
                associations.setdefault(relative_path, []).append(reference)

            row_conclusions = {
                document for document in conclusion_documents if document in spike_value
            }
            referenced_conclusions.update(row_conclusions)
            if not mentioned_paths and not row_conclusions and spike_value != SPIKE_NO_SUPPORT_TEXT:
                errors.append(
                    f"{TRACEABILITY_PATH} 主题“{topic}”{criterion_id} 穿刺列必须写实际结论或资产，"
                    f"没有直接支撑时精确写“{SPIKE_NO_SUPPORT_TEXT}”"
                )

    unlinked_assets = sorted(set(current_assets) - set(associations))
    if unlinked_assets:
        errors.append(f"当前工作流已登记穿刺资产尚未关联任何实际验收条件：{unlinked_assets}")
    unlinked_conclusions = sorted(set(conclusion_documents) - referenced_conclusions)
    if unlinked_conclusions:
        errors.append(f"当前工作流穿刺结论尚未关联任何实际验收条件：{unlinked_conclusions}")
    if errors:
        raise ValueError("\n".join(
            f"{index}. {error}"
            for index, error in enumerate(dict.fromkeys(errors), start=1)
        ))
    return {
        path: sorted(set(references))
        for path, references in sorted(associations.items())
    }


def bind_spike_assets_to_acceptance_conditions(
    project_root: str,
    state,
    topics: list[str],
) -> str:
    """验收计划确认时，把追踪表中的真实逐 AC 关联回填到资产登记状态。"""

    associations = collect_spike_asset_acceptance_links(
        project_root,
        state.workflow_id,
        topics,
    )
    changed = 0
    for asset in state.spike_assets:
        relative_path = asset.relative_path.replace("\\", "/").rstrip("/")
        linked = associations.get(relative_path)
        if asset.workflow_id == state.workflow_id:
            updated = linked or []
        elif linked:
            updated = sorted(set(asset.acceptance_conditions) | set(linked))
        else:
            continue
        if asset.acceptance_conditions != updated:
            asset.acceptance_conditions = updated
            changed += 1
    return f"已回填 {changed} 项穿刺资产的验收条件关联"


def validate_structure(
    project_root: str,
    workflow_id: str,
    topics: list[str] | None = None,
    *,
    require_initial_statuses: bool = False,
    require_completed_updates: bool = False,
) -> tuple[bool, str]:
    """校验当前工作流章节、兼容表头和主题行。"""
    try:
        content, _relative_path = _read_traceability(project_root)
        match = _workflow_match(content, workflow_id)
    except ValueError as exc:
        return False, str(exc)

    lines = match.group(1).splitlines()
    found_headers: list[list[str]] = []
    rows: list[list[str]] = []
    for line in lines:
        cells = _split_table_line(line)
        if cells is None:
            continue
        if cells in SUPPORTED_HEADERS:
            found_headers.append(cells)
            continue
        if len(cells) in {len(TRACEABILITY_HEADERS), len(LEGACY_TRACEABILITY_HEADERS)}:
            rows.append(cells)

    errors: list[str] = []
    required_headers = _required_headers_for_workflow(project_root, workflow_id)
    if not found_headers:
        expected_columns = len(required_headers or TRACEABILITY_HEADERS)
        errors.append(
            f"{TRACEABILITY_PATH} 当前工作流章节缺少受支持的 {_column_count_label(expected_columns)}表头"
        )
        active_headers = required_headers or TRACEABILITY_HEADERS
    else:
        active_headers = found_headers[0]
        if any(headers != active_headers for headers in found_headers[1:]):
            errors.append(f"{TRACEABILITY_PATH} 当前工作流章节混用了九列和十列表头")
        if required_headers is not None and active_headers != required_headers:
            errors.append(
                f"{TRACEABILITY_PATH} 当前新路径工作流必须使用十列表头，"
                "并包含“穿刺结论与可复用内容”"
            )

    matching_shape_rows = [row for row in rows if len(row) == len(active_headers)]
    wrong_shape_rows = [row for row in rows if len(row) != len(active_headers)]
    if wrong_shape_rows:
        errors.append(
            f"{TRACEABILITY_PATH} 当前工作流章节有 {len(wrong_shape_rows)} 条记录与表头列数不一致"
        )
    rows = matching_shape_rows
    if not rows:
            errors.append(
                f"{TRACEABILITY_PATH} 当前工作流章节没有 {_column_count_label(len(active_headers))}交付记录"
            )

    expected_topics = topics or []
    for topic in expected_topics:
        if not rows:
            errors.append(
                f"{TRACEABILITY_PATH} 主题“{topic}”未检查：当前工作流章节没有"
                f"{_column_count_label(len(active_headers))}交付记录"
            )
            continue
        markers = _topic_markers(project_root, topic)
        topic_rows = [row for row in rows if any(marker in _cell(row, "验收主题") for marker in markers)]
        if not topic_rows:
            errors.append(f"{TRACEABILITY_PATH} 缺少主题“{topic}”的交付记录")
            continue
        if any(not all(cell.strip() for cell in row) for row in topic_rows):
            errors.append(f"{TRACEABILITY_PATH} 主题“{topic}”存在空单元格")
        if require_initial_statuses:
            for row_index, row in enumerate(topic_rows, start=1):
                expected = {
                    header: value
                    for header, value in _INITIAL_VALUES_BY_HEADER.items()
                    if header in _headers_for_row(row)
                }
                actual = {header: _cell(row, header) for header in expected}
                if actual != expected:
                    errors.append(
                        f"{TRACEABILITY_PATH} 主题“{topic}”第 {row_index} 条记录尚未保持初始状态："
                        f"预期 {expected}，实际 {actual}"
                    )
        if require_completed_updates:
            for row_index, row in enumerate(topic_rows, start=1):
                pending = [
                    header
                    for header in _INITIAL_VALUES_BY_HEADER
                    if header in _headers_for_row(row) and _cell(row, header) in _INITIAL_VALUES
                ]
                if pending:
                    errors.append(
                        f"{TRACEABILITY_PATH} 主题“{topic}”第 {row_index} 条记录仍有未更新的阶段列：{pending}"
                    )

    if errors:
        unique = list(dict.fromkeys(errors))
        return False, "\n".join(
            f"{index}. {error}" for index, error in enumerate(unique, start=1)
        )

    return (
        True,
        f"{TRACEABILITY_PATH} 当前工作流包含 {len(rows)} 条"
        f"{_column_count_label(len(active_headers))}交付记录",
    )


def _trace_cell(value: str) -> str:
    """转义单元格里的管道符和换行，避免破坏追踪表表格（R3 在生成器统一执行）。"""
    text = str(value)
    text = text.replace("\\", "\\\\")
    text = text.replace("|", "\\|")
    text = text.replace("\r\n", "<br>").replace("\n", "<br>").replace("\r", "<br>")
    return text


def _source_link(basis: str) -> str:
    """把 AC 的产品设计依据链到功能文档第 4 章。

    依据已经是 Markdown 链接时原样保留；写的是 ``spec/功能_X.md R18`` 这类
    文档路径时取 ``X`` 作为功能文档名，不再二次拼 ``功能_`` 前缀（修双重路径）。
    """
    if re.search(r"\[[^\]]+\]\([^)]+\)", basis):
        # 依据已带链接：链接相对验收计划文档（../），追踪表在项目根，改写为 ./ 保持可解析
        return _trace_cell(re.sub(r"\]\(\.\./", "](./", basis))
    match = re.search(r"(?:\.\./|(?<![\w/]))spec/功能_(.+?)\.md", basis)
    name = match.group(1).strip() if match else ""
    if not name:
        stripped = basis.split(" R")[0].split("（")[0].split("；")[0].strip()
        if stripped.startswith("功能_"):
            stripped = stripped[len("功能_"):]
        name = re.sub(r"\.md$", "", stripped).strip()
    if not name:
        return _trace_cell(basis)
    return f"[产品设计：{_trace_cell(name)}](./spec/功能_{_trace_cell(name)}.md#4-规则)"


def _current_requirement_text(project_root: str, workflow_id: str) -> str:
    """从产品总说明本轮修改记录取本次需求；取不到时给一个指回修改记录的说明。"""
    try:
        overview = os.path.join(project_root, artifact_paths_mod.PRODUCT_OVERVIEW_DOC)
        if os.path.isfile(overview):
            content = Path(overview).read_text(encoding="utf-8")
            for line in content.splitlines():
                if workflow_id in line and "|" in line:
                    cells = [c.strip() for c in line.split("|")]
                    # 修改记录行：| 日期 | 工作流编号 | 用户需求 | 修改类型 | 修改内容 | ...
                    for index, cell in enumerate(cells):
                        if cell == workflow_id and index + 2 < len(cells):
                            return _trace_cell(cells[index + 2])
    except Exception:
        pass
    return f"详见 spec/产品总说明.md 第 9 章工作流 {workflow_id} 的修改记录。"


def _topic_row_lines(
    project_root: str,
    workflow_id: str,
    topic: str,
    headers: list[str],
    spike_initial: str = SPIKE_SKIPPED_TEXT,
) -> list[str]:
    """按主题的验收计划记录表生成追踪表行，单元格初值与新建章节完全一致。

    spike_initial 只在补行路径由调用方按当前穿刺事实传入待复核文本；
    建章节路径保持修复前的固定跳过初值，保证首轮行为逐字节不变。
    """
    from . import records as records_mod

    rel = records_mod.table_relative_path(project_root, workflow_id, "acceptance_plan", topic)
    if not records_mod.table_exists(project_root, rel):
        return []
    table = records_mod.load_table(os.path.join(project_root, rel))
    plan_path = topic_paths(project_root, topic)["acceptance_plan"]
    plan_link = f"[{_trace_cell(topic)}](./{_trace_cell(plan_path)})"
    rows: list[str] = []
    for ac in table.get("验收条件", []):
        ac_id = str(ac.get("验收条件编号", "")).strip()
        cond = str(ac.get("通过标准", "")).strip()
        basis = str(ac.get("产品设计依据", "")).strip()
        cond_cell = _trace_cell(f"{ac_id}：{cond}") if ac_id and cond else _trace_cell(ac_id or cond)
        cells_by_header = {
            "需求来源与设计依据": _source_link(basis),
            "验收主题": plan_link,
            "验收条件": cond_cell,
            "穿刺结论与可复用内容": spike_initial,
            **_INITIAL_VALUES_BY_HEADER,
        }
        try:
            row = [cells_by_header.get(header, "") for header in headers]
        except TypeError:
            return rows
        rows.append(_format_table_line(row))
    return rows


def _topic_row_lines_with_ids(
    project_root: str,
    workflow_id: str,
    topic: str,
    headers: list[str],
    spike_initial: str = SPIKE_SKIPPED_TEXT,
) -> list[tuple[str, str]]:
    """与 _topic_row_lines 同行序，返回每条生成行的 AC 编号，供按 AC 粒度补行。"""
    from . import records as records_mod

    rel = records_mod.table_relative_path(project_root, workflow_id, "acceptance_plan", topic)
    if not records_mod.table_exists(project_root, rel):
        return []
    table = records_mod.load_table(os.path.join(project_root, rel))
    ac_ids = [
        str(ac.get("验收条件编号", "")).strip()
        for ac in table.get("验收条件", [])
    ]
    lines = _topic_row_lines(
        project_root, workflow_id, topic, headers, spike_initial=spike_initial
    )
    return list(zip(ac_ids, lines))


def _is_table_separator(line: str) -> bool:
    stripped = line.strip()
    if not (stripped.startswith("|") and stripped.endswith("|")):
        return False
    cells = [cell.strip() for cell in stripped.strip("|").split("|")]
    return bool(cells) and all(re.fullmatch(r"[-:]+", cell) for cell in cells)


def _delivery_table_bounds(section: str) -> tuple[int, int, list[str]] | None:
    """返回章节内最后一个追踪表头块的（表头行下标、数据末尾行下标、表头列）。"""
    lines = section.splitlines()
    bounds: tuple[int, int, list[str]] | None = None
    i = 0
    while i < len(lines):
        cells = _split_table_line(lines[i])
        if cells is not None and any(cells == h for h in SUPPORTED_HEADERS):
            headers = next(h for h in SUPPORTED_HEADERS if h == cells)
            j = i + 1
            end = i
            if j < len(lines) and _is_table_separator(lines[j]):
                end = j
                j += 1
            while j < len(lines):
                next_cells = _split_table_line(lines[j])
                if next_cells is None or len(next_cells) != len(headers):
                    break
                end = j
                j += 1
            bounds = (i, end, headers)
            i = j
            continue
        i += 1
    return bounds


def _append_missing_topic_rows(
    project_root: str,
    relative: str,
    content: str,
    heading_match: re.Match[str],
    workflow_id: str,
    topics: list[str],
) -> bool:
    """章节已存在时为表内无行的主题在交付链路表末尾补行；有追加才写文件。"""
    section = heading_match.group(1)
    bounds = _delivery_table_bounds(section)
    if bounds is None:
        return False
    _, last_row_index, headers = bounds
    # 补行只发生在退回重走路径：本轮已确认跳过穿刺时新行直接写跳过文本；
    # 尚未重新确认（spike 未跑/未跳过）时写待复核文本，与旧行重置状态一致。
    spike_initial = SPIKE_RECHECK_TEXT
    try:
        state = load_state(project_root)
        if state is not None and state.workflow_id == workflow_id and state.spike_skipped:
            spike_initial = SPIKE_SKIPPED_TEXT
    except Exception:
        pass
    appended: list[str] = []
    for topic in topics:
        existing_ids = set()
        for _line_index, cells in _topic_rows(project_root, section, topic):
            try:
                criterion_cell = _cell(cells, "验收条件")
            except ValueError:
                continue
            match = _CRITERION_ID_RE.search(criterion_cell)
            if match:
                existing_ids.add(match.group(1))
        # 粒度到验收条件：主题已有旧行时，表里新增的 AC 仍要补行；已有 AC 的行不动。
        rows = [
            line
            for ac_id, line in _topic_row_lines_with_ids(
                project_root, workflow_id, topic, headers, spike_initial=spike_initial
            )
            if ac_id not in existing_ids
        ]
        if rows:
            appended.extend(rows)
    if not appended:
        return False
    section_lines = section.split("\n")
    merged = (
        section_lines[: last_row_index + 1]
        + appended
        + section_lines[last_row_index + 1 :]
    )
    new_section = "\n".join(merged)
    content = content[: heading_match.start(1)] + new_section + content[heading_match.end(1) :]
    _write_traceability(project_root, relative, content)
    return True


def ensure_workflow_section(
    project_root: str,
    workflow_id: str,
    topics: list[str],
) -> bool:
    """追踪表没有当前工作流章节时按模板生成；章节已存在时为缺行主题补交付行。

    断言三：表流程生成全部文档。退回 acceptance_plan 后向索引追加新主题时，
    旧章节保留，新主题必须按建章节同一初值规则自动补行，不能要求手工添加。
    """
    relative = _trace_relative_path(project_root)
    full = os.path.join(project_root, relative)
    if os.path.isfile(full):
        content = Path(full).read_text(encoding="utf-8")
    else:
        content = "# 需求交付追踪表\n"
    heading_match = _workflow_heading_pattern(workflow_id).search(content)
    if heading_match is not None:
        return _append_missing_topic_rows(
            project_root, relative, content, heading_match, workflow_id, topics
        )
    lines = [
        "## " + workflow_id,
        "",
        "### 本次需求",
        "",
        _current_requirement_text(project_root, workflow_id),
        "",
        "### 交付链路",
        "",
        "| " + " | ".join(TRACEABILITY_HEADERS) + " |",
        "|" + "---|" * len(TRACEABILITY_HEADERS),
    ]
    for topic in topics:
        lines += _topic_row_lines(project_root, workflow_id, topic, TRACEABILITY_HEADERS)
    lines += [
        "",
        "### 阻塞和退回记录",
        "",
        "| 时间 | 阶段 | 原因 | 处理结果 |",
        "|---|---|---|---|",
        "| 暂无 | 暂无 | 暂无 | 暂无 |",
        "",
    ]
    section = "\n".join(lines)
    content = content.rstrip("\n") + "\n" + section
    _write_traceability(project_root, relative, content)
    return True


def _update_stage_rows(
    project_root: str,
    workflow_id: str,
    topics: list[str],
    updates: dict[str, object],
) -> str:
    """先计算本阶段全部列，再一次写回，避免留下半张更新表。"""
    content, relative_path = _read_traceability(project_root)
    match = _workflow_match(content, workflow_id)
    section_lines = match.group(1).splitlines(keepends=True)
    changed = 0
    replacements: dict[int, list[str]] = {}

    for topic in topics:
        rows = _topic_rows(project_root, "".join(section_lines), topic)
        if not rows:
            raise ValueError(f"{TRACEABILITY_PATH} 缺少主题“{topic}”的交付记录")
        for line_index, cells in rows:
            updated_cells = list(cells)
            for column_header, value_factory in updates.items():
                _set_cell(
                    updated_cells,
                    column_header,
                    value_factory(topic, updated_cells),
                )
            replacements[line_index] = updated_cells

    for line_index, cells in sorted(replacements.items()):
        original_line = section_lines[line_index]
        line_ending = original_line[len(original_line.rstrip("\r\n")) :]
        section_lines[line_index] = _format_table_line(cells) + line_ending
        changed += 1

    updated_section = "".join(section_lines)
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

    验收计划、实施或测试计划变化后，原来的下游链接不能继续表示有效结果。
    这里只改当前工作流，不改旧工作流；后续阶段重新确认时会再写回自己的列。
    """

    reset_headers = {
        "acceptance_plan": set(_INITIAL_VALUES_BY_HEADER),
        "impl": set(_INITIAL_VALUES_BY_HEADER),
        # 测试验证在实施之后；测试变化不应抹掉已经确认的实施计划和实施记录。
        "qa": {"测试项", "测试结果", "验收结果", "更新后的代码设计"},
        "test_plan": {"测试项", "测试结果", "验收结果", "更新后的代码设计"},
        "test_code": {"测试结果", "验收结果", "更新后的代码设计"},
        "test_execution": {"测试结果", "验收结果", "更新后的代码设计"},
    }.get(stage_name)
    if reset_headers is None or not topics:
        return f"{TRACEABILITY_PATH} 无需重置阶段 {stage_name} 的下游列"

    if not (Path(project_root) / _trace_relative_path(project_root)).is_file():
        return f"{TRACEABILITY_PATH} 不存在，无需重置阶段 {stage_name} 的下游列"

    content, relative_path = _read_traceability(project_root)
    match = _workflow_match(content, workflow_id)
    section_lines = match.group(1).splitlines(keepends=True)
    changed = 0

    for topic in topics:
        rows = _topic_rows(project_root, "".join(section_lines), topic)
        for line_index, cells in rows:
            _reset_cells(cells, reset_headers)
            original_line = section_lines[line_index]
            line_ending = original_line[len(original_line.rstrip("\r\n")) :]
            section_lines[line_index] = _format_table_line(cells) + line_ending
            changed += 1

    if changed == 0:
        return f"{TRACEABILITY_PATH} 当前工作流没有可重置的主题记录"

    updated_section = "".join(section_lines)
    updated = _replace_workflow_section(content, workflow_id, updated_section)
    if updated != content:
        _write_traceability(project_root, relative_path, updated)
    return f"已重置 {TRACEABILITY_PATH} 当前工作流 {changed} 条失效下游记录"


# 各返回目标只重置确实失效的后续列。旧阶段名仅用于迁移中的活动轮次。
_ALL_DOWNSTREAM_HEADERS = set(_INITIAL_VALUES_BY_HEADER)
_RETURN_RESET_HEADERS: dict[str, set[str]] = {
    "spec": _ALL_DOWNSTREAM_HEADERS,
    "code_design": _ALL_DOWNSTREAM_HEADERS,
    "revise_code_design": _ALL_DOWNSTREAM_HEADERS,
    "project_design_init": _ALL_DOWNSTREAM_HEADERS,
    "reproduce": _ALL_DOWNSTREAM_HEADERS,
    "spike": _ALL_DOWNSTREAM_HEADERS,
    "acceptance_plan": _ALL_DOWNSTREAM_HEADERS,
    "impl": _ALL_DOWNSTREAM_HEADERS,
    "qa": {"测试项", "测试结果", "验收结果", "更新后的代码设计"},
    "test_plan": {"测试项", "测试结果", "验收结果", "更新后的代码设计"},
    "test_code": {"测试结果", "验收结果", "更新后的代码设计"},
    "test_execution": {"测试结果", "验收结果", "更新后的代码设计"},
    "topic_acceptance": {"验收结果", "更新后的代码设计"},
    "regression_test": {},
    "overall_acceptance": {},
    "update_code_design": {"更新后的代码设计"},
}
_RETURN_RECHECKS_SPIKE = {
    "spec",
    "code_design",
    "revise_code_design",
    "project_design_init",
    "reproduce",
    "spike",
}
_RETURN_REMOVE_CONCLUSIONS: dict[
    str,
    tuple[tuple[str, re.Pattern[str], str], ...],
] = {
    "regression_test": (
        ("测试结果", _REGRESSION_CONCLUSION_RE, "待执行"),
        ("验收结果", _OVERALL_ACCEPTANCE_CONCLUSION_RE, "待执行"),
    ),
    "overall_acceptance": (
        ("验收结果", _OVERALL_ACCEPTANCE_CONCLUSION_RE, "待执行"),
    ),
}


def resolve_spike_recheck_for_skip(project_root: str, workflow_id: str) -> str:
    """本轮确认跳过穿刺后，把当前工作流待复核的穿刺列回补为跳过文本。

    退回会把穿刺列重置为“待重新确认；已登记资产保留”；第二遍 spike --skip 之后
    校验要求无资产引用的行精确写跳过文本。    引用了穿刺资产路径的行不动，
    交给穿刺关联校验处理。"""
    content, relative_path = _read_traceability(project_root)
    match = _workflow_heading_pattern(workflow_id).search(content)
    if match is None:
        # 本轮追踪表章节尚未创建（新轮次 spike 先于 acceptance_plan），无需回补。
        return f"{TRACEABILITY_PATH} 尚无当前工作流章节，无需回补穿刺列"
    section_lines = match.group(1).splitlines(keepends=True)
    updated_rows = 0
    for line_index, line in enumerate(section_lines):
        cells = _split_table_line(line)
        if cells is None or cells in SUPPORTED_HEADERS:
            continue
        try:
            headers = _headers_for_row(cells)
        except ValueError:
            continue
        if "穿刺结论与可复用内容" not in headers:
            continue
        if _cell(cells, "穿刺结论与可复用内容").strip() != SPIKE_RECHECK_TEXT:
            continue
        original_line = section_lines[line_index]
        line_ending = original_line[len(original_line.rstrip("\r\n")) :]
        _set_cell(cells, "穿刺结论与可复用内容", SPIKE_SKIPPED_TEXT)
        section_lines[line_index] = _format_table_line(cells) + line_ending
        updated_rows += 1
    updated = _replace_workflow_section(content, workflow_id, "".join(section_lines))
    if updated != content:
        _write_traceability(project_root, relative_path, updated)
    return f"已回补 {TRACEABILITY_PATH} 穿刺列 {updated_rows} 行为跳过文本"


def reset_topics_for_return(
    project_root: str,
    workflow_id: str,
    topics: list[str],
    target_stage: str,
) -> str:
    """流程退回时，只清理受影响主题从目标阶段开始的当前交付状态。

    支持当前路径中的任意真实上游；独立主题的行保持不变。
    """
    headers = _RETURN_RESET_HEADERS.get(target_stage)
    if headers is None:
        raise ValueError(f"不支持从追踪表退回阶段: {target_stage}")
    conclusion_rules = _RETURN_REMOVE_CONCLUSIONS.get(target_stage, ())
    recheck_spike = target_stage in _RETURN_RECHECKS_SPIKE
    if not headers and not conclusion_rules and not recheck_spike:
        return f"{TRACEABILITY_PATH} 阶段 {target_stage} 没有需要重置的追踪列"
    content, relative_path = _read_traceability(project_root)
    match = _workflow_match(content, workflow_id)
    section_lines = match.group(1).splitlines(keepends=True)
    changed_lines: set[int] = set()
    for topic in topics:
        rows = _topic_rows(project_root, "".join(section_lines), topic)
        if not rows:
            raise ValueError(f"{TRACEABILITY_PATH} 缺少主题“{topic}”的交付记录")
        for line_index, cells in rows:
            original_cells = list(cells)
            _reset_cells(cells, headers)
            if recheck_spike and "穿刺结论与可复用内容" in _headers_for_row(cells):
                _set_cell(cells, "穿刺结论与可复用内容", SPIKE_RECHECK_TEXT)
            if cells != original_cells:
                original_line = section_lines[line_index]
                line_ending = original_line[len(original_line.rstrip("\r\n")) :]
                section_lines[line_index] = _format_table_line(cells) + line_ending
                changed_lines.add(line_index)

    # 最终回归和整体验收是整轮唯一的全局结论。状态失效时必须从当前工作流
    # 每一行删除该结论，不能只删用户列出的直接受影响主题；主题自身的结果链接保留。
    if conclusion_rules:
        for line_index, line in enumerate(section_lines):
            cells = _split_table_line(line)
            if cells is None or cells in SUPPORTED_HEADERS:
                continue
            try:
                _headers_for_row(cells)
            except ValueError:
                continue
            original_cells = list(cells)
            for header, pattern, fallback in conclusion_rules:
                _set_cell(
                    cells,
                    header,
                    _remove_appended_text(
                    _cell(cells, header),
                    pattern,
                    fallback,
                    ),
                )
            if cells != original_cells:
                original_line = section_lines[line_index]
                line_ending = original_line[len(original_line.rstrip("\r\n")) :]
                section_lines[line_index] = _format_table_line(cells) + line_ending
                changed_lines.add(line_index)
    updated = _replace_workflow_section(content, workflow_id, "".join(section_lines))
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
    section_lines = match.group(1).splitlines(keepends=True)
    changed = 0
    for topic in topics:
        rows = _topic_rows(project_root, "".join(section_lines), topic)
        if not rows:
            raise ValueError(f"{TRACEABILITY_PATH} 缺少主题“{topic}”的交付记录")
        for line_index, cells in rows:
            _set_cell(cells, "测试结果", "待执行")
            original_line = section_lines[line_index]
            line_ending = original_line[len(original_line.rstrip("\r\n")) :]
            section_lines[line_index] = _format_table_line(cells) + line_ending
            changed += 1

    updated = _replace_workflow_section(content, workflow_id, "".join(section_lines))
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

    test_item_update = {
        "测试项": lambda topic, cells: _set_or_append_text(
            _cell(cells, "测试项"),
            _test_plan_links(
                project_root,
                topic,
                _criterion_id_from_cell(topic, _cell(cells, "验收条件")),
            ),
        )
    }
    test_result_update = {
        "测试结果": lambda topic, cells: (
            _set_or_append_link(
                _cell(cells, "测试结果"),
                "测试结果",
                f"./{topic_paths(project_root, topic)['test_result']}",
            )
            if criterion_requires_test_code(
                project_root,
                topic,
                _criterion_id_from_cell(topic, _cell(cells, "验收条件")),
            )
            else _set_or_append_text(
                _cell(cells, "测试结果"),
                "无自动化测试项，转主题验收",
            )
        )
    }

    if stage_name == "test_plan":
        return _update_stage_rows(
            project_root,
            workflow_id,
            topics,
            test_item_update,
        )

    if stage_name == "impl":
        return _update_stage_rows(
            project_root,
            workflow_id,
            topics,
            {
                "实施计划与任务": lambda topic, cells: _set_or_append_link(
                    _cell(cells, "实施计划与任务"),
                    "实施前计划",
                    f"./{topic_paths(project_root, topic)['impl_doc']}#2-实施前计划",
                ),
                "实施记录与代码": lambda topic, cells: _set_or_append_link(
                    _cell(cells, "实施记录与代码"),
                    "实施后记录",
                    f"./{topic_paths(project_root, topic)['impl_doc']}#3-实施后记录",
                ),
            },
        )

    if stage_name == "test_execution":
        return _update_stage_rows(
            project_root,
            workflow_id,
            topics,
            test_result_update,
        )

    if stage_name == "qa":
        return _update_stage_rows(
            project_root,
            workflow_id,
            topics,
            {**test_item_update, **test_result_update},
        )

    if stage_name == "topic_acceptance":
        return _update_stage_rows(
            project_root,
            workflow_id,
            topics,
            {
                "验收结果": lambda topic, cells: _set_or_append_link(
                    _cell(cells, "验收结果"),
                    "主题验收结果",
                    f"./{topic_paths(project_root, topic)['acceptance_result']}",
                )
            },
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
            {
                "测试结果": lambda _topic, cells: _set_or_append_text(
                    _cell(cells, "测试结果"),
                    conclusion,
                )
            },
        )

    if stage_name == "overall_acceptance":
        return _update_stage_rows(
            project_root,
            workflow_id,
            topics,
            {
                "验收结果": lambda _topic, cells: _set_or_append_text(
                    _cell(cells, "验收结果"),
                    "整体验收：用户已确认",
                )
            },
        )

    if stage_name == "update_code_design":
        return _update_stage_rows(
            project_root,
            workflow_id,
            topics,
            {
                "更新后的代码设计": lambda _topic, cells: _set_or_append_link(
                    _cell(cells, "更新后的代码设计"),
                    "最终代码设计",
                    f"./{artifact_paths_mod.CODE_DESIGN_DOC}",
                )
            },
        )

    raise ValueError(f"阶段 {stage_name} 没有追踪表更新规则")
