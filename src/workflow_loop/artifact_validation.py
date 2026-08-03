import hashlib
import json
import os
import re
import sys
from datetime import datetime

from . import acceptance_records as acceptance_records_mod
from . import artifact_paths as artifact_paths_mod
from . import process_runner as process_runner_mod
from . import test_runner as test_runner_mod
from .state import load_state
from .test_mapping import (
    automated_topics,
    automated_test_items,
    parse_test_plan_items,
)
from .topic import topic_file_key, topic_paths
from .traceability import validate_structure as validate_traceability_structure
from .topic_relations import relation_signature, read_topic_index
from .verification import (
    compute_code_snapshot_hash,
    compute_file_hashes,
    get_linked_product_design_paths,
)


PROJECT_INIT_EVIDENCE_PATH = artifact_paths_mod.DESIGN_INIT_EVIDENCE_DOC
TRACEABILITY_PATH = artifact_paths_mod.TRACEABILITY_DOC
# 缺陷记录使用稳定中文文件标识：bug/缺陷_<缺陷文件标识>.md
BUG_FILENAME_RE = re.compile(r"^缺陷_[A-Za-z0-9_\-一-鿿㐀-䶿]+\.md$")
BUG_INDEX_FILENAMES = {"索引.md"}
ACCEPTANCE_CRITERION_RE = re.compile(r"^###\s+(AC-\d{2,})：?.*$", re.MULTILINE)
ACCEPTANCE_PLAN_SECTIONS = [
    "1. 本次需求与验收目标",
    "2. 产品设计依据",
    "3. 验收范围",
    "4. 验收条件",
    "5. 完成判定",
    "6. 上下游文档",
]
TEST_PLAN_SECTIONS = [
    "1. 验收条件覆盖",
    "2. 针对性回归范围",
    "3. 测试条件要求",
    "4. 未决测试条件",
    "5. 上下游文档",
]
ARCHITECTURE_DOCUMENT_SECTIONS = [
    "1. 文档说明",
    "2. 产品概览",
    "3. 产品设计如何决定代码架构",
    "4. 代码架构分层",
    "5. 架构关键节点",
    "6. 各产品功能的代码设计",
    "7. 多个功能共同使用的代码",
    "8. 产品设计与代码实现的差异",
    "9. 最终同步结论",
]
CODE_SUFFIXES = {
    ".c", ".cc", ".cpp", ".cxx", ".h", ".hpp", ".java", ".kt", ".kts",
    ".py", ".pyi", ".go", ".rs", ".swift", ".m", ".mm", ".js", ".jsx",
    ".ts", ".tsx", ".vue", ".svelte", ".rb", ".php", ".cs", ".fs", ".ets",
}
# 最终架构文档不能把计划性表述写成最终事实
FINAL_DESIGN_FORBIDDEN_WORDS = ("待实施", "待验证", "待补充", "尚未实现")
MACHINE_RECORD_TOKEN_RE = re.compile(
    r"(?<![A-Za-z0-9_-])(?:RUN|REG)-[^\s，,；;、|()\[\]{}<>`]+"
)


def _read_text(project_root: str, rel_path: str) -> str:
    with open(os.path.join(project_root, rel_path), "r", encoding="utf-8") as f:
        return f.read()


def _field(content: str, label: str) -> str | None:
    match = re.search(rf"^-\s*{re.escape(label)}：\s*(.+?)\s*$", content, re.MULTILINE)
    return match.group(1).strip() if match else None


def _argv_text(argv: list[str]) -> str:
    """把参数数组编码成可读且可精确比对的单行 JSON。"""
    return json.dumps(argv, ensure_ascii=False, separators=(",", ":"))


def _environment_text(platform: str, executable: str) -> str:
    """固定编码测试平台和实际可执行文件。"""
    return f"平台={platform}；可执行文件={executable}"


def _output_tail_text(output_tail: str) -> str:
    """把可能含换行的输出摘要编码成单行 JSON 字符串。"""
    return json.dumps(output_tail, ensure_ascii=False)


def _topic_test_record_id(topic: str, test_id: str, record) -> str:
    """按测试执行器的机器事实公式复算主题测试记录编号。"""
    payload = (
        f"{topic}|{test_id}|{record.started_at}|{record.finished_at}|"
        f"{record.exit_code}|{record.output_sha256}"
    )
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()[:8]
    compact_time = (record.started_at or "").replace(":", "").replace("-", "")
    return f"RUN-{compact_time}-{digest}"


def _section(content: str, heading: str) -> str | None:
    match = re.search(
        rf"^##\s+{re.escape(heading)}\s*$\n(.*?)(?=^##\s+|\Z)",
        content,
        re.MULTILINE | re.DOTALL,
    )
    return match.group(1).strip() if match else None


def _acceptance_criterion_sections(content: str) -> list[tuple[str, str]]:
    """拆出“验收条件”章节中的每条 AC，供固定字段校验。"""
    criteria_content = _section(content, "4. 验收条件")
    if criteria_content is None:
        return []
    matches = list(ACCEPTANCE_CRITERION_RE.finditer(criteria_content))
    sections: list[tuple[str, str]] = []
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(criteria_content)
        sections.append((match.group(1), criteria_content[match.end() : end].strip()))
    return sections


def _acceptance_result_criterion_sections(content: str) -> list[tuple[str, str]]:
    """拆出主题验收结果中的每条 AC，检查它们是否全部明确通过。"""
    criteria_content = _section(content, "2. 验收条件结果")
    if criteria_content is None:
        return []
    matches = list(ACCEPTANCE_CRITERION_RE.finditer(criteria_content))
    sections: list[tuple[str, str]] = []
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(criteria_content)
        sections.append((match.group(1), criteria_content[match.end() : end].strip()))
    return sections


def _workflow_section(content: str, workflow_id: str) -> str | None:
    match = re.search(
        rf"^##\s+{re.escape(workflow_id)}\s*$\n(.*?)(?=^##\s+|\Z)",
        content,
        re.MULTILINE | re.DOTALL,
    )
    return match.group(1).strip() if match else None


def _markdown_table_rows(content: str) -> list[list[str]]:
    rows: list[list[str]] = []
    for line in content.splitlines():
        stripped = line.strip()
        if not stripped.startswith("|") or not stripped.endswith("|"):
            continue
        cells = [cell.strip() for cell in stripped.strip("|").split("|")]
        if not cells or all(re.fullmatch(r"[-:]+", cell) for cell in cells):
            continue
        rows.append(cells)
    return rows


def _markdown_tables(content: str) -> list[tuple[list[str], list[list[str]]]]:
    """按表头、数据行拆出 Markdown 表格。"""
    lines = content.splitlines()
    tables: list[tuple[list[str], list[list[str]]]] = []
    index = 0
    while index + 1 < len(lines):
        header_line = lines[index].strip()
        separator_line = lines[index + 1].strip()
        if not (
            header_line.startswith("|")
            and header_line.endswith("|")
            and separator_line.startswith("|")
            and separator_line.endswith("|")
        ):
            index += 1
            continue

        headers = [cell.strip() for cell in header_line.strip("|").split("|")]
        separators = [
            cell.strip() for cell in separator_line.strip("|").split("|")
        ]
        if (
            len(headers) != len(separators)
            or not headers
            or not all(re.fullmatch(r":?-{3,}:?", cell) for cell in separators)
        ):
            index += 1
            continue

        rows: list[list[str]] = []
        index += 2
        while index < len(lines):
            row_line = lines[index].strip()
            if not (row_line.startswith("|") and row_line.endswith("|")):
                break
            row = [cell.strip() for cell in row_line.strip("|").split("|")]
            if len(row) == len(headers):
                rows.append(row)
            index += 1
        tables.append((headers, rows))
    return tables


def _has_real_text(value: str | None, *, allow_none: bool = False) -> bool:
    if value is None:
        return False
    normalized = value.strip()
    if not normalized:
        return False
    if allow_none and normalized in {"无", "暂无"}:
        return True
    lowered = normalized.lower()
    return not (
        normalized in {"无", "暂无", "待补充", "未填写"}
        or "<" in normalized
        or "todo" in lowered
    )


def _is_safe_topic_name(value: str | None) -> bool:
    """主题显示名称不能包含路径分隔符或目录跳转（文件名另用文件标识）。"""
    if not _has_real_text(value):
        return False
    normalized = value.strip()
    return normalized not in {".", ".."} and os.path.basename(normalized) == normalized


def _machine_record_ids(content: str | None) -> set[str]:
    """从正式文档字段中解析机器测试和最终回归记录编号。"""
    if not content:
        return set()
    trailing_punctuation = "。.!！?？：:；;，,）)]}>\"'”’"
    return {
        match.group(0).rstrip(trailing_punctuation)
        for match in MACHINE_RECORD_TOKEN_RE.finditer(content)
    }


def _reference_parts(raw_reference: str) -> tuple[str, str | None, str | None]:
    """拆出项目文件引用及其符号、锚点或行号目标。"""
    value = raw_reference.strip()
    if value.startswith("<") and value.endswith(">"):
        value = value[1:-1].strip()
    value = value.replace("\\", "/")
    if re.match(r"^[A-Za-z][A-Za-z0-9+.-]*://", value):
        return value, None, None

    if "::" in value:
        path, target = value.split("::", 1)
        return path, "symbol", target
    if "#" in value:
        path, target = value.split("#", 1)
        return path, "anchor", target
    line_match = re.fullmatch(r"(.+):(\d+)", value)
    if line_match:
        return line_match.group(1), "line", line_match.group(2)
    return value, None, None


def _resolve_project_reference(
    project_root: str,
    raw_reference: str,
) -> tuple[str, str | None, str | None] | None:
    """把架构文档中的文件引用解析为项目根下真实文件。"""
    path_text, target_kind, target = _reference_parts(raw_reference)
    if (
        not path_text
        or os.path.isabs(path_text)
        or re.match(r"^[A-Za-z]:/", path_text)
        or re.match(r"^[A-Za-z][A-Za-z0-9+.-]*://", path_text)
    ):
        return None

    if path_text.startswith(("./", "../")):
        relative_path = os.path.normpath(os.path.join("spec", path_text))
    else:
        relative_path = os.path.normpath(path_text)
    project_root_abs = os.path.abspath(project_root)
    full_path = os.path.abspath(os.path.join(project_root_abs, relative_path))
    try:
        if os.path.commonpath([project_root_abs, full_path]) != project_root_abs:
            return None
    except ValueError:
        return None
    if not os.path.isfile(full_path):
        return None
    return relative_path.replace(os.sep, "/"), target_kind, target


def _looks_like_file_reference(raw_reference: str) -> bool:
    """判断一个 Markdown 标识是否在声明文件路径，而不是代码符号。"""
    path_text, _, _ = _reference_parts(raw_reference)
    suffix = os.path.splitext(path_text)[1].lower()
    known_non_code_suffixes = {
        ".md", ".json", ".toml", ".yaml", ".yml", ".ini", ".cfg",
        ".sh", ".ps1", ".bat", ".cmd", ".pro", ".pri", ".cmake",
    }
    return (
        "/" in path_text
        or "\\" in raw_reference
        or suffix in CODE_SUFFIXES
        or suffix in known_non_code_suffixes
        or os.path.basename(path_text) in {"Makefile", "CMakeLists.txt"}
    )


def _reference_candidates(content: str) -> list[str]:
    """提取反引号、Markdown 链接和裸写项目路径中的文件引用候选。"""
    candidates = list(re.findall(r"`([^`\n]+)`", content))
    candidates.extend(re.findall(r"\[[^\]]+\]\(([^)]+)\)", content))
    raw_content = re.sub(r"\[[^\]]+\]\([^)]+\)", "", content)
    candidates.extend(
        re.findall(
            r"(?<![A-Za-z0-9_.-])"
            r"(?:\.{0,2}/)?"
            r"(?:[A-Za-z0-9_\-\u3400-\u9fff]+/)+"
            r"[A-Za-z0-9_.\-\u3400-\u9fff]+"
            r"(?:(?:::|#)[A-Za-z0-9_.:()\-\u3400-\u9fff]+|:\d+)?",
            raw_content,
        )
    )
    return list(dict.fromkeys(candidate.strip() for candidate in candidates if candidate.strip()))


def _declared_symbol(raw_symbol: str) -> str | None:
    """解析正式代码位置中声明的类、函数、方法、常量或配置项。"""
    value = raw_symbol.strip()
    value = re.sub(r"\([^()]*\)$", "", value).strip()
    if re.fullmatch(r"--[a-z0-9][a-z0-9-]*", value):
        return value
    if re.fullmatch(
        r"[A-Za-z_][A-Za-z0-9_]*(?:(?:\.|::)[A-Za-z_][A-Za-z0-9_]*)*",
        value,
    ):
        return value
    return None


def _symbol_is_locatable(file_content: str, raw_symbol: str) -> bool:
    """以完整标识边界检查符号，避免 `run` 误命中 `runner`。"""
    value = raw_symbol.strip()
    value = re.sub(r"\[[^\]]*\]$", "", value)
    value = re.sub(r"\([^()]*\)$", "", value).strip()
    if value.startswith("--"):
        return re.search(
            rf"(?<![A-Za-z0-9-]){re.escape(value)}(?![A-Za-z0-9-])",
            file_content,
        ) is not None
    lookup = re.split(r"::|\.", value)[-1]
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", lookup):
        return False
    return re.search(
        rf"(?<![A-Za-z0-9_]){re.escape(lookup)}(?![A-Za-z0-9_])",
        file_content,
    ) is not None


def _markdown_anchor_exists(file_content: str, anchor: str) -> bool:
    """检查 Markdown 标题锚点或显式 HTML id 是否真实存在。"""
    normalized_anchor = anchor.strip().lstrip("#").lower()
    if not normalized_anchor:
        return False
    if re.search(
        rf"\bid\s*=\s*['\"]{re.escape(normalized_anchor)}['\"]",
        file_content,
        re.IGNORECASE,
    ):
        return True
    for heading in re.findall(r"^#{1,6}\s+(.+?)\s*#*\s*$", file_content, re.MULTILINE):
        heading = re.sub(r"`([^`]+)`", r"\1", heading)
        slug = re.sub(r"[^\w\u3400-\u9fff -]", "", heading.lower())
        slug = re.sub(r"\s+", "-", slug.strip())
        if slug == normalized_anchor:
            return True
    return False


def _reference_target_is_locatable(
    project_root: str,
    reference: tuple[str, str | None, str | None],
    fallback_symbols: list[str],
) -> bool:
    """检查文件引用中的行号、锚点、符号或同单元格符号。"""
    relative_path, target_kind, target = reference
    file_content = _read_text(project_root, relative_path)
    if target_kind == "line" and target is not None:
        line_number = int(target)
        return 1 <= line_number <= len(file_content.splitlines())
    if target_kind == "anchor" and target is not None:
        line_match = re.fullmatch(r"L(\d+)", target, re.IGNORECASE)
        if line_match:
            line_number = int(line_match.group(1))
            return 1 <= line_number <= len(file_content.splitlines())
        return _markdown_anchor_exists(file_content, target)
    if target_kind == "symbol" and target is not None:
        return _symbol_is_locatable(file_content, target)
    return any(_symbol_is_locatable(file_content, symbol) for symbol in fallback_symbols)


def _feature_code_mappings(
    project_root: str,
    section: str,
) -> tuple[bool, str, list[str]]:
    """逐个校验正式功能表中声明的代码文件和全部反引号符号。"""
    mapped_paths: set[str] = set()
    mapping_cells = 0
    for headers, rows in _markdown_tables(section):
        code_indexes = [
            index
            for index, header in enumerate(headers)
            if header.strip("* `") in {"代码位置", "对应代码"}
        ]
        for row in rows:
            for code_index in code_indexes:
                mapping_cells += 1
                cell = row[code_index]
                if not _has_real_text(cell):
                    return False, "代码位置存在空值或模板占位符", []

                references: list[tuple[str, str | None, str | None]] = []
                symbols: list[str] = []
                for token in _reference_candidates(cell):
                    resolved = _resolve_project_reference(project_root, token)
                    if resolved is not None:
                        suffix = os.path.splitext(resolved[0])[1].lower()
                        if suffix not in CODE_SUFFIXES:
                            continue
                        if resolved[0].startswith("tests/"):
                            return False, f"代码位置不能用测试文件代替产品代码: {resolved[0]}", []
                        references.append(resolved)
                        mapped_paths.add(resolved[0])
                        if resolved[1] == "symbol" and resolved[2]:
                            symbols.append(resolved[2])
                        continue
                    if _looks_like_file_reference(token):
                        path_text, _, _ = _reference_parts(token)
                        if os.path.splitext(path_text)[1].lower() in CODE_SUFFIXES:
                            return False, f"代码位置引用的文件不存在或不在项目内: {token}", []

                    symbol = _declared_symbol(token)
                    if symbol is not None:
                        symbols.append(symbol)

                references = list(dict.fromkeys(references))
                symbols = list(dict.fromkeys(symbols))
                if not references:
                    return False, f"代码位置没有项目内真实代码文件: {cell}", []
                if not symbols:
                    return False, f"代码位置没有反引号可定位符号: {cell}", []

                file_contents = {
                    relative_path: _read_text(project_root, relative_path)
                    for relative_path, _, _ in references
                }
                for symbol in symbols:
                    if not any(
                        _symbol_is_locatable(file_content, symbol)
                        for file_content in file_contents.values()
                    ):
                        return (
                            False,
                            f"代码符号 `{symbol}` 无法在同一代码位置声明的文件中定位",
                            [],
                        )

    if mapping_cells == 0 or not mapped_paths:
        return False, "功能段没有按正式表格填写代码位置和对应代码", []
    return True, "", sorted(mapped_paths)


def _feature_verification_locations(
    project_root: str,
    section: str,
) -> tuple[bool, str]:
    """逐格校验验证位置指向项目内真实文件和可定位目标。"""
    verification_cells = 0
    for headers, rows in _markdown_tables(section):
        verification_indexes = [
            index
            for index, header in enumerate(headers)
            if header.strip("* `") in {"验证位置", "验证依据"}
        ]
        for row in rows:
            for verification_index in verification_indexes:
                verification_cells += 1
                cell = row[verification_index]
                if not _has_real_text(cell):
                    return False, "验证位置存在空值或模板占位符"

                references: list[tuple[str, str | None, str | None]] = []
                fallback_symbols: list[str] = []
                for token in _reference_candidates(cell):
                    resolved = _resolve_project_reference(project_root, token)
                    if resolved is not None:
                        references.append(resolved)
                        continue
                    if _looks_like_file_reference(token):
                        return False, f"验证位置引用的文件不存在或不在项目内: {token}"
                    symbol = _declared_symbol(token)
                    if symbol is not None:
                        fallback_symbols.append(symbol)

                references = list(dict.fromkeys(references))
                fallback_symbols = list(dict.fromkeys(fallback_symbols))
                if not references:
                    return False, f"验证位置没有项目内真实文件: {cell}"
                for reference in references:
                    if not _reference_target_is_locatable(
                        project_root,
                        reference,
                        fallback_symbols,
                    ):
                        return (
                            False,
                            f"验证位置没有可定位的行号、标题、测试函数或运行入口: {cell}",
                        )

    if verification_cells == 0:
        return False, "功能段没有按正式表格填写验证位置或验证依据"
    return True, ""


def _required_final_machine_record_ids(wf_state) -> tuple[set[str] | None, str]:
    """汇总最终设计核对依据必须精确列出的当前机器记录编号。"""
    stage_state = wf_state.stages.get("topic_acceptance")
    if stage_state is None:
        return None, "缺少 topic_acceptance（主题验收阶段）状态"

    required: set[str] = set()
    for topic in wf_state.topics:
        for criterion_id, record in stage_state.acceptance_records.get(topic, {}).items():
            if not acceptance_records_mod.record_is_current(record, wf_state):
                return None, f"{topic} / {criterion_id} 的程序验收记录已经失效"
            required.update(record.test_record_ids)

    regression = wf_state.regression_test
    if regression.status != "passed" or not regression.record_id:
        return None, "最终全量回归没有当前有效的机器记录编号"
    required.add(regression.record_id)
    return required, ""


def _architecture_feature_sections(content: str) -> list[str]:
    """拆出“各产品功能的代码设计”中的每个 6.x 功能段。"""
    feature_content = _section(content, "6. 各产品功能的代码设计") or ""
    matches = list(re.finditer(r"^###\s+6\.\d+\s+.+$", feature_content, re.MULTILINE))
    sections: list[str] = []
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(feature_content)
        sections.append(feature_content[match.start() : end].strip())
    return sections


def changed_stage_paths(
    project_root: str,
    stage_name: str,
    current_paths: list[str],
) -> tuple[bool, str, list[str]]:
    """比较讨论完成时的基线，返回本阶段新增、修改或删除的文件。"""
    state = load_state(project_root)
    if state is None or stage_name not in state.stages:
        return (False, "找不到当前工作流阶段状态，无法判断文件是否属于本次工作", [])

    stage_state = state.stages[stage_name]
    if stage_state.artifact_baseline_captured_at is None:
        return (False, "没有阶段产物基线；请先执行 --discuss-done，再修改产物文件", [])

    current_hashes = compute_file_hashes(project_root, current_paths)
    baseline_hashes = stage_state.artifact_baseline_hashes
    all_paths = sorted(set(baseline_hashes) | set(current_hashes))
    changed = [
        rel_path
        for rel_path in all_paths
        if baseline_hashes.get(rel_path) != current_hashes.get(rel_path)
    ]
    if not changed:
        return (False, "相关文件与讨论完成时相同，不能证明本阶段已经生成或修改产物", [])
    return (True, f"本阶段发生变化的文件: {changed}", changed)


def validate_project_design_init_evidence(
    project_root: str,
    workflow_id: str,
) -> tuple[bool, str]:
    full_path = os.path.join(project_root, PROJECT_INIT_EVIDENCE_PATH)
    if not os.path.isfile(full_path):
        return (False, f"缺少 {PROJECT_INIT_EVIDENCE_PATH}")

    content = _read_text(project_root, PROJECT_INIT_EVIDENCE_PATH)
    if _field(content, "工作流编号") != workflow_id:
        return (False, "项目设计初始化证据中的工作流编号与当前工作流不一致")
    if _field(content, "代码检查状态") != "已完成":
        return (False, "项目设计初始化证据必须写“代码检查状态：已完成”")

    code_section = _section(content, "1. 已检查代码")
    if not code_section:
        return (False, "项目设计初始化证据缺少“1. 已检查代码”内容")

    checked_code_paths: list[str] = []
    for line in code_section.splitlines():
        if not line.strip().startswith("|"):
            continue
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if len(cells) < 3 or cells[0] in {"代码路径", "---", "-"}:
            continue
        raw_path = cells[0].strip("`")
        rel_path = re.sub(r"(?::\d+|#L\d+)$", "", raw_path)
        full_code_path = os.path.join(project_root, rel_path)
        if os.path.isfile(full_code_path) and os.path.splitext(rel_path)[1].lower() in CODE_SUFFIXES:
            checked_code_paths.append(rel_path)
        else:
            return (False, f"已检查代码中包含不存在或不是代码文件的路径: {raw_path}")
        if not _has_real_text(cells[1]) or not _has_real_text(cells[2]):
            return (False, f"已检查代码必须写清检查内容和得到的事实: {raw_path}")

    if not checked_code_paths:
        return (False, "项目设计初始化证据至少要列出一个实际检查过的代码文件")

    run_condition = _field(content, "运行条件")
    run_status = _field(content, "执行状态")
    run_result = _field(content, "执行结果")
    command = _field(content, "执行命令")
    result_summary = _field(content, "结果摘要")
    unavailable_reason = _field(content, "未执行原因")
    unverified_scope = _field(content, "未验证范围")

    if run_condition == "具备":
        if run_status != "已执行":
            return (False, "运行条件写“具备”时，执行状态必须是“已执行”")
        if run_result not in {"通过", "失败", "部分通过"}:
            return (False, "已经执行时，执行结果必须是“通过”“失败”或“部分通过”")
        if not _has_real_text(command) or not _has_real_text(result_summary):
            return (False, "已经执行时必须写清实际命令和结果摘要")
    elif run_condition == "不具备":
        if run_status != "未执行" or run_result != "未执行":
            return (False, "运行条件写“不具备”时，执行状态和执行结果都必须是“未执行”")
        if not _has_real_text(unavailable_reason) or not _has_real_text(unverified_scope):
            return (False, "无法运行时必须写清未执行原因和未验证范围")
    else:
        return (False, "运行条件只能写“具备”或“不具备”")

    calibration = _section(content, "3. 产品与代码设计校准结果")
    if not _has_real_text(calibration):
        return (False, "必须写清产品文档与代码设计文档怎样根据调查结果完成校准")

    return (True, f"项目设计初始化调查证据有效，已核对代码文件: {checked_code_paths}")


def validate_final_code_design_document(
    project_root: str,
    workflow_id: str,
) -> tuple[bool, str]:
    """校验最终架构文档已经完成产品、功能、架构和真实代码映射。

    功能范围以产品总说明当前链接的功能文档为准；每个功能必须唯一匹配一个
    6.x 功能段，映射真实代码文件、可定位符号和验证位置，并拒绝计划性表述。
    """
    relative_path = artifact_paths_mod.CODE_DESIGN_DOC
    full_path = os.path.join(project_root, relative_path)
    if not os.path.isfile(full_path):
        return False, f"{relative_path} 不存在"

    content = _read_text(project_root, relative_path)
    product_path = os.path.join(project_root, artifact_paths_mod.PRODUCT_OVERVIEW_DOC)
    if not os.path.isfile(product_path):
        return False, f"{artifact_paths_mod.PRODUCT_OVERVIEW_DOC} 不存在，无法核对最终产品设计"
    missing_sections = [
        heading
        for heading in ARCHITECTURE_DOCUMENT_SECTIONS
        if _section(content, heading) is None
    ]
    if missing_sections:
        return False, f"{relative_path} 缺少章节: {missing_sections}"

    # 功能范围以产品总说明当前链接的功能文档为准，不扫描目录里的废弃文档
    feature_paths = [
        path
        for path in get_linked_product_design_paths(project_root)
        if path != artifact_paths_mod.PRODUCT_OVERVIEW_DOC
    ]
    if not feature_paths:
        return False, "产品总说明没有链接任何功能文档，无法建立功能到代码映射"

    feature_sections = _architecture_feature_sections(content)
    if not feature_sections:
        return False, "最终架构文档没有按产品功能编写 6.x 功能代码设计"

    for feature_path in feature_paths:
        feature_name = os.path.basename(feature_path)
        matching_sections = [section for section in feature_sections if feature_name in section]
        if len(matching_sections) != 1:
            return False, f"最终架构文档必须唯一映射功能文档: {feature_path}"
        section = matching_sections[0]
        mapping_ok, mapping_detail, mapped_code_paths = _feature_code_mappings(
            project_root,
            section,
        )
        if not mapping_ok:
            return (
                False,
                f"最终架构文档的功能代码映射无效: {feature_path}；{mapping_detail}",
            )
        verification_ok, verification_detail = _feature_verification_locations(
            project_root,
            section,
        )
        if not verification_ok:
            return (
                False,
                f"最终架构文档的功能验证位置无效: {feature_path}；{verification_detail}",
            )
        forbidden = [word for word in FINAL_DESIGN_FORBIDDEN_WORDS if word in section]
        if forbidden:
            return (
                False,
                f"最终架构文档功能段不能把计划性表述写成最终事实（{forbidden}）: {feature_path}",
            )

    feature_code_section = _section(content, "6. 各产品功能的代码设计") or ""
    if "代码位置" not in feature_code_section:
        return False, "最终架构文档的功能代码设计缺少“代码位置”"

    sync_section = _section(content, "9. 最终同步结论") or ""
    expected_fields = {
        "工作流编号": workflow_id,
        "产品设计核对": "一致",
        "功能文档核对": "一致",
        "代码实现核对": "一致",
        "功能到代码映射": "完整",
        "未处理差异": "暂无",
    }
    for label, expected in expected_fields.items():
        actual = _field(sync_section, label)
        if actual != expected:
            return False, f"最终同步结论的“{label}”必须是“{expected}”，当前是“{actual or '缺少'}”"

    sync_type = _field(sync_section, "本次同步类型")
    if sync_type not in {"架构变化", "架构未变化"}:
        return False, "最终同步结论的“本次同步类型”只能写“架构变化”或“架构未变化”"
    verification_basis = _field(sync_section, "核对依据")
    if not _has_real_text(verification_basis):
        return False, "最终同步结论必须写清可以复核的核对依据"
    state = load_state(project_root)
    if state is None or state.workflow_id != workflow_id:
        return False, "找不到当前工作流状态，无法核对机器记录编号"
    required_record_ids, record_detail = _required_final_machine_record_ids(state)
    if required_record_ids is None:
        return False, record_detail
    actual_record_ids = _machine_record_ids(verification_basis)
    if actual_record_ids != required_record_ids:
        missing_ids = sorted(required_record_ids - actual_record_ids)
        extra_ids = sorted(actual_record_ids - required_record_ids)
        return (
            False,
            "最终同步结论的核对依据必须精确列出当前机器记录编号；"
            f"缺少={missing_ids}，额外或拼接错误={extra_ids}",
        )

    return (
        True,
        f"最终设计同步有效：已核对 {len(feature_paths)} 个功能，并完成真实代码映射",
    )


def validate_reproduce_documents(
    project_root: str,
    changed_paths: list[str],
    workflow_id: str,
) -> tuple[bool, str]:
    index_path = artifact_paths_mod.BUG_INDEX_DOC
    normalized_changed = [path.replace(os.sep, "/") for path in changed_paths]
    if index_path not in normalized_changed:
        return (False, f"{index_path} 没有在本阶段更新")
    if not os.path.isfile(os.path.join(project_root, index_path)):
        return (False, f"{index_path} 不存在")

    changed_bug_docs = [
        rel_path
        for rel_path in normalized_changed
        if rel_path.startswith("bug/")
        and os.path.basename(rel_path) not in BUG_INDEX_FILENAMES
        and os.path.isfile(os.path.join(project_root, rel_path))
        and rel_path.endswith(".md")
    ]
    if not changed_bug_docs:
        return (False, "本阶段没有新增或修改缺陷记录文档")

    index_content = _read_text(project_root, index_path)
    required_sections = [
        "1. 缺陷现象",
        "2. 真实复现条件",
        "3. 复现步骤",
        "4. 实际结果",
        "5. 期望结果",
        "6. 根因",
        "7. 修复仍存在的不确定性",
    ]

    topics: list[str] = []
    for rel_path in changed_bug_docs:
        filename = os.path.basename(rel_path)
        if not BUG_FILENAME_RE.match(filename):
            return (False, f"缺陷记录文件名必须是 缺陷_<缺陷文件标识>.md: {filename}")
        if not re.search(rf"\((?:\./)?{re.escape(filename)}\)", index_content):
            return (False, f"{index_path} 没有链接本次缺陷记录: {filename}")

        content = _read_text(project_root, rel_path)
        if _field(content, "工作流编号") != workflow_id:
            return (False, f"{filename} 的工作流编号与当前工作流不一致")
        if _field(content, "复现状态") != "已复现":
            return (False, f"{filename} 必须写“复现状态：已复现”")
        if _field(content, "根因状态") != "已确认":
            return (False, f"{filename} 必须写“根因状态：已确认”")
        topic = _field(content, "验收主题")
        if not _is_safe_topic_name(topic):
            return (False, f"{filename} 必须写清唯一验收主题")
        topics.append(topic or "")

        for heading in required_sections:
            if not _has_real_text(_section(content, heading), allow_none=heading.startswith("7.")):
                return (False, f"{filename} 的“{heading}”缺少具体内容")

        condition_section = _section(content, "2. 真实复现条件") or ""
        if not _has_real_text(_field(condition_section, "运行环境")):
            return (False, f"{filename} 必须写清真实运行环境")
        if not _has_real_text(_field(condition_section, "真实输入")):
            return (False, f"{filename} 必须写清触发缺陷的真实输入")

        root_section = _section(content, "6. 根因") or ""
        for label in ("根因说明", "根因位置", "根因证据"):
            if not _has_real_text(_field(root_section, label)):
                return (False, f"{filename} 必须写清{label}")

    duplicates = sorted({topic for topic in topics if topics.count(topic) > 1})
    if duplicates:
        return (False, f"多份缺陷记录使用了重复验收主题: {duplicates}")

    return (
        True,
        f"本阶段缺陷记录已复现、确认根因并确定验收主题: {dict(zip(changed_bug_docs, topics))}",
    )


def validate_acceptance_plan_documents(
    project_root: str,
    workflow_id: str,
    topics: list[str],
) -> tuple[bool, str]:
    """校验主题验收计划和当前工作流的需求交付追踪表。"""
    index_ok, index_detail = validate_acceptance_index(
        project_root,
        workflow_id,
        topics,
    )
    if not index_ok:
        return False, index_detail

    traceability_ok, traceability_detail = validate_traceability_structure(
        project_root,
        workflow_id,
        topics,
        require_initial_statuses=True,
    )
    if not traceability_ok:
        return False, traceability_detail

    traceability_full_path = os.path.join(project_root, TRACEABILITY_PATH)
    if not os.path.isfile(traceability_full_path):
        return (False, f"{TRACEABILITY_PATH} 不存在")

    traceability_content = _read_text(project_root, TRACEABILITY_PATH)
    workflow_content = _workflow_section(traceability_content, workflow_id)
    if workflow_content is None:
        return (False, f"{TRACEABILITY_PATH} 缺少当前工作流章节: {workflow_id}")

    traceability_rows = [
        row
        for row in _markdown_table_rows(workflow_content)
        if len(row) == 9 and row[0] != "需求来源与设计依据"
    ]
    if not traceability_rows:
        return (False, f"{TRACEABILITY_PATH} 当前工作流章节没有九列交付链路记录")

    all_criteria: list[str] = []
    for topic in topics:
        paths = topic_paths(project_root, topic)
        rel_path = paths["acceptance_plan"]
        full_path = os.path.join(project_root, rel_path)
        if not os.path.isfile(full_path):
            return (False, f"缺少验收计划文档: {rel_path}")

        content = _read_text(project_root, rel_path)
        if _field(content, "验收主题") != topic:
            return (False, f"{rel_path} 的验收主题显示名称必须是“{topic}”")
        for heading in ACCEPTANCE_PLAN_SECTIONS:
            if _section(content, heading) is None:
                return (False, f"{rel_path} 缺少“{heading}”")

        criterion_sections = _acceptance_criterion_sections(content)
        criterion_ids = [criterion_id for criterion_id, _ in criterion_sections]
        if not criterion_ids:
            return (False, f"{rel_path} 至少需要一条 AC-01 形式的验收条件")
        if len(criterion_ids) != len(set(criterion_ids)):
            return (False, f"{rel_path} 存在重复验收条件编号")
        for criterion_id, criterion_content in criterion_sections:
            for label in ("条件与触发", "预期结果", "产品设计依据"):
                if not _has_real_text(_field(criterion_content, label)):
                    return (False, f"{rel_path} 的 {criterion_id} 缺少具体“{label}”")
            product_basis = _field(criterion_content, "产品设计依据") or ""
            if re.search(r"\[[^\]]+\]\([^)]+\)", product_basis) is None:
                return (False, f"{rel_path} 的 {criterion_id} 产品设计依据必须是可打开的链接")
        if f"../{TRACEABILITY_PATH}" not in content:
            return (False, f"{rel_path} 的上下游文档没有链接 ../{TRACEABILITY_PATH}")
        test_plan_rel = paths["test_plan"]
        if f"../{test_plan_rel}" not in content and os.path.basename(test_plan_rel) not in content:
            return (False, f"{rel_path} 没有写下游测试计划路径 {test_plan_rel}")

        for criterion_id in criterion_ids:
            matching_rows = [
                row
                for row in traceability_rows
                if paths["acceptance_plan"] in row[1] and criterion_id in row[2]
            ]
            if len(matching_rows) != 1:
                return (
                    False,
                    f"{TRACEABILITY_PATH} 中主题“{topic}”的 {criterion_id} 必须且只能占一行",
                )
            row = matching_rows[0]
            expected_statuses = ["待制定", "待制定", "待执行", "待执行", "待执行", "待更新"]
            if row[3:] != expected_statuses:
                return (
                    False,
                    f"{TRACEABILITY_PATH} 中主题“{topic}”的 {criterion_id} 后续状态必须是 {expected_statuses}",
                )
            all_criteria.append(f"{topic}:{criterion_id}")

    return (
        True,
        f"验收计划结构完整，追踪表逐条覆盖 {len(all_criteria)} 条验收条件: {topics}",
    )


def _validate_topic_index_rows(
    project_root: str,
    workflow_id: str,
    topics: list[str],
    relative_path: str,
    expected_headers: list[str],
    expected_links: dict[str, str],
    allowed_text_values: dict[str, set[str]] | None = None,
) -> tuple[bool, str, list]:
    """校验主题索引的主题集合、顺序、链接和前置关系。

    expected_links 的值使用 "{key}" 占位符，按主题文件标识展开。
    """

    try:
        relations = read_topic_index(
            project_root,
            relative_path,
            workflow_id,
            expected_headers,
            allowed_text_values,
        )
    except ValueError as exc:
        return False, str(exc), []

    actual_topics = [relation.topic for relation in relations]
    if len(actual_topics) != len(set(actual_topics)):
        return False, f"{relative_path} 存在重复验收主题", []
    if set(actual_topics) != set(topics):
        return (
            False,
            f"{relative_path} 的主题必须覆盖当前工作流全部主题；当前主题 {topics}，索引主题 {actual_topics}",
            [],
        )

    orders = [relation.order for relation in relations]
    if sorted(orders) != list(range(1, len(relations) + 1)):
        return False, f"{relative_path} 展示顺序必须从 1 开始连续编号", []

    order_by_topic = {relation.topic: relation.order for relation in relations}
    for relation in relations:
        file_key = topic_file_key(project_root, relation.topic)
        for header, path_template in expected_links.items():
            expected_path = path_template.format(key=file_key)
            actual_value = relation.links.get(header)
            if actual_value != expected_path:
                allowed = (allowed_text_values or {}).get(header, set())
                if actual_value in allowed:
                    continue
                return False, f"{relative_path} 主题“{relation.topic}”的“{header}”链接错误", []
        for prerequisite in relation.prerequisites:
            if prerequisite not in order_by_topic:
                return False, f"{relative_path} 主题“{relation.topic}”引用了不存在的前置主题“{prerequisite}”", []
            if prerequisite == relation.topic:
                return False, f"{relative_path} 主题“{relation.topic}”不能依赖自己", []
            if order_by_topic[prerequisite] >= relation.order:
                return (
                    False,
                    f"{relative_path} 主题“{relation.topic}”的前置主题“{prerequisite}”必须排在前面",
                    [],
                )

    # 依赖关系用深度优先搜索（DFS）检查，避免主题互相等待。
    dependencies = {
        relation.topic: relation.prerequisites for relation in relations
    }
    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(topic: str) -> bool:
        if topic in visiting:
            return False
        if topic in visited:
            return True
        visiting.add(topic)
        if not all(visit(prerequisite) for prerequisite in dependencies[topic]):
            return False
        visiting.remove(topic)
        visited.add(topic)
        return True

    if not all(visit(topic) for topic in dependencies):
        return False, f"{relative_path} 的主题前置关系存在循环", []
    return True, "", relations


def validate_acceptance_index(
    project_root: str,
    workflow_id: str,
    topics: list[str],
) -> tuple[bool, str]:
    """校验验收索引，并作为后续阶段主题关系的来源。"""

    ok, detail, _ = _validate_topic_index_rows(
        project_root,
        workflow_id,
        topics,
        artifact_paths_mod.ACCEPTANCE_INDEX_DOC,
        ["展示顺序", "验收主题", "前置主题", "验收计划", "主题验收结果"],
        {
            "验收计划": "./{key}_验收计划.md",
            "主题验收结果": "./{key}_验收结果.md",
        },
    )
    return ok, detail or f"{artifact_paths_mod.ACCEPTANCE_INDEX_DOC} 结构完整"


def validate_inherited_topic_index(
    project_root: str,
    workflow_id: str,
    topics: list[str],
    relative_path: str,
    expected_headers: list[str],
    expected_links: dict[str, str],
    allowed_text_values: dict[str, set[str]] | None = None,
) -> tuple[bool, str]:
    """校验 qa/ 或 impl/ 索引是否继承验收索引的主题关系。"""

    source_ok, source_detail, source_relations = _validate_topic_index_rows(
        project_root,
        workflow_id,
        topics,
        artifact_paths_mod.ACCEPTANCE_INDEX_DOC,
        ["展示顺序", "验收主题", "前置主题", "验收计划", "主题验收结果"],
        {
            "验收计划": "./{key}_验收计划.md",
            "主题验收结果": "./{key}_验收结果.md",
        },
    )
    if not source_ok:
        return False, source_detail
    target_ok, target_detail, target_relations = _validate_topic_index_rows(
        project_root,
        workflow_id,
        topics,
        relative_path,
        expected_headers,
        expected_links,
        allowed_text_values,
    )
    if not target_ok:
        return False, target_detail
    if relation_signature(source_relations) != relation_signature(target_relations):
        return False, f"{relative_path} 的主题关系没有继承 {artifact_paths_mod.ACCEPTANCE_INDEX_DOC}"
    return True, f"{relative_path} 已继承 {artifact_paths_mod.ACCEPTANCE_INDEX_DOC} 的主题关系"


def validate_downstream_traceability(
    project_root: str,
    workflow_id: str,
    topics: list[str],
) -> tuple[bool, str]:
    """后续阶段共用的追踪表门禁，不要求测试计划正文结构。"""
    return validate_traceability_structure(project_root, workflow_id, topics)


def validate_test_plan_documents(
    project_root: str,
    workflow_id: str,
    topics: list[str],
) -> tuple[bool, str]:
    """校验测试计划结构，以及每条 AC 到 TC 的覆盖关系。"""
    qa_index = artifact_paths_mod.QA_INDEX_DOC
    index_path = os.path.join(project_root, qa_index)
    if not os.path.isfile(index_path):
        return False, f"{qa_index} 不存在"
    inherited_ok, inherited_detail = validate_inherited_topic_index(
        project_root,
        workflow_id,
        topics,
        qa_index,
        ["展示顺序", "验收主题", "前置主题", "验收计划", "测试计划", "测试结果"],
        {
            "验收计划": "../acceptance/{key}_验收计划.md",
            "测试计划": "./{key}_测试计划.md",
            "测试结果": "./{key}_测试结果.md",
        },
        {"测试结果": {"无自动化测试项"}},
    )
    if not inherited_ok:
        return False, inherited_detail
    index_content = _read_text(project_root, qa_index)
    index_relations = read_topic_index(
        project_root,
        qa_index,
        workflow_id,
        ["展示顺序", "验收主题", "前置主题", "验收计划", "测试计划", "测试结果"],
        {"测试结果": {"无自动化测试项"}},
    )
    relation_by_topic = {relation.topic: relation for relation in index_relations}

    total_criteria = 0
    total_test_items = 0
    for topic in topics:
        paths = topic_paths(project_root, topic)
        acceptance_rel_path = paths["acceptance_plan"]
        test_rel_path = paths["test_plan"]
        test_plan_name = os.path.basename(test_rel_path)
        if test_plan_name not in index_content:
            return False, f"{qa_index} 缺少主题测试计划链接: {test_plan_name}"
        if not os.path.isfile(os.path.join(project_root, acceptance_rel_path)):
            return False, f"缺少上游验收计划: {acceptance_rel_path}"
        if not os.path.isfile(os.path.join(project_root, test_rel_path)):
            return False, f"缺少测试计划文档: {test_rel_path}"

        acceptance_content = _read_text(project_root, acceptance_rel_path)
        test_content = _read_text(project_root, test_rel_path)
        if _field(test_content, "工作流编号") != workflow_id:
            return False, f"{test_rel_path} 的工作流编号与当前工作流不一致"
        for heading in TEST_PLAN_SECTIONS:
            if _section(test_content, heading) is None:
                return False, f"{test_rel_path} 缺少“{heading}”"
        if f"../{acceptance_rel_path}" not in test_content:
            return False, f"{test_rel_path} 缺少上游验收计划链接"
        if f"../{artifact_paths_mod.IMPL_INDEX_DOC}" not in test_content:
            return False, f"{test_rel_path} 缺少下游实施计划链接"
        if re.search(r"测试(?:结果|状态)\s*[：:]\s*(?:通过|失败)", test_content):
            return False, f"{test_rel_path} 不能提前填写测试通过或失败"

        criterion_ids = ACCEPTANCE_CRITERION_RE.findall(acceptance_content)
        if not criterion_ids:
            return False, f"{acceptance_rel_path} 没有可覆盖的验收条件"
        coverage = _section(test_content, "1. 验收条件覆盖") or ""
        try:
            test_items = parse_test_plan_items(project_root, topic)
        except ValueError as exc:
            return False, str(exc)
        test_result_name = os.path.basename(paths["test_result"])
        expected_result_cell = (
            f"./{test_result_name}"
            if any(item.requires_test_code for item in test_items)
            else "无自动化测试项"
        )
        if any(item.requires_test_code for item in test_items):
            if f"./{test_result_name}" not in test_content:
                return False, f"{test_rel_path} 缺少下游测试结果链接"
        elif "无自动化测试结果，转主题验收" not in test_content:
            return False, f"{test_rel_path} 是纯人工验收主题，必须写“无自动化测试结果，转主题验收”"
        actual_result_cell = relation_by_topic[topic].links.get("测试结果")
        if actual_result_cell != expected_result_cell:
            return (
                False,
                f"{qa_index} 主题“{topic}”的测试结果位置应为 {expected_result_cell}",
            )
        for criterion_id in criterion_ids:
            criterion_items = [
                item for item in test_items if item.criterion_id == criterion_id
            ]
            if not criterion_items:
                return False, f"{test_rel_path} 没有覆盖 {criterion_id}"
            criterion_lines = [line for line in coverage.splitlines() if criterion_id in line]
            if not any(f"../{acceptance_rel_path}#" in line for line in criterion_lines):
                return False, f"{test_rel_path} 的 {criterion_id} 没有链接到验收计划具体位置"
        total_criteria += len(criterion_ids)
        total_test_items += len(test_items)

    return (
        True,
        f"测试计划结构完整，{len(topics)} 个主题覆盖 {total_criteria} 条验收条件，包含 {total_test_items} 个测试项",
    )


def _validate_topic_result_file(
    project_root: str,
    rel_path: str,
    workflow_id: str,
    status_label: str,
) -> tuple[bool, str]:
    full_path = os.path.join(project_root, rel_path)
    if not os.path.isfile(full_path):
        return False, f"{rel_path} 不存在"
    content = _read_text(project_root, rel_path)
    if _field(content, "工作流编号") != workflow_id:
        return False, f"{rel_path} 的工作流编号与当前工作流不一致"
    if _field(content, status_label) != "通过":
        return False, f"{rel_path} 必须明确写“{status_label}：通过”"
    return True, ""


def _validate_topic_acceptance_result(
    project_root: str,
    workflow_id: str,
    topic: str,
) -> tuple[bool, str]:
    """校验正式主题验收结果只包含全部通过的当前验收条件。"""
    paths = topic_paths(project_root, topic)
    rel_path = paths["acceptance_result"]
    ok, detail = _validate_topic_result_file(
        project_root,
        rel_path,
        workflow_id,
        "验收结果",
    )
    if not ok:
        return False, detail

    content = _read_text(project_root, rel_path)
    if _field(content, "验收主题") != topic:
        return False, f"{rel_path} 的验收主题必须是“{topic}”"
    if not _has_real_text(_field(content, "验收完成时间")):
        return False, f"{rel_path} 缺少具体验收完成时间"

    for heading in ("1. 验收依据", "2. 验收条件结果", "3. 上下游文档"):
        if not _has_real_text(_section(content, heading)):
            return False, f"{rel_path} 缺少具体“{heading}”"

    state = load_state(project_root)
    if state is None or state.workflow_id != workflow_id:
        return False, f"{rel_path} 找不到当前工作流状态"
    stage_state = state.stages.get("topic_acceptance")
    if stage_state is None:
        return False, "缺少 topic_acceptance（主题验收阶段）状态"

    plan_rel_path = paths["acceptance_plan"]
    if not os.path.isfile(os.path.join(project_root, plan_rel_path)):
        return False, f"{plan_rel_path} 不存在"
    plan_content = _read_text(project_root, plan_rel_path)
    plan_ids = [
        criterion_id
        for criterion_id, _ in _acceptance_criterion_sections(plan_content)
    ]
    result_sections = _acceptance_result_criterion_sections(content)
    result_ids = [criterion_id for criterion_id, _ in result_sections]
    if not plan_ids:
        return False, f"{plan_rel_path} 没有可验收的 AC-xx"
    if result_ids != plan_ids:
        return (
            False,
            f"{rel_path} 的验收条件必须与验收计划完全一致: 计划={plan_ids}, 结果={result_ids}",
        )

    try:
        methods = acceptance_records_mod.criterion_methods(project_root, topic)
    except ValueError as exc:
        return False, str(exc)
    records = stage_state.acceptance_records.get(topic, {})
    valid_methods = acceptance_records_mod.ACCEPTANCE_METHODS
    for criterion_id, criterion_content in result_sections:
        record = records.get(criterion_id)
        if record is None or not acceptance_records_mod.record_is_current(record, state):
            return False, f"{rel_path} 的 {criterion_id} 缺少当前有效的程序验收记录"
        method = _field(criterion_content, "验收方式")
        if method not in valid_methods or method != methods.get(criterion_id):
            return False, f"{rel_path} 的 {criterion_id} 验收方式不合法"
        for label in ("验收条件", "自动化依据", "实际结果", "验收证据", "程序记录"):
            if not _has_real_text(_field(criterion_content, label)):
                return False, f"{rel_path} 的 {criterion_id} 缺少具体“{label}”"
        if _field(criterion_content, "判定") != "通过":
            return False, f"{rel_path} 的 {criterion_id} 必须明确写“判定：通过”"
        if _field(criterion_content, "实际结果") != record.actual_result:
            return False, f"{rel_path} 的 {criterion_id} 实际结果与程序记录不一致"
        if _field(criterion_content, "验收证据") != record.evidence:
            return False, f"{rel_path} 的 {criterion_id} 验收证据与程序记录不一致"
        if _field(criterion_content, "程序记录") != record.record_id:
            return False, f"{rel_path} 的 {criterion_id} 程序记录编号不一致"

        # 自动化或混合条件必须逐项列出作为依据的精确机器测试记录编号
        machine_ids_text = _field(criterion_content, "机器测试记录编号")
        if method == "人工验收":
            if machine_ids_text not in (None, "不适用"):
                return False, f"{rel_path} 的 {criterion_id} 是纯人工验收，机器测试记录编号必须写“不适用”"
        else:
            if not _has_real_text(machine_ids_text):
                return False, f"{rel_path} 的 {criterion_id} 缺少机器测试记录编号"
            expected_machine_ids = set(record.test_record_ids)
            actual_machine_ids = _machine_record_ids(machine_ids_text)
            if actual_machine_ids != expected_machine_ids or not expected_machine_ids:
                missing_ids = sorted(expected_machine_ids - actual_machine_ids)
                extra_ids = sorted(actual_machine_ids - expected_machine_ids)
                return (
                    False,
                    f"{rel_path} 的 {criterion_id} 机器测试记录编号与当前记录不一致："
                    f"缺少={missing_ids}，额外或拼接错误={extra_ids}",
                )

        manual_confirmation = _field(criterion_content, "人工确认")
        if method == "自动化测试":
            if manual_confirmation != "不适用":
                return False, f"{rel_path} 的 {criterion_id} 是纯自动化验收，人工确认必须写“不适用”"
            for label in ("用户实际回答", "确认时间"):
                if _field(criterion_content, label) != "不适用":
                    return False, f"{rel_path} 的 {criterion_id} 的“{label}”必须写“不适用”"
            if not all(test_id in (_field(criterion_content, "自动化依据") or "") for test_id in record.test_ids):
                return False, f"{rel_path} 的 {criterion_id} 缺少对应自动化测试项"
        else:
            if manual_confirmation != "通过":
                return False, f"{rel_path} 的 {criterion_id} 需要人工验收，人工确认必须写“通过”"
            for label in (
                "验收对象",
                "开始前条件",
                "观察内容",
                "预期结果",
                "用户需要回答",
                "用户实际回答",
                "确认时间",
            ):
                if not _has_real_text(_field(criterion_content, label)):
                    return False, f"{rel_path} 的 {criterion_id} 人工验收步骤缺少具体“{label}”"
            if re.search(r"^\s*1\.\s+\S+", criterion_content, re.MULTILINE) is None:
                return False, f"{rel_path} 的 {criterion_id} 人工验收步骤缺少具体操作"
            if _field(criterion_content, "用户实际回答") != record.user_answer:
                return False, f"{rel_path} 的 {criterion_id} 用户回答与程序记录不一致"
            if _field(criterion_content, "确认时间") != record.confirmed_at:
                return False, f"{rel_path} 的 {criterion_id} 确认时间与程序记录不一致"
            automated_basis = _field(criterion_content, "自动化依据") or ""
            if method == "人工验收" and automated_basis != "不适用":
                return False, f"{rel_path} 的 {criterion_id} 是纯人工验收，自动化依据必须写“不适用”"
            if method == "自动化测试 + 人工验收" and not all(
                test_id in automated_basis for test_id in record.test_ids
            ):
                return False, f"{rel_path} 的 {criterion_id} 缺少混合验收使用的自动化测试项"

    required_links = [
        f"./{os.path.basename(paths['acceptance_plan'])}",
        f"../{paths['impl_doc']}",
        f"../{TRACEABILITY_PATH}",
    ]
    if any(method != "人工验收" for method in methods.values()):
        required_links.append(f"../{paths['test_result']}")
    elif "无自动化测试项" not in content:
        return False, f"{rel_path} 是纯人工验收主题，必须明确写“无自动化测试项”"
    for required_link in required_links:
        if required_link not in content:
            return False, f"{rel_path} 缺少上下游链接: {required_link}"
    return True, ""


def _test_result_sections(content: str) -> dict[str, str]:
    result_content = _section(content, "3. 测试项结果")
    if result_content is None:
        return {}
    matches = list(
        re.finditer(
            r"^###\s+(TC-\d{2,})[：:].*$",
            result_content,
            re.MULTILINE,
        )
    )
    sections: dict[str, str] = {}
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(result_content)
        sections[match.group(1)] = result_content[match.end() : end].strip()
    return sections


def _validate_topic_test_execution_result(
    project_root: str,
    workflow_id: str,
    topic: str,
    items,
    tasks,
) -> tuple[bool, str]:
    """主题测试结果必须逐字段引用当前机器记录，不接受手写成功。"""
    rel_path = topic_paths(project_root, topic)["test_result"]
    full_path = os.path.join(project_root, rel_path)
    if not os.path.isfile(full_path):
        return False, f"{rel_path} 不存在"
    content = _read_text(project_root, rel_path)
    if _field(content, "工作流编号") != workflow_id:
        return False, f"{rel_path} 的工作流编号与当前工作流不一致"
    if _field(content, "验收主题") != topic:
        return False, f"{rel_path} 的验收主题必须是“{topic}”"
    if _field(content, "自动化测试结果") != "通过":
        return False, f"{rel_path} 必须明确写“自动化测试结果：通过”"

    all_plan_items = parse_test_plan_items(project_root, topic)
    needs_manual = any(item.test_method != "自动化测试" for item in all_plan_items)
    expected_manual_status = "待主题验收" if needs_manual else "无需人工验收"
    if _field(content, "人工验收状态") != expected_manual_status:
        return False, f"{rel_path} 的人工验收状态必须是“{expected_manual_status}”"
    if needs_manual and _section(content, "4. 人工验收交接") in {None, "", "无需人工验收"}:
        return False, f"{rel_path} 有人工验收内容，但缺少具体人工验收交接"

    sections = _test_result_sections(content)
    expected_ids = {item.test_id for item in items}
    if set(sections) != expected_ids:
        return False, f"{rel_path} 的测试项结果必须正好覆盖 {sorted(expected_ids)}"

    for item in items:
        task = tasks.get(item.test_id)
        if task is None:
            return False, f"{topic} / {item.test_id} 没有登记测试任务"
        record = task.current_record
        if task.status != "passed" or record is None:
            return False, f"{topic} / {item.test_id} 没有当前有效的通过记录"
        if record.status != "passed" or record.exit_code != 0:
            return False, f"{topic} / {item.test_id} 的当前执行记录不是退出码 0 的通过状态"
        if record.command != task.command:
            return False, f"{topic} / {item.test_id} 的执行命令和登记命令不一致"
        if record.test_entries != task.test_entries:
            return False, f"{topic} / {item.test_id} 的执行入口和登记入口不一致"
        if record.cwd != task.cwd:
            return False, f"{topic} / {item.test_id} 的工作目录和登记内容不一致"
        if record.timeout_seconds != task.timeout_seconds:
            return False, f"{topic} / {item.test_id} 的超时时间和登记内容不一致"
        if not record.code_snapshot_hash or not record.test_code_hash:
            return False, f"{topic} / {item.test_id} 的执行记录没有绑定代码快照"
        if not record.record_id:
            return False, f"{topic} / {item.test_id} 的执行记录缺少机器记录编号"
        if record.record_id != _topic_test_record_id(topic, item.test_id, record):
            return False, f"{topic} / {item.test_id} 的机器记录编号与执行事实不一致"
        if (
            isinstance(record.timeout_seconds, bool)
            or not isinstance(record.timeout_seconds, int)
            or record.timeout_seconds <= 0
        ):
            return False, f"{topic} / {item.test_id} 的机器记录超时时间不合法"
        if (
            not isinstance(record.started_at, str)
            or not isinstance(record.finished_at, str)
            or isinstance(record.duration_seconds, bool)
            or not isinstance(record.duration_seconds, (int, float))
            or record.duration_seconds < 0
        ):
            return False, f"{topic} / {item.test_id} 的机器记录时间或时长不完整"
        try:
            record_started_at = datetime.fromisoformat(record.started_at)
            record_finished_at = datetime.fromisoformat(record.finished_at)
        except ValueError:
            return False, f"{topic} / {item.test_id} 的机器记录时间格式不合法"
        if (
            record_started_at.tzinfo is None
            or record_finished_at.tzinfo is None
            or record_finished_at < record_started_at
        ):
            return False, f"{topic} / {item.test_id} 的机器记录时间顺序不合法"
        if not record.platform or not record.executable:
            return False, f"{topic} / {item.test_id} 的机器记录缺少平台或实际可执行文件"
        if not isinstance(record.output_tail, str):
            return False, f"{topic} / {item.test_id} 的机器记录输出摘要不是文本"
        if not isinstance(record.output_sha256, str) or re.fullmatch(
            r"[0-9a-f]{64}",
            record.output_sha256,
        ) is None:
            return False, f"{topic} / {item.test_id} 的机器记录输出哈希不完整"
        if (
            isinstance(record.output_bytes, bool)
            or not isinstance(record.output_bytes, int)
            or record.output_bytes < 0
        ):
            return False, f"{topic} / {item.test_id} 的机器记录输出字节数不合法"

        section = sections[item.test_id]
        if item.criterion_id not in (_field(section, "对应验收条件") or ""):
            return False, f"{rel_path} 的 {item.test_id} 没有对应 {item.criterion_id}"
        # 机器事实统一编码成单行文本，再与正式结果逐字段精确比对。
        checks = [
            ("机器记录编号", record.record_id),
            ("工作目录", record.cwd or "项目根"),
            ("测试入口", _argv_text(record.test_entries)),
            ("执行命令", _argv_text(record.command)),
            ("超时（秒）", record.timeout_seconds),
            ("运行环境", _environment_text(record.platform, record.executable)),
            ("开始时间", record.started_at),
            ("结束时间", record.finished_at),
            ("时长（秒）", record.duration_seconds),
            ("退出码", record.exit_code),
            ("输出摘要", _output_tail_text(record.output_tail)),
            ("输出哈希", record.output_sha256),
            ("输出字节数", record.output_bytes),
            ("产品代码哈希", record.code_snapshot_hash),
            ("测试代码哈希", record.test_code_hash),
        ]
        for label, expected_value in checks:
            actual_value = _field(section, label)
            if expected_value is None or actual_value != str(expected_value):
                return (
                    False,
                    f"{rel_path} 的 {item.test_id} “{label}”与机器记录不一致"
                    f"（记录 {expected_value!r}，文档 {actual_value!r}）",
                )
        if _field(section, "自动化测试结果") != "通过":
            return False, f"{rel_path} 的 {item.test_id} 必须写“自动化测试结果：通过”"
        if not _has_real_text(_field(section, "实际结果")):
            return False, f"{rel_path} 的 {item.test_id} 缺少实际结果"
        if not _has_real_text(_field(section, "证据")):
            return False, f"{rel_path} 的 {item.test_id} 缺少可复核证据"
    return True, ""


def validate_test_execution_results(
    project_root: str,
    workflow_id: str,
    topics: list[str],
) -> tuple[bool, str]:
    """测试执行阶段只校验主题测试结果，不能提前要求主题验收结果。

    只接受当前机器记录；不再保留“只看旧文档通过”的兼容放行。
    """
    failures = []
    try:
        automated = automated_topics(project_root, topics)
        automated_items = automated_test_items(project_root, topics)
    except ValueError as exc:
        return False, str(exc)
    manual_only = [topic for topic in topics if topic not in automated]
    if not automated:
        return True, f"全部主题都没有自动化测试项，直接进入主题验收: {manual_only}"
    state = load_state(project_root)
    if state is None or state.workflow_id != workflow_id:
        return False, "找不到当前工作流的测试执行状态"
    stage_state = state.stages.get("test_execution")
    if stage_state is None:
        return False, "缺少 test_execution（测试执行阶段）状态，正式结果必须来自真实执行记录"
    for topic in automated:
        topic_items = [item for item in automated_items if item.topic == topic]
        test_ok, test_detail = _validate_topic_test_execution_result(
            project_root,
            workflow_id,
            topic,
            topic_items,
            stage_state.test_tasks.get(topic, {}),
        )
        if not test_ok:
            failures.append(test_detail)
    if failures:
        return False, "；".join(failures)
    if manual_only:
        return (
            True,
            f"自动化主题测试结果都明确通过: {automated}；无自动化测试项: {manual_only}",
        )
    return True, f"全部主题测试执行记录和正式结果一致并明确通过: {automated}"


def validate_topic_acceptance_results(
    project_root: str,
    workflow_id: str,
    topics: list[str],
) -> tuple[bool, str]:
    """主题验收阶段只校验主题验收结果，测试前置由调用方先检查。"""
    failures = []
    for topic in topics:
        acceptance_ok, acceptance_detail = _validate_topic_acceptance_result(
            project_root,
            workflow_id,
            topic,
        )
        if not acceptance_ok:
            failures.append(acceptance_detail)
    if failures:
        return False, "；".join(failures)
    return True, f"全部主题验收结果都明确通过: {topics}"


def validate_topic_execution_results(
    project_root: str,
    workflow_id: str,
    topics: list[str],
) -> tuple[bool, str]:
    """兼容旧调用：按新顺序分别校验测试结果和主题验收结果。"""
    test_ok, test_detail = validate_test_execution_results(project_root, workflow_id, topics)
    if not test_ok:
        return False, test_detail
    return validate_topic_acceptance_results(project_root, workflow_id, topics)


def validate_final_regression_state(
    project_root: str,
    workflow_id: str,
) -> tuple[bool, str]:
    """逐字段校验最终全量回归的当前机器事实。"""
    state = load_state(project_root)
    if state is None or state.workflow_id != workflow_id:
        return (False, "找不到当前工作流状态，不能确认最终全量回归")
    result = state.regression_test
    if result.status == "unavailable":
        return (False, "最终全量回归明确失败：当前平台没有可执行的项目全量测试入口")
    if result.status != "passed":
        return (False, f"最终全量回归状态不是通过：{result.status}")
    if result.exit_code != 0:
        return (False, f"最终全量回归退出码不是 0：{result.exit_code}")

    # 入口必须与当前平台登记的项目全量入口一致
    expected_argv, entry_detail = test_runner_mod.resolve_regression_entry(project_root)
    if expected_argv is None:
        return (False, f"当前项目全量测试入口无效：{entry_detail}")
    if list(result.entry or []) != expected_argv:
        return (
            False,
            f"最终全量回归使用的入口 {result.entry} 与当前平台登记入口 {expected_argv} 不一致，"
            "必须重新真实执行",
        )
    if list(result.command or []) != expected_argv:
        return (
            False,
            f"最终全量回归实际命令 {result.command} 与当前平台登记入口 {expected_argv} 不一致",
        )
    if result.cwd != "":
        return (False, "最终全量回归必须在项目根执行")
    if result.timeout_seconds != test_runner_mod.TEST_TIMEOUT_SECONDS:
        return (
            False,
            "最终全量回归超时时间与程序固定值不一致："
            f"{result.timeout_seconds} != {test_runner_mod.TEST_TIMEOUT_SECONDS}",
        )

    if not result.started_at or not result.finished_at:
        return (False, "最终全量回归缺少开始时间或结束时间")
    try:
        started_at = datetime.fromisoformat(result.started_at)
        finished_at = datetime.fromisoformat(result.finished_at)
    except (TypeError, ValueError):
        return (False, "最终全量回归开始时间或结束时间不是合法 ISO 8601 时间")
    if started_at.tzinfo is None or finished_at.tzinfo is None or finished_at < started_at:
        return (False, "最终全量回归时间缺少时区或结束时间早于开始时间")
    if (
        isinstance(result.duration_seconds, bool)
        or not isinstance(result.duration_seconds, (int, float))
        or result.duration_seconds < 0
    ):
        return (False, f"最终全量回归时长不合法：{result.duration_seconds}")

    if not isinstance(result.output_tail, str):
        return (False, "最终全量回归输出摘要不是文本")
    if not isinstance(result.output_sha256, str) or re.fullmatch(
        r"[0-9a-f]{64}",
        result.output_sha256,
    ) is None:
        return (False, "最终全量回归输出哈希不是完整 SHA-256")
    if (
        isinstance(result.output_bytes, bool)
        or not isinstance(result.output_bytes, int)
        or result.output_bytes < 0
    ):
        return (False, f"最终全量回归输出字节数不合法：{result.output_bytes}")
    if result.platform != sys.platform:
        return (
            False,
            f"最终全量回归记录平台 {result.platform!r} 与当前平台 {sys.platform!r} 不一致",
        )
    expected_executable = process_runner_mod.resolve_executable(expected_argv[0])
    if result.executable != expected_executable:
        return (
            False,
            f"最终全量回归实际可执行文件 {result.executable!r} "
            f"与当前入口 {expected_executable!r} 不一致",
        )

    expected_record_id = test_runner_mod.regression_record_id(
        result.started_at,
        result.finished_at,
        result.exit_code,
        result.output_sha256,
        result.command,
    )
    if result.record_id != expected_record_id:
        return (
            False,
            f"最终全量回归机器记录编号不一致：{result.record_id!r} != {expected_record_id!r}",
        )
    if result.code_snapshot_hash != compute_code_snapshot_hash(project_root):
        return (False, "最终全量回归完成后代码又发生变化，必须重新执行全量测试")
    return (
        True,
        f"最终全量测试机器事实完整且匹配当前入口和代码："
        f"{result.command}（机器记录 {result.record_id}）",
    )


def validate_overall_acceptance_prerequisites(
    project_root: str,
    workflow_id: str,
    topics: list[str],
) -> tuple[bool, str]:
    """整体验收只校验前置结果，不读取或要求独立的整体结果文档。"""
    if not topics:
        return (False, "当前工作流没有验收主题，不能进行整体验收")
    test_ok, test_detail = validate_test_execution_results(
        project_root,
        workflow_id,
        topics,
    )
    if not test_ok:
        return (False, f"主题测试尚未全部通过，不能进行整体验收: {test_detail}")

    acceptance_ok, acceptance_detail = validate_topic_acceptance_results(
        project_root,
        workflow_id,
        topics,
    )
    if not acceptance_ok:
        return (False, f"主题验收尚未全部通过，不能进行整体验收: {acceptance_detail}")

    regression_ok, regression_detail = validate_final_regression_state(
        project_root,
        workflow_id,
    )
    if not regression_ok:
        return (False, regression_detail)
    return (True, "全部主题验收和最终全量回归都已明确通过，可以请用户确认整体验收")
