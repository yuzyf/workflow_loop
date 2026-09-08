"""由最终同步事实准备正式架构；定位、冲突和证据检查全部先于写文件。"""

from __future__ import annotations

import hashlib
import re

from markdown_it import MarkdownIt

from . import acceptance_records
from . import artifact_validation
from . import state as state_mod


SYNC_HEADING = "9. 最终同步结论"
SYNC_FIELDS = {
    "产品设计核对": "一致",
    "功能文档核对": "一致",
    "代码实现核对": "一致",
    "功能到代码映射": "完整",
    "未处理差异": "暂无",
}
CHECKS_START = "<!-- workflow-loop:design-sync-checks:start -->"
CHECKS_END = "<!-- workflow-loop:design-sync-checks:end -->"


def _digest(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def _headings(content: str) -> list[tuple[str, int, int, int]]:
    tokens = MarkdownIt("commonmark").enable("table").parse(content)
    offsets = [0]
    for line in content.splitlines(keepends=True):
        offsets.append(offsets[-1] + len(line))
    return [
        (tokens[index + 1].content, int(token.tag[1:]), offsets[token.map[0]], offsets[token.map[1]])
        for index, token in enumerate(tokens)
        if token.type == "heading_open" and token.map is not None
    ]


def _section_bounds(content: str, heading: str) -> tuple[int, int]:
    headings = _headings(content)
    found = [index for index, item in enumerate(headings) if item[0] == heading]
    if len(found) != 1:
        raise ValueError(f"架构章节「{heading}」必须唯一存在，实际匹配 {len(found)} 处")
    index = found[0]
    _, level, _, start = headings[index]
    end = next((item[2] for item in headings[index + 1:] if item[1] <= level), len(content))
    return start, end


def _structure(content: str) -> list[tuple[str, str]]:
    tokens = MarkdownIt("commonmark").enable("table").parse(content)
    structure = []
    for index, token in enumerate(tokens):
        if token.type == "heading_open":
            structure.append((token.tag, tokens[index + 1].content))
        elif token.type.startswith(("table_", "thead_", "tbody_", "tr_", "th_", "td_")):
            structure.append((token.type, ""))
        elif token.type in {"fence", "code_block"}:
            structure.append((token.type, token.info))
        if token.type in {"html_inline", "html_block"} and "<a " in token.content:
            structure.append((token.type, token.content))
        for child in token.children or []:
            if child.type == "html_inline" and "<a " in child.content:
                structure.append((child.type, child.content))
    return structure


def _apply_body_changes(baseline: str, changes: dict | None) -> str:
    replacements: list[tuple[int, int, str]] = []
    sync_start, sync_end = _section_bounds(baseline, SYNC_HEADING)
    for index, row in enumerate((changes or {}).get("正文变更", []), 1):
        location = f"架构正文变更表第 {index} 行"
        if any(not isinstance(row.get(key), str) or not row[key].strip() for key in ("章节", "原文", "新文", "依据")):
            raise ValueError(f"{location} 必须填写章节、原文、新文和可复核依据")
        start, end = _section_bounds(baseline, row["章节"])
        if start < sync_end and end > sync_start:
            raise ValueError(f"{location} 不能修改最终同步固定字段；这些字段由同步结论表和当前状态生成")
        old = row["原文"]
        region = baseline[start:end]
        if region.count(old) != 1:
            raise ValueError(f"{location} 在章节「{row['章节']}」的原文必须唯一匹配，实际匹配 {region.count(old)} 处；保留正式架构")
        begin = start + region.index(old)
        finish = begin + len(old)
        if any(begin < previous_end and finish > previous_start for previous_start, previous_end, _ in replacements):
            raise ValueError(f"{location} 与其他正文变更位置重叠，不能确定事实来源")
        replacements.append((begin, finish, row["新文"]))
    content = baseline
    for start, end, replacement in sorted(replacements, reverse=True):
        content = content[:start] + replacement + content[end:]
    if _structure(content) != _structure(baseline):
        raise ValueError("架构正文变更不能改变原有标题、表格结构、代码块或定位锚点；请只修改对应事实")
    return content


def _sync_conclusions(table: dict) -> dict[str, str]:
    rows = table.get("核对项", [])
    for index, row in enumerate(rows, 1):
        if any(not isinstance(row.get(key), str) for key in ("核对项", "核对结论", "设计影响", "代码影响")):
            raise ValueError(f"最终同步表核对项第 {index} 行必须填写文字，不能填数组或对象")
    conclusions = {row["核对项"]: row["核对结论"] for row in rows}
    errors = []
    for label, expected in SYNC_FIELDS.items():
        if conclusions.get(label) != expected:
            errors.append(f"核对项「{label}」必须为「{expected}」，实际为「{conclusions.get(label, '缺少')}」")
    if conclusions.get("本次同步类型") not in {"架构变化", "架构未变化"}:
        errors.append("核对项「本次同步类型」必须为「架构变化」或「架构未变化」")
    allowed = set(SYNC_FIELDS) | {"本次同步类型"}
    for row in rows:
        if row["核对项"] not in allowed:
            errors.append(f"未知核对项「{row['核对项']}」；补充依据请写入同步说明")
        if row["设计影响"] not in {"需要修改", "无需修改"}:
            errors.append(f"核对项「{row['核对项']}」的设计影响必须为需要修改或无需修改")
        if row["代码影响"] != "无需修改":
            errors.append(f"核对项「{row['核对项']}」仍有代码影响；先返回实施，不得生成已完成结论")
    if not table.get("同步说明") or any(not isinstance(item, str) or not item.strip() for item in table["同步说明"]):
        errors.append("同步说明必须填写本轮实际核对依据")
    if errors:
        raise ValueError("；".join(errors))
    return conclusions


def _replace_sync_fields(content: str, fields: dict[str, str], table: dict) -> str:
    from .records import _md_cell

    start, end = _section_bounds(content, SYNC_HEADING)
    section = content[start:end]
    for label, value in fields.items():
        pattern = re.compile(rf"^[ \t]*(?:[-*][ \t]+)?{re.escape(label)}[：:][^\r\n]*", re.MULTILINE)
        matches = list(pattern.finditer(section))
        if len(matches) > 1:
            raise ValueError(f"正式架构第九章的「{label}」重复，不能确定应更新哪一处")
        line = f"- {label}：{value}"
        if matches:
            section = pattern.sub(lambda _: line, section, count=1)
        else:
            section = section.rstrip() + "\n" + line + "\n"
    block = [CHECKS_START, "| 核对项 | 核对结论 | 设计影响 | 代码影响 |", "|---|---|---|---|"]
    for row in table["核对项"]:
        block.append("| " + " | ".join(_md_cell(row[key]) for key in ("核对项", "核对结论", "设计影响", "代码影响")) + " |")
    block.append(CHECKS_END)
    rendered = "\n".join(block)
    if CHECKS_START in section or CHECKS_END in section:
        if section.count(CHECKS_START) != 1 or section.count(CHECKS_END) != 1 or section.index(CHECKS_START) > section.index(CHECKS_END):
            raise ValueError("最终同步核对清单边界损坏，保留正式架构")
        before, _, rest = section.partition(CHECKS_START)
        _, _, after = rest.partition(CHECKS_END)
        section = before + rendered + after
    else:
        section = section.rstrip() + "\n\n" + rendered + "\n"
    return content[:start] + section + content[end:]


def prepare_design_sync(
    project_root: str,
    wf_state: state_mod.WorkflowState,
    table: dict,
    changes: dict | None,
    current_content: str,
    previous: dict | None = None,
) -> tuple[str, dict]:
    """返回候选正文和生成基准；失败抛 ValueError，不写文档、表、凭据或状态。"""
    conclusions = _sync_conclusions(table)
    if not current_content.strip():
        raise ValueError("正式架构正文基准不存在；不能仅凭同步结论编造架构正文")
    if wf_state.current_stage != "update_code_design":
        raise ValueError("只有最终代码设计同步阶段可以生成正式架构")
    for name in ("topic_acceptance", "regression_test", "overall_acceptance"):
        stage = wf_state.stages.get(name)
        if stage is None or stage.status != "done" or not stage.gate.user_confirmed:
            raise ValueError(f"{name}（最终同步的前置阶段）尚未完成确认，不能生成完成结论")
    if not wf_state.topics:
        raise ValueError("本轮没有已验收主题，不能生成完成结论")
    for topic in wf_state.topics:
        if not acceptance_records.topic_records_complete(project_root, wf_state, topic):
            raise ValueError(f"主题「{topic}」缺少覆盖全部验收条件的当前有效记录")
    regression_ok, detail = artifact_validation.validate_final_regression_state(project_root, wf_state.workflow_id)
    if not regression_ok:
        raise ValueError(f"最终全量回归证据不可用：{detail}")
    record_ids, detail = artifact_validation._required_final_machine_record_ids(wf_state)
    if record_ids is None:
        raise ValueError(detail)

    if previous is not None:
        baseline = previous.get("base_content")
        if not isinstance(baseline, str) or previous.get("base_hash") != _digest(baseline):
            raise ValueError("正式架构生成基准损坏，不能从当前正文重建基准掩盖冲突")
    else:
        baseline = current_content
    content = _apply_body_changes(baseline, changes)
    basis = "；".join(item.replace("\r\n", " ").replace("\n", " ") for item in table["同步说明"])
    fields = {
        "工作流编号": wf_state.workflow_id,
        "本次同步类型": conclusions["本次同步类型"],
        **{label: conclusions[label] for label in SYNC_FIELDS},
        "核对依据": f"{basis}；当前有效机器记录：{'、'.join(sorted(record_ids))}",
    }
    content = _replace_sync_fields(content, fields, table)
    if previous is not None and _digest(current_content) not in {previous.get("generated_hash"), _digest(content)}:
        raise ValueError("正式架构在上次生成后被直接修改；保留手改正文，请把改动写回正文变更表，且原文仍须对应首次生成基准")
    valid, detail = artifact_validation.validate_final_code_design_document(
        project_root, wf_state.workflow_id, candidate_content=content,
    )
    if not valid:
        raise ValueError(detail)
    return content, {"base_content": baseline, "base_hash": _digest(baseline), "generated_hash": _digest(content)}
