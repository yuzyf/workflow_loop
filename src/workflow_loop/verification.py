import hashlib
import os
import re

from .state import WorkflowState, StageState, GateState
from .topic import candidate_topics


# product.md 功能清单中的本地 Markdown 链接
# 只接受 spec/ 下的小写英文 feature_*.md，外部链接和其它文件不算产品功能文档
PRODUCT_FEATURE_LINK_RE = re.compile(
    r"\[[^\]]+\]\((?:\./)?(feature_[a-z0-9_]+\.md)(?:#[^)]+)?\)"
)


# 计算单个文件的 SHA256 哈希
# 用于 Verification Invalidation：绑定上游内容，检测变化
# 文件不存在时返回 None（还没产出过的 stage）
def compute_file_hash(project_root: str, rel_path: str) -> str | None:
    # 拼出文件的完整路径（项目根 + 相对路径）
    full_path = os.path.join(project_root, rel_path)
    # 文件不存在 → 返回 None
    if not os.path.exists(full_path):
        return None
    # 读文件二进制内容，算 SHA256
    with open(full_path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


def compute_file_hashes(
    project_root: str,
    rel_paths: list[str],
) -> dict[str, str | None]:
    """计算一组相对路径的文件哈希，保留当时不存在的文件。"""
    return {
        rel_path: compute_file_hash(project_root, rel_path)
        for rel_path in sorted(set(rel_paths))
    }


# 读取 product.md 中真实链接的功能文档路径
# 产品设计整体哈希以这里返回的文件为准，不扫描目录里的废弃 feature_*.md
def get_linked_product_design_paths(project_root: str) -> list[str]:
    product_path = os.path.join(project_root, "spec", "product.md")
    paths = [os.path.join("spec", "product.md")]
    if not os.path.exists(product_path):
        return paths

    with open(product_path, "r", encoding="utf-8") as f:
        content = f.read()

    for filename in PRODUCT_FEATURE_LINK_RE.findall(content):
        paths.append(os.path.join("spec", filename))
    return sorted(set(paths))


# 对一组文档计算稳定的整体 SHA256
# 路径也参与哈希，所以新增、删除或替换链接都会改变结果
def compute_document_set_hash(project_root: str, rel_paths: list[str]) -> str:
    parts = []
    for rel_path in sorted(set(rel_paths)):
        file_hash = compute_file_hash(project_root, rel_path)
        parts.append(f"{rel_path}:{file_hash or '<missing>'}")
    return hashlib.sha256("\n".join(parts).encode("utf-8")).hexdigest()


def normalize_topics(topics: str | list[str] | None) -> list[str]:
    """兼容旧版单主题参数，并统一返回主题列表。"""
    if topics is None:
        return []
    if isinstance(topics, str):
        return [topics] if topics else []
    return [topic for topic in topics if topic]


# 计算产品总说明及其功能清单链接文档的整体哈希
def compute_product_design_hash(project_root: str) -> tuple[str | None, list[str]]:
    paths = get_linked_product_design_paths(project_root)
    if compute_file_hash(project_root, os.path.join("spec", "product.md")) is None:
        return (None, paths)
    return (compute_document_set_hash(project_root, paths), paths)


# 计算代码设计文档哈希
def compute_code_design_hash(project_root: str) -> str | None:
    return compute_file_hash(project_root, os.path.join("spec", "architecture_code_design.md"))


# 计算项目代码快照的哈希（impl_hash 和修改前测试基线的一部分）
# 只读取代码、测试、脚本和项目构建配置，不把 state/journal/Markdown 文档算进去
# 这样记录测试结果和追加日志不会误使测试基线失效
def compute_code_snapshot_hash(project_root: str) -> str:
    code_suffixes = (
        ".py", ".ts", ".tsx", ".js", ".jsx", ".go", ".rs", ".java",
        ".kt", ".swift", ".ets", ".sh", ".bash", ".zsh",
    )
    config_names = {
        "pyproject.toml", "package.json", "package-lock.json", "yarn.lock",
        "pnpm-lock.yaml", "Cargo.toml", "Cargo.lock", "go.mod", "go.sum",
        "CMakeLists.txt", "Makefile", "justfile",
    }
    excluded_dirs = {
        ".git", ".workflow_loop", "__pycache__", ".venv", "node_modules",
        ".pytest_cache", "dist", "build",
    }
    file_digests = []
    for root, dirs, files in os.walk(project_root):
        dirs[:] = [directory for directory in dirs if directory not in excluded_dirs]
        for filename in files:
            relative_path = os.path.relpath(os.path.join(root, filename), project_root)
            if not filename.endswith(code_suffixes) and filename not in config_names:
                continue
            full_path = os.path.join(project_root, relative_path)
            try:
                with open(full_path, "rb") as stream:
                    content_hash = hashlib.sha256(stream.read()).hexdigest()
            except OSError:
                continue
            file_digests.append(f"{relative_path}:{content_hash}")
    return hashlib.sha256("\n".join(sorted(file_digests)).encode("utf-8")).hexdigest()


# 计算实施阶段和主题执行阶段使用的实施综合哈希（impl_hash）
# 包含两部分：impl/ 下全部实施记录内容哈希 + 代码快照哈希
# 在 gate impl --confirmed 时首次绑定，主题执行阶段继续使用；进入最终全量回归和整体验收前检查
def compute_impl_hash(project_root: str, topics: str | list[str] | None = None) -> str:
    # 收集哈希的各部分
    parts = []
    # 实施任务与验收主题不一定一一对应，因此绑定 impl/ 下全部实施记录。
    impl_dir = os.path.join(project_root, "impl")
    if os.path.isdir(impl_dir):
        impl_paths = [
            os.path.join("impl", filename)
            for filename in os.listdir(impl_dir)
            if filename.endswith(".md")
        ]
        if impl_paths:
            parts.append(f"impl_docs:{compute_document_set_hash(project_root, impl_paths)}")
    # 加入代码快照哈希（git status / 文件 mtime+size）
    parts.append(f"code_snapshot:{compute_code_snapshot_hash(project_root)}")
    # 合并所有部分算最终 SHA256
    return hashlib.sha256("\n".join(parts).encode("utf-8")).hexdigest()


# 计算测试计划文件 qa/<topic>_plan.md 的 SHA256
# 在 gate test_plan --confirmed 时记录；变化时使主题执行及其后续结果失效
def compute_test_plan_hash(project_root: str, topics: str | list[str] | None) -> str | None:
    topic_list = normalize_topics(topics)
    if not topic_list:
        return None
    paths = [os.path.join("qa", f"{topic}_plan.md") for topic in topic_list]
    return compute_document_set_hash(project_root, paths)


# 计算验收计划文件和验收主题索引的 SHA256
# 在 gate acceptance_plan --confirmed 时记录
# acceptance_plan 或主题关系变化时把 test_plan 和后续阶段退回待检查
def compute_acceptance_plan_hash(project_root: str, topics: str | list[str] | None) -> str | None:
    topic_list = normalize_topics(topics)
    if not topic_list:
        return None
    paths = [
        os.path.join("acceptance", "index.md"),
        *[os.path.join("acceptance", f"{topic}_plan.md") for topic in topic_list],
    ]
    return compute_document_set_hash(project_root, paths)


# 计算测试结果文件 qa/<topic>_result.md 的 SHA256
# 在 gate topic_execution --confirmed 时记录；变化时使最终全量回归和整体验收失效
def compute_test_result_hash(project_root: str, topics: str | list[str] | None) -> str | None:
    topic_list = normalize_topics(topics)
    if not topic_list:
        return None
    paths = [os.path.join("qa", f"{topic}_result.md") for topic in topic_list]
    return compute_document_set_hash(project_root, paths)


def compute_regression_test_result_hash(project_root: str) -> str | None:
    return compute_file_hash(project_root, os.path.join("qa", "final_regression_result.md"))


# 清零单个 stage 的所有门禁状态（3 道闸全清，状态回 pending）
# 用于 Verification Invalidation：上游变化时清零下游
def clear_stage_gates(stage: StageState) -> None:
    # 重置 3 道闸为全新 GateState（全 False）
    stage.gate = GateState()
    # stage 状态回到 pending（需要重新走 7 步模式）
    stage.status = "pending"


def reset_stages_and_move_current(state: WorkflowState, stage_names: list[str]) -> None:
    """清零指定阶段，并把当前阶段退回到路径中最早的受影响阶段。"""
    affected = []
    for stage_name in stage_names:
        if stage_name in state.stages:
            clear_stage_gates(state.stages[stage_name])
            affected.append(stage_name)

    if not affected:
        return

    order = {stage_name: index for index, stage_name in enumerate(state.stage_path)}
    earliest = min(affected, key=lambda stage_name: order.get(stage_name, len(order)))
    state.current_stage = earliest
    state.stages[earliest].status = "in_progress"


# 检查 Verification Invalidation：上游内容是否变化，变化则清零下游
# 在进入下游 stage 的第 2 道闸（gate 无 flag）时调用
# 返回失效列表：[(变化的源头, 被清零的下游), ...]
def check_invalidation(state: WorkflowState, project_root: str) -> list[tuple[str, str]]:
    invalidations: list[tuple[str, str]] = []
    topics = state.topics or ([state.topic] if state.topic else [])

    # 验收计划决定后续全部工作。内容、主题新增或主题删除后，从验收计划重新开始。
    if state.verification.acceptance_plan_hash is not None:
        current_topics = candidate_topics(project_root)
        current_ap = compute_acceptance_plan_hash(project_root, current_topics)
        if current_ap != state.verification.acceptance_plan_hash:
            reset_stages_and_move_current(
                state,
                [
                    "acceptance_plan",
                    "test_plan",
                    "impl",
                    "topic_execution",
                    "test",
                    "acceptance",
                    "regression_test",
                    "overall_acceptance",
                    "update_code_design",
                ],
            )
            state.verification.acceptance_plan_hash = None
            state.verification.test_plan_hash = None
            state.verification.impl_hash = None
            state.verification.test_result_hash = None
            state.verification.regression_test_result_hash = None
            invalidations.append(("acceptance_plan", "acceptance_plan 及全部后续阶段"))
            return invalidations

    # 测试计划变化后，测试计划本身、实施计划和执行结果都必须重新确认。
    if state.verification.test_plan_hash is not None:
        current_tp = compute_test_plan_hash(project_root, topics)
        if current_tp != state.verification.test_plan_hash:
            reset_stages_and_move_current(
                state,
                [
                    "test_plan",
                    "impl",
                    "topic_execution",
                    "test",
                    "acceptance",
                    "regression_test",
                    "overall_acceptance",
                    "update_code_design",
                ],
            )
            state.verification.test_plan_hash = None
            state.verification.impl_hash = None
            state.verification.test_result_hash = None
            state.verification.regression_test_result_hash = None
            invalidations.append(("test_plan", "test_plan 及全部后续阶段"))
            return invalidations

    # 实施代码或实施记录变化后，从主题执行重新开始。
    if state.verification.impl_hash is not None:
        current_impl = compute_impl_hash(project_root, topics)
        if current_impl != state.verification.impl_hash:
            reset_stages_and_move_current(
                state,
                [
                    "topic_execution",
                    "test",
                    "acceptance",
                    "regression_test",
                    "overall_acceptance",
                    "update_code_design",
                ],
            )
            state.verification.impl_hash = None
            state.verification.test_result_hash = None
            state.verification.regression_test_result_hash = None
            invalidations.append(("impl", "topic_execution 及全部后续阶段"))
            return invalidations

    # 某个主题的测试结果变化后，从主题执行重新确认。
    if state.verification.test_result_hash is not None:
        current_test_result = compute_test_result_hash(project_root, topics)
        if current_test_result != state.verification.test_result_hash:
            reset_stages_and_move_current(
                state,
                [
                    "topic_execution",
                    "acceptance",
                    "regression_test",
                    "overall_acceptance",
                    "update_code_design",
                ],
            )
            state.verification.test_result_hash = None
            state.verification.regression_test_result_hash = None
            invalidations.append(("test", "topic_execution 及全部后续阶段"))
            return invalidations

    # 最终全量回归结果变化后，从最终全量回归重新开始。
    if state.verification.regression_test_result_hash is not None:
        current_regression = compute_regression_test_result_hash(project_root)
        if current_regression != state.verification.regression_test_result_hash:
            reset_stages_and_move_current(
                state,
                ["regression_test", "overall_acceptance", "update_code_design"],
            )
            state.verification.regression_test_result_hash = None
            invalidations.append(("regression_test", "regression_test、overall_acceptance 和 update_code_design"))
            return invalidations

    return invalidations
