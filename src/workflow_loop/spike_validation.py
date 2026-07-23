import os
import re
from dataclasses import dataclass

from . import state as state_mod
from . import verification as verification_mod


FIELD_RE = re.compile(r"^- ([^：\n]+)：\s*(.*)$")
INDEX_ITEM_RE = re.compile(r"^## (SP-\d{3})\s+(.+?)\s*$")
DETAIL_SECTION_RE = re.compile(r"^## ([1-8])\.\s+(.+?)\s*$")
MARKDOWN_LINK_RE = re.compile(r"\[[^\]]+\]\(([^)]+)\)")
PLACEHOLDER_RE = re.compile(r"<[^>\n]+>")

INDEX_REQUIRED_FIELDS = [
    "真实场景",
    "要验证的不确定性",
    "验证结果用于决定什么",
    "结论文档",
    "穿刺状态",
    "是否阻塞后续",
    "产品设计影响",
    "代码设计影响",
    "后续处理阶段",
]

EXPECTED_DETAIL_SECTIONS = {
    "1": "真实场景与不确定性",
    "2": "验证结果用于决定什么",
    "3": "已知事实与验证范围",
    "4": "验证方法",
    "5": "实际执行记录",
    "6": "实际观察结果",
    "7": "结论",
    "8": "对后续工作的影响",
}

METHOD_FIELDS = ["使用的方法", "临时内容位置", "执行步骤", "外部影响"]
EXECUTION_FIELDS = ["执行时间", "运行环境", "实际命令", "真实输入或样本", "执行失败"]
RESULT_FIELDS = ["结果状态", "是否阻塞后续", "已确认内容", "仍未确认内容"]
IMPACT_FIELDS = [
    "产品设计影响",
    "产品设计更新位置",
    "代码设计影响",
    "代码设计更新位置",
    "剩余风险",
    "后续处理阶段",
    "后续需要检查什么",
]

INDEX_STATUSES = {"待验证", "已确认", "限制已确认", "仍未确认"}
RESULT_STATUSES = {"已确认", "限制已确认", "仍未确认"}
YES_NO = {"是", "否"}
DESIGN_IMPACTS = {"需要修改", "无需修改"}
FOLLOW_UP_STAGES = {"无", "plan", "fix_plan", "test_plan", "impl", "test", "acceptance"}


@dataclass
class SpikeIndexItem:
    item_id: str
    name: str
    fields: dict[str, str]


@dataclass
class SpikeDetail:
    metadata: dict[str, str]
    sections: dict[str, str]
    section_fields: dict[str, dict[str, str]]


def _read_text(path: str) -> str:
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


def _parse_fields(lines: list[str], context: str) -> tuple[dict[str, str], list[str]]:
    fields: dict[str, str] = {}
    errors = []
    for line in lines:
        match = FIELD_RE.match(line.strip())
        if not match:
            continue
        key, value = match.groups()
        if key in fields:
            errors.append(f"{context} 重复字段：{key}")
            continue
        fields[key] = value.strip()
    return fields, errors


def _missing_or_placeholder(value: str | None) -> bool:
    if value is None or not value.strip():
        return True
    return PLACEHOLDER_RE.search(value) is not None


def _require_fields(fields: dict[str, str], required: list[str], context: str) -> list[str]:
    errors = []
    for key in required:
        if key not in fields:
            errors.append(f"{context} 缺少字段：{key}")
        elif _missing_or_placeholder(fields[key]):
            errors.append(f"{context} 字段未填写：{key}")
    return errors


def parse_spike_index(path: str) -> tuple[str | None, list[SpikeIndexItem], list[str]]:
    lines = _read_text(path).splitlines()
    item_starts = []
    for index, line in enumerate(lines):
        match = INDEX_ITEM_RE.match(line.strip())
        if match:
            item_starts.append((index, match.group(1), match.group(2).strip()))

    errors = []
    top_end = item_starts[0][0] if item_starts else len(lines)
    top_fields, top_errors = _parse_fields(lines[:top_end], "穿刺清单")
    errors.extend(top_errors)
    workflow_id = top_fields.get("工作流编号")
    if _missing_or_placeholder(workflow_id):
        errors.append("穿刺清单缺少有效的工作流编号")

    items = []
    seen_ids = set()
    for position, (start, item_id, name) in enumerate(item_starts):
        end = item_starts[position + 1][0] if position + 1 < len(item_starts) else len(lines)
        fields, field_errors = _parse_fields(lines[start + 1:end], f"穿刺项 {item_id}")
        errors.extend(field_errors)
        if item_id in seen_ids:
            errors.append(f"穿刺清单重复编号：{item_id}")
        seen_ids.add(item_id)
        errors.extend(_require_fields(fields, INDEX_REQUIRED_FIELDS, f"穿刺项 {item_id}"))
        items.append(SpikeIndexItem(item_id=item_id, name=name, fields=fields))

    if not items:
        errors.append("穿刺清单中没有任何穿刺项")
    return workflow_id, items, errors


def parse_spike_detail(path: str) -> tuple[SpikeDetail, list[str]]:
    lines = _read_text(path).splitlines()
    section_starts = []
    for index, line in enumerate(lines):
        match = DETAIL_SECTION_RE.match(line.strip())
        if match:
            section_starts.append((index, match.group(1), match.group(2).strip()))

    errors = []
    top_end = section_starts[0][0] if section_starts else len(lines)
    metadata, metadata_errors = _parse_fields(lines[:top_end], os.path.basename(path))
    errors.extend(metadata_errors)
    errors.extend(_require_fields(metadata, ["工作流编号", "穿刺项编号"], os.path.basename(path)))

    sections: dict[str, str] = {}
    section_fields: dict[str, dict[str, str]] = {}
    for position, (start, number, title) in enumerate(section_starts):
        end = section_starts[position + 1][0] if position + 1 < len(section_starts) else len(lines)
        if number in sections:
            errors.append(f"{os.path.basename(path)} 重复章节：{number}")
            continue
        expected_title = EXPECTED_DETAIL_SECTIONS.get(number)
        if expected_title != title:
            errors.append(
                f"{os.path.basename(path)} 第 {number} 章标题应为“{expected_title}”，实际为“{title}”"
            )
        body_lines = lines[start + 1:end]
        body = "\n".join(body_lines).strip()
        sections[number] = body
        fields, field_errors = _parse_fields(body_lines, f"{os.path.basename(path)} 第 {number} 章")
        section_fields[number] = fields
        errors.extend(field_errors)

    for number, title in EXPECTED_DETAIL_SECTIONS.items():
        if number not in sections:
            errors.append(f"{os.path.basename(path)} 缺少第 {number} 章“{title}”")
            continue
        body = sections[number]
        if not body or PLACEHOLDER_RE.search(body):
            errors.append(f"{os.path.basename(path)} 第 {number} 章未填写完成")

    errors.extend(_require_fields(section_fields.get("4", {}), METHOD_FIELDS, f"{os.path.basename(path)} 第 4 章"))
    errors.extend(_require_fields(section_fields.get("5", {}), EXECUTION_FIELDS, f"{os.path.basename(path)} 第 5 章"))
    errors.extend(_require_fields(section_fields.get("7", {}), RESULT_FIELDS, f"{os.path.basename(path)} 第 7 章"))
    errors.extend(_require_fields(section_fields.get("8", {}), IMPACT_FIELDS, f"{os.path.basename(path)} 第 8 章"))

    observation = sections.get("6", "").strip()
    if observation in {"无", "暂无"}:
        errors.append(f"{os.path.basename(path)} 第 6 章必须记录实际观察结果")

    return SpikeDetail(metadata=metadata, sections=sections, section_fields=section_fields), errors


def _detail_path_from_link(project_root: str, value: str) -> tuple[str | None, str | None]:
    match = MARKDOWN_LINK_RE.search(value)
    if not match:
        return (None, "结论文档字段必须使用 Markdown 链接")
    target = match.group(1).split("#", 1)[0].strip()
    if os.path.isabs(target):
        return (None, "结论文档不能使用绝对路径")

    if target.startswith("./"):
        target = target[2:]
    if target.startswith("spec/"):
        rel_path = os.path.normpath(target)
    else:
        rel_path = os.path.normpath(os.path.join("spec", target))

    if rel_path.startswith(".."):
        return (None, "结论文档路径不能离开 spec/ 目录")
    if not re.fullmatch(r"spec/spike_[a-z0-9_]+\.md", rel_path):
        return (None, "结论文档文件名必须是 spec/spike_<english-name>.md")
    if rel_path == os.path.join("spec", "spike_index.md"):
        return (None, "穿刺清单不能作为结论文档")
    return (rel_path, None)


def _validate_choice(value: str | None, allowed: set[str], label: str, context: str) -> list[str]:
    if value not in allowed:
        return [f"{context} 的“{label}”值无效：{value or '空'}"]
    return []


def _is_none_value(value: str | None) -> bool:
    return value is None or not value.strip() or value.strip() in {"无", "暂无"}


def validate_spike_stage(project_root: str) -> tuple[bool, str]:
    state = state_mod.load_state(project_root)
    if state is None:
        return (False, "找不到当前工作流状态")

    index_path = os.path.join(project_root, "spec", "spike_index.md")
    if not os.path.exists(index_path):
        return (False, "spec/spike_index.md 不存在")

    workflow_id, items, errors = parse_spike_index(index_path)
    if workflow_id and workflow_id != state.workflow_id:
        errors.append(
            f"穿刺清单属于工作流 {workflow_id}，当前工作流是 {state.workflow_id}"
        )

    seen_detail_paths = set()
    product_design_needs_change = False
    code_design_needs_change = False

    for item in items:
        context = f"穿刺项 {item.item_id}"
        fields = item.fields
        if any(key not in fields or _missing_or_placeholder(fields.get(key)) for key in INDEX_REQUIRED_FIELDS):
            continue

        errors.extend(_validate_choice(fields.get("穿刺状态"), INDEX_STATUSES, "穿刺状态", context))
        if fields.get("穿刺状态") == "待验证":
            errors.append(f"{context} 仍是待验证，不能通过门2")
        errors.extend(_validate_choice(fields.get("是否阻塞后续"), YES_NO, "是否阻塞后续", context))
        errors.extend(_validate_choice(fields.get("产品设计影响"), DESIGN_IMPACTS, "产品设计影响", context))
        errors.extend(_validate_choice(fields.get("代码设计影响"), DESIGN_IMPACTS, "代码设计影响", context))
        errors.extend(_validate_choice(fields.get("后续处理阶段"), FOLLOW_UP_STAGES, "后续处理阶段", context))

        detail_rel_path, link_error = _detail_path_from_link(project_root, fields["结论文档"])
        if link_error:
            errors.append(f"{context}：{link_error}")
            continue
        assert detail_rel_path is not None
        if detail_rel_path in seen_detail_paths:
            errors.append(f"多个穿刺项使用同一份结论文档：{detail_rel_path}")
            continue
        seen_detail_paths.add(detail_rel_path)

        detail_path = os.path.join(project_root, detail_rel_path)
        if not os.path.exists(detail_path):
            errors.append(f"{context} 的结论文档不存在：{detail_rel_path}")
            continue

        detail, detail_errors = parse_spike_detail(detail_path)
        errors.extend(detail_errors)
        if detail.metadata.get("工作流编号") != state.workflow_id:
            errors.append(f"{detail_rel_path} 的工作流编号与当前工作流不一致")
        if detail.metadata.get("穿刺项编号") != item.item_id:
            errors.append(f"{detail_rel_path} 的穿刺项编号与清单中的 {item.item_id} 不一致")

        result_fields = detail.section_fields.get("7", {})
        impact_fields = detail.section_fields.get("8", {})
        result_status = result_fields.get("结果状态")
        blocked = result_fields.get("是否阻塞后续")
        product_impact = impact_fields.get("产品设计影响")
        code_impact = impact_fields.get("代码设计影响")
        follow_up = impact_fields.get("后续处理阶段")

        errors.extend(_validate_choice(result_status, RESULT_STATUSES, "结果状态", detail_rel_path))
        errors.extend(_validate_choice(blocked, YES_NO, "是否阻塞后续", detail_rel_path))
        errors.extend(_validate_choice(product_impact, DESIGN_IMPACTS, "产品设计影响", detail_rel_path))
        errors.extend(_validate_choice(code_impact, DESIGN_IMPACTS, "代码设计影响", detail_rel_path))
        errors.extend(_validate_choice(follow_up, FOLLOW_UP_STAGES, "后续处理阶段", detail_rel_path))

        if fields.get("穿刺状态") != result_status:
            errors.append(f"{context} 的穿刺状态与结论文档结果状态不一致")
        if fields.get("是否阻塞后续") != blocked:
            errors.append(f"{context} 的阻塞状态与结论文档不一致")
        if fields.get("产品设计影响") != product_impact:
            errors.append(f"{context} 的产品设计影响与结论文档不一致")
        if fields.get("代码设计影响") != code_impact:
            errors.append(f"{context} 的代码设计影响与结论文档不一致")
        if fields.get("后续处理阶段") != follow_up:
            errors.append(f"{context} 的后续处理阶段与结论文档不一致")

        if blocked == "是":
            errors.append(f"{context} 仍然阻塞后续，不能通过门2")

        if result_status == "仍未确认":
            if _is_none_value(result_fields.get("仍未确认内容")):
                errors.append(f"{detail_rel_path} 必须写清仍未确认内容")
            if _is_none_value(impact_fields.get("剩余风险")):
                errors.append(f"{detail_rel_path} 必须写清剩余风险")
            if follow_up == "无":
                errors.append(f"{detail_rel_path} 必须指定后续处理阶段")
            if _is_none_value(impact_fields.get("后续需要检查什么")):
                errors.append(f"{detail_rel_path} 必须写清后续需要检查什么")

        if state.intent == "bugfix" and product_impact == "需要修改":
            errors.append(
                f"{detail_rel_path} 需要修改产品设计，不能继续 bugfix；请结束当前流程后启动 product_change"
            )
        if state.intent == "bugfix" and follow_up == "plan":
            errors.append(f"{detail_rel_path} 在 bugfix 中应使用 fix_plan，不应使用 plan")
        if state.intent != "bugfix" and follow_up == "fix_plan":
            errors.append(f"{detail_rel_path} 当前不是 bugfix，不能使用 fix_plan")

        product_location = impact_fields.get("产品设计更新位置")
        code_location = impact_fields.get("代码设计更新位置")
        if product_impact == "需要修改":
            product_design_needs_change = True
            if _is_none_value(product_location):
                errors.append(f"{detail_rel_path} 必须写清产品设计更新位置")
        elif not _is_none_value(product_location):
            errors.append(f"{detail_rel_path} 产品设计无需修改时，更新位置应写“无”")

        if code_impact == "需要修改":
            code_design_needs_change = True
            if _is_none_value(code_location):
                errors.append(f"{detail_rel_path} 必须写清代码设计更新位置")
        elif not _is_none_value(code_location):
            errors.append(f"{detail_rel_path} 代码设计无需修改时，更新位置应写“无”")

    baseline = state.spike_baseline
    if baseline.captured_at is None:
        if not baseline.legacy_unavailable:
            errors.append("穿刺开始时的产品设计和代码设计基线尚未记录")
        elif product_design_needs_change or code_design_needs_change:
            errors.append(
                "当前是缺少入场设计基线的旧工作流，无法证明设计文档在穿刺后发生了变化"
            )
    else:
        current_product_hash, _ = verification_mod.compute_product_design_hash(project_root)
        current_code_hash = verification_mod.compute_code_design_hash(project_root)
        if product_design_needs_change:
            if baseline.product_design_hash is None or current_product_hash is None:
                errors.append("无法比较产品设计修改前后的哈希")
            elif baseline.product_design_hash == current_product_hash:
                errors.append("穿刺结论要求修改产品设计，但产品设计哈希没有变化")
        if code_design_needs_change:
            if baseline.code_design_hash is None or current_code_hash is None:
                errors.append("无法比较代码设计修改前后的哈希")
            elif baseline.code_design_hash == current_code_hash:
                errors.append("穿刺结论要求修改代码设计，但代码设计哈希没有变化")

    if errors:
        return (False, "；".join(errors))
    return (True, f"穿刺清单和 {len(items)} 份结论文档通过校验")
