import os
import re
import shlex

from . import acceptance_records as acceptance_records_mod
from .state import load_state
from .test_mapping import (
    automated_topics,
    automated_test_items,
    parse_test_plan_items,
)
from .traceability import validate_structure as validate_traceability_structure
from .topic_relations import relation_signature, read_topic_index
from .verification import compute_code_snapshot_hash, compute_file_hashes


PROJECT_INIT_EVIDENCE_PATH = os.path.join("spec", "project_design_init_evidence.md")
TRACEABILITY_PATH = "traceability.md"
BUG_FILENAME_RE = re.compile(r"^\d{4}-\d{2}-\d{2}_\d{4}-.+\.md$")
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
CODE_SUFFIXES = {
    ".c", ".cc", ".cpp", ".cxx", ".h", ".hpp", ".java", ".kt", ".kts",
    ".py", ".pyi", ".go", ".rs", ".swift", ".m", ".mm", ".js", ".jsx",
    ".ts", ".tsx", ".vue", ".svelte", ".rb", ".php", ".cs", ".fs", ".ets",
}


def _read_text(project_root: str, rel_path: str) -> str:
    with open(os.path.join(project_root, rel_path), "r", encoding="utf-8") as f:
        return f.read()


def _field(content: str, label: str) -> str | None:
    match = re.search(rf"^-\s*{re.escape(label)}：\s*(.+?)\s*$", content, re.MULTILINE)
    return match.group(1).strip() if match else None


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
    """主题会进入文件名和路径，不能包含路径分隔符或目录跳转。"""
    if not _has_real_text(value):
        return False
    normalized = value.strip()
    return normalized not in {".", ".."} and os.path.basename(normalized) == normalized


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


def validate_reproduce_documents(
    project_root: str,
    changed_paths: list[str],
    workflow_id: str,
) -> tuple[bool, str]:
    index_path = os.path.join("bug", "index.md")
    if index_path not in changed_paths:
        return (False, "bug/index.md 没有在本阶段更新")
    if not os.path.isfile(os.path.join(project_root, index_path)):
        return (False, "bug/index.md 不存在")

    changed_bug_docs = [
        rel_path
        for rel_path in changed_paths
        if rel_path.startswith(f"bug{os.sep}")
        and rel_path != index_path
        and os.path.isfile(os.path.join(project_root, rel_path))
        and rel_path.endswith(".md")
    ]
    if not changed_bug_docs:
        return (False, "本阶段没有新增或修改 bug 记录文档")

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
            return (False, f"bug 记录文件名不符合 YYYY-MM-DD_HHmm-<bug描述>.md: {filename}")
        if not re.search(rf"\((?:\./)?{re.escape(filename)}\)", index_content):
            return (False, f"bug/index.md 没有链接本次 bug 记录: {filename}")

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
        f"本阶段 bug 记录已复现、确认根因并确定验收主题: {dict(zip(changed_bug_docs, topics))}",
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
        rel_path = os.path.join("acceptance", f"{topic}_plan.md")
        full_path = os.path.join(project_root, rel_path)
        if not os.path.isfile(full_path):
            return (False, f"缺少验收计划文档: {rel_path}")

        content = _read_text(project_root, rel_path)
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
        if "../traceability.md" not in content:
            return (False, f"{rel_path} 的上下游文档没有链接 ../traceability.md")
        if f"../qa/{topic}_plan.md" not in content:
            return (False, f"{rel_path} 没有写下游测试计划路径 qa/{topic}_plan.md")

        for criterion_id in criterion_ids:
            expected_topic_path = f"acceptance/{topic}_plan.md"
            matching_rows = [
                row
                for row in traceability_rows
                if expected_topic_path in row[1] and criterion_id in row[2]
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
    """校验主题索引的主题集合、顺序、链接和前置关系。"""

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
        for header, path_template in expected_links.items():
            expected_path = path_template.format(topic=relation.topic)
            if relation.links.get(header) != expected_path:
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
        os.path.join("acceptance", "index.md"),
        ["展示顺序", "验收主题", "前置主题", "验收计划", "主题验收结果"],
        {
            "验收计划": "./{topic}_plan.md",
            "主题验收结果": "./{topic}_result.md",
        },
    )
    return ok, detail or "acceptance/index.md 结构完整"


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
        os.path.join("acceptance", "index.md"),
        ["展示顺序", "验收主题", "前置主题", "验收计划", "主题验收结果"],
        {
            "验收计划": "./{topic}_plan.md",
            "主题验收结果": "./{topic}_result.md",
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
        return False, f"{relative_path} 的主题关系没有继承 acceptance/index.md"
    return True, f"{relative_path} 已继承 acceptance/index.md 的主题关系"


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
    index_path = os.path.join(project_root, "qa", "index.md")
    if not os.path.isfile(index_path):
        return False, "qa/index.md 不存在"
    inherited_ok, inherited_detail = validate_inherited_topic_index(
        project_root,
        workflow_id,
        topics,
        os.path.join("qa", "index.md"),
        ["展示顺序", "验收主题", "前置主题", "验收计划", "测试计划", "测试结果"],
        {
            "验收计划": "../acceptance/{topic}_plan.md",
            "测试计划": "./{topic}_plan.md",
        },
        {"测试结果": {"无自动化测试项"}},
    )
    if not inherited_ok:
        return False, inherited_detail
    index_content = _read_text(project_root, os.path.join("qa", "index.md"))
    index_links = set(re.findall(r"\[[^\]]+\]\((?:\./)?([^)]*_plan\.md)\)", index_content))
    index_relations = read_topic_index(
        project_root,
        os.path.join("qa", "index.md"),
        workflow_id,
        ["展示顺序", "验收主题", "前置主题", "验收计划", "测试计划", "测试结果"],
        {"测试结果": {"无自动化测试项"}},
    )
    relation_by_topic = {relation.topic: relation for relation in index_relations}

    total_criteria = 0
    total_test_items = 0
    for topic in topics:
        acceptance_rel_path = os.path.join("acceptance", f"{topic}_plan.md")
        test_rel_path = os.path.join("qa", f"{topic}_plan.md")
        if f"{topic}_plan.md" not in index_links:
            return False, f"qa/index.md 缺少主题测试计划链接: {topic}_plan.md"
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
        if f"../acceptance/{topic}_plan.md" not in test_content:
            return False, f"{test_rel_path} 缺少上游验收计划链接"
        if "../impl/index.md" not in test_content:
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
        expected_result_cell = (
            f"./{topic}_result.md"
            if any(item.requires_test_code for item in test_items)
            else "无自动化测试项"
        )
        if any(item.requires_test_code for item in test_items):
            if f"./{topic}_result.md" not in test_content:
                return False, f"{test_rel_path} 缺少下游测试结果链接"
        elif "无自动化测试结果，转主题验收" not in test_content:
            return False, f"{test_rel_path} 是纯人工验收主题，必须写“无自动化测试结果，转主题验收”"
        actual_result_cell = relation_by_topic[topic].links.get("测试结果")
        if actual_result_cell != expected_result_cell:
            return (
                False,
                f"qa/index.md 主题“{topic}”的测试结果位置应为 {expected_result_cell}",
            )
        for criterion_id in criterion_ids:
            criterion_items = [
                item for item in test_items if item.criterion_id == criterion_id
            ]
            if not criterion_items:
                return False, f"{test_rel_path} 没有覆盖 {criterion_id}"
            criterion_lines = [line for line in coverage.splitlines() if criterion_id in line]
            if not any(f"../acceptance/{topic}_plan.md#" in line for line in criterion_lines):
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
    rel_path = os.path.join("acceptance", f"{topic}_result.md")
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

    plan_rel_path = os.path.join("acceptance", f"{topic}_plan.md")
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
        f"./{topic}_plan.md",
        f"../impl/{topic}.md",
        "../traceability.md",
    ]
    if any(method != "人工验收" for method in methods.values()):
        required_links.append(f"../qa/{topic}_result.md")
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
    rel_path = os.path.join("qa", f"{topic}_result.md")
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
        if set(record.test_entries) != set(task.test_entries):
            return False, f"{topic} / {item.test_id} 的执行入口和登记入口不一致"
        if not record.code_snapshot_hash or not record.test_code_hash:
            return False, f"{topic} / {item.test_id} 的执行记录没有绑定代码快照"

        section = sections[item.test_id]
        if item.criterion_id not in (_field(section, "对应验收条件") or ""):
            return False, f"{rel_path} 的 {item.test_id} 没有对应 {item.criterion_id}"
        if _field(section, "退出码") != "0":
            return False, f"{rel_path} 的 {item.test_id} 必须写真实退出码 0"
        if _field(section, "自动化测试结果") != "通过":
            return False, f"{rel_path} 的 {item.test_id} 必须写“自动化测试结果：通过”"
        command_text = _field(section, "执行命令") or ""
        if command_text != shlex.join(task.command):
            return False, f"{rel_path} 的 {item.test_id} 执行命令与程序记录不一致"
        entry_text = _field(section, "测试入口") or ""
        missing_entries = [entry for entry in task.test_entries if entry not in entry_text]
        if missing_entries:
            return False, f"{rel_path} 的 {item.test_id} 缺少测试入口: {missing_entries}"
        if not _field(section, "实际结果"):
            return False, f"{rel_path} 的 {item.test_id} 缺少实际结果"
        if not _field(section, "证据"):
            return False, f"{rel_path} 的 {item.test_id} 缺少可复核证据"
    return True, ""


def validate_test_execution_results(
    project_root: str,
    workflow_id: str,
    topics: list[str],
) -> tuple[bool, str]:
    """测试执行阶段只校验主题测试结果，不能提前要求主题验收结果。"""
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
        # 兼容旧的单元测试夹具和旧工作流快照；新的 test_execution 状态一旦存在，
        # 必须严格检查当前执行记录，不能再只看文档里的“通过”。
        compatibility_failures = []
        for topic in automated:
            compatibility_ok, compatibility_detail = _validate_topic_result_file(
                project_root,
                os.path.join("qa", f"{topic}_result.md"),
                workflow_id,
                "测试结果",
            )
            if not compatibility_ok:
                compatibility_failures.append(compatibility_detail)
        if compatibility_failures:
            return False, "；".join(compatibility_failures)
        return True, f"兼容旧状态：主题测试结果都明确通过: {automated}"
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
    """最终全量回归只接受程序实际执行统一测试入口后的通过状态。"""
    state = load_state(project_root)
    if state is None or state.workflow_id != workflow_id:
        return (False, "找不到当前工作流状态，不能确认最终全量回归")
    result = state.regression_test
    if result.status != "passed":
        return (False, f"最终全量回归状态不是通过：{result.status}")
    if result.code_snapshot_hash != compute_code_snapshot_hash(project_root):
        return (False, "最终全量回归完成后代码又发生变化，必须重新执行全量测试")
    return (True, f"最终全量测试已通过统一入口：{result.command}")


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
