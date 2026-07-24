import os

from .project import load_project
from .state import load_state


def list_acceptance_plan_topics(project_root: str) -> list[str]:
    """从 acceptance/<topic>_plan.md 文件名读取全部主题名称。"""
    acceptance_dir = os.path.join(project_root, "acceptance")
    if not os.path.isdir(acceptance_dir):
        return []

    suffix = "_plan.md"
    return sorted(
        filename[: -len(suffix)]
        for filename in os.listdir(acceptance_dir)
        if filename.endswith(suffix) and filename != suffix
    )


def current_workflow_topics(project_root: str) -> list[str]:
    """读取当前 Workflow Run（工作流运行）的主题，兼容旧版单主题状态。"""
    state = load_state(project_root)
    if state is None:
        return []
    if state.topics:
        return state.topics
    return [state.topic] if state.topic else []


def candidate_topics(project_root: str) -> list[str]:
    """返回本次验收计划里的主题：保留当前主题，并接纳未使用过的新主题。"""
    current = set(current_workflow_topics(project_root))
    project = load_project(project_root)
    history = set(project.topic_history if project is not None else [])
    return [
        topic
        for topic in list_acceptance_plan_topics(project_root)
        if topic in current or topic not in history
    ]


def missing_topic_files(
    project_root: str,
    directory: str,
    suffix: str,
    topics: list[str],
) -> list[str]:
    """返回缺失的按主题命名文件，例如 qa/<topic>_plan.md。"""
    return [
        os.path.join(directory, f"{topic}{suffix}")
        for topic in topics
        if not os.path.isfile(os.path.join(project_root, directory, f"{topic}{suffix}"))
    ]
