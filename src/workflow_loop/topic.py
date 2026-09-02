import os
import re

from . import artifact_paths as artifact_paths_mod
from .project import load_project
from .state import load_state
from .topic_relations import read_topic_index


# 固定字段只接受冒号后的同一行内容。这里不能使用 ``\s*``，否则空字段会
# 跨过换行把下一字段误当成值。
WORKFLOW_FIELD_RE = re.compile(
    r"^-[ \t]*工作流编号：[ \t]*([^\r\n]+?)[ \t]*$",
    re.MULTILINE,
)
TOPIC_FIELD_RE = re.compile(
    r"^-[ \t]*验收主题：[ \t]*([^\r\n]+?)[ \t]*$",
    re.MULTILINE,
)


def topic_file_key(project_root: str, topic: str) -> str:
    """取得验收主题的稳定文件标识：优先项目映射，缺少时确定性生成（不保存）。

    主题名称是业务标识；文件标识只用于拼路径。文件名清理不改变主题显示名称。
    """
    project = load_project(project_root)
    return artifact_paths_mod.resolve_key_for(project, "topic", topic)


def topic_paths(project_root: str, topic: str) -> dict[str, str]:
    """按统一路径规则返回一个主题的全部正式文档路径（相对项目根）。"""
    file_key = topic_file_key(project_root, topic)
    return {
        "acceptance_plan": artifact_paths_mod.topic_acceptance_plan(file_key),
        "acceptance_result": artifact_paths_mod.topic_acceptance_result(file_key),
        "test_plan": artifact_paths_mod.topic_test_plan(file_key),
        "test_result": artifact_paths_mod.topic_test_result(file_key),
        "impl_doc": artifact_paths_mod.topic_impl_doc(file_key),
    }


def list_acceptance_index_topics(
    project_root: str,
    workflow_id: str | None = None,
) -> list[str]:
    """按 acceptance/索引.md 的展示顺序读取验收主题完整显示名称。"""

    state = load_state(project_root)
    effective_workflow_id = workflow_id or (state.workflow_id if state is not None else None)
    if effective_workflow_id is None:
        return []
    relations = read_topic_index(
        project_root,
        artifact_paths_mod.ACCEPTANCE_INDEX_DOC,
        effective_workflow_id,
    )
    return [relation.topic for relation in relations]


def list_reproduce_topics(project_root: str, workflow_id: str | None = None) -> list[str]:
    """从当前工作流的缺陷复现记录读取验收主题。"""
    bug_dir = os.path.join(project_root, "bug")
    if not os.path.isdir(bug_dir):
        return []

    topics: list[str] = []
    for filename in sorted(os.listdir(bug_dir)):
        if (
            not filename.endswith(".md")
            or filename == os.path.basename(artifact_paths_mod.BUG_INDEX_DOC)
        ):
            continue
        with open(os.path.join(bug_dir, filename), "r", encoding="utf-8") as f:
            content = f.read()
        if workflow_id is not None:
            workflow_match = WORKFLOW_FIELD_RE.search(content)
            if workflow_match is None or workflow_match.group(1).strip() != workflow_id:
                continue
        topic_match = TOPIC_FIELD_RE.search(content)
        if topic_match is not None:
            topics.append(topic_match.group(1).strip())
    return topics


def current_workflow_topics(project_root: str) -> list[str]:
    """读取当前 Workflow Run（工作流运行）的主题，兼容旧版单主题状态。"""
    state = load_state(project_root)
    if state is None:
        return []
    if state.topics:
        return state.topics
    if state.topic:
        return [state.topic]
    # 断言三：state.topics 空时，从 topic_relations 工作记录表读（表为唯一输入，不靠 state.topics）
    try:
        from . import records as records_mod
        import os
        _rel = records_mod.table_relative_path(project_root, state.workflow_id, "topic_relations", "")
        if records_mod.table_exists(project_root, _rel):
            _t = records_mod.load_table(os.path.join(project_root, _rel))
            _topics = [
                str(r.get("验收主题", "")).strip()
                for r in _t.get("主题关系", [])
                if str(r.get("验收主题", "")).strip()
            ]
            if _topics:
                return _topics
    except Exception:
        pass
    return []


def candidate_topics(project_root: str) -> list[str]:
    """返回本次验收计划里的主题：保留当前主题，并接纳未使用过的新主题。"""
    current = set(current_workflow_topics(project_root))
    project = load_project(project_root)
    history = set(project.topic_history if project is not None else [])
    topics = list_acceptance_index_topics(project_root)
    return [
        topic
        for topic in topics
        if topic in current or topic not in history
    ]


def acceptance_topics(
    project_root: str,
    intent: str,
    stage: str,
    state_topics: list[str] | None = None,
) -> list[str]:
    """返回当前环节应使用的验收主题集。

    验收计划环节（非修 bug）用 candidate_topics：保留 state 已记录主题，并接纳
    acceptance/索引.md 中未使用过的新主题——退回后往索引追加主题时校验集不能钉死
    在旧主题；candidate_topics 为空时回退 state 主题。其他环节主题已在验收计划
    第三道门写入 state，直接取 state_topics（未传入时读磁盘 state）。

    state_topics 供调用方传入内存中的 wf_state.topics，避免依赖磁盘 state 的写入时机。
    """
    if state_topics is None:
        state_topics = current_workflow_topics(project_root)
    if stage == "acceptance_plan" and intent != "bugfix":
        return candidate_topics(project_root) or list(state_topics)
    return list(state_topics) or current_workflow_topics(project_root)


def missing_topic_documents(
    project_root: str,
    kind: str,
    topics: list[str],
) -> list[str]:
    """返回缺失的主题正式文档路径。

    kind 取值：acceptance_plan / acceptance_result / test_plan / test_result / impl_doc。
    """
    missing: list[str] = []
    for topic in topics:
        relative_path = topic_paths(project_root, topic)[kind]
        if not os.path.isfile(os.path.join(project_root, relative_path)):
            missing.append(relative_path)
    return missing
