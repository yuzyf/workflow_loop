import os
import re

from .state import load_state
from .verification import compute_file_hashes


PROJECT_INIT_EVIDENCE_PATH = os.path.join("spec", "project_design_init_evidence.md")
BUG_FILENAME_RE = re.compile(r"^\d{4}-\d{2}-\d{2}_\d{4}-.+\.md$")
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

    return (True, f"本阶段 bug 记录已复现并确认根因: {changed_bug_docs}")
