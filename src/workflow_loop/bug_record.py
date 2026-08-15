"""按阶段追加缺陷修复结果，不改写缺陷复现事实。"""

from __future__ import annotations

import re
from pathlib import Path

from . import artifact_paths as artifact_paths_mod
from .state import load_state
from .topic import topic_paths


BUG_DIR = "bug"
BUG_INDEX = artifact_paths_mod.BUG_INDEX_DOC
# 固定字段的空白只允许在同一行；``\s*`` 会吞掉换行，导致下一字段被误读。
WORKFLOW_RE = re.compile(r"^-[ \t]*工作流编号：[ \t]*([^\r\n]+?)[ \t]*$", re.MULTILINE)
TOPIC_RE = re.compile(r"^-[ \t]*验收主题：[ \t]*([^\r\n]+?)[ \t]*$", re.MULTILINE)
RESULT_SECTION_RE = re.compile(
    r"^##\s+8\.\s*修复与验收结果\s*$\n(.*?)(?=^##\s+|\Z)",
    re.MULTILINE | re.DOTALL,
)
# 索引文件不是缺陷记录正文
INDEX_FILENAMES = {"索引.md"}


def _records_for_workflow(project_root: str, workflow_id: str, topics: list[str]):
    bug_dir = Path(project_root) / BUG_DIR
    if not bug_dir.is_dir():
        raise ValueError("bug/ 目录不存在，无法更新缺陷状态")

    records: list[tuple[Path, str]] = []
    for path in sorted(bug_dir.glob("*.md")):
        if path.name in INDEX_FILENAMES:
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
        raise ValueError(f"{BUG_INDEX} 不存在，无法更新缺陷索引")

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
        raise ValueError(f"{BUG_INDEX} 没有链接缺陷记录: {filename}")
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
    """更新当前工作流缺陷记录和缺陷索引，重复执行同一阶段不会重复追加。

    details 中的 {topic_test_result} 和 {topic_acceptance_result} 会替换为该主题的
    中文正式结果路径；始终只追加结论，不改写原始复现条件、实际结果、期望和根因。
    """
    records = _records_for_workflow(project_root, workflow_id, topics)
    updated = []
    for path, topic in records:
        paths = topic_paths(project_root, topic)
        topic_details = [
            detail
            .replace("{topic_test_result}", f"../{paths['test_result']}")
            .replace("{topic_acceptance_result}", f"../{paths['acceptance_result']}")
            .replace("{topic_impl_doc}", f"../{paths['impl_doc']}")
            for detail in details
        ]
        body = "\n".join([f"- 最终状态：{status}", *topic_details])
        content = path.read_text(encoding="utf-8")
        updated_content = _replace_result_update(content, stage_label, workflow_id, body)
        if updated_content != content:
            path.write_text(updated_content, encoding="utf-8")
        _update_index_status(project_root, path.name, status)
        updated.append(path.name)
    return f"已更新缺陷状态“{status}”: {updated}"


def record_topic_acceptance_pass(project_root: str, workflow_id: str, topics: list[str]) -> str:
    return update_status(
        project_root,
        workflow_id,
        topics,
        stage_label="主题验收结果",
        status="主题验收通过，待全量回归",
        details=[
            "- 实施记录：[实施记录]({topic_impl_doc})",
            "- 主题测试结果：[测试结果]({topic_test_result})",
            "- 主题验收结果：[验收结果]({topic_acceptance_result})",
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
            "- 回归结果：统一测试入口执行失败、超时或无法启动，详情见当前工作流 state.json 和 journal",
            "- 处理要求：修复后重新执行测试代码、主题测试、主题验收、最终全量回归和整体验收",
        ],
    )


def record_regression_pass(project_root: str, workflow_id: str, topics: list[str]) -> str:
    return update_status(
        project_root,
        workflow_id,
        topics,
        stage_label="最终全量回归结果",
        status="全量回归通过，待整体验收",
        details=[
            "- 回归结果：统一测试入口执行通过，详情见当前工作流 state.json 和 journal",
            "- 后续处理：等待用户进行整体验收",
        ],
    )


def has_explicit_regression_failure(project_root: str, workflow_id: str) -> bool:
    """执行失败、超时和无法启动都算未通过，不只有退出码非零一种情况。"""
    state = load_state(project_root)
    return (
        state is not None
        and state.workflow_id == workflow_id
        and state.regression_test.status in ("failed", "timeout", "error", "unavailable")
    )


def record_overall_acceptance_pass(project_root: str, workflow_id: str, topics: list[str]) -> str:
    return update_status(
        project_root,
        workflow_id,
        topics,
        stage_label="整体验收确认",
        status="已修复并验收",
        details=[
            "- 最终全量回归：统一测试入口已通过，详情见当前工作流 state.json 和 journal",
            "- 整体验收：用户已确认",
        ],
    )
