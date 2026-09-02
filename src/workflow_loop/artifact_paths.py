"""正式产物路径的唯一来源。

所有阶段、校验、哈希、追踪、清理和恢复代码都只能调用本模块取得正式产物路径，
不能自行拼接后缀。面向用户的正式产物固定使用中文文件名；`spec`、`acceptance`、
`qa`、`impl`、`bug` 等程序固定目录名保持英文。

显示名称与文件标识分离：功能、主题、穿刺项和缺陷在文档标题与正文中保留用户
确认的完整中文显示名称；进入文件名时使用稳定的中文文件标识。已有映射保存在
`.workflow_loop/project.json` 的 `artifact_file_keys` 中，后续阶段读取已保存的
对应关系，不重新猜测。
"""

from __future__ import annotations

import os
import re
import unicodedata

# ─── 固定正式产物路径（相对项目根） ───
PRODUCT_OVERVIEW_DOC = "spec/产品总说明.md"
CODE_DESIGN_DOC = "spec/代码架构设计.md"
DESIGN_INIT_EVIDENCE_DOC = "spec/项目设计初始化证据.md"
SPIKE_INDEX_DOC = "spec/穿刺清单.md"
ACCEPTANCE_INDEX_DOC = "acceptance/索引.md"
QA_INDEX_DOC = "qa/索引.md"
IMPL_INDEX_DOC = "impl/索引.md"
BUG_INDEX_DOC = "bug/索引.md"
TRACEABILITY_DOC = "需求交付追踪表.md"

# 文件标识分类：功能、验收主题、穿刺项、缺陷
FILE_KEY_CATEGORIES = ("feature", "topic", "spike", "bug")

# 文件标识允许的字符：中文、英文字母、数字、下划线和连字符
_ALLOWED_CHAR = re.compile(r"[A-Za-z0-9_\-一-鿿㐀-䶿]")
# 文件标识长度上限（字符数），避免超出各平台路径限制
MAX_FILE_KEY_LENGTH = 80
# Windows 保留名称（大小写不敏感；文件标识必须避开）
_WINDOWS_RESERVED = {
    "CON", "PRN", "AUX", "NUL",
    *{f"COM{i}" for i in range(1, 10)},
    *{f"LPT{i}" for i in range(1, 10)},
}


def make_file_key(display_name: str) -> str:
    """把显示名称清理成跨平台安全的中文文件标识（纯函数，不查映射）。

    只保留中文字符、英文字母、数字、下划线和连字符；空格、斜杠、反斜杠、冒号、
    问号、引号、换行和其它标点统一替换为单个下划线；去掉开头与结尾的点、空格、
    下划线并限制长度；避开 Windows 保留名称。无法得到安全标识时抛 ValueError。
    """
    if display_name is None:
        raise ValueError("显示名称不能为空")
    # Unicode 规范化：同一个视觉名称在不同输入法下得到同一标识
    normalized = unicodedata.normalize("NFC", str(display_name))

    pieces: list[str] = []
    previous_was_placeholder = False
    for char in normalized:
        if _ALLOWED_CHAR.fullmatch(char):
            pieces.append(char)
            previous_was_placeholder = False
        else:
            # 连续的非法字符只折叠成一个下划线
            if not previous_was_placeholder:
                pieces.append("_")
            previous_was_placeholder = True
    key = "".join(pieces)
    # 去掉开头与结尾的点、空格和下划线
    key = key.strip("._ \t")
    # 限制长度后再清理一次结尾
    key = key[:MAX_FILE_KEY_LENGTH].strip("._ \t")
    if not key:
        raise ValueError(f"显示名称无法生成安全文件标识: {display_name!r}")
    if key.upper() in _WINDOWS_RESERVED:
        # 保留名称追加下划线避开，例如 CON → CON_
        key = key + "_"
    return key


def resolve_file_key(
    saved_keys: dict[str, str],
    all_used_keys: set[str],
    display_name: str,
    keys_by_name_all: dict[str, str] | None = None,
) -> str:
    """在一个分类内解析显示名称的文件标识。

    saved_keys 是该分类已保存的 显示名称→文件标识 映射；all_used_keys 是全部
    分类已占用的标识（大小写不敏感比较，避免只在大小写上不同的路径冲突）；
    keys_by_name_all 是全部分类的 显示名称→文件标识 映射。
    已保存的名称直接返回旧标识；新名称生成标识，冲突时依次追加 `_2`、`_3`。

    同一显示名称在不同分类表示同一件事（缺陷名与验收主题名相同是常态），
    因此先在全部分类中按名称复用同一标识；否则第二个分类必然被迫追加 `_2`，
    使生成路径与登记路径分叉。不同名称之间仍不允许共用标识。
    """
    if display_name in saved_keys:
        return saved_keys[display_name]
    if keys_by_name_all is not None and display_name in keys_by_name_all:
        return keys_by_name_all[display_name]
    base_key = make_file_key(display_name)
    used_lower = {key.lower() for key in all_used_keys}
    candidate = base_key
    suffix = 2
    while candidate.lower() in used_lower:
        candidate = f"{base_key}_{suffix}"
        suffix += 1
    return candidate


def register_file_keys(project, category: str, display_names: list[str]) -> dict[str, str]:
    """把一批显示名称的文件标识登记进项目状态（不落盘，调用方负责保存）。

    拒绝两类漂移：同一显示名称改绑到另一标识；一个标识被另一显示名称占用。
    返回本次新增的 显示名称→文件标识。
    """
    if category not in FILE_KEY_CATEGORIES:
        raise ValueError(f"未知文件标识分类: {category}")
    keys = project.artifact_file_keys.setdefault(category, {})
    all_used = {
        key
        for mapping in project.artifact_file_keys.values()
        for key in mapping.values()
    }
    keys_by_name_all = _keys_by_name(project)
    reverse = {key: name for name, key in keys.items()}
    added: dict[str, str] = {}
    for display_name in display_names:
        if display_name in keys:
            continue
        key = resolve_file_key(keys, all_used, display_name, keys_by_name_all)
        owner = reverse.get(key)
        if owner is not None and owner != display_name:
            raise ValueError(
                f"文件标识 {key!r} 已被显示名称 {owner!r} 占用，不能再分配给 {display_name!r}"
            )
        keys[display_name] = key
        reverse[key] = display_name
        all_used.add(key)
        keys_by_name_all[display_name] = key
        added[display_name] = key
    return added


def _keys_by_name(project) -> dict[str, str]:
    """全部分类的 显示名称→文件标识 映射，供同名跨分类复用同一标识。"""
    if project is None:
        return {}
    merged: dict[str, str] = {}
    for mapping in project.artifact_file_keys.values():
        merged.update(mapping)
    return merged


def lookup_file_key(project, category: str, display_name: str) -> str | None:
    """读取已保存的文件标识；没有登记时返回 None。"""
    if project is None:
        return None
    return project.artifact_file_keys.get(category, {}).get(display_name)


def resolve_key_for(project, category: str, display_name: str) -> str:
    """取得显示名称的稳定文件标识：优先已保存映射，否则确定性生成（不保存）。"""
    saved = project.artifact_file_keys.get(category, {}) if project is not None else {}
    all_used = (
        {
            key
            for mapping in project.artifact_file_keys.values()
            for key in mapping.values()
        }
        if project is not None
        else set()
    )
    return resolve_file_key(saved, all_used, display_name, _keys_by_name(project))


# ─── 按文件标识生成动态正式产物路径 ───


def feature_doc(file_key: str) -> str:
    return f"spec/功能_{file_key}.md"


def spike_doc(file_key: str) -> str:
    return f"spec/穿刺_{file_key}.md"


def bug_doc(file_key: str) -> str:
    return f"bug/缺陷_{file_key}.md"


def topic_acceptance_plan(file_key: str) -> str:
    return f"acceptance/{file_key}_验收计划.md"


def topic_acceptance_result(file_key: str) -> str:
    return f"acceptance/{file_key}_验收结果.md"


def topic_test_plan(file_key: str) -> str:
    return f"qa/{file_key}_测试计划.md"


def topic_test_result(file_key: str) -> str:
    return f"qa/{file_key}_测试结果.md"


def topic_impl_doc(file_key: str) -> str:
    return f"impl/{file_key}_实施记录.md"


def managed_artifact_paths(project, wf_state=None, project_root: str | None = None) -> list[str]:
    """列出工作流拥有的正式产物路径，不把目录中的任意 Markdown 算进来。

    固定文档、项目中已经登记的文件标识、当前主题，以及磁盘上使用工作流保留
    命名格式的文件都属于受管范围。最后一类用于覆盖“文档已经创建、第三道门尚未
    登记文件标识就作废”的真实场景；`spec/notes.md` 之类用户自有文件不会命中。

    project 可以是 ``ProjectState``，也可以为 None。wf_state 只读取 topics/topic，
    因此旧状态和当前状态都可安全传入。
    """
    paths = {
        PRODUCT_OVERVIEW_DOC,
        CODE_DESIGN_DOC,
        DESIGN_INIT_EVIDENCE_DOC,
        SPIKE_INDEX_DOC,
        ACCEPTANCE_INDEX_DOC,
        QA_INDEX_DOC,
        IMPL_INDEX_DOC,
        BUG_INDEX_DOC,
        TRACEABILITY_DOC,
    }

    mappings = getattr(project, "artifact_file_keys", {}) if project is not None else {}
    for file_key in mappings.get("feature", {}).values():
        paths.add(feature_doc(file_key))
    for file_key in mappings.get("spike", {}).values():
        paths.add(spike_doc(file_key))
    for file_key in mappings.get("bug", {}).values():
        paths.add(bug_doc(file_key))
    for file_key in mappings.get("topic", {}).values():
        paths.update(
            {
                topic_acceptance_plan(file_key),
                topic_acceptance_result(file_key),
                topic_test_plan(file_key),
                topic_test_result(file_key),
                topic_impl_doc(file_key),
            }
        )

    topics = list(getattr(wf_state, "topics", []) or []) if wf_state is not None else []
    legacy_topic = getattr(wf_state, "topic", None) if wf_state is not None else None
    if not topics and legacy_topic:
        topics = [legacy_topic]
    for topic in topics:
        file_key = resolve_key_for(project, "topic", topic)
        paths.update(
            {
                topic_acceptance_plan(file_key),
                topic_acceptance_result(file_key),
                topic_test_plan(file_key),
                topic_test_result(file_key),
                topic_impl_doc(file_key),
            }
        )

    # 保留命名格式是工作流的正式命名空间。只接纳普通文件名，不递归扫描目录，
    # 从而不会把用户自己的说明、样本或笔记纳入整轮恢复。
    reserved_patterns = {
        "spec": (
            re.compile(r"^功能_[A-Za-z0-9_\-一-鿿㐀-䶿]+\.md$"),
            re.compile(r"^穿刺_[A-Za-z0-9_\-一-鿿㐀-䶿]+\.md$"),
        ),
        "acceptance": (
            re.compile(r"^[A-Za-z0-9_\-一-鿿㐀-䶿]+_(?:验收计划|验收结果)\.md$"),
        ),
        "qa": (
            re.compile(r"^[A-Za-z0-9_\-一-鿿㐀-䶿]+_(?:测试计划|测试结果)\.md$"),
        ),
        "impl": (
            re.compile(r"^[A-Za-z0-9_\-一-鿿㐀-䶿]+_实施记录\.md$"),
        ),
        "bug": (
            re.compile(r"^缺陷_[A-Za-z0-9_\-一-鿿㐀-䶿]+\.md$"),
        ),
    }
    if isinstance(project_root, str):
        for directory, patterns in reserved_patterns.items():
            full_dir = os.path.join(project_root, directory)
            if not os.path.isdir(full_dir):
                continue
            for filename in os.listdir(full_dir):
                if any(pattern.fullmatch(filename) for pattern in patterns):
                    paths.add(f"{directory}/{filename}")

    return sorted(paths)
