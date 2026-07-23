import hashlib
import os
import re
import subprocess

from .state import WorkflowState, StageState, GateState


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


# 计算产品总说明及其功能清单链接文档的整体哈希
def compute_product_design_hash(project_root: str) -> tuple[str | None, list[str]]:
    paths = get_linked_product_design_paths(project_root)
    if compute_file_hash(project_root, os.path.join("spec", "product.md")) is None:
        return (None, paths)
    return (compute_document_set_hash(project_root, paths), paths)


# 计算代码设计文档哈希
def compute_code_design_hash(project_root: str) -> str | None:
    return compute_file_hash(project_root, os.path.join("spec", "architecture_code_design.md"))


# 计算项目代码快照的哈希（impl_hash 的一部分）
# 优先用 git status --porcelain + git diff --stat 的输出做哈希
# 非 git 仓库时退化为遍历代码文件的 mtime+size 快照
def compute_code_snapshot_hash(project_root: str) -> str:
    # 尝试用 git 命令获取代码变更快照
    try:
        # 跑 git status --porcelain 拿到仓库脏度（哪些文件改了）
        result = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=project_root, capture_output=True, text=True, timeout=10,
        )
        # git 命令失败（非 git 仓库或 git 未安装）→ 抛异常走 fallback
        if result.returncode != 0:
            raise subprocess.SubprocessError("git status failed")
        # 拿到 porcelain 输出
        porcelain = result.stdout
        # 跑 git diff --stat 拿到变更统计
        diff_stat = subprocess.run(
            ["git", "diff", "--stat"],
            cwd=project_root, capture_output=True, text=True, timeout=10,
        ).stdout
        # 合并两个输出，算 SHA256
        combined = porcelain + "\n" + diff_stat
        return hashlib.sha256(combined.encode("utf-8")).hexdigest()
    # git 命令超时 / git 未安装 / 非 git 仓库 → 走 fallback
    except (subprocess.TimeoutExpired, FileNotFoundError, subprocess.SubprocessError):
        # 收集所有代码文件的信息（路径+大小+mtime）
        code_files = []
        # 遍历项目目录
        for root, dirs, files in os.walk(project_root):
            # 跳过这些目录（不参与代码快照）
            dirs[:] = [d for d in dirs if d not in (".git", ".workflow_loop", "__pycache__", ".venv", "node_modules")]
            # 遍历文件
            for f in files:
                # 只算代码文件
                if f.endswith((".py", ".ts", ".tsx", ".js", ".jsx", ".go", ".rs", ".java", ".kt", ".swift", ".ets")):
                    # 拼出完整路径
                    full_path = os.path.join(root, f)
                    # 拿到文件 stat 信息
                    st = os.stat(full_path)
                    # 收集 路径:大小:mtime
                    code_files.append(f"{full_path}:{st.st_size}:{int(st.st_mtime)}")
        # 排序后算 SHA256（排序保证同一组文件不同顺序产生相同哈希）
        return hashlib.sha256("\n".join(sorted(code_files)).encode("utf-8")).hexdigest()


# 计算 impl 阶段的综合哈希（impl_hash）
# 包含两部分：impl/<topic>.md 内容哈希 + 代码快照哈希
# 在 gate impl --confirmed 时记录；进入 test/acceptance 的第 2 道闸时检查
def compute_impl_hash(project_root: str, topic: str | None) -> str:
    # 收集哈希的各部分
    parts = []
    # 如果有主题（plan/fix_plan 定下后），算 impl/<topic>.md 的文件哈希
    if topic:
        # impl 实施记录文件的路径
        impl_md = os.path.join(project_root, "impl", f"{topic}.md")
        # 算文件内容哈希
        file_hash = compute_file_hash(project_root, os.path.join("impl", f"{topic}.md"))
        # 文件存在 → 加入哈希部分
        if file_hash:
            parts.append(f"impl_md:{file_hash}")
    # 加入代码快照哈希（git status / 文件 mtime+size）
    parts.append(f"code_snapshot:{compute_code_snapshot_hash(project_root)}")
    # 合并所有部分算最终 SHA256
    return hashlib.sha256("\n".join(parts).encode("utf-8")).hexdigest()


# 计算测试计划文件 qa/<topic>_plan.md 的 SHA256
# 在 gate test_plan --confirmed 时记录；test_plan 变化时清零 test 和 acceptance
def compute_test_plan_hash(project_root: str, topic: str | None) -> str | None:
    # 没有主题 → 返回 None（还没到 plan/fix_plan stage）
    if not topic:
        return None
    # 算 qa/<topic>_plan.md 的文件哈希
    return compute_file_hash(project_root, os.path.join("qa", f"{topic}_plan.md"))


# 计算验收计划文件 acceptance/<topic>_plan.md 的 SHA256
# 在 gate acceptance_plan --confirmed 时记录
# acceptance_plan 变化时清零 acceptance 并把 test_plan 退回待检查
def compute_acceptance_plan_hash(project_root: str, topic: str | None) -> str | None:
    # 没有主题 → 返回 None
    if not topic:
        return None
    # 算 acceptance/<topic>_plan.md 的文件哈希
    return compute_file_hash(project_root, os.path.join("acceptance", f"{topic}_plan.md"))


# 计算测试结果文件 qa/<topic>_result.md 的 SHA256
# 在 gate test --confirmed 时记录；test 结果变化时清零 acceptance
def compute_test_result_hash(project_root: str, topic: str | None) -> str | None:
    # 没有主题 → 返回 None
    if not topic:
        return None
    # 算 qa/<topic>_result.md 的文件哈希
    return compute_file_hash(project_root, os.path.join("qa", f"{topic}_result.md"))


# 清零单个 stage 的所有门禁状态（3 道闸全清，状态回 pending）
# 用于 Verification Invalidation：上游变化时清零下游
def clear_stage_gates(stage: StageState) -> None:
    # 重置 3 道闸为全新 GateState（全 False）
    stage.gate = GateState()
    # stage 状态回到 pending（需要重新走 7 步模式）
    stage.status = "pending"


# 检查 Verification Invalidation：上游内容是否变化，变化则清零下游
# 在进入下游 stage 的第 2 道闸（gate 无 flag）时调用
# 返回失效列表：[(变化的源头, 被清零的下游), ...]
def check_invalidation(state: WorkflowState, project_root: str) -> list[tuple[str, str]]:
    # 收集所有失效事件
    invalidations = []
    # 当前 Run 的主题（plan/fix_plan 定下后才有）
    topic = state.topic

    # 检查 1：impl 是否变化（impl_hash）
    if state.verification.impl_hash is not None:
        # 重算当前 impl 哈希
        current_impl = compute_impl_hash(project_root, topic)
        # 哈希不一致 → impl 变了，清零 test 和 acceptance
        if current_impl != state.verification.impl_hash:
            # 清零 test 和 acceptance 的所有门禁
            for stage_name in ["test", "acceptance"]:
                if stage_name in state.stages:
                    clear_stage_gates(state.stages[stage_name])
            # 记录失效事件
            invalidations.append(("impl", "test/acceptance"))

    # 检查 2：test_plan 是否变化（test_plan_hash）
    if state.verification.test_plan_hash is not None:
        # 重算当前 test_plan 哈希
        current_tp = compute_test_plan_hash(project_root, topic)
        # 哈希不一致 → test_plan 变了，清零 test 和 acceptance
        if current_tp != state.verification.test_plan_hash:
            for stage_name in ["test", "acceptance"]:
                if stage_name in state.stages:
                    clear_stage_gates(state.stages[stage_name])
            invalidations.append(("test_plan", "test/acceptance"))

    # 检查 3：acceptance_plan 是否变化（acceptance_plan_hash）
    if state.verification.acceptance_plan_hash is not None:
        # 重算当前 acceptance_plan 哈希
        current_ap = compute_acceptance_plan_hash(project_root, topic)
        # 哈希不一致 → acceptance_plan 变了
        if current_ap != state.verification.acceptance_plan_hash:
            # 清零 acceptance 的所有门禁
            if "acceptance" in state.stages:
                clear_stage_gates(state.stages["acceptance"])
            # 把 test_plan 退回待检查（code_validated 和 user_confirmed 清零，discussion_complete 保留）
            if "test_plan" in state.stages:
                state.stages["test_plan"].gate.code_validated = False
                state.stages["test_plan"].gate.user_confirmed = False
                state.stages["test_plan"].status = "pending"
            # 记录失效事件
            invalidations.append(("acceptance_plan", "acceptance + test_plan"))

    # 返回所有失效事件
    return invalidations
