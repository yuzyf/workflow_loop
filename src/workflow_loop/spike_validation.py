import os
import re
from dataclasses import dataclass, field

from . import artifact_paths as artifact_paths_mod
from . import state as state_mod
from . import verification as verification_mod


FIELD_RE = re.compile(r"^- ([^：\n]+)：\s*(.*)$")
INDEX_ITEM_RE = re.compile(r"^## (SP-\d{3})\s+(.+?)\s*$")
DETAIL_SECTION_RE = re.compile(r"^## ([1-9])\.\s+(.+?)\s*$")
MARKDOWN_LINK_RE = re.compile(r"\[[^\]]+\]\(([^)]+)\)")
PLACEHOLDER_RE = re.compile(r"<[^>\n]+>")
AC_RE = re.compile(r"\bAC-\d+\b", re.IGNORECASE)

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
    "9": "可复用资产",
}
BASE_REQUIRED_DETAIL_SECTIONS = tuple(str(index) for index in range(1, 9))

ASSET_TABLE_HEADERS = (
    "资产目录",
    "用途",
    "运行方法",
    "依赖与非敏感输入",
    "不保留内容",
    "支撑验收条件",
)
PENDING_ACCEPTANCE_LINK = "待验收计划关联"
FORBIDDEN_ASSET_DIRECTORIES = {
    ".cache",
    ".git",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".venv",
    "__pycache__",
    "build",
    "coverage",
    "dist",
    "logs",
    "node_modules",
    "output",
    "outputs",
    "results",
    "venv",
}
FORBIDDEN_ASSET_SUFFIXES = {
    ".key",
    ".log",
    ".out",
    ".p12",
    ".pem",
    ".pfx",
    ".pyc",
    ".pyo",
    ".tmp",
}
FORBIDDEN_ASSET_NAMES = {
    ".ds_store",
    ".env",
    "credentials.json",
    "id_dsa",
    "id_ed25519",
    "id_rsa",
    "secrets.json",
    "stderr",
    "stdout",
    "thumbs.db",
}
PURE_OUTPUT_STEMS = {"output", "outputs", "report", "reports", "result", "results"}
HIGH_CONFIDENCE_SECRET_PATTERNS = (
    re.compile(rb"-----BEGIN (?:[A-Z0-9]+ )?PRIVATE KEY-----"),
    re.compile(rb"AKIA[0-9A-Z]{16}"),
    re.compile(rb"gh[pousr]_[A-Za-z0-9]{20,}"),
    re.compile(rb"sk-[A-Za-z0-9]{20,}"),
)

# 可复用穿刺资产登记允许的命令入口。这里只限制 argv[0]（命令的第一个参数，
# 也就是启动程序），命令参数仍由 spike_reuse.py 逐项检查是否越出资产目录。
REUSABLE_ASSET_EXECUTABLES = {
    "bash",
    "cmake",
    "make",
    "node",
    "npm",
    "npx",
    "pnpm",
    "pwsh",
    "pytest",
    "python",
    "python3",
    "sh",
    "uv",
}


def is_reusable_asset_executable_name(value: str) -> bool:
    """判断命令入口是否属于登记阶段已有的受控可执行程序集合。"""

    normalized = os.path.basename(value.replace("\\", "/")).casefold()
    normalized = re.sub(r"\.(?:exe|cmd|bat)$", "", normalized)
    if normalized in REUSABLE_ASSET_EXECUTABLES:
        return True
    return bool(re.fullmatch(r"python3(?:\.\d+)?", normalized))

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
FOLLOW_UP_STAGES = {
    "无",
    "acceptance_plan",
    "test_plan",
    "impl",
    "test_code",
    "test_execution",
    "topic_acceptance",
    "regression_test",
    "overall_acceptance",
    "update_code_design",
}


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
    assets: list["SpikeAssetSpec"] = field(default_factory=list)


@dataclass
class SpikeAssetSpec:
    relative_path: str
    purpose: str
    run_method: str
    dependencies_and_inputs: str
    excluded_content: str
    acceptance_conditions: list[str]


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


def _table_cells(line: str) -> list[str]:
    return [cell.strip() for cell in line.strip().strip("|").split("|")]


def _parse_acceptance_conditions(value: str, context: str) -> tuple[list[str], list[str]]:
    normalized = value.strip()
    if normalized == PENDING_ACCEPTANCE_LINK:
        return [], []
    references = []
    for part in re.split(r"<br\s*/?>|[、，,；;]", normalized):
        item = part.strip()
        if not item:
            continue
        match = AC_RE.search(item)
        if match is None:
            return [], [
                f"{context} 的支撑验收条件必须写“{PENDING_ACCEPTANCE_LINK}”或具体 AC 编号：{item!r}"
            ]
        references.append(item[: match.start()] + match.group(0).upper() + item[match.end() :])
    if not references:
        return [], [f"{context} 没有可识别的支撑验收条件"]
    return list(dict.fromkeys(references)), []


def _parse_asset_section(body: str, context: str) -> tuple[list[SpikeAssetSpec], list[str]]:
    if body.strip() == "暂无":
        return [], []
    lines = body.splitlines()
    header_index = next(
        (index for index, line in enumerate(lines) if line.strip().startswith("|")),
        None,
    )
    if header_index is None:
        return [], [f"{context} 必须写“暂无”或固定可复用资产表"]
    headers = _table_cells(lines[header_index])
    if headers != list(ASSET_TABLE_HEADERS):
        return [], [f"{context} 的可复用资产表头必须是 {list(ASSET_TABLE_HEADERS)}"]

    rows: list[SpikeAssetSpec] = []
    errors: list[str] = []
    for row_number, line in enumerate(lines[header_index + 1 :], header_index + 2):
        stripped = line.strip()
        if not stripped.startswith("|"):
            if rows:
                break
            continue
        cells = _table_cells(stripped)
        if all(re.fullmatch(r"[-:]+", cell) for cell in cells):
            continue
        if len(cells) != len(headers):
            errors.append(
                f"{context} 的可复用资产表第 {row_number} 行有 {len(cells)} 列，表头有 {len(headers)} 列"
            )
            continue
        row = dict(zip(headers, cells))
        for header in ASSET_TABLE_HEADERS:
            if _missing_or_placeholder(row[header]):
                errors.append(f"{context} 的可复用资产表第 {row_number} 行未填写：{header}")
        acceptance_conditions, acceptance_errors = _parse_acceptance_conditions(
            row["支撑验收条件"],
            f"{context} 第 {row_number} 行",
        )
        errors.extend(acceptance_errors)
        if any(_missing_or_placeholder(row[header]) for header in ASSET_TABLE_HEADERS):
            continue
        rows.append(
            SpikeAssetSpec(
                relative_path=row["资产目录"],
                purpose=row["用途"],
                run_method=row["运行方法"],
                dependencies_and_inputs=row["依赖与非敏感输入"],
                excluded_content=row["不保留内容"],
                acceptance_conditions=acceptance_conditions,
            )
        )
    if not rows and not errors:
        errors.append(f"{context} 的可复用资产表没有任何数据行；没有资产时必须只写“暂无”")
    if len(rows) > 1:
        errors.append(f"{context} 每个穿刺项只能登记自己的一个隔离资产目录")
    return rows, errors


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

    for number in BASE_REQUIRED_DETAIL_SECTIONS:
        title = EXPECTED_DETAIL_SECTIONS[number]
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

    assets: list[SpikeAssetSpec] = []
    if "9" in sections:
        assets, asset_errors = _parse_asset_section(
            sections["9"],
            f"{os.path.basename(path)} 第 9 章",
        )
        errors.extend(asset_errors)

    return SpikeDetail(
        metadata=metadata,
        sections=sections,
        section_fields=section_fields,
        assets=assets,
    ), errors


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
    # 结论文档使用稳定中文文件标识：spec/穿刺_<穿刺项文件标识>.md
    normalized = rel_path.replace(os.sep, "/")
    if not re.fullmatch(r"spec/穿刺_[A-Za-z0-9_\-一-鿿㐀-䶿]+\.md", normalized):
        return (None, "结论文档文件名必须是 spec/穿刺_<穿刺项文件标识>.md")
    if normalized == artifact_paths_mod.SPIKE_INDEX_DOC:
        return (None, "穿刺清单不能作为结论文档")
    return (rel_path, None)


def _validate_choice(value: str | None, allowed: set[str], label: str, context: str) -> list[str]:
    if value not in allowed:
        return [f"{context} 的“{label}”值无效：{value or '空'}"]
    return []


def _is_none_value(value: str | None) -> bool:
    return value is None or not value.strip() or value.strip() in {"无", "暂无"}


def _normalized_asset_path(raw_path: str) -> str:
    value = raw_path.strip().strip("`").replace("\\", "/").rstrip("/")
    if not value or value.startswith("/") or re.match(r"^[A-Za-z]:", value):
        raise ValueError(f"资产目录必须是项目内相对路径：{raw_path!r}")
    if any(part in {"", ".", ".."} for part in value.split("/")):
        raise ValueError(f"资产目录不能越过当前项目：{raw_path!r}")
    return value


def _asset_item_key(detail_rel_path: str) -> str:
    filename = os.path.basename(detail_rel_path)
    prefix = "穿刺_"
    suffix = ".md"
    if not filename.startswith(prefix) or not filename.endswith(suffix):
        raise ValueError(f"无法从结论文档得到穿刺项文件标识：{detail_rel_path}")
    return filename[len(prefix) : -len(suffix)]


def _expected_asset_path(workflow_id: str, detail_rel_path: str) -> str:
    # 延迟导入，避免 stages 包初始化时 stages.py 与本模块互相导入。
    from .stages.base import expected_spike_asset_path

    return expected_spike_asset_path(workflow_id, _asset_item_key(detail_rel_path))


def _looks_like_run_method(value: str) -> bool:
    normalized = value.strip()
    if normalized in {"无", "暂无", "同上", "见上文", "见第 4 章"}:
        return False
    return bool(
        re.search(
            r"(?:`[^`]+`|(?:^|\s)(?:\./|bash|cmake|make|node|npm|npx|pnpm|python|python3|pwsh|pytest|sh|uv)(?:\s|$))",
            normalized,
            re.IGNORECASE,
        )
    )


def _validate_excluded_content(value: str, context: str) -> list[str]:
    missing = [
        label
        for label in ("敏感", "缓存", "日志", "纯结果")
        if label not in value
    ]
    if missing:
        return [
            f"{context} 的“不保留内容”必须明确排除敏感数据、缓存、日志和纯结果输出；缺少 {missing}"
        ]
    return []


def _forbidden_asset_file_reason(relative_inside_asset: str) -> str | None:
    parts = relative_inside_asset.replace("\\", "/").split("/")
    lowered_parts = [part.casefold() for part in parts]
    for part in lowered_parts[:-1]:
        if part in FORBIDDEN_ASSET_DIRECTORIES:
            return f"包含不应保留的目录 {part!r}"

    filename = lowered_parts[-1]
    stem, suffix = os.path.splitext(filename)
    if filename in FORBIDDEN_ASSET_NAMES:
        return f"包含敏感或机器生成文件 {filename!r}"
    if filename.startswith(".env.") and filename not in {
        ".env.example",
        ".env.sample",
        ".env.template",
    }:
        return f"包含可能保存真实环境凭据的文件 {filename!r}"
    if suffix in FORBIDDEN_ASSET_SUFFIXES:
        return f"包含不应保留的文件类型 {suffix!r}"
    if stem in PURE_OUTPUT_STEMS:
        return f"包含纯结果输出文件 {filename!r}"
    if filename in {"cookies.txt", "session.json", "sessions.json"}:
        return f"包含会话或凭据文件 {filename!r}"
    return None


def _validate_asset_directory(
    project_root: str,
    relative_path: str,
    context: str,
) -> list[str]:
    full_path = os.path.join(project_root, *relative_path.split("/"))
    if not os.path.isdir(full_path) or os.path.islink(full_path):
        return [f"{context} 的可复用资产目录不存在或不是普通目录：{relative_path}"]

    errors: list[str] = []
    file_count = 0
    for root, directories, files in os.walk(full_path, topdown=True, followlinks=False):
        safe_directories = []
        for directory in sorted(directories):
            directory_path = os.path.join(root, directory)
            relative_inside = os.path.relpath(directory_path, full_path).replace(os.sep, "/")
            if os.path.islink(directory_path):
                errors.append(f"{context} 的资产目录包含符号链接：{relative_inside}")
                continue
            reason = _forbidden_asset_file_reason(relative_inside + "/placeholder")
            if reason:
                errors.append(f"{context} 的资产目录 {reason}：{relative_inside}")
                continue
            safe_directories.append(directory)
        directories[:] = safe_directories

        for filename in sorted(files):
            file_path = os.path.join(root, filename)
            relative_inside = os.path.relpath(file_path, full_path).replace(os.sep, "/")
            if os.path.islink(file_path) or not os.path.isfile(file_path):
                errors.append(f"{context} 的资产目录包含非普通文件：{relative_inside}")
                continue
            file_count += 1
            reason = _forbidden_asset_file_reason(relative_inside)
            if reason:
                errors.append(f"{context} 的资产目录 {reason}：{relative_inside}")
                continue
            try:
                with open(file_path, "rb") as stream:
                    sample = stream.read(1024 * 1024)
            except OSError as exc:
                errors.append(f"{context} 无法读取资产文件 {relative_inside}：{exc}")
                continue
            if any(pattern.search(sample) for pattern in HIGH_CONFIDENCE_SECRET_PATTERNS):
                errors.append(f"{context} 的资产文件疑似包含真实密钥或令牌：{relative_inside}")
    if file_count == 0:
        errors.append(f"{context} 的可复用资产目录没有任何可重新运行的文件：{relative_path}")
    return errors


def validate_reusable_asset_directory(
    project_root: str,
    relative_path: str,
    context: str = "可复用穿刺资产",
) -> list[str]:
    """复用登记阶段的同一套目录安全检查，供后续重跑前后再次核对。"""

    return _validate_asset_directory(project_root, relative_path, context)


def _asset_registrations_for_detail(
    project_root: str,
    state: state_mod.WorkflowState,
    item: SpikeIndexItem,
    detail_rel_path: str,
    detail: SpikeDetail,
) -> tuple[list[state_mod.SpikeAssetRegistration], list[str]]:
    context = f"{detail_rel_path} 第 9 章"
    errors: list[str] = []
    if state.stage_path_version >= 2 and "9" not in detail.sections:
        return [], [f"{detail_rel_path} 缺少第 9 章“可复用资产”"]
    if state.spike_skipped and detail.assets:
        return [], ["本轮已经跳过穿刺，不能登记可复用资产"]

    result_status = detail.section_fields.get("7", {}).get("结果状态")
    if detail.assets and result_status not in {"已确认", "限制已确认"}:
        errors.append(f"{context} 只有已经形成结论的穿刺项才能登记可复用资产")

    registrations: list[state_mod.SpikeAssetRegistration] = []
    try:
        expected_path = _expected_asset_path(state.workflow_id, detail_rel_path)
    except ValueError as exc:
        return [], [f"{context}：{exc}"]
    temporary_location = detail.section_fields.get("4", {}).get("临时内容位置", "")
    for asset in detail.assets:
        try:
            relative_path = _normalized_asset_path(asset.relative_path)
        except ValueError as exc:
            errors.append(f"{context}：{exc}")
            continue
        if relative_path != expected_path:
            errors.append(
                f"{context} 的资产目录必须按当前工作流和穿刺项隔离："
                f"应为 {expected_path}，实际为 {relative_path}"
            )
        if relative_path not in temporary_location.replace("\\", "/"):
            errors.append(f"{context} 的资产目录必须和第 4 章“临时内容位置”一致")
        if _missing_or_placeholder(asset.purpose) or asset.purpose in {"无", "暂无", "同上"}:
            errors.append(f"{context} 必须写清资产如何用于重新取得本次结论")
        if not _looks_like_run_method(asset.run_method):
            errors.append(f"{context} 的运行方法必须包含可以实际执行的完整命令")
        if (
            _missing_or_placeholder(asset.dependencies_and_inputs)
            or asset.dependencies_and_inputs in {"无", "暂无", "同上"}
        ):
            errors.append(f"{context} 必须明确写出依赖和非敏感输入；没有额外内容时也要分别说明")
        errors.extend(_validate_excluded_content(asset.excluded_content, context))
        if relative_path == expected_path:
            errors.extend(_validate_asset_directory(project_root, relative_path, context))
        registrations.append(
            state_mod.SpikeAssetRegistration(
                workflow_id=state.workflow_id,
                spike_id=item.item_id,
                relative_path=relative_path,
                conclusion_document=detail_rel_path.replace(os.sep, "/"),
                acceptance_conditions=asset.acceptance_conditions,
                purpose=asset.purpose,
                run_method=asset.run_method,
                status="registered",
            )
        )
    return registrations, errors


def collect_spike_asset_registrations(
    project_root: str,
) -> list[state_mod.SpikeAssetRegistration]:
    """读取第二道门已经校验的穿刺文档，生成待用户确认的资产登记。"""

    state = state_mod.load_state(project_root)
    if state is None:
        raise ValueError("找不到当前工作流状态")
    index_path = os.path.join(project_root, artifact_paths_mod.SPIKE_INDEX_DOC)
    workflow_id, items, errors = parse_spike_index(index_path)
    if workflow_id != state.workflow_id:
        errors.append("穿刺清单工作流编号与当前状态不一致")
    registrations: list[state_mod.SpikeAssetRegistration] = []
    for item in items:
        detail_rel_path, link_error = _detail_path_from_link(project_root, item.fields.get("结论文档", ""))
        if link_error or detail_rel_path is None:
            errors.append(f"穿刺项 {item.item_id}：{link_error or '结论文档链接无效'}")
            continue
        detail_path = os.path.join(project_root, detail_rel_path)
        if not os.path.isfile(detail_path):
            errors.append(f"穿刺项 {item.item_id} 的结论文档不存在：{detail_rel_path}")
            continue
        detail, detail_errors = parse_spike_detail(detail_path)
        errors.extend(detail_errors)
        item_registrations, item_errors = _asset_registrations_for_detail(
            project_root,
            state,
            item,
            detail_rel_path,
            detail,
        )
        registrations.extend(item_registrations)
        errors.extend(item_errors)
    paths = [registration.relative_path for registration in registrations]
    if len(paths) != len(set(paths)):
        errors.append("多个穿刺项重复登记了同一可复用资产目录")
    if errors:
        raise ValueError("；".join(dict.fromkeys(errors)))
    return registrations


def validate_spike_stage(project_root: str) -> tuple[bool, str]:
    state = state_mod.load_state(project_root)
    if state is None:
        return (False, "找不到当前工作流状态")

    index_path = os.path.join(project_root, artifact_paths_mod.SPIKE_INDEX_DOC)
    if not os.path.exists(index_path):
        return (False, f"{artifact_paths_mod.SPIKE_INDEX_DOC} 不存在")

    workflow_id, items, errors = parse_spike_index(index_path)
    if workflow_id and workflow_id != state.workflow_id:
        errors.append(
            f"穿刺清单属于工作流 {workflow_id}，当前工作流是 {state.workflow_id}"
        )

    seen_detail_paths = set()
    registrations: list[state_mod.SpikeAssetRegistration] = []
    product_design_needs_change = False

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

        item_registrations, asset_errors = _asset_registrations_for_detail(
            project_root,
            state,
            item,
            detail_rel_path,
            detail,
        )
        registrations.extend(item_registrations)
        errors.extend(asset_errors)

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
        product_location = impact_fields.get("产品设计更新位置")
        code_location = impact_fields.get("代码设计更新位置")
        if product_impact == "需要修改":
            product_design_needs_change = True
            if _is_none_value(product_location):
                errors.append(f"{detail_rel_path} 必须写清产品设计更新位置")
        elif not _is_none_value(product_location):
            errors.append(f"{detail_rel_path} 产品设计无需修改时，更新位置应写“无”")

        if code_impact == "需要修改":
            if _is_none_value(code_location):
                errors.append(f"{detail_rel_path} 必须写清代码设计更新位置")
        elif not _is_none_value(code_location):
            errors.append(f"{detail_rel_path} 代码设计无需修改时，更新位置应写“无”")

    baseline = state.spike_baseline
    if baseline.captured_at is None:
        if not baseline.legacy_unavailable:
            errors.append("穿刺开始时的产品设计和代码设计基线尚未记录")
        elif product_design_needs_change:
            errors.append(
                "当前是缺少入场产品设计基线的旧工作流，无法证明产品设计在穿刺后发生了变化"
            )
    else:
        current_product_hash, _ = verification_mod.compute_product_design_hash(project_root)
        if product_design_needs_change:
            if baseline.product_design_hash is None or current_product_hash is None:
                errors.append("无法比较产品设计修改前后的哈希")
            elif baseline.product_design_hash == current_product_hash:
                errors.append("穿刺结论要求修改产品设计，但产品设计哈希没有变化")

    registered_paths = [registration.relative_path for registration in registrations]
    if len(registered_paths) != len(set(registered_paths)):
        errors.append("多个穿刺项重复登记了同一可复用资产目录")

    if errors:
        return (False, "；".join(dict.fromkeys(errors)))
    return (
        True,
        f"穿刺清单、{len(items)} 份结论文档和 {len(registrations)} 项可复用资产通过校验",
    )
