import os
import re

from .state import load_state
from .traceability import validate_structure as validate_traceability_structure
from .verification import compute_file_hashes


PROJECT_INIT_EVIDENCE_PATH = os.path.join("spec", "project_design_init_evidence.md")
TRACEABILITY_PATH = "traceability.md"
FINAL_REGRESSION_RESULT_PATH = os.path.join("qa", "final_regression_result.md")
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
TEST_ITEM_LINK_RE = re.compile(
    r"\[(TC-\d{2,})\s+([^\]]+)\]\(#(tc-\d{2,})\)"
)
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

        criterion_ids = ACCEPTANCE_CRITERION_RE.findall(content)
        if not criterion_ids:
            return (False, f"{rel_path} 至少需要一条 AC-01 形式的验收条件")
        if len(criterion_ids) != len(set(criterion_ids)):
            return (False, f"{rel_path} 存在重复验收条件编号")
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
    index_content = _read_text(project_root, os.path.join("qa", "index.md"))
    index_links = set(re.findall(r"\[[^\]]+\]\((?:\./)?([^)]*_plan\.md)\)", index_content))

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
        if "../plan/index.md" not in test_content:
            return False, f"{test_rel_path} 缺少下游实施计划链接"
        if f"./{topic}_result.md" not in test_content:
            return False, f"{test_rel_path} 缺少下游测试结果链接"
        if re.search(r"测试(?:结果|状态)\s*[：:]\s*(?:通过|失败)", test_content):
            return False, f"{test_rel_path} 不能提前填写测试通过或失败"

        criterion_ids = ACCEPTANCE_CRITERION_RE.findall(acceptance_content)
        if not criterion_ids:
            return False, f"{acceptance_rel_path} 没有可覆盖的验收条件"
        coverage = _section(test_content, "1. 验收条件覆盖") or ""
        for column in ("验收条件链接", "测试项", "验证方向", "预期观察结果", "证据要求"):
            if column not in coverage:
                return False, f"{test_rel_path} 的验收条件覆盖缺少“{column}”列"
        test_items = TEST_ITEM_LINK_RE.findall(coverage)
        if not test_items:
            return False, f"{test_rel_path} 没有带编号、名称和锚点的测试项"
        for test_id, test_name, anchor_id in test_items:
            if test_id.lower() != anchor_id.lower():
                return False, f"{test_rel_path} 的测试项 {test_id} 锚点必须是 #{test_id.lower()}"
            if not _has_real_text(test_name):
                return False, f"{test_rel_path} 的测试项 {test_id} 缺少直白名称"
            if f'id="{anchor_id.lower()}"' not in coverage:
                return False, f"{test_rel_path} 的测试项 {test_id} 缺少可跳转锚点"
        for criterion_id in criterion_ids:
            criterion_lines = [
                line for line in coverage.splitlines()
                if criterion_id in line
            ]
            if not criterion_lines:
                return False, f"{test_rel_path} 没有覆盖 {criterion_id}"
            if not any(
                f"../acceptance/{topic}_plan.md#" in line
                for line in criterion_lines
            ):
                return False, f"{test_rel_path} 的 {criterion_id} 没有链接到验收计划具体位置"
            if not any(TEST_ITEM_LINK_RE.search(line) for line in criterion_lines):
                return False, f"{test_rel_path} 的 {criterion_id} 没有关联测试项"
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


def validate_topic_execution_results(
    project_root: str,
    workflow_id: str,
    topics: list[str],
) -> tuple[bool, str]:
    """主题执行阶段必须同时留下通过的测试结果和主题验收结果。"""
    failures = []
    for topic in topics:
        test_ok, test_detail = _validate_topic_result_file(
            project_root,
            os.path.join("qa", f"{topic}_result.md"),
            workflow_id,
            "测试结果",
        )
        acceptance_ok, acceptance_detail = _validate_topic_result_file(
            project_root,
            os.path.join("acceptance", f"{topic}_result.md"),
            workflow_id,
            "验收结果",
        )
        if not test_ok:
            failures.append(test_detail)
        if not acceptance_ok:
            failures.append(acceptance_detail)
    if failures:
        return False, "；".join(failures)
    return True, f"全部主题测试结果和主题验收结果都明确通过: {topics}"


def validate_final_regression_result(
    project_root: str,
    workflow_id: str,
) -> tuple[bool, str]:
    """最终全量回归只有明确记录当前工作流通过时才能过门禁。"""
    full_path = os.path.join(project_root, FINAL_REGRESSION_RESULT_PATH)
    if not os.path.isfile(full_path):
        return (False, f"{FINAL_REGRESSION_RESULT_PATH} 不存在")

    content = _read_text(project_root, FINAL_REGRESSION_RESULT_PATH)
    if _field(content, "工作流编号") != workflow_id:
        return (False, "最终全量回归结果中的工作流编号与当前工作流不一致")

    status = _field(content, "回归状态")
    if status != "通过":
        return (
            False,
            "最终全量回归没有明确写“回归状态：通过”，不能进入整体验收",
        )
    return (True, "最终全量回归已明确通过")


def validate_overall_acceptance_prerequisites(
    project_root: str,
    workflow_id: str,
    topics: list[str],
) -> tuple[bool, str]:
    """整体验收只校验前置结果，不读取或要求独立的整体结果文档。"""
    if not topics:
        return (False, "当前工作流没有验收主题，不能进行整体验收")
    topic_ok, topic_detail = validate_topic_execution_results(
        project_root,
        workflow_id,
        topics,
    )
    if not topic_ok:
        return (False, f"主题验收尚未全部通过，不能进行整体验收: {topic_detail}")

    regression_ok, regression_detail = validate_final_regression_result(
        project_root,
        workflow_id,
    )
    if not regression_ok:
        return (False, regression_detail)
    return (True, "全部主题验收和最终全量回归都已明确通过，可以请用户确认整体验收")
