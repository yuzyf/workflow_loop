"""按阶段追加缺陷修复结果，不改写缺陷复现事实。"""

from __future__ import annotations

import re
from pathlib import Path


BUG_DIR = "bug"
BUG_INDEX = "bug/index.md"
WORKFLOW_RE = re.compile(r"^-\s*工作流编号：\s*(.+?)\s*$", re.MULTILINE)
TOPIC_RE = re.compile(r"^-\s*验收主题：\s*(.+?)\s*$", re.MULTILINE)
RESULT_SECTION_RE = re.compile(
    r"^##\s+8\.\s*修复与验收结果\s*$\n(.*?)(?=^##\s+|\Z)",
    re.MULTILINE | re.DOTALL,
)
REGRESSION_WORKFLOW_RE = WORKFLOW_RE
REGRESSION_STATUS_RE = re.compile(r"^-\s*回归状态：\s*(.+?)\s*$", re.MULTILINE)


def _records_for_workflow(project_root: str, workflow_id: str, topics: list[str]):
    bug_dir = Path(project_root) / BUG_DIR
    if not bug_dir.is_dir():
        raise ValueError("bug/ 目录不存在，无法更新缺陷状态")

    records: list[tuple[Path, str]] = []
    for path in sorted(bug_dir.glob("*.md")):
        if path.name == "index.md":
            continue
        content = path.read_text(encoding="utf-8")
        workflow_match = WORKFLOW_RE.search(content)
        topic_match = TOPIC_RE.search(content)
        if (
            workflow_match is not None
            and workflow_match.group(1).strip() == workflow_id
            and topic_match is not None
            and topic_match.group(1).strip() in topics
        ):
            records.append((path, topic_match.group(1).strip()))

    if not records:
        raise ValueError(f"当前工作流没有找到对应验收主题的缺陷记录: {topics}")

    found_topics = [topic for _, topic in records]
    missing = sorted(set(topics) - set(found_topics))
    duplicates = sorted(topic for topic in set(found_topics) if found_topics.count(topic) > 1)
    if missing:
        raise ValueError(f"缺陷记录缺少验收主题: {missing}")
    if duplicates:
        raise ValueError(f"同一工作流有多份缺陷记录使用同一验收主题: {duplicates}")
    return records


def _replace_result_update(content: str, stage_label: str, workflow_id: str, body: str) -> str:
    marker = f"### {stage_label}（工作流 {workflow_id}）"
    block = f"{marker}\n{body.strip()}\n"
    section_match = RESULT_SECTION_RE.search(content)
    if section_match is None:
        separator = "" if content.endswith("\n") else "\n"
        return f"{content}{separator}\n## 8. 修复与验收结果\n\n{block}"

    section = section_match.group(1)
    marker_pattern = re.compile(
        rf"^###\s+{re.escape(stage_label)}（工作流 {re.escape(workflow_id)}）\s*$\n"
        r".*?(?=^###\s+|\Z)",
        re.MULTILINE | re.DOTALL,
    )
    if marker_pattern.search(section):
        section = marker_pattern.sub(block, section, count=1)
    else:
        section = section.rstrip() + "\n\n" + block
    return content[: section_match.start(1)] + section + content[section_match.end(1) :]


def _update_index_status(project_root: str, filename: str, status: str) -> None:
    index_path = Path(project_root) / BUG_INDEX
    if not index_path.is_file():
        raise ValueError("bug/index.md 不存在，无法更新缺陷索引")

    content = index_path.read_text(encoding="utf-8")
    lines = content.splitlines()
    markers = {f"({filename})", f"(./{filename})"}
    found = False
    for index, line in enumerate(lines):
        if not any(marker in line for marker in markers) or not line.strip().startswith("|"):
            continue
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if len(cells) < 2:
            continue
        cells[-1] = status
        lines[index] = "| " + " | ".join(cells) + " |"
        found = True
        break
    if not found:
        raise ValueError(f"bug/index.md 没有链接缺陷记录: {filename}")
    index_path.write_text("\n".join(lines) + ("\n" if content.endswith("\n") else ""), encoding="utf-8")


def update_status(
    project_root: str,
    workflow_id: str,
    topics: list[str],
    *,
    stage_label: str,
    status: str,
    details: list[str],
) -> str:
    """更新当前工作流缺陷记录和 bug 索引，重复执行同一阶段不会重复追加。"""
    records = _records_for_workflow(project_root, workflow_id, topics)
    updated = []
    for path, topic in records:
        topic_details = [detail.replace("{topic}", topic) for detail in details]
        body = "\n".join([f"- 最终状态：{status}", *topic_details])
        content = path.read_text(encoding="utf-8")
        updated_content = _replace_result_update(content, stage_label, workflow_id, body)
        if updated_content != content:
            path.write_text(updated_content, encoding="utf-8")
        _update_index_status(project_root, path.name, status)
        updated.append(path.name)
    return f"已更新缺陷状态“{status}”: {updated}"


def _implementation_record_detail(project_root: str) -> str:
    impl_dir = Path(project_root) / "impl"
    files = sorted(impl_dir.glob("*.md")) if impl_dir.is_dir() else []
    if not files:
        raise ValueError("impl/ 下没有实施记录，无法写入缺陷修复结果")
    links = [f"[{path.name}](../impl/{path.name})" for path in files]
    return "- 实施记录：" + "<br>".join(links)


def record_topic_acceptance_pass(project_root: str, workflow_id: str, topics: list[str]) -> str:
    return update_status(
        project_root,
        workflow_id,
        topics,
        stage_label="主题验收结果",
        status="主题验收通过，待全量回归",
        details=[
            _implementation_record_detail(project_root),
            "- 主题测试结果：[测试结果](../qa/{topic}_result.md)",
            "- 主题验收结果：[验收结果](../acceptance/{topic}_result.md)",
            "- 最终全量回归：待执行",
        ],
    )


def record_regression_failure(project_root: str, workflow_id: str, topics: list[str]) -> str:
    return update_status(
        project_root,
        workflow_id,
        topics,
        stage_label="最终全量回归结果",
        status="回归失败，重新处理中",
        details=[
            "- 回归结果：[最终全量回归](../qa/final_regression_result.md)",
            "- 处理要求：修复后重新执行主题执行、最终全量回归和整体验收",
        ],
    )


def has_explicit_regression_failure(project_root: str, workflow_id: str) -> bool:
    path = Path(project_root) / "qa" / "final_regression_result.md"
    if not path.is_file():
        return False
    content = path.read_text(encoding="utf-8")
    workflow_match = REGRESSION_WORKFLOW_RE.search(content)
    status_match = REGRESSION_STATUS_RE.search(content)
    return (
        workflow_match is not None
        and workflow_match.group(1).strip() == workflow_id
        and status_match is not None
        and status_match.group(1).strip() == "失败"
    )


def record_overall_acceptance_pass(project_root: str, workflow_id: str, topics: list[str]) -> str:
    return update_status(
        project_root,
        workflow_id,
        topics,
        stage_label="整体验收确认",
        status="已修复并验收",
        details=[
            "- 最终全量回归：[回归结果](../qa/final_regression_result.md)",
            "- 整体验收：用户已确认",
        ],
    )
