import argparse
import os
import shutil
import sys
from datetime import datetime

from . import state as state_mod
from . import journal as journal_mod
from . import role_doc as role_doc_mod
from . import project as project_mod
from . import verification as verification_mod
from . import installer as installer_mod
from . import bug_record as bug_record_mod
from . import traceability as traceability_mod
from . import topic as topic_mod
from . import topic_relations as topic_relations_mod
from . import test_runner as test_runner_mod
from . import test_execution as test_execution_mod
from . import test_mapping as test_mapping_mod
from . import acceptance_records as acceptance_records_mod
from . import rollback as rollback_mod
from .verification import (
    compute_code_snapshot_hash,
    compute_non_test_code_snapshot_hash,
    compute_test_code_snapshot_hash,
)
from .path_composer import build_stage_path, INTENT_CHOICES
from .stages import ProjectDesignInitStage
from .stages.base import StageStrategy, clean_spike_tmp

# stdout 分隔线，用于分隔"命令输出"和"下一步指令"
NEXT_STEP_SEPARATOR = "─" * 42
# .workflow_loop 目录名
WORKFLOW_LOOP_DIRNAME = ".workflow_loop"
# 所有 stage 共用的写作规范路径（相对 .workflow_loop/）
GLOBAL_WRITING_STANDARD_PATH = "Standardized_Repository/global/document_writing.md"
# from_scratch 清场时探测的过程产物目录列表（Clean Detect List）
# 这些目录下有文件时需要 --confirm-clean 才能删除
CLEAN_DETECT_DIRS = ["spec", "acceptance", "qa", "impl", "bug"]
# from_scratch 清场时需要一起删除的项目根文件
CLEAN_DETECT_FILES = ["traceability.md"]

STAGE_LABELS = {
    "spec": "产品设计",
    "code_design": "初步代码设计",
    "revise_code_design": "设计期代码设计修订",
    "project_design_init": "项目设计初始化",
    "reproduce": "缺陷复现",
    "spike": "技术不确定性穿刺",
    "acceptance_plan": "验收计划",
    "test_plan": "测试计划",
    "impl": "代码实施",
    "test_code": "测试代码编写",
    "test_execution": "测试执行",
    "topic_acceptance": "主题验收",
    "regression_test": "最终全量回归",
    "overall_acceptance": "整体验收",
    "update_code_design": "详细代码设计收尾",
}


# 打印 stdout 末尾的"下一步"指令（stdout 驱动原则的核心）
# 每条命令结束前都调这个，AI 读 stdout 知道下一步干啥
def print_next_step(instruction: str) -> None:
    # 分隔线 + 下一步指令
    print(f"\n{NEXT_STEP_SEPARATOR}\n下一步：{instruction}")


def stage_label(stage_name: str) -> str:
    """给 stage 标识补充中文含义，避免用户只看到英文代码名。"""
    label = STAGE_LABELS.get(stage_name)
    return f"{stage_name}（{label}）" if label else stage_name


def recovery_instruction(wf_state) -> str | None:
    """返回当前阶段在恢复流程中的动作说明。"""
    summary = verification_mod.recovery_summary(wf_state)
    action = verification_mod.recovery_stage_action(wf_state, wf_state.current_stage)
    if not summary or not action:
        return None
    return f"原因：{summary}。当前不是从头重做，当前阶段要做的是：{action}。"


def print_recovery_details(wf_state) -> None:
    """打印当前退回原因和本阶段动作；没有恢复上下文时不输出。"""
    summary = verification_mod.recovery_summary(wf_state)
    action = verification_mod.recovery_stage_action(wf_state, wf_state.current_stage)
    if not summary or not action:
        return
    print(f"退回原因: {summary}")
    print(f"当前阶段: {stage_label(wf_state.current_stage)}")
    print(f"当前要做: {action}")
    print("说明: 重新经过一个阶段不等于从头重做；先核对旧产出，只有不再符合最新上游时才修改。")


# 根据当前阶段的门禁状态，给出不会跨阶段的下一步
def current_stage_next_instruction(wf_state) -> str:
    stage_name = wf_state.current_stage
    if stage_name == "completed":
        return "调 `workflow done` 标记本次工作流完成"

    stage_state = wf_state.stages.get(stage_name)
    if stage_state is None:
        return "调 `workflow status` 查看当前工作流状态"

    gate = stage_state.gate
    recovery = recovery_instruction(wf_state)
    prefix = f"{recovery} " if recovery else ""
    if not gate.discussion_complete:
        return (
            f"{prefix}调 `workflow discuss` 加载当前 {stage_label(stage_name)}材料；"
            f"讨论完成后调 `workflow gate {stage_name} --discuss-done`"
        )
    if not gate.code_validated:
        if stage_name == "topic_acceptance":
            project_root = resolve_project_root() or os.getcwd()
            progress = acceptance_records_mod.acceptance_progress(project_root, wf_state)
            pending = [line for line in progress if "待验收" in line]
            if pending:
                return (
                    f"{prefix}继续按主题逐条验收；用户回答后调 `workflow acceptance record`。"
                    f"当前待处理：{pending}"
                )
            return (
                f"{prefix}生成或复核全部 `acceptance/<topic>_result.md` 后，"
                "调 `workflow gate topic_acceptance`"
            )
        if stage_name == "impl" and recovery:
            if stage_state.existing_code_accepted_hash is not None:
                return f"{prefix}既有实施代码已经确认，调 `workflow gate impl` 执行实施校验"
            return (
                f"{prefix}如果现有代码已经符合最新计划，先调 "
                "`workflow gate impl --accept-existing-code`；否则修改代码后调 `workflow gate impl`"
            )
        if stage_name == "impl":
            prepared, _, _ = rollback_mod.validate_prepared(
                resolve_project_root() or os.getcwd(),
                wf_state,
            )
            if not prepared:
                return (
                    f"{prefix}先调 `workflow gate impl --prepare-code` 保存实施计划所列文件的修改前内容；"
                    "保存成功后再修改代码"
                )
        if stage_name == "test_code" and recovery:
            if stage_state.existing_test_code_accepted_hash is not None:
                return f"{prefix}既有测试代码已经确认，调 `workflow gate test_code` 执行测试代码校验"
            return (
                f"{prefix}如果现有测试代码已经覆盖最新测试计划，先调 "
                "`workflow gate test_code --accept-existing-test-code`；否则修改测试代码后调 `workflow gate test_code`"
            )
        return (
            f"{prefix}完成当前 {stage_label(stage_name)}的产出文件后，"
            f"调 `workflow gate {stage_name}` 执行校验"
        )
    if not gate.user_confirmed:
        return (
            f"{prefix}用户确认当前 {stage_label(stage_name)}的产出后，"
            f"调 `workflow gate {stage_name} --confirmed`"
        )
    return "调 `workflow status` 查看当前工作流状态"


def restore_recovery_context_from_journal(project_root: str, wf_state) -> bool:
    """为旧 state.json 从 Journal（追加式历史日志）补回退回说明。"""
    if wf_state.recovery.source_stage:
        return False

    first_affected_stage = {
        "acceptance_plan": "acceptance_plan",
        "test_plan": "test_plan",
        "impl": "impl",
        "test_code": "test_code",
        "test_execution": "topic_acceptance",
        "topic_acceptance": "regression_test",
        "regression_test": "regression_test",
    }
    default_reasons = {
        "acceptance_plan": "验收主题或验收条件已经改变，后续计划、代码和结果必须重新核对",
        "test_plan": "测试项、测试方式或测试范围已经改变，后续实施和测试必须重新核对",
        "impl": "实施代码或实施记录已经改变，原测试和验收结果不能继续代表当前实现",
        "test_code": "测试代码、测试配置或统一测试入口已经改变，旧执行记录必须作废",
        "test_execution": "主题测试结果已经改变，旧主题验收和后续结论必须重新确认",
        "topic_acceptance": "主题验收结果已经改变，旧全量回归和整体验收结论不能继续使用",
        "regression_test": "全量回归状态或回归后的代码已经改变，必须重新执行全量回归",
    }
    stage_indexes = {name: index for index, name in enumerate(wf_state.stage_path)}
    current_index = stage_indexes.get(wf_state.current_stage)
    if current_index is None:
        return False

    for entry in reversed(journal_mod.read_all(project_root)):
        action = entry.get("action")
        if action == "验证失效":
            source_stage = entry.get("from_stage")
            target_stage = first_affected_stage.get(source_stage)
            reason = entry.get("reason")
            if reason in {None, "上游内容已变化", "用户确认前发现上游内容已变化"}:
                reason = default_reasons.get(source_stage, "上游内容变化")
        elif action == "流程退回":
            source_stage = entry.get("to_stage")
            target_stage = source_stage
            reason = entry.get("reason") or "用户确认退回"
        else:
            continue
        if not source_stage or target_stage not in stage_indexes:
            continue
        target_index = stage_indexes[target_stage]
        if current_index < target_index:
            continue
        affected_stages = wf_state.stage_path[target_index:]
        if wf_state.current_stage not in affected_stages:
            continue
        verification_mod.set_recovery_context(
            wf_state,
            source_stage,
            affected_stages,
            reason,
        )
        return True
    return False


def clear_completed_material_recovery(project_root: str, wf_state) -> bool:
    """清除已经完成的模板/规范复核提示，并保留 Journal 历史。"""
    recovery = wf_state.recovery
    if not verification_mod.clear_completed_material_recovery(wf_state):
        return False
    journal_mod.append_entry(
        project_root,
        "恢复提示已处理",
        "workflow.py",
        workflow_id=wf_state.workflow_id,
        source_stage=recovery.source_stage,
        reason=recovery.reason,
    )
    state_mod.save_state(project_root, wf_state)
    return True


def ensure_impl_recovery_baseline(project_root: str, wf_state) -> bool:
    """恢复到 impl 时记录当前代码，供后续判断是复用还是重新实施。"""
    if wf_state.current_stage != "impl":
        return False
    if not verification_mod.recovery_summary(wf_state):
        return False
    stage_state = wf_state.stages.get("impl")
    if stage_state is None or stage_state.code_baseline_hash is not None:
        return False
    stage_state.code_baseline_hash = compute_non_test_code_snapshot_hash(project_root)
    journal_mod.append_entry(
        project_root,
        "恢复流程实施代码基线",
        "workflow.py",
        workflow_id=wf_state.workflow_id,
        stage="impl",
        code_snapshot_hash=stage_state.code_baseline_hash,
        reason="恢复流程开始时记录现有代码，后续由用户决定复用还是修改",
    )
    return True


# 从当前工作目录向上查找 .workflow_loop/ 目录，定位项目根
# 日常命令（start/discuss/gate 等）用这个找项目根
# 安装命令（install-project）不用这个，直接用 cwd
def resolve_project_root() -> str | None:
    # 从当前目录开始
    current = os.getcwd()
    # 一直向上找
    while True:
        # 找到 .workflow_loop/ → 返回当前目录作为项目根
        if os.path.exists(os.path.join(current, WORKFLOW_LOOP_DIRNAME)):
            return current
        # 取父目录
        parent = os.path.dirname(current)
        # 到根目录了还没找到 → 返回 None
        if parent == current:
            return None
        # 继续向上
        current = parent


# 加载 .workflow_loop/ 下的 .md 文档内容（discuss 命令用）
# 路径为 None → 返回占位文本；文件不存在 → 返回错误提示
def load_doc_content(project_root: str, rel_path: str | None) -> str:
    # 路径为 None → 该 stage 没有配置文档
    if rel_path is None:
        return "（无文档配置）"
    # 拼完整路径（项目根 + .workflow_loop/ + 相对路径）
    full_path = os.path.join(project_root, WORKFLOW_LOOP_DIRNAME, rel_path)
    # 文件不存在 → 返回错误提示
    if not os.path.exists(full_path):
        return f"（文档 {rel_path} 不存在，请创建后重试）"
    # 读文件内容
    with open(full_path, "r", encoding="utf-8") as f:
        return f.read()


def compute_stage_material_hash(project_root: str, stage: StageStrategy) -> str:
    """计算当前阶段 AI 实际需要阅读的全部材料哈希。"""
    material_paths: list[str] = [GLOBAL_WRITING_STANDARD_PATH]
    if stage.prompt_doc_path():
        material_paths.append(stage.prompt_doc_path())
    if stage.standard_doc_path():
        material_paths.append(stage.standard_doc_path())
    material_paths.append(f"__role__/{stage.name()}")
    for prompt_path, standard_path in stage.additional_doc_paths():
        material_paths.extend([prompt_path, standard_path])
    material_paths.extend(stage.additional_standard_doc_paths())

    parts: list[str] = []
    for relative_path in sorted(set(material_paths)):
        if relative_path.startswith("__role__/"):
            role = role_doc_mod.get_role_doc(stage.name()) or {}
            content = f"{role.get('role', '')}\n{role.get('description', '')}"
        else:
            full_path = os.path.join(project_root, WORKFLOW_LOOP_DIRNAME, relative_path)
            if not os.path.isfile(full_path):
                content = f"<missing:{relative_path}>"
            else:
                with open(full_path, "r", encoding="utf-8") as stream:
                    content = stream.read()
        parts.append(f"{relative_path}\n{content}")
    return verification_mod.hash_text("\n\n".join(parts))


# 记录进入穿刺阶段时的产品设计和代码设计内容哈希
# 新流程只在真正进入 spike 时记录；旧 state.json 已经停在 spike 且没有基线时，明确标记无法还原
# 旧状态里的穿刺产物路径也在这里迁移为新的固定清单路径
def ensure_spike_baseline(
    project_root: str,
    wf_state: state_mod.WorkflowState,
    *,
    capture_if_missing: bool = False,
) -> bool:
    changed = False
    spike_state = wf_state.stages.get("spike")
    expected_artifact_paths = ["spec/spike_index.md"]
    if spike_state is not None and spike_state.artifact_paths != expected_artifact_paths:
        spike_state.artifact_paths = expected_artifact_paths
        changed = True
        journal_mod.append_entry(
            project_root,
            "穿刺状态迁移",
            "workflow.py",
            artifact_paths=expected_artifact_paths,
        )

    if wf_state.spike_baseline.captured_at is not None:
        return changed

    if not capture_if_missing:
        if not wf_state.spike_baseline.legacy_unavailable:
            wf_state.spike_baseline.legacy_unavailable = True
            journal_mod.append_entry(
                project_root,
                "穿刺基线缺失",
                "workflow.py",
                reason="旧工作流没有保存进入 spike 时的设计哈希，不能用当前文件冒充旧基线",
            )
            changed = True
        return changed

    product_hash, product_paths = verification_mod.compute_product_design_hash(project_root)
    wf_state.spike_baseline = state_mod.SpikeBaselineState(
        captured_at=state_mod.now_iso(),
        product_design_hash=product_hash,
        product_design_paths=product_paths,
        code_design_hash=verification_mod.compute_code_design_hash(project_root),
        legacy_unavailable=False,
    )
    journal_mod.append_entry(
        project_root,
        "穿刺设计基线",
        "workflow.py",
        product_design_hash=product_hash,
        product_design_paths=product_paths,
        code_design_hash=wf_state.spike_baseline.code_design_hash,
    )
    return True


def ensure_stage_artifact_baseline(
    project_root: str,
    wf_state: state_mod.WorkflowState,
    stage: StageStrategy,
) -> bool:
    """在开始写产物前保存文件哈希；同一阶段只记录一次。"""
    stage_state = wf_state.stages.get(stage.name())
    if stage_state is None or stage_state.artifact_baseline_captured_at is not None:
        return False

    tracked_paths = stage.change_tracked_paths(project_root)
    if not tracked_paths:
        return False

    stage_state.artifact_baseline_captured_at = state_mod.now_iso()
    stage_state.artifact_baseline_hashes = verification_mod.compute_file_hashes(
        project_root,
        tracked_paths,
    )
    journal_mod.append_entry(
        project_root,
        "阶段产物基线",
        "workflow.py",
        stage=stage.name(),
        artifact_hashes=stage_state.artifact_baseline_hashes,
    )
    return True


def ensure_stage_path_current(project_root: str, wf_state: state_mod.WorkflowState) -> bool:
    """让当前状态中的阶段路径和现行阶段定义保持一致。"""
    stage_instances = build_stage_path(wf_state.intent, project_root)

    # project_design_init（项目设计初始化）只在开工时决定是否加入路径。
    # 本次 Run 已经包含它时，即使项目标记后来变为 true，也要保留本次路径。
    if "project_design_init" in wf_state.stage_path and not any(
        stage.name() == "project_design_init" for stage in stage_instances
    ):
        stage_instances.insert(0, ProjectDesignInitStage())

    expected_names = [stage.name() for stage in stage_instances]
    if wf_state.stage_path == expected_names:
        artifact_paths_changed = False
        for stage in stage_instances:
            stage_state = wf_state.stages.get(stage.name())
            expected_artifacts = stage.artifact_paths()
            if stage_state is not None and stage_state.artifact_paths != expected_artifacts:
                stage_state.artifact_paths = expected_artifacts
                artifact_paths_changed = True
        if artifact_paths_changed:
            journal_mod.append_entry(
                project_root,
                "阶段产物路径迁移",
                "workflow.py",
                stage_path=expected_names,
            )
        return artifact_paths_changed

    old_stages = wf_state.stages
    new_stages = {}
    for stage in stage_instances:
        stage_name = stage.name()
        if stage_name in old_stages:
            stage_state = old_stages[stage_name]
            stage_state.artifact_paths = stage.artifact_paths()
        else:
            stage_state = state_mod.StageState(
                status="pending",
                artifact_paths=stage.artifact_paths(),
                artifact_produced_at=None,
                gate=state_mod.GateState(),
            )
        new_stages[stage_name] = stage_state

    current_stage = "completed"
    for stage_name in expected_names:
        if new_stages[stage_name].status != "done":
            current_stage = stage_name
            break

    for stage_name, stage_state in new_stages.items():
        if stage_state.status != "done":
            stage_state.status = "in_progress" if stage_name == current_stage else "pending"

    previous_path = wf_state.stage_path
    previous_stage = wf_state.current_stage
    wf_state.stage_path = expected_names
    wf_state.stages = new_stages
    wf_state.current_stage = current_stage
    journal_mod.append_entry(
        project_root,
        "阶段路径迁移",
        "workflow.py",
        previous_path=previous_path,
        current_path=expected_names,
        previous_stage=previous_stage,
        current_stage=current_stage,
    )
    return True


# 从 stage 实例列表里找对应 stage 名的策略实例
# discuss 和 gate 命令用这个找当前 stage 的策略
def get_stage_strategy(stage_name: str, state: state_mod.WorkflowState, stage_instances: list[StageStrategy]) -> StageStrategy | None:
    # 遍历 stage 实例列表
    for stage in stage_instances:
        # 名字匹配 → 返回该实例
        if stage.name() == stage_name:
            return stage
    # 没找到
    return None


# 探测项目根下是否有过程产物（from_scratch 清场用）
# 检查 CLEAN_DETECT_DIRS 里的目录是否存在且含文件
# 不监测 .workflow_loop/Template_Repository/ 和 Standardized_Repository/
def detect_clean_artifacts(project_root: str) -> list[str]:
    # 收集有内容的产物目录
    found = []
    # 遍历清场监测清单
    for dir_name in CLEAN_DETECT_DIRS:
        # 拼出目录路径
        dir_path = os.path.join(project_root, dir_name)
        # 目录存在
        if os.path.isdir(dir_path):
            # 检查目录下是否有任何文件（递归遍历）
            has_files = any(
                os.path.isfile(os.path.join(root, f))
                for root, dirs, files in os.walk(dir_path)
                for f in files
            )
            # 有文件 → 加入待删清单
            if has_files:
                found.append(dir_name)
    for file_name in CLEAN_DETECT_FILES:
        if os.path.isfile(os.path.join(project_root, file_name)):
            found.append(file_name)
    # 返回有内容的目录列表
    return found


# 删除项目根下的过程产物（from_scratch --confirm-clean 时调用）
# 删除 CLEAN_DETECT_DIRS 里有文件的目录
def clean_artifacts(project_root: str) -> list[str]:
    # 收集已清理的目录
    cleaned = []
    # 遍历清场监测清单
    for dir_name in CLEAN_DETECT_DIRS:
        # 拼出目录路径
        dir_path = os.path.join(project_root, dir_name)
        # 目录存在
        if os.path.isdir(dir_path):
            # 检查是否有文件
            has_files = any(
                os.path.isfile(os.path.join(root, f))
                for root, dirs, files in os.walk(dir_path)
                for f in files
            )
            # 有文件 → 删除整个目录
            if has_files:
                shutil.rmtree(dir_path)
                cleaned.append(dir_name)
    for file_name in CLEAN_DETECT_FILES:
        file_path = os.path.join(project_root, file_name)
        if os.path.isfile(file_path):
            os.remove(file_path)
            cleaned.append(file_name)
    # 返回已清理的目录列表
    return cleaned


# start 命令：启动工作流或检查状态
# 不带 --intent → 只读状态检查，不初始化 Run
# 带 --intent → 初始化 Run（from_scratch 另循 Clean Confirm）
def cmd_start(args) -> None:
    # 定位项目根
    project_root = resolve_project_root()
    # 找不到 .workflow_loop/ → 项目未安装
    if project_root is None:
        print("错误：找不到 .workflow_loop/ 目录。请先在项目根执行官方安装脚本。")
        sys.exit(1)

    # 检查项目是否已安装（project.json 存在且 installer_version 匹配）
    if not project_mod.is_installed(project_root):
        print("错误：项目未安装。请先在项目根执行官方安装脚本。")
        sys.exit(1)

    # 不带 --intent → 只读状态检查
    if args.intent is None:
        # 读已有 state
        existing = state_mod.load_state(project_root)
        # 有进行中 Run → 提示继续原流程，禁止开新 Run
        if existing is not None and existing.run_status == "active":
            if ensure_stage_path_current(project_root, existing):
                state_mod.save_state(project_root, existing)
            print(f"有进行中 Run（workflow_id: {existing.workflow_id}）")
            print(f"当前 stage: {existing.current_stage}")
            print(f"intent: {existing.intent}")
            print_next_step("调 `workflow status` 查看详情，或先 `workflow done`/`workflow abort` 结束当前 Run")
            return
        # 无进行中 Run → 列出三种意图
        print("无可进行中 Run。可选工作意图：")
        for intent in INTENT_CHOICES:
            print(f"  {intent}")
        print_next_step("根据用户提问确定意图，调 `workflow start --intent from_scratch|product_change|bugfix`")
        return

    # 带 --intent → 初始化 Run
    intent = args.intent

    # Active Run Guard：有进行中 Run → 禁止再 start
    if state_mod.is_active_run(project_root):
        print("错误：有进行中 Run。请先 `workflow done` 或 `workflow abort` 结束当前 Run。")
        sys.exit(1)

    # from_scratch 的 Clean Confirm 两段式
    if intent == "from_scratch":
        # 探测过程产物
        artifacts = detect_clean_artifacts(project_root)
        # 有产物且无 --confirm-clean → 只打印将删清单，不删、不开 Run
        if artifacts and not args.confirm_clean:
            print("检测到以下过程产物目录包含文件；确认后会删除整个目录及其中全部内容：")
            for d in artifacts:
                print(f"  {d}/")
            print("从零做不会保留这些目录中的其他文件。")
            print_next_step("用户确认清场后，调 `workflow start --intent from_scratch --confirm-clean`")
            return
        # 有产物且有 --confirm-clean → 删除产物后继续
        if artifacts and args.confirm_clean:
            cleaned = clean_artifacts(project_root)
            print(f"已清理: {cleaned}")
        # 无论是否发现并删除旧产物，都把 project_design_initialized 置为 false
        project_mod.set_project_design_initialized(project_root, False)

    # 生成 workflow_id：YYYY-MM-DD-HHmm-<intent>
    now = state_mod.now_iso()
    date_part = now[:10]
    # 去掉冒号避免文件名问题
    time_part = now[11:16].replace(":", "")
    workflow_id = f"{date_part}-{time_part}-{intent}"

    # 调 PathComposer 生成 stage 列表
    stages = build_stage_path(intent, project_root)
    # 提取 stage 名列表存入 state.stage_path
    stage_path = [s.name() for s in stages]

    # 初始化每个 stage 的状态
    stages_state = {}
    for stage in stages:
        stages_state[stage.name()] = state_mod.StageState(
            status="pending",
            artifact_paths=stage.artifact_paths(),
            artifact_produced_at=None,
            gate=state_mod.GateState(),
        )
    # 第一个 stage 标记为 in_progress
    first_stage_name = stages[0].name()
    stages_state[first_stage_name].status = "in_progress"

    # 组装 WorkflowState（全集 schema）
    wf_state = state_mod.WorkflowState(
        workflow_id=workflow_id,
        intent=intent,
        run_status="active",
        current_stage=first_stage_name,
        started_at=now,
        stage_path=stage_path,
        stages=stages_state,
        clean_confirmed=args.confirm_clean if intent == "from_scratch" else False,
    )

    # 保存 state.json
    state_mod.save_state(project_root, wf_state)

    # 写 journal：工作流启动
    journal_mod.append_entry(project_root, "工作流启动", "ai",
                            workflow_id=workflow_id, intent=intent)
    # 写 journal：路径生成
    journal_mod.append_entry(project_root, "路径生成", "workflow.py",
                            intent=intent, stage_path=stage_path)
    # 写 journal：清场确认（如果执行了清场）
    if intent == "from_scratch" and args.confirm_clean:
        journal_mod.append_entry(project_root, "清场确认", "workflow.py",
                                cleaned_paths=cleaned if 'cleaned' in dir() else [])

    # 打印路径向开工摘要（不倾倒文档百科）
    print(f"═══ 工作流启动 ═══")
    print(f"workflow_id: {workflow_id}")
    print(f"intent: {intent}")
    print(f"stage_path: {' → '.join(stage_path)}")
    print(f"当前 stage: {first_stage_name}")
    # product_change/bugfix 显示 project_design_initialized 状态
    if intent == "product_change" or intent == "bugfix":
        pdi = project_mod.is_project_design_initialized(project_root)
        print(f"project_design_initialized: {pdi}")

    # 下一步：discuss
    print_next_step("调 `workflow discuss` 加载第一个 stage 提示词")


# discuss 命令：加载全局写作规范 + 当前 stage 的提示词/规范/角色定义，完整输出给 AI
# Prompt Full Print：提示词/规范的消费者是 AI，必须在 stdout 给出完整正文
def cmd_discuss(args) -> None:
    # 定位项目根
    project_root = resolve_project_root()

    if project_root is None:
        print("错误：找不到 .workflow_loop/ 目录。")
        sys.exit(1)

    # 读 state
    wf_state = state_mod.load_state(project_root)
    # state 不存在 → 还没 start
    if wf_state is None:
        print("错误：还没启动工作流。调 `workflow start --intent <意图>` 开始。")
        sys.exit(1)
    # Run 已结束 → 不能 discuss
    if wf_state.run_status != "active":
        print(f"错误：Run 已 {wf_state.run_status}，无法 discuss。")
        sys.exit(1)
    if ensure_stage_path_current(project_root, wf_state):
        state_mod.save_state(project_root, wf_state)
    if restore_recovery_context_from_journal(project_root, wf_state):
        state_mod.save_state(project_root, wf_state)
    clear_completed_material_recovery(project_root, wf_state)
    if ensure_impl_recovery_baseline(project_root, wf_state):
        state_mod.save_state(project_root, wf_state)
    # 工作流已完成
    if wf_state.current_stage == "completed":
        print("错误：工作流已完成。")
        sys.exit(1)

    # 兼容旧状态：已经进入 spike 但没有入场基线时，在加载提示词前标记无法还原
    if wf_state.current_stage == "spike" and ensure_spike_baseline(project_root, wf_state):
        state_mod.save_state(project_root, wf_state)

    # 从 PathComposer 重建 stage 实例列表
    stage_instances = build_stage_path(wf_state.intent, project_root)
    # 找当前 stage 的策略
    stage = get_stage_strategy(wf_state.current_stage, wf_state, stage_instances)
    if stage is None:
        print(f"错误：找不到 stage '{wf_state.current_stage}' 的策略实现")
        sys.exit(1)

    material_hash = compute_stage_material_hash(project_root, stage)
    stage_state = wf_state.stages[stage.name()]
    if (
        stage_state.discussion_material_hash is not None
        and stage_state.discussion_material_hash != material_hash
    ):
        verification_mod.clear_stage_gates(stage_state)
        stage_state.status = "in_progress"
        stage_index = wf_state.stage_path.index(stage.name())
        verification_mod.set_recovery_context(
            wf_state,
            stage.name(),
            wf_state.stage_path[stage_index:],
            "当前阶段的流程模板或规范已经更新，旧讨论结论必须重新确认",
        )
        journal_mod.append_entry(
            project_root,
            "阶段材料变化导致讨论失效",
            "workflow.py",
            workflow_id=wf_state.workflow_id,
            stage=stage.name(),
            previous_material_hash=stage_state.discussion_material_hash,
            current_material_hash=material_hash,
        )
    stage_state.discussion_material_hash = material_hash
    automated_acceptance_records = []
    if stage.name() == "topic_acceptance":
        try:
            automated_acceptance_records = acceptance_records_mod.ensure_automated_records(
                project_root,
                wf_state,
            )
        except ValueError:
            automated_acceptance_records = []
        for record in automated_acceptance_records:
            journal_mod.append_entry(
                project_root,
                "自动化验收记录",
                "workflow.py",
                workflow_id=wf_state.workflow_id,
                topic=record.topic,
                criterion_id=record.criterion_id,
                result=record.result,
                record_id=record.record_id,
                test_ids=record.test_ids,
            )
    if ensure_impl_recovery_baseline(project_root, wf_state):
        state_mod.save_state(project_root, wf_state)
    state_mod.save_state(project_root, wf_state)

    # 加载全局写作规范（所有 stage 共用）
    global_writing_content = load_doc_content(project_root, GLOBAL_WRITING_STANDARD_PATH)
    prompt_path = stage.prompt_doc_path()
    standard_path = stage.standard_doc_path()
    # 加载模版提示词（Prompt Full Print：完整正文）
    print("当前路径：", prompt_path or "内置代码规则")
    prompt_content = load_doc_content(project_root, prompt_path) if prompt_path else None
    # 规范文件只承载需要 AI 阅读的可变写作规则。固定门禁规则直接由代码执行。
    standard_content = load_doc_content(project_root, standard_path) if standard_path else None
    # 加载角色定义
    role_doc = role_doc_mod.get_role_doc(stage.name())

    # 打印 stage 头
    print(f"═══ {stage.name()} stage（{STAGE_LABELS.get(stage.name(), stage.name())}）═══")
    if verification_mod.recovery_summary(wf_state):
        print("\n【为什么重新进入当前阶段】")
        print_recovery_details(wf_state)
    # 打印角色定义
    print(f"\n【角色定义】")
    if role_doc:
        print(f"角色: {role_doc['role']}")
        print(f"描述: {role_doc['description']}")
    else:
        print("（无角色定义）")
    # 打印全局写作规范全文
    print(f"\n【全局写作规范】")
    print(global_writing_content)
    # 打印提示词全文
    if prompt_content is not None:
        print(f"\n【流程模版】")
        print(prompt_content)
    # 打印规范词全文
    if standard_content is not None:
        print(f"\n【流程规范】")
        print(standard_content)

    # 打印附加提示词/规范（project_design_init 加载 spec + code_design 两组）
    for extra_prompt_path, extra_standard_path in stage.additional_doc_paths():
        print(f"\n【附加流程模版: {extra_prompt_path}】")
        print(load_doc_content(project_root, extra_prompt_path))
        print(f"\n【附加流程规范: {extra_standard_path}】")
        print(load_doc_content(project_root, extra_standard_path))

    # 打印只有规范、没有对应产物模板的附加规则。
    for extra_standard_path in stage.additional_standard_doc_paths():
        print(f"\n【代码开发规范: {extra_standard_path}】")
        print(load_doc_content(project_root, extra_standard_path))

    # 打印指令
    print(f"\n【指令】")
    print(stage.instruction())
    # 打印期望产出
    print(f"\n【期望产出】")
    print(f"文件: {stage.artifact_paths()}")
    if stage.name() == "topic_acceptance":
        print("\n【当前主题验收进度】")
        for line in acceptance_records_mod.acceptance_progress(project_root, wf_state):
            print(f"- {line}")

    # 写 journal：提示词加载
    journal_mod.append_entry(project_root, "提示词加载", "workflow.py",
                            workflow_id=wf_state.workflow_id,
                            stage=stage.name(), prompt_doc=stage.prompt_doc_path(),
                            standard_doc=stage.standard_doc_path(),
                            additional_standard_docs=stage.additional_standard_doc_paths(),
                            global_writing_standard=GLOBAL_WRITING_STANDARD_PATH,
                            material_hash=material_hash)
    # 写 journal：角色文档加载
    journal_mod.append_entry(project_root, "角色文档加载", "workflow.py",
                            stage=stage.name())

    print_next_step(
        f"用这个提示词和用户讨论。讨论完用户说'完毕'后，"
        f"调 `workflow gate {stage.name()} --discuss-done`"
    )


def _has_loaded_stage_materials(
    project_root: str,
    workflow_state: state_mod.WorkflowState,
    stage,
) -> bool:
    """确认当前工作流已经通过 workflow discuss 加载当前阶段全部材料。"""

    def belongs_to_current_workflow(entry: dict) -> bool:
        # 新日志直接使用 workflow_id 区分不同工作流。
        entry_workflow_id = entry.get("workflow_id")
        if entry_workflow_id is not None:
            return entry_workflow_id == workflow_state.workflow_id

        # 兼容新增 workflow_id 之前写入的旧日志：
        # 没有 workflow_id 时，只接受当前工作流启动之后的记录，避免误用更早 Run 的记录。
        entry_ts = entry.get("ts")
        if not entry_ts or not workflow_state.started_at:
            return False
        try:
            return datetime.fromisoformat(entry_ts) >= datetime.fromisoformat(workflow_state.started_at)
        except ValueError:
            return False

    required_standard_docs = set(stage.additional_standard_doc_paths())
    current_material_hash = compute_stage_material_hash(project_root, stage)
    saved_material_hash = workflow_state.stages.get(
        stage.name(),
        state_mod.StageState(),
    ).discussion_material_hash
    if saved_material_hash is not None and saved_material_hash != current_material_hash:
        return False
    for entry in reversed(journal_mod.read_all(project_root)):
        if entry.get("action") != "提示词加载":
            continue
        if not belongs_to_current_workflow(entry):
            continue
        if entry.get("stage") != stage.name():
            continue
        if entry.get("prompt_doc") != stage.prompt_doc_path():
            continue
        if entry.get("standard_doc") != stage.standard_doc_path():
            continue
        loaded_standard_docs = set(entry.get("additional_standard_docs", []))
        if (
            required_standard_docs.issubset(loaded_standard_docs)
            and (
                entry.get("material_hash") == current_material_hash
                or saved_material_hash is None
            )
        ):
            return True
    return False


def apply_stage_completion_updates(
    project_root: str,
    wf_state: state_mod.WorkflowState,
    stage_name: str,
) -> list[str]:
    """执行阶段确认后必须落盘的追踪表和缺陷状态更新。"""
    topics = topic_mod.current_workflow_topics(project_root)
    if stage_name in {
        "test_plan",
        "impl",
        "test_execution",
        "topic_acceptance",
        "regression_test",
        "overall_acceptance",
        "update_code_design",
    }:
        detail = traceability_mod.update_for_stage(
            project_root,
            wf_state.workflow_id,
            topics,
            stage_name,
        )
        journal_mod.append_entry(
            project_root,
            "需求交付追踪更新",
            "workflow.py",
            stage=stage_name,
            details=detail,
        )
        updates = [detail]
    else:
        updates = []

    if wf_state.intent != "bugfix":
        return updates

    if stage_name == "topic_acceptance":
        detail = bug_record_mod.record_topic_acceptance_pass(
            project_root,
            wf_state.workflow_id,
            topics,
        )
    elif stage_name == "regression_test":
        detail = bug_record_mod.record_regression_pass(
            project_root,
            wf_state.workflow_id,
            topics,
        )
    elif stage_name == "overall_acceptance":
        detail = bug_record_mod.record_overall_acceptance_pass(
            project_root,
            wf_state.workflow_id,
            topics,
        )
    else:
        return updates

    journal_mod.append_entry(
        project_root,
        "缺陷状态更新",
        "workflow.py",
        stage=stage_name,
        details=detail,
    )
    updates.append(detail)
    return updates


def validate_stage_output(
    project_root: str,
    wf_state: state_mod.WorkflowState,
    stage_name: str,
    stage: StageStrategy,
) -> tuple[bool, str]:
    """执行阶段产物校验；test_plan 额外执行修改前全量测试基线。"""

    if stage_name == "regression_test":
        passed, details = test_runner_mod.run_final_regression(project_root, wf_state)
        journal_mod.append_entry(
            project_root,
            "最终全量回归",
            "workflow.py",
            stage=stage_name,
            passed=passed,
            **test_runner_mod.regression_journal_fields(wf_state),
        )
        state_mod.save_state(project_root, wf_state)
        if not passed:
            return False, details

    passed, details = stage.code_validate(project_root)
    if stage_name != "test_plan" or not passed:
        return passed, details

    baseline_result = test_runner_mod.ensure_test_baseline(project_root, wf_state)
    action = "修改前全量测试复用" if baseline_result.reused else "修改前全量测试"
    journal_mod.append_entry(
        project_root,
        action,
        "workflow.py",
        stage=stage_name,
        passed=baseline_result.passed,
        ran=baseline_result.ran,
        reused=baseline_result.reused,
        **test_runner_mod.baseline_journal_fields(wf_state),
    )
    if not baseline_result.passed:
        return False, f"{details}；{baseline_result.detail}"
    return True, f"{details}；{baseline_result.detail}"


def _load_active_workflow_for_command(project_root: str) -> state_mod.WorkflowState:
    workflow_state = state_mod.load_state(project_root)
    if workflow_state is None:
        print("错误：还没启动工作流")
        sys.exit(1)
    if workflow_state.run_status != "active":
        print(f"错误：Run 已 {workflow_state.run_status}，不能执行当前命令")
        sys.exit(1)
    if restore_recovery_context_from_journal(project_root, workflow_state):
        state_mod.save_state(project_root, workflow_state)
    if ensure_impl_recovery_baseline(project_root, workflow_state):
        state_mod.save_state(project_root, workflow_state)
    return workflow_state


def _test_execution_inputs_are_current(
    project_root: str,
    wf_state: state_mod.WorkflowState,
) -> bool:
    """测试登记和执行前先确认实施结果、计划和测试代码没有失效。"""
    invalidations = verification_mod.check_invalidation(wf_state, project_root)
    if invalidations:
        ensure_impl_recovery_baseline(project_root, wf_state)
        state_mod.save_state(project_root, wf_state)
        for from_stage, to_stages in invalidations:
            journal_mod.append_entry(
                project_root,
                "验证失效",
                "workflow.py",
                from_stage=from_stage,
                to_stage=to_stages,
                reason=wf_state.recovery.reason or "测试登记或执行前发现上游内容变化",
            )
        print("═══ 测试执行前置内容已失效 ═══")
        for from_stage, to_stages in invalidations:
            print(f"{from_stage} 变化，已退回 {to_stages}")
        print_recovery_details(wf_state)
        print_next_step(current_stage_next_instruction(wf_state))
        return False
    if wf_state.verification.test_code_hash is None:
        print("错误：缺少 test_code 确认后的测试代码哈希")
        print_next_step("先完成 test_code 阶段并通过用户确认")
        return False
    return True


def _test_execution_materials_are_loaded(
    project_root: str,
    wf_state: state_mod.WorkflowState,
) -> bool:
    """测试登记和执行只接受本次 workflow discuss 加载的当前材料。"""
    stage = get_stage_strategy(
        "test_execution",
        wf_state,
        build_stage_path(wf_state.intent, project_root),
    )
    if stage is None:
        return False
    stage_state = wf_state.stages.get("test_execution")
    return (
        stage_state is not None
        and stage_state.discussion_material_hash == compute_stage_material_hash(project_root, stage)
    )


def cmd_test_prepare(args) -> None:
    """登记一个测试项的真实 argv 命令，不执行命令。"""
    project_root = resolve_project_root()
    if project_root is None:
        print("错误：找不到 .workflow_loop/ 目录。")
        sys.exit(1)
    wf_state = _load_active_workflow_for_command(project_root)
    if wf_state.current_stage != "test_execution":
        print(f"错误：当前 stage 是 {wf_state.current_stage}，不能登记主题测试命令")
        print_next_step(current_stage_next_instruction(wf_state))
        return
    if not _test_execution_materials_are_loaded(project_root, wf_state):
        print("错误：还没有通过 workflow discuss 加载当前测试执行模板和规范")
        print_next_step("先调 `workflow discuss`，阅读当前测试执行模板和规范")
        return
    if not _test_execution_inputs_are_current(project_root, wf_state):
        return

    command = list(args.command_argv or [])
    if command and command[0] == "--":
        command = command[1:]
    try:
        task = test_execution_mod.prepare_task(
            project_root,
            wf_state,
            args.topic,
            args.tc,
            command,
            args.timeout,
        )
    except ValueError as exc:
        print("═══ 测试命令登记失败 ═══")
        print(f"详情: {exc}")
        print_next_step("补齐测试计划、测试入口或安全命令后重新调 `workflow test prepare`")
        return

    journal_mod.append_entry(
        project_root,
        "测试项任务登记",
        "user",
        workflow_id=wf_state.workflow_id,
        topic=args.topic,
        test_id=args.tc,
        test_entries=task.test_entries,
        command=task.command,
        dependencies=task.dependencies,
        timeout_seconds=task.timeout_seconds,
    )
    state_mod.save_state(project_root, wf_state)
    print("═══ 测试项任务已登记 ═══")
    print(f"主题: {args.topic}")
    print(f"测试项: {args.tc}")
    print(f"测试入口: {', '.join(task.test_entries)}")
    print(f"执行命令: {' '.join(task.command)}")
    print(f"前置测试项: {', '.join(task.dependencies) if task.dependencies else '无'}")
    print(f"超时: {task.timeout_seconds} 秒")
    missing = test_execution_mod.missing_prepared_tasks(project_root, wf_state)
    if missing:
        print_next_step(f"继续登记剩余测试项: {missing}")
    else:
        print_next_step("确认所有测试项和命令后，调 `workflow gate test_execution --discuss-done`")


def cmd_test_run(args) -> None:
    """执行已经登记的主题测试任务。"""
    project_root = resolve_project_root()
    if project_root is None:
        print("错误：找不到 .workflow_loop/ 目录。")
        sys.exit(1)
    wf_state = _load_active_workflow_for_command(project_root)
    if wf_state.current_stage != "test_execution":
        print(f"错误：当前 stage 是 {wf_state.current_stage}，不能执行主题测试")
        print_next_step(current_stage_next_instruction(wf_state))
        return
    if not _test_execution_materials_are_loaded(project_root, wf_state):
        print("错误：当前测试执行材料没有加载，或加载后内容已经变化")
        print_next_step("先调 `workflow discuss`，重新阅读当前测试执行模板和规范")
        return
    if not _test_execution_inputs_are_current(project_root, wf_state):
        return
    stage_state = wf_state.stages.get("test_execution")
    if stage_state is None or not stage_state.gate.discussion_complete:
        print("错误：测试执行任务还没有经过讨论确认")
        print_next_step("先登记全部测试项，再调 `workflow gate test_execution --discuss-done`")
        return
    try:
        attempts = test_execution_mod.run_prepared_tasks(
            project_root,
            wf_state,
            args.parallel,
        )
    except ValueError as exc:
        print("═══ 测试执行未开始 ═══")
        print(f"详情: {exc}")
        print_next_step("补齐测试任务登记后重新调 `workflow test run`")
        return

    print("═══ 主题测试执行完成 ═══")
    print(test_execution_mod.summarize_attempts(attempts))
    for attempt in attempts:
        print(f"- {attempt.topic} / {attempt.test_id}: {attempt.status}")
        if attempt.status != "passed":
            if attempt.error:
                print(f"  原因: {attempt.error}")
            if attempt.output_tail:
                print("  输出摘要:")
                print(attempt.output_tail)
    failed = [attempt for attempt in attempts if attempt.status != "passed"]
    if failed:
        print_next_step("先判断问题属于 impl、test_code、test_plan、acceptance_plan、spec 或临时环境，再调 `workflow return --to ...`")
    else:
        automated_topics = test_mapping_mod.automated_topics(project_root, wf_state.topics)
        if automated_topics:
            print_next_step("根据当前成功记录补齐或复核各主题 qa/<topic>_result.md，再调 `workflow gate test_execution`")
        else:
            print_next_step("当前没有自动化测试结果文件需要生成，直接调 `workflow gate test_execution`")


def cmd_acceptance_record(args) -> None:
    """记录一条人工或混合验收条件的用户回答。"""
    project_root = resolve_project_root()
    if project_root is None:
        print("错误：找不到 .workflow_loop/ 目录。")
        sys.exit(1)
    wf_state = _load_active_workflow_for_command(project_root)
    if wf_state.current_stage != "topic_acceptance":
        print(f"错误：当前 stage 是 {wf_state.current_stage}，不能记录主题验收回答")
        print_next_step(current_stage_next_instruction(wf_state))
        return
    try:
        created = acceptance_records_mod.ensure_automated_records(project_root, wf_state)
        record = acceptance_records_mod.record_user_result(
            project_root,
            wf_state,
            topic=args.topic,
            criterion_id=args.criterion,
            result=args.result,
            actual_result=args.actual_result,
            user_answer=args.answer,
            evidence=args.evidence or "",
        )
    except ValueError as exc:
        print("═══ 主题验收记录失败 ═══")
        print(f"详情: {exc}")
        print_next_step("先把当前问题问清楚；用户确认后再记录，不能直接生成主题验收结果")
        return

    for auto_record in created:
        journal_mod.append_entry(
            project_root,
            "自动化验收记录",
            "workflow.py",
            workflow_id=wf_state.workflow_id,
            topic=auto_record.topic,
            criterion_id=auto_record.criterion_id,
            result=auto_record.result,
            record_id=auto_record.record_id,
            test_ids=auto_record.test_ids,
        )
    action = "人工验收记录" if record.result == "passed" else "主题验收问题记录"
    journal_mod.append_entry(
        project_root,
        action,
        "user",
        workflow_id=wf_state.workflow_id,
        topic=record.topic,
        criterion_id=record.criterion_id,
        result=record.result,
        actual_result=record.actual_result,
        user_answer=record.user_answer,
        evidence=record.evidence,
        confirmed_at=record.confirmed_at,
        record_id=record.record_id,
    )
    state_mod.save_state(project_root, wf_state)
    print("═══ 主题验收回答已记录 ═══" if record.result == "passed" else "═══ 主题验收问题已记录 ═══")
    print(f"主题: {record.topic}")
    print(f"验收条件: {record.criterion_id}")
    print(f"程序记录: {record.record_id}")
    if record.result != "passed":
        print_next_step("先调查问题并和用户确认处理方式，再由用户决定是否 workflow return")
        return
    if acceptance_records_mod.topic_records_complete(project_root, wf_state, record.topic):
        print_next_step(f"生成或复核 `acceptance/{record.topic}_result.md`，再继续其他可验收主题")
    else:
        print_next_step("继续展示当前主题尚未确认的人工验收条件")


def _stage_index_map(wf_state: state_mod.WorkflowState) -> dict[str, int]:
    return {stage_name: index for index, stage_name in enumerate(wf_state.stage_path)}


def _clear_topic_test_state(
    project_root: str,
    wf_state: state_mod.WorkflowState,
    topics: list[str],
) -> None:
    stage_state = wf_state.stages.get("test_execution")
    if stage_state is not None:
        for topic in topics:
            for task in stage_state.test_tasks.get(topic, {}).values():
                task.status = "pending"
                task.current_record = None
                task.last_error = None
            if topic in stage_state.test_tasks:
                del stage_state.test_tasks[topic]
    for topic in topics:
        result_path = os.path.join(project_root, "qa", f"{topic}_result.md")
        if os.path.exists(result_path):
            os.remove(result_path)
        acceptance_path = os.path.join(project_root, "acceptance", f"{topic}_result.md")
        if os.path.exists(acceptance_path):
            os.remove(acceptance_path)
    acceptance_records_mod.clear_topic_records(project_root, wf_state, topics)


def cmd_return(args) -> None:
    """用户确认后把当前工作流退回指定阶段，并清理受影响主题的当前状态。"""
    project_root = resolve_project_root()
    if project_root is None:
        print("错误：找不到 .workflow_loop/ 目录。")
        sys.exit(1)
    wf_state = _load_active_workflow_for_command(project_root)
    stage_indexes = _stage_index_map(wf_state)
    if args.to not in stage_indexes:
        print(f"错误：目标阶段不在当前工作流路径中: {args.to}")
        return
    if wf_state.current_stage not in stage_indexes or stage_indexes[args.to] >= stage_indexes[wf_state.current_stage]:
        print(f"错误：只能退回当前阶段之前的阶段，当前是 {wf_state.current_stage}")
        return
    if not args.reason.strip():
        print("错误：必须说明为什么退回")
        return

    affected_topics = list(dict.fromkeys(args.topic or []))
    if args.all_topics:
        affected_topics = list(wf_state.topics)
    if not affected_topics:
        affected_topics = list(wf_state.topics)
    unknown = sorted(set(affected_topics) - set(wf_state.topics))
    if unknown:
        print(f"错误：受影响主题不属于当前工作流: {unknown}")
        return
    try:
        relations = topic_relations_mod.read_topic_index(
            project_root,
            os.path.join("acceptance", "index.md"),
            wf_state.workflow_id,
            ["展示顺序", "验收主题", "前置主题", "验收计划", "主题验收结果"],
        )
        expanded_topics = topic_relations_mod.expand_dependents(relations, affected_topics)
    except ValueError as exc:
        print("═══ 工作流退回失败 ═══")
        print(f"详情: 无法读取验收主题依赖关系：{exc}")
        print_next_step("先修正 acceptance/index.md 的主题关系后再调 `workflow return`")
        return
    affected_topics = expanded_topics

    # 先确认追踪表能够完成退回更新，再删除测试/验收结果。
    # 否则追踪表错误会留下“state 仍在原阶段、结果文件却已经被删”的半完成状态。
    try:
        trace_detail = traceability_mod.reset_topics_for_return(
            project_root,
            wf_state.workflow_id,
            affected_topics,
            args.to,
        )
    except ValueError as exc:
        print("═══ 工作流退回失败 ═══")
        print(f"详情: {exc}")
        return

    previous_stage = wf_state.current_stage
    downstream_names = wf_state.stage_path[stage_indexes[args.to] :]
    for stage_name in downstream_names:
        stage_state = wf_state.stages[stage_name]
        verification_mod.clear_stage_gates(stage_state)
        stage_state.status = "pending"
    wf_state.current_stage = args.to
    wf_state.stages[args.to].status = "in_progress"
    verification_mod.set_recovery_context(
        wf_state,
        args.to,
        downstream_names,
        args.reason.strip(),
    )
    if ensure_impl_recovery_baseline(project_root, wf_state):
        state_mod.save_state(project_root, wf_state)

    if stage_indexes[args.to] <= stage_indexes.get("test_execution", len(wf_state.stage_path)):
        _clear_topic_test_state(project_root, wf_state, affected_topics)
        wf_state.verification.test_result_hash = None
        wf_state.verification.acceptance_result_hash = None
        wf_state.verification.regression_test_result_hash = None
        wf_state.regression_test = state_mod.RegressionTestState()
    if stage_indexes[args.to] <= stage_indexes.get("test_code", len(wf_state.stage_path)):
        wf_state.verification.test_code_hash = None
    if stage_indexes[args.to] <= stage_indexes.get("test_plan", len(wf_state.stage_path)):
        wf_state.verification.test_plan_hash = None
    if stage_indexes[args.to] <= stage_indexes.get("acceptance_plan", len(wf_state.stage_path)):
        wf_state.verification.acceptance_plan_hash = None
    if stage_indexes[args.to] <= stage_indexes.get("impl", len(wf_state.stage_path)):
        wf_state.verification.impl_hash = None

    journal_mod.append_entry(
        project_root,
        "流程退回",
        "user",
        workflow_id=wf_state.workflow_id,
        from_stage=previous_stage,
        to_stage=args.to,
        topics=affected_topics,
        reason=args.reason.strip(),
        traceability=trace_detail,
    )
    state_mod.save_state(project_root, wf_state)
    print("═══ 工作流已退回 ═══")
    print(f"目标阶段: {args.to}")
    print(f"受影响主题: {', '.join(affected_topics)}")
    print(f"原因: {args.reason.strip()}")
    print(trace_detail)
    print_recovery_details(wf_state)
    print_next_step(current_stage_next_instruction(wf_state))


# gate 命令：3 道闸的总入口 + spike --skip
# --discuss-done：第 1 道闸（讨论完毕）
# 无 flag：第 2 道闸（代码校验 + Verification Invalidation 检查）
# --confirmed：第 3 道闸（用户确认 + 推进 + 记录 hash + 设置架构标记）
def cmd_gate(args) -> None:
    # 定位项目根
    project_root = resolve_project_root()
    if project_root is None:
        print("错误：找不到 .workflow_loop/ 目录。")
        sys.exit(1)

    # 读 state
    wf_state = state_mod.load_state(project_root)
    if wf_state is None:
        print("错误：还没启动工作流")
        sys.exit(1)
    # Run 已结束 → 不能 gate
    if wf_state.run_status != "active":
        print(f"错误：Run 已 {wf_state.run_status}，无法 gate。")
        sys.exit(1)
    if ensure_stage_path_current(project_root, wf_state):
        state_mod.save_state(project_root, wf_state)
    if restore_recovery_context_from_journal(project_root, wf_state):
        state_mod.save_state(project_root, wf_state)
    clear_completed_material_recovery(project_root, wf_state)
    if ensure_impl_recovery_baseline(project_root, wf_state):
        state_mod.save_state(project_root, wf_state)

    # 要过门禁的 stage 名
    stage_name = args.stage

    # 所有门禁只能操作当前正在进行的 stage，不能跨阶段提前标记或推进
    if stage_name not in wf_state.stages:
        print(f"错误：stage '{stage_name}' 不在当前工作流的 stages 里")
        print_next_step(current_stage_next_instruction(wf_state))
        sys.exit(1)
    if stage_name != wf_state.current_stage:
        print(f"错误：当前 stage 是 {wf_state.current_stage}，不能操作 {stage_name} 的门禁")
        requested_stage = wf_state.stages[stage_name]
        if requested_stage.gate.user_confirmed:
            print(
                f"{stage_label(stage_name)}已经完成；你刚才重复调用了它的门禁，"
                f"当前应处理 {stage_label(wf_state.current_stage)}。"
            )
        print_recovery_details(wf_state)
        print_next_step(current_stage_next_instruction(wf_state))
        sys.exit(1)

    # --rebaseline 是实施阶段的显式基线确认，不得和其它门禁动作合用。
    if (
        args.rebaseline
        or args.prepare_code
        or args.accept_existing_code
        or args.accept_existing_test_code
    ) and (
        args.skip or args.discuss_done or args.confirmed
    ):
        print(
            "错误：--rebaseline、--prepare-code、--accept-existing-code 和 "
            "--accept-existing-test-code 不能和其它 gate 参数同时使用"
        )
        sys.exit(1)

    # ── 特殊：--skip（仅 spike）──
    if args.skip:
        # --skip 只适用于 spike stage
        if stage_name != "spike":
            print(f"错误：--skip 仅适用于 spike stage，不适用于 {stage_name}")
            sys.exit(1)
        # 标记 spike 跳过
        wf_state.spike_skipped = True
        # 绕过三道门（全设 True）
        wf_state.stages[stage_name].gate.discussion_complete = True
        wf_state.stages[stage_name].gate.code_validated = True
        wf_state.stages[stage_name].gate.user_confirmed = True
        wf_state.stages[stage_name].status = "done"
        # 找下一个 stage
        stage_names = list(wf_state.stages.keys())
        current_idx = stage_names.index(stage_name)
        # 有下一个 stage → 推进
        if current_idx + 1 < len(stage_names):
            next_stage = stage_names[current_idx + 1]
            wf_state.current_stage = next_stage
            wf_state.stages[next_stage].status = "in_progress"
        # 清理可能存在的临时内容
        cleaned_paths = clean_spike_tmp(project_root)
        # 保存 state
        state_mod.save_state(project_root, wf_state)
        # 写 journal：spike 跳过
        journal_mod.append_entry(project_root, "spike 跳过", "workflow.py",
                                cleaned_paths=cleaned_paths)
        # 写 journal：阶段推进
        journal_mod.append_entry(project_root, "阶段推进", "workflow.py",
                                from_=stage_name, to=wf_state.current_stage)
        # 打印跳过信息
        print(f"═══ {stage_name} 跳过 ═══")
        print(f"进入 {wf_state.current_stage}")
        print_next_step(f"调 `workflow discuss` 加载 {wf_state.current_stage} stage 提示词")
        return

    # 拿 stage 的 gate 状态
    stage_state = wf_state.stages[stage_name]
    gate = stage_state.gate

    # 找到当前阶段策略。第一道门需要它确定哪些文件要记录修改前基线。
    stage_instances = build_stage_path(wf_state.intent, project_root)
    stage = get_stage_strategy(stage_name, wf_state, stage_instances)
    if stage is None:
        print(f"错误：找不到 stage '{stage_name}' 的策略实现")
        sys.exit(1)

    if stage_name == "topic_acceptance":
        try:
            created_records = acceptance_records_mod.ensure_automated_records(
                project_root,
                wf_state,
            )
        except ValueError as exc:
            print("═══ topic_acceptance 自动化验收准备失败 ═══")
            print(f"详情: {exc}")
            print_next_step("先修正验收计划、测试计划或测试结果，再重新进入主题验收")
            return
        for record in created_records:
            journal_mod.append_entry(
                project_root,
                "自动化验收记录",
                "workflow.py",
                workflow_id=wf_state.workflow_id,
                topic=record.topic,
                criterion_id=record.criterion_id,
                result=record.result,
                record_id=record.record_id,
                test_ids=record.test_ids,
            )
        if created_records:
            state_mod.save_state(project_root, wf_state)

    # ── --prepare-code：保存实施计划所列文件的真实修改前内容 ──
    if args.prepare_code:
        if stage_name != "impl":
            print("错误：--prepare-code 只适用于 impl stage")
            sys.exit(1)
        try:
            detail, paths = rollback_mod.prepare_impl(project_root, wf_state)
        except ValueError as exc:
            print("═══ impl 实施前回退基线准备失败 ═══")
            print(f"详情: {exc}")
            print_next_step("修正实施计划中的文件路径或代码基线后，重新调 `workflow gate impl --prepare-code`")
            return
        state_mod.save_state(project_root, wf_state)
        journal_mod.append_entry(
            project_root,
            "实施前文件回退基线",
            "workflow.py",
            workflow_id=wf_state.workflow_id,
            manifest=wf_state.rollback.manifest_path,
            manifest_hash=wf_state.rollback.manifest_hash,
            plan_hash=wf_state.rollback.plan_hash,
            planned_paths=paths,
        )
        print("═══ impl 实施前回退基线已保存 ═══")
        print(detail)
        print(f"计划修改文件: {paths}")
        print_next_step("现在可以按实施计划修改代码；完成实施后记录后调 `workflow gate impl`")
        return

    current_material_hash = compute_stage_material_hash(project_root, stage)
    if (
        gate.discussion_complete
        and (
            (
                stage_state.discussion_material_hash is not None
                and stage_state.discussion_material_hash != current_material_hash
            )
            or (
                stage_name == "test_execution"
                and stage_state.discussion_material_hash is None
            )
        )
    ):
        previous_material_hash = stage_state.discussion_material_hash
        verification_mod.clear_stage_gates(stage_state)
        stage_state.discussion_material_hash = None
        stage_state.status = "in_progress"
        stage_index = wf_state.stage_path.index(stage_name)
        verification_mod.set_recovery_context(
            wf_state,
            stage_name,
            wf_state.stage_path[stage_index:],
            "当前阶段的流程模板或规范已经更新，旧讨论结论必须重新确认",
        )
        journal_mod.append_entry(
            project_root,
            "阶段材料变化导致讨论失效",
            "workflow.py",
            workflow_id=wf_state.workflow_id,
            stage=stage_name,
            previous_material_hash=previous_material_hash,
            current_material_hash=current_material_hash,
        )
        if ensure_impl_recovery_baseline(project_root, wf_state):
            state_mod.save_state(project_root, wf_state)
        state_mod.save_state(project_root, wf_state)
        if not args.discuss_done:
            print(f"═══ {stage_name} 讨论材料已变化 ═══")
            print("旧的讨论确认已经失效，必须重新阅读当前材料")
            print_recovery_details(wf_state)
            print_next_step("先调 `workflow discuss`，阅读更新后的阶段材料")
            return

    # ── --accept-existing-code：用户确认已有代码就是本次实施结果 ──
    if args.accept_existing_code:
        if stage_name != "impl":
            print("错误：--accept-existing-code 只适用于 impl stage")
            sys.exit(1)
        if not gate.discussion_complete:
            print("错误：必须先通过 `workflow gate impl --discuss-done`，才能确认已有代码")
            print_next_step("先完成实施计划讨论，再调 `workflow gate impl --discuss-done`")
            return
        rollback_ok, rollback_detail, _ = rollback_mod.validate_prepared(
            project_root,
            wf_state,
        )
        if not rollback_ok:
            print("═══ impl 既有代码确认失败 ═══")
            print(f"详情: {rollback_detail}")
            print_next_step("先调 `workflow gate impl --prepare-code` 保存当前计划对应的回退清单")
            return
        valid, detail, _ = stage.validate_implementation_records(project_root, wf_state)
        if not valid:
            print("═══ impl 既有代码确认失败 ═══")
            print(f"详情: {detail}")
            print_next_step("补齐实施后记录和追踪表后再调 `workflow gate impl --accept-existing-code`")
            return

        current_hash = compute_non_test_code_snapshot_hash(project_root)
        previous_hash = stage_state.existing_code_accepted_hash
        stage_state.code_baseline_hash = current_hash
        stage_state.existing_code_accepted_hash = current_hash
        journal_mod.append_entry(
            project_root,
            "既有实施代码确认",
            "user",
            workflow_id=wf_state.workflow_id,
            stage=stage_name,
            previous_existing_code_hash=previous_hash,
            code_snapshot_hash=current_hash,
            reason="用户确认当前代码已经是本次需求的实施结果",
        )
        state_mod.save_state(project_root, wf_state)
        print("═══ impl 既有实施代码已确认 ═══")
        print(f"已确认代码快照: {current_hash}")
        print_next_step("调 `workflow gate impl` 做实施代码校验")
        return

    # ── --accept-existing-test-code：用户确认既有测试代码仍覆盖最新测试计划 ──
    if args.accept_existing_test_code:
        if stage_name != "test_code":
            print("错误：--accept-existing-test-code 只适用于 test_code stage")
            sys.exit(1)
        if not gate.discussion_complete:
            print("错误：必须先通过 `workflow gate test_code --discuss-done`，才能确认既有测试代码")
            print_next_step("先调 `workflow discuss` 阅读测试代码流程规范和代码开发规范")
            return
        valid, detail = stage.validate_existing_test_code(project_root)
        if not valid:
            print("═══ test_code 既有测试代码确认失败 ═══")
            print(f"详情: {detail}")
            print_next_step("修改测试代码后调 `workflow gate test_code`，或补齐确认条件后重试")
            return
        current_hash = compute_test_code_snapshot_hash(project_root)
        previous_hash = stage_state.existing_test_code_accepted_hash
        stage_state.existing_test_code_accepted_hash = current_hash
        journal_mod.append_entry(
            project_root,
            "既有测试代码确认",
            "user",
            workflow_id=wf_state.workflow_id,
            stage=stage_name,
            previous_existing_test_code_hash=previous_hash,
            test_code_snapshot_hash=current_hash,
            reason="用户确认当前测试代码已经覆盖最新测试计划",
        )
        state_mod.save_state(project_root, wf_state)
        print("═══ test_code 既有测试代码已确认 ═══")
        print(f"已确认测试代码快照: {current_hash}")
        print_next_step("调 `workflow gate test_code` 做测试代码校验")
        return

    # ── --rebaseline：用户确认当前代码作为新的实施前基线 ──
    if args.rebaseline:
        if stage_name != "impl":
            print("错误：--rebaseline 只适用于 impl stage")
            sys.exit(1)
        if gate.discussion_complete:
            print("错误：impl 的讨论已经完成，不能再重设实施前代码基线")
            print_next_step("按当前 impl 门禁继续，或作废当前 Run 后重新启动工作流")
            sys.exit(1)
        if not _has_loaded_stage_materials(project_root, wf_state, stage):
            print("错误：重设基线前必须先通过 workflow discuss 加载实施阶段的全部材料")
            print_next_step("先调 `workflow discuss`，阅读实施计划模板、实施流程规范和代码开发规范")
            return

        previous_hash = stage_state.code_baseline_hash
        current_hash = compute_non_test_code_snapshot_hash(project_root)
        stage_state.code_baseline_hash = current_hash
        stage_state.existing_code_accepted_hash = None
        journal_mod.append_entry(
            project_root,
            "实施代码基线重设",
            "user",
            workflow_id=wf_state.workflow_id,
            stage=stage_name,
            reason="用户确认当前代码为实施计划确认前的现状基线",
            previous_code_snapshot_hash=previous_hash,
            code_snapshot_hash=current_hash,
        )
        state_mod.save_state(project_root, wf_state)
        print(f"═══ {stage_name} 实施前代码基线已重设 ═══")
        print(f"当前代码基线: {current_hash}")
        print_next_step("确认实施前计划没有继续修改代码后，调 `workflow gate impl --discuss-done`")
        return

    # ── 第 1 道闸：--discuss-done ──
    if args.discuss_done:
        # 兼容旧状态：第一道门前处理产物路径迁移，并标记缺失的入场基线
        if stage_name == "spike" and ensure_spike_baseline(project_root, wf_state):
            state_mod.save_state(project_root, wf_state)
        if (
            stage_name in {"impl", "test_code", "test_execution"}
            and not gate.discussion_complete
            and not _has_loaded_stage_materials(project_root, wf_state, stage)
        ):
            print(f"═══ {stage_name} 讨论完成校验失败 ═══")
            if stage_name == "impl":
                print("详情：还没有通过 workflow discuss 加载实施阶段的全部材料")
                print_next_step("先调 `workflow discuss`，阅读实施计划模板、实施流程规范和代码开发规范")
            elif stage_name == "test_code":
                print("详情：还没有通过 workflow discuss 加载测试代码阶段的流程规范和代码开发规范")
                print_next_step("先调 `workflow discuss`，阅读测试代码流程规范和测试代码开发规范")
            else:
                print(f"详情：还没有通过 workflow discuss 加载 {stage_name} 阶段的当前材料")
                print_next_step(f"先调 `workflow discuss`，阅读 {stage_name} 阶段模板和规范")
            return
        if not gate.discussion_complete:
            valid, detail = stage.discussion_validate(project_root, wf_state)
            if not valid:
                print(f"═══ {stage_name} 讨论完成校验失败 ═══")
                print(f"详情: {detail}")
                print_next_step(f"补齐讨论阶段要求后重新调 `workflow gate {stage_name} --discuss-done`")
                return
        # 已经标记过了 → 提示
        if gate.discussion_complete:
            print(f"提示：{stage_name} 的讨论已经标记完毕了")
        else:
            # 标记讨论完毕
            gate.discussion_complete = True
            stage_state.discussion_material_hash = current_material_hash
            # 写 journal：门禁讨论完毕
            journal_mod.append_entry(project_root, "门禁讨论完毕", "user",
                                    stage=stage_name, passed=True)
        # 讨论结束后、开始写文件前记录基线。重复调用不会覆盖原基线。
        if stage_name == "test_code" and stage_state.test_code_baseline_hash is None:
            stage_state.test_code_baseline_hash = verification_mod.compute_test_code_snapshot_hash(
                project_root,
            )
            stage_state.non_test_code_baseline_hash = verification_mod.compute_non_test_code_snapshot_hash(
                project_root,
            )
            journal_mod.append_entry(
                project_root,
                "测试代码基线",
                "workflow.py",
                stage=stage_name,
                test_code_snapshot_hash=stage_state.test_code_baseline_hash,
                non_test_code_snapshot_hash=stage_state.non_test_code_baseline_hash,
            )
            try:
                rollback_test_paths = rollback_mod.prepare_test_code_baseline(
                    project_root,
                    wf_state,
                )
            except ValueError as exc:
                gate.discussion_complete = False
                stage_state.discussion_material_hash = None
                stage_state.test_code_baseline_hash = None
                stage_state.non_test_code_baseline_hash = None
                state_mod.save_state(project_root, wf_state)
                print("═══ test_code 讨论完成校验失败 ═══")
                print(f"详情: 无法保存测试代码修改前内容：{exc}")
                print_next_step("先修复 impl 的回退清单，再重新调 `workflow gate test_code --discuss-done`")
                return
            journal_mod.append_entry(
                project_root,
                "测试代码回退基线",
                "workflow.py",
                workflow_id=wf_state.workflow_id,
                saved_paths=rollback_test_paths,
                manifest_hash=wf_state.rollback.manifest_hash,
            )
        ensure_stage_artifact_baseline(project_root, wf_state, stage)
        # 保存 gate 和基线
        state_mod.save_state(project_root, wf_state)
        # 打印讨论完毕
        print(f"═══ {stage_name} 讨论完毕 ═══")
        print(f"可以写产出文件了")
        if recovery_instruction(wf_state):
            print_next_step(current_stage_next_instruction(wf_state))
        else:
            if stage_name == "impl":
                print_next_step(
                    "实施前计划已经确认。先调 `workflow gate impl --prepare-code` 保存计划修改文件的原内容，"
                    "保存成功后再修改代码"
                )
            else:
                print_next_step(
                    f"写产出文件 {stage_state.artifact_paths}。"
                    f"写完调 `workflow gate {stage_name}`"
                )
        return

    # ── 第 2 道闸：无 flag（代码校验）──
    if not args.confirmed:
        # 前置检查：discussion_complete 必须为 True
        if not gate.discussion_complete:
            print(f"错误：{stage_name} 还没标记讨论完毕，请先调 "
                  f"`workflow gate {stage_name} --discuss-done`")
            sys.exit(1)

        # 穿刺门2比较设计文档前后变化；旧状态缺少基线时明确标记无法还原
        if stage_name == "spike" and ensure_spike_baseline(project_root, wf_state):
            state_mod.save_state(project_root, wf_state)

        # 兼容旧状态：讨论已经完成但没有记录基线时，从当前文件开始记录。
        # 这样旧文件不能直接通过，必须在记录后再次修改。
        if ensure_stage_artifact_baseline(project_root, wf_state, stage):
            state_mod.save_state(project_root, wf_state)

        # Verification Invalidation 检查：上游 hash 是否变化
        invalidations = verification_mod.check_invalidation(wf_state, project_root)
        # 有失效 → 清零下游，解释哪些阶段只需复核、哪些结果必须重做
        if invalidations:
            ensure_impl_recovery_baseline(project_root, wf_state)
            # 保存清零后的 state
            state_mod.save_state(project_root, wf_state)
            # 写 journal：验证失效
            for from_stage, to_stages in invalidations:
                journal_mod.append_entry(project_root, "验证失效", "workflow.py",
                                        from_stage=from_stage, to_stage=to_stages,
                                        reason=wf_state.recovery.reason or "上游内容已变化")
            # 打印失效信息
            print(f"═══ 验证失效 ═══")
            for from_stage, to_stages in invalidations:
                print(f"  {from_stage} 变化 → 清零 {to_stages}")
            print_recovery_details(wf_state)
            print_next_step(current_stage_next_instruction(wf_state))
            return

        if stage_name == "test_code":
            try:
                changed_test_paths = rollback_mod.finalize_test_code_changes(
                    project_root,
                    wf_state,
                )
            except ValueError as exc:
                print("═══ test_code 回退记录校验失败 ═══")
                print(f"详情: {exc}")
                print_next_step("修复测试代码回退记录后再调 `workflow gate test_code`")
                return
            state_mod.save_state(project_root, wf_state)
            journal_mod.append_entry(
                project_root,
                "测试代码变化登记",
                "workflow.py",
                workflow_id=wf_state.workflow_id,
                changed_paths=changed_test_paths,
                manifest_hash=wf_state.rollback.manifest_hash,
            )

        # 跑 code_validate（第 2 道闸的核心）；test_plan 还会执行修改前全量测试
        passed, details = validate_stage_output(
            project_root,
            wf_state,
            stage_name,
            stage,
        )
        # 写 journal：门禁代码校验
        journal_mod.append_entry(project_root, "门禁代码校验", "workflow.py",
                                stage=stage_name, passed=passed, details=details)

        # 检查产出文件是否存在（写 journal：产出文件检查）
        for artifact in stage_state.artifact_paths:
            full_path = os.path.join(project_root, artifact)
            exists = os.path.exists(full_path)
            journal_mod.append_entry(project_root, "产出文件检查", "workflow.py",
                                    stage=stage_name, artifact=artifact, exists=exists)

        # 校验不通过
        if not passed:
            if (
                stage_name == "regression_test"
                and wf_state.intent == "bugfix"
                and bug_record_mod.has_explicit_regression_failure(
                    project_root,
                    wf_state.workflow_id,
                )
            ):
                try:
                    failure_detail = bug_record_mod.record_regression_failure(
                        project_root,
                        wf_state.workflow_id,
                        topic_mod.current_workflow_topics(project_root),
                    )
                    journal_mod.append_entry(
                        project_root,
                        "缺陷状态更新",
                        "workflow.py",
                        stage=stage_name,
                        details=failure_detail,
                    )
                except ValueError as exc:
                    journal_mod.append_entry(
                        project_root,
                        "缺陷状态更新失败",
                        "workflow.py",
                        stage=stage_name,
                        details=str(exc),
                    )
            # 之前通过过门2，但产物后来被改坏时，旧的通过标记必须失效
            gate.code_validated = False
            gate.user_confirmed = False
            state_mod.save_state(project_root, wf_state)
            print(f"═══ {stage_name} 代码校验失败 ═══")
            print(f"详情: {details}")
            recovery_command_needed = (
                "--accept-existing-code" in details
                or "--accept-existing-test-code" in details
            )
            if recovery_instruction(wf_state) and recovery_command_needed:
                print_next_step(current_stage_next_instruction(wf_state))
            elif recovery_instruction(wf_state):
                print_next_step(
                    f"按上面的具体详情修正当前 {stage_label(stage_name)}，"
                    f"修正后再调 `workflow gate {stage_name}`"
                )
            else:
                print_next_step(f"产出文件未就绪，补完后再调 `workflow gate {stage_name}`")
            return

        # 校验通过
        gate.code_validated = True
        # 标记产出时间
        if stage_state.artifact_produced_at is None:
            stage_state.artifact_produced_at = state_mod.now_iso()
        # 保存 state
        state_mod.save_state(project_root, wf_state)
        # 写 journal：门禁代码校验通过
        journal_mod.append_entry(project_root, "门禁代码校验", "workflow.py",
                                stage=stage_name, passed=True, details=details)
        # 打印校验通过
        print(f"═══ {stage_name} 代码校验通过 ═══")
        print(f"详情: {details}")
        # 下一步：问用户确认
        print_next_step(
            f"问用户'{stage_name} 写完了？'，用户确认后调 "
            f"`workflow gate {stage_name} --confirmed`"
        )
        return

    # ── 第 3 道闸：--confirmed（用户确认 + 推进）──
    # 前置检查：code_validated 必须为 True
    if not gate.code_validated:
        print(f"错误：{stage_name} 还没跑代码校验，请先调 "
              f"`workflow gate {stage_name}`")
        sys.exit(1)

    # 门2通过后文件仍可能变化。门3推进前必须重新检查当前文件，不能只相信旧布尔值。
    invalidations = verification_mod.check_invalidation(wf_state, project_root)
    if invalidations:
        ensure_impl_recovery_baseline(project_root, wf_state)
        state_mod.save_state(project_root, wf_state)
        for from_stage, to_stages in invalidations:
            journal_mod.append_entry(
                project_root,
                "验证失效",
                "workflow.py",
                from_stage=from_stage,
                to_stage=to_stages,
                reason=wf_state.recovery.reason or "用户确认前发现上游内容已变化",
            )
        print("═══ 用户确认前校验失败 ═══")
        for from_stage, to_stages in invalidations:
            print(f"  {from_stage} 变化 → 清零 {to_stages}")
        print_recovery_details(wf_state)
        print_next_step(current_stage_next_instruction(wf_state))
        return

    passed, details = validate_stage_output(
        project_root,
        wf_state,
        stage_name,
        stage,
    )
    journal_mod.append_entry(
        project_root,
        "门禁确认前复核",
        "workflow.py",
        stage=stage_name,
        passed=passed,
        details=details,
    )
    if not passed:
        gate.code_validated = False
        gate.user_confirmed = False
        state_mod.save_state(project_root, wf_state)
        print(f"═══ {stage_name} 用户确认前校验失败 ═══")
        print(f"详情: {details}")
        print_next_step(f"修正文档后重新调 `workflow gate {stage_name}`")
        return

    # 修 bug 在 reproduce（缺陷复现）确认时确定并登记验收主题。
    if stage_name == "reproduce" and wf_state.intent == "bugfix":
        topics = topic_mod.list_reproduce_topics(project_root, wf_state.workflow_id)
        if not topics:
            print("错误：缺陷复现记录没有验收主题")
            print_next_step("在 bug/<缺陷记录>.md 中补充验收主题后重新执行缺陷复现门禁")
            return
        try:
            project_mod.register_topics(project_root, topics)
        except ValueError as exc:
            print(f"错误：{exc}")
            print_next_step("修改重复的主题名称后重新执行缺陷复现门禁")
            return
        wf_state.topics = topics
        wf_state.topic = topics[0] if len(topics) == 1 else None
        journal_mod.append_entry(
            project_root,
            "主题确定",
            "user",
            stage="reproduce",
            topics=topics,
        )

    # acceptance_plan（验收计划）确认时，从计划文件名确定本次全部主题并登记历史。
    # bugfix 主题已经在 reproduce 确认，这里只复核，不再登记或新增。
    elif stage_name == "acceptance_plan":
        if wf_state.intent == "bugfix":
            topics = topic_mod.list_acceptance_index_topics(
                project_root,
                wf_state.workflow_id,
            )
            if not topics:
                print("错误：修 bug 的验收主题必须先在缺陷复现阶段确定")
                print_next_step("返回 reproduce 阶段补充验收主题")
                return
        else:
            topics = topic_mod.list_acceptance_index_topics(
                project_root,
                wf_state.workflow_id,
            )
        if not topics:
            print("错误：没有找到 acceptance/index.md 中的本次验收主题")
            print_next_step("补充 acceptance/index.md 和 acceptance/<topic>_plan.md 后重新执行验收计划门禁")
            return
        if wf_state.intent != "bugfix":
            previous_topics = set(wf_state.topics or ([wf_state.topic] if wf_state.topic else []))
            new_topics = [topic for topic in topics if topic not in previous_topics]
            try:
                project_mod.register_topics(project_root, new_topics)
            except ValueError as exc:
                print(f"错误：{exc}")
                print_next_step("修改重复的主题名称后重新执行验收计划门禁")
                return
        wf_state.topics = topics
        wf_state.topic = topics[0] if len(topics) == 1 else None
        journal_mod.append_entry(
            project_root,
            "主题确定",
            "user",
            topics=topics,
        )

    # 阶段确认前先写入固定的追踪表和缺陷状态；更新失败时不推进阶段。
    try:
        apply_stage_completion_updates(
            project_root,
            wf_state,
            stage_name,
        )
    except ValueError as exc:
        gate.user_confirmed = False
        state_mod.save_state(project_root, wf_state)
        print(f"═══ {stage_name} 固定记录更新失败 ═══")
        print(f"详情: {exc}")
        print_next_step(f"补齐固定记录后重新调 `workflow gate {stage_name} --confirmed`")
        return

    # 标记用户确认
    gate.user_confirmed = True
    # stage 状态改为 done
    stage_state.status = "done"
    # 模板/规范变更触发的恢复只解释触发阶段；该阶段重新确认后不再向后续阶段显示旧原因。
    clear_completed_material_recovery(project_root, wf_state)

    # 调 on_advance 钩子（spike 清理临时代码、样本和原始输出）
    cleaned_paths = stage.on_advance(project_root)
    if stage_name == "spike":
        journal_mod.append_entry(
            project_root,
            "spike 清理",
            "workflow.py",
            cleaned_paths=cleaned_paths,
        )

    # ── 记录 verification hash（验证绑定哈希）──
    # impl 完成后绑定实施代码和实施记录；后续测试阶段只绑定自己的结果。
    if stage_name == "impl":
        wf_state.verification.impl_hash = verification_mod.compute_impl_hash(project_root, wf_state.topics)
        # 实施代码变化后，测试代码、测试执行、主题验收和后续阶段必须重做。
        for sn in ["test_code", "test_execution", "topic_acceptance", "regression_test", "overall_acceptance"]:
            if sn in wf_state.stages:
                verification_mod.clear_stage_gates(wf_state.stages[sn])
        wf_state.verification.test_result_hash = None
        wf_state.verification.acceptance_result_hash = None
        wf_state.verification.test_code_hash = None
    # test_plan stage → 记录 test_plan_hash
    elif stage_name == "test_plan":
        wf_state.verification.test_plan_hash = verification_mod.compute_test_plan_hash(project_root, wf_state.topics)
        wf_state.verification.test_code_hash = None
        wf_state.verification.test_result_hash = None
        wf_state.verification.acceptance_result_hash = None
    # acceptance_plan stage → 记录 acceptance_plan_hash，退 test_plan 待检查
    elif stage_name == "acceptance_plan":
        wf_state.verification.acceptance_plan_hash = verification_mod.compute_acceptance_plan_hash(project_root, wf_state.topics)
        wf_state.verification.test_code_hash = None
        wf_state.verification.test_result_hash = None
        wf_state.verification.acceptance_result_hash = None
        # acceptance_plan 变了 → test_plan 需要重新检查
        if "test_plan" in wf_state.stages:
            wf_state.stages["test_plan"].gate.code_validated = False
            wf_state.stages["test_plan"].gate.user_confirmed = False
            wf_state.stages["test_plan"].status = "pending"
    # test_code stage → 冻结确认后的测试代码、测试配置和统一测试入口。
    elif stage_name == "test_code":
        wf_state.verification.test_code_hash = verification_mod.compute_test_code_snapshot_hash(
            project_root
        )
        wf_state.verification.test_result_hash = None
        wf_state.verification.acceptance_result_hash = None
    # test_execution stage → 记录 test_result_hash
    elif stage_name == "test_execution":
        wf_state.verification.test_result_hash = verification_mod.compute_test_result_hash(project_root, wf_state.topics)
        wf_state.verification.acceptance_result_hash = None
    # topic_acceptance stage → 记录 acceptance_result_hash
    elif stage_name == "topic_acceptance":
        wf_state.verification.acceptance_result_hash = verification_mod.compute_acceptance_result_hash(
            project_root,
            wf_state.topics,
        )
    elif stage_name == "regression_test":
        wf_state.verification.regression_test_result_hash = (
            verification_mod.compute_regression_test_result_hash(project_root)
        )

    # ── 设置 Architecture Gate Marks ──
    # 前段架构 stage → preliminary_done
    if stage_name in ("code_design", "revise_code_design", "project_design_init"):
        wf_state.architecture.preliminary_done = True
        journal_mod.append_entry(project_root, "架构标记", "workflow.py",
                                mark="preliminary_done", stage=stage_name)
    # 末段架构 stage → detailed_done
    if stage_name == "update_code_design":
        wf_state.architecture.detailed_done = True
        journal_mod.append_entry(project_root, "架构标记", "workflow.py",
                                mark="detailed_done", stage=stage_name)

    # ── 设置 project_design_initialized ──
    # project_design_init 完成 → 置 true
    if stage_name == "project_design_init":
        project_mod.set_project_design_initialized(project_root, True)
    # from_scratch 的 code_design 完成 + spec 也完成 → 置 true
    elif stage_name == "code_design" and wf_state.intent == "from_scratch":
        if "spec" in wf_state.stages and wf_state.stages["spec"].gate.user_confirmed:
            project_mod.set_project_design_initialized(project_root, True)
    # from_scratch 的 spec 完成 + code_design 也完成 → 置 true
    elif stage_name == "spec" and wf_state.intent == "from_scratch":
        if "code_design" in wf_state.stages and wf_state.stages["code_design"].gate.user_confirmed:
            project_mod.set_project_design_initialized(project_root, True)

    # 写 journal：门禁用户确认
    journal_mod.append_entry(project_root, "门禁用户确认", "user",
                            stage=stage_name, passed=True)

    # 找下一个 stage
    stage_names = list(wf_state.stages.keys())
    current_idx = stage_names.index(stage_name)

    # 有下一个 stage → 推进
    if current_idx + 1 < len(stage_names):
        next_stage = stage_names[current_idx + 1]
        wf_state.current_stage = next_stage
        wf_state.stages[next_stage].status = "in_progress"
        # 新流程在真正进入 spike 时记录设计基线
        if next_stage == "spike":
            ensure_spike_baseline(project_root, wf_state, capture_if_missing=True)
        if next_stage == "impl":
            wf_state.stages[next_stage].code_baseline_hash = compute_non_test_code_snapshot_hash(project_root)
            journal_mod.append_entry(
                project_root,
                "实施代码基线",
                "workflow.py",
                stage=next_stage,
                code_snapshot_hash=wf_state.stages[next_stage].code_baseline_hash,
            )
        # 保存 state
        state_mod.save_state(project_root, wf_state)
        # 写 journal：阶段推进
        journal_mod.append_entry(project_root, "阶段推进", "workflow.py",
                                from_=stage_name, to=next_stage)
        # 打印完成 + 进入下一 stage
        print(f"═══ {stage_name} 完成 ═══")
        print(f"进入 {next_stage}")
        # 下一步：discuss 下一 stage
        print_recovery_details(wf_state)
        print_next_step(current_stage_next_instruction(wf_state))
    # 没有下一个 stage → 所有 stage 已完成
    else:
        # 临时置 "completed"，由 done 命令确认
        wf_state.current_stage = "completed"
        # 保存 state
        state_mod.save_state(project_root, wf_state)
        # 写 journal：阶段推进到 completed
        journal_mod.append_entry(project_root, "阶段推进", "workflow.py",
                                from_=stage_name, to="completed")
        # 打印完成
        print(f"═══ {stage_name} 完成 ═══")
        print(f"所有 stage 已完成")
        # 下一步：done
        print_next_step("调 `workflow done` 标记完成")


# status 命令：打印 state + journal 摘要；旧状态会先迁移到当前阶段顺序
def cmd_status(args) -> None:
    # 定位项目根
    project_root = resolve_project_root()
    if project_root is None:
        print("找不到 .workflow_loop/ 目录。请先在项目根执行官方安装脚本。")
        return

    # 读 state
    wf_state = state_mod.load_state(project_root)
    if wf_state is None:
        print("还没启动工作流。调 `workflow start` 查看可选意图。")
        return
    if wf_state.run_status == "active" and ensure_stage_path_current(project_root, wf_state):
        state_mod.save_state(project_root, wf_state)
    if restore_recovery_context_from_journal(project_root, wf_state):
        state_mod.save_state(project_root, wf_state)
    clear_completed_material_recovery(project_root, wf_state)
    if ensure_impl_recovery_baseline(project_root, wf_state):
        state_mod.save_state(project_root, wf_state)

    # 打印 state 摘要
    print(f"═══ 工作流状态 ═══")
    print(f"workflow_id: {wf_state.workflow_id}")
    print(f"intent: {wf_state.intent}")
    print(f"run_status: {wf_state.run_status}")
    print(f"当前 stage: {wf_state.current_stage}")
    print(f"主题: {wf_state.topics or '（未定）'}")
    print(f"启动时间: {wf_state.started_at}")
    print(f"结束时间: {wf_state.ended_at or '（未完成）'}")
    print(f"作废时间: {wf_state.aborted_at or '（未作废）'}")
    print(f"spike_skipped: {wf_state.spike_skipped}")
    print(f"架构: preliminary_done={wf_state.architecture.preliminary_done}, detailed_done={wf_state.architecture.detailed_done}")
    if wf_state.rollback.manifest_path:
        print(
            "实施前回退基线: 已准备 "
            f"（{wf_state.rollback.manifest_path}，计划文件 {wf_state.rollback.planned_paths}）"
        )
    else:
        print("实施前回退基线: 未准备")
    if verification_mod.recovery_summary(wf_state):
        print("\n当前处于上游变化后的恢复流程：")
        print_recovery_details(wf_state)
    # 打印每个 stage 的门禁状态
    print(f"\n各阶段门禁状态：")
    for name, stage_state in wf_state.stages.items():
        gate = stage_state.gate
        # 3 道闸用 ✓/✗ 显示
        d = "✓" if gate.discussion_complete else "✗"
        c = "✓" if gate.code_validated else "✗"
        u = "✓" if gate.user_confirmed else "✗"
        # 当前 stage 用 → 标记
        marker = "→" if name == wf_state.current_stage else " "
        print(f"  {marker} {name:20s} [{stage_state.status:12s}] 讨论:{d} 校验:{c} 确认:{u}")
    # 打印 journal 最近 10 条
    print(f"\n最近 journal 记录：")
    recent = journal_mod.read_recent(project_root, count=10)
    for entry in recent:
        print(f"  [{entry.get('ts', '')}] {entry.get('action', '')} ({entry.get('actor', '')})")
    print(f"\n下一步：{current_stage_next_instruction(wf_state)}")


# done 命令：清理临时回退副本，标记 Run 为 completed，写结束时间
# 不再二次确认；保留正式产物；不改写 bug/index.md
def cmd_done(args) -> None:
    # 定位项目根
    project_root = resolve_project_root()
    if project_root is None:
        print("错误：找不到 .workflow_loop/ 目录。")
        sys.exit(1)

    # 读 state
    wf_state = state_mod.load_state(project_root)
    if wf_state is None:
        print("错误：还没启动工作流")
        sys.exit(1)
    # 已经是 completed
    if wf_state.run_status == "completed":
        print("错误：Run 已经是 completed 状态")
        sys.exit(1)
    # 已经是 aborted
    if wf_state.run_status == "aborted":
        print("错误：Run 已经是 aborted 状态")
        sys.exit(1)
    # 前置检查：current_stage 必须是 "completed"（末段 --confirmed 推进后）
    if wf_state.current_stage != "completed":
        print(f"错误：还有未完成的 stage（当前: {wf_state.current_stage}），"
              f"请先完成所有 stage 的 gate --confirmed")
        sys.exit(1)

    try:
        cleaned_snapshots = rollback_mod.cleanup(project_root, wf_state.workflow_id)
    except OSError as exc:
        print("═══ 工作流完成失败 ═══")
        print(f"详情: 无法清理临时回退副本：{exc}")
        print_next_step("保留当前 Run，处理回退目录权限后重新调 `workflow done`")
        return
    wf_state.rollback = state_mod.RollbackState()
    # 标记 Run 为 completed
    wf_state.run_status = "completed"
    # 写结束时间
    wf_state.ended_at = state_mod.now_iso()
    # 保存 state
    state_mod.save_state(project_root, wf_state)
    # 写 journal：Run 完成
    journal_mod.append_entry(project_root, "Run 完成", "workflow.py",
                            workflow_id=wf_state.workflow_id,
                            cleaned_rollback_paths=cleaned_snapshots)

    # 打印完成信息
    print(f"═══ 工作流完成 ═══")
    print(f"workflow_id: {wf_state.workflow_id}")
    print(f"完成时间: {wf_state.ended_at}")
    # 下一步：工作流结束
    print_next_step("工作流完成。本次 workflow 结束。")


# abort 命令：恢复已保存的实施和测试代码文件，再将进行中的 Run 正式中止
# 保留正式过程文档和 state.json；成功后删除临时回退副本
def cmd_abort(args) -> None:
    # 定位项目根
    project_root = resolve_project_root()
    if project_root is None:
        print("错误：找不到 .workflow_loop/ 目录。")
        sys.exit(1)

    # 读 state
    wf_state = state_mod.load_state(project_root)
    if wf_state is None:
        print("错误：还没启动工作流")
        sys.exit(1)
    # 前置检查：只有 active 可以 abort
    if wf_state.run_status != "active":
        print(f"错误：Run 状态为 {wf_state.run_status}，无法 abort（仅 active 可 abort）")
        sys.exit(1)

    restored_paths: list[str] = []
    impl_state = wf_state.stages.get("impl")
    if wf_state.rollback.manifest_path and wf_state.rollback.restored_at is None:
        try:
            restored_paths = rollback_mod.restore(project_root, wf_state)
        except ValueError as exc:
            journal_mod.append_entry(
                project_root,
                "Run 中止回退失败",
                "workflow.py",
                workflow_id=wf_state.workflow_id,
                reason=str(exc),
            )
            print("═══ 工作流中止失败 ═══")
            print(f"详情: {exc}")
            print_next_step("先处理无法安全回退的文件；回退副本已保留，当前 Run 仍是 active")
            return
        wf_state.rollback.restored_at = state_mod.now_iso()
        state_mod.save_state(project_root, wf_state)
        journal_mod.append_entry(
            project_root,
            "Run 中止代码已恢复",
            "workflow.py",
            workflow_id=wf_state.workflow_id,
            restored_paths=restored_paths,
            restored_at=wf_state.rollback.restored_at,
        )
    elif (
        wf_state.rollback.restored_at is None
        and
        impl_state is not None
        and impl_state.code_baseline_hash is not None
        and compute_non_test_code_snapshot_hash(project_root) != impl_state.code_baseline_hash
    ):
        print("═══ 工作流中止失败 ═══")
        print("详情: 实施代码已经变化，但当前 Run 没有保存真实文件副本，不能安全回退")
        print_next_step("不要手工标记中止；先确认缺失副本的代码怎样恢复")
        return

    try:
        cleaned_snapshots = rollback_mod.cleanup(project_root, wf_state.workflow_id)
    except OSError as exc:
        journal_mod.append_entry(
            project_root,
            "Run 中止清理失败",
            "workflow.py",
            workflow_id=wf_state.workflow_id,
            reason=str(exc),
            restored_paths=restored_paths,
        )
        print("═══ 工作流中止失败 ═══")
        print(f"详情: 代码已经恢复，但临时回退副本清理失败：{exc}")
        print_next_step("处理回退目录权限后重新调 `workflow abort`，当前 Run 仍是 active")
        return
    wf_state.rollback = state_mod.RollbackState()
    # 标记 Run 为 aborted
    wf_state.run_status = "aborted"
    # 写作废时间
    wf_state.aborted_at = state_mod.now_iso()
    # 保存 state（不删除，保留本次中止历史）
    state_mod.save_state(project_root, wf_state)
    # 写 journal：Run 作废
    journal_mod.append_entry(project_root, "Run 作废", "workflow.py",
                            workflow_id=wf_state.workflow_id,
                            restored_paths=restored_paths,
                            cleaned_rollback_paths=cleaned_snapshots)

    # 打印作废信息
    print(f"═══ 工作流作废 ═══")
    print(f"workflow_id: {wf_state.workflow_id}")
    print(f"作废时间: {wf_state.aborted_at}")
    if restored_paths:
        print(f"已恢复实施前代码文件: {restored_paths}")
    # 下一步：可重新开新 Run
    print_next_step(f"Run 已作废。可重新调 `workflow start --intent {wf_state.intent}` 开新 Run")


# install-project 命令：安装当前项目（由 install.sh 调用）
# 项目根用 cwd（install.sh 已确认目录）
def cmd_install_project(args) -> None:
    # 项目根 = 当前工作目录
    project_root = os.getcwd()
    # 调 installer 安装项目
    code = installer_mod.install_project(project_root)
    # 退出
    sys.exit(code)


# CLI 入口：解析参数、分发到对应 handler
def main() -> None:
    # 创建 argparse 解析器
    parser = argparse.ArgumentParser(
        description="workflow_loop 工作流管理 CLI",
        prog="workflow",
    )
    # 子命令
    subparsers = parser.add_subparsers(dest="command", help="可用命令")

    # start 命令
    start_parser = subparsers.add_parser("start", help="启动工作流或检查状态")
    # --intent：工作意图（不带时只读状态检查）
    start_parser.add_argument("--intent", choices=INTENT_CHOICES, default=None,
                             help="工作意图（不带时只读状态检查）")
    # --confirm-clean：从零做清场确认（仅 from_scratch）
    start_parser.add_argument("--confirm-clean", action="store_true",
                             help="从零做清场确认（仅 from_scratch）")

    # discuss 命令（无参数，读 state.current_stage）
    subparsers.add_parser("discuss", help="加载当前 stage 提示词")

    # test 命令：测试执行阶段先登记真实命令，再正式执行。
    test_parser = subparsers.add_parser("test", help="登记或执行主题测试")
    test_subparsers = test_parser.add_subparsers(dest="test_action", required=True)
    test_prepare_parser = test_subparsers.add_parser("prepare", help="登记一个测试项的真实命令")
    test_prepare_parser.add_argument("--topic", required=True, help="验收主题名称")
    test_prepare_parser.add_argument("--tc", required=True, help="测试项编号，例如 TC-01")
    test_prepare_parser.add_argument(
        "--timeout",
        type=int,
        default=test_execution_mod.DEFAULT_TIMEOUT_SECONDS,
        help="单个测试项超时秒数，默认 600",
    )
    test_prepare_parser.add_argument(
        "command_argv",
        nargs=argparse.REMAINDER,
        help="在 -- 后写实际测试命令及参数",
    )
    test_run_parser = test_subparsers.add_parser("run", help="执行尚无当前成功记录的已登记主题测试")
    test_run_parser.add_argument(
        "--parallel",
        type=int,
        default=None,
        help="最多并行执行的独立主题数；默认读取 project.json 的 test_parallelism",
    )

    # acceptance 命令：用户在聊天中回答后，由 AI 记录当前 AC 的验收事实。
    acceptance_parser = subparsers.add_parser("acceptance", help="记录主题验收回答")
    acceptance_subparsers = acceptance_parser.add_subparsers(
        dest="acceptance_action",
        required=True,
    )
    acceptance_record_parser = acceptance_subparsers.add_parser(
        "record",
        help="记录一条人工或混合验收条件",
    )
    acceptance_record_parser.add_argument("--topic", required=True, help="验收主题名称")
    acceptance_record_parser.add_argument(
        "--criterion",
        required=True,
        help="验收条件编号，例如 AC-01",
    )
    acceptance_record_parser.add_argument(
        "--result",
        required=True,
        choices=("passed", "failed", "blocked"),
        help="验收结果：passed（通过）、failed（未通过）、blocked（无法继续验证）",
    )
    acceptance_record_parser.add_argument(
        "--actual-result",
        required=True,
        help="验收者实际观察到的结果",
    )
    acceptance_record_parser.add_argument(
        "--answer",
        required=True,
        help="验收者的实际回答",
    )
    acceptance_record_parser.add_argument(
        "--evidence",
        default="",
        help="可选证据说明；没有独立证据时可以省略",
    )

    # gate 命令
    gate_parser = subparsers.add_parser("gate", help="过门禁")
    # stage 名（位置参数）
    gate_parser.add_argument("stage", help="stage 名")
    # --discuss-done：第 1 道闸
    gate_parser.add_argument("--discuss-done", action="store_true",
                             help="标记讨论完毕（第 1 道闸）")
    # --confirmed：第 3 道闸
    gate_parser.add_argument("--confirmed", action="store_true",
                             help="用户确认 + 推进（第 3 道闸）")
    # --skip：跳过 stage（仅 spike）
    gate_parser.add_argument("--skip", action="store_true",
                             help="跳过 stage（仅 spike）")
    # --rebaseline：用户确认当前代码作为 impl 的新实施前基线
    gate_parser.add_argument("--rebaseline", action="store_true",
                             help="重设 impl 实施前代码基线（仅用户确认后使用）")
    gate_parser.add_argument(
        "--prepare-code",
        action="store_true",
        help="保存 impl 计划修改文件的真实修改前内容，供整个 Run 中止时回退",
    )
    # --accept-existing-code：用户确认代码在计划确认前已经是本次实施结果
    gate_parser.add_argument("--accept-existing-code", action="store_true",
                             help="确认当前已有代码就是本次实施结果（仅 impl）")
    # --accept-existing-test-code：上游计划变化后确认现有测试代码仍然适用
    gate_parser.add_argument(
        "--accept-existing-test-code",
        action="store_true",
        help="确认当前已有测试代码仍覆盖最新测试计划（仅 test_code）",
    )
    # status 命令（旧状态可能先迁移阶段路径）
    subparsers.add_parser("status", help="打印状态摘要")
    # done 命令
    subparsers.add_parser("done", help="标记完成")
    # abort 命令
    subparsers.add_parser("abort", help="作废当前 Run")

    # return 命令：测试失败或发现上游问题时，由用户确认后退回对应阶段。
    return_parser = subparsers.add_parser("return", help="退回当前阶段之前的指定阶段")
    return_parser.add_argument(
        "--to",
        required=True,
        choices=("spec", "acceptance_plan", "test_plan", "impl", "test_code"),
        help="退回目标阶段",
    )
    return_parser.add_argument(
        "--topic",
        action="append",
        help="受影响主题；可重复填写。未填写时默认当前全部主题",
    )
    return_parser.add_argument(
        "--all-topics",
        action="store_true",
        help="明确标记当前全部主题都受影响",
    )
    return_parser.add_argument("--reason", required=True, help="退回原因")

    # install-project 命令（由 install.sh 调用）
    subparsers.add_parser("install-project", help="安装当前项目（由 install.sh 调用）")

    # 解析参数
    args = parser.parse_args()

    # 没传命令 → 打印 help
    if args.command is None:
        parser.print_help()
        sys.exit(1)

    # 分发到对应 handler
    if args.command == "start":
        cmd_start(args)
    elif args.command == "discuss":
        cmd_discuss(args)
    elif args.command == "test":
        if args.test_action == "prepare":
            cmd_test_prepare(args)
        else:
            cmd_test_run(args)
    elif args.command == "acceptance":
        cmd_acceptance_record(args)
    elif args.command == "gate":
        cmd_gate(args)
    elif args.command == "status":
        cmd_status(args)
    elif args.command == "done":
        cmd_done(args)
    elif args.command == "abort":
        cmd_abort(args)
    elif args.command == "return":
        cmd_return(args)
    elif args.command == "install-project":
        cmd_install_project(args)
    else:
        # 未知命令（argparse 应该已经拦了，这是兜底）
        print(f"未知命令: {args.command}")
        parser.print_help()
        sys.exit(1)


# 脚本直接运行时调 main
if __name__ == "__main__":
    main()
