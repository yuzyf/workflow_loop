import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
from datetime import datetime

from . import PRODUCT_IDENTITY
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
from . import test_entry as test_entry_mod
from . import test_execution as test_execution_mod
from . import test_mapping as test_mapping_mod
from . import acceptance_records as acceptance_records_mod
from . import rollback as rollback_mod
from . import stage_materials as stage_materials_mod
from . import artifact_paths as artifact_paths_mod
from . import spike_validation as spike_validation_mod
from .stage_materials import MaterialError
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
CLEAN_DETECT_FILES = [artifact_paths_mod.TRACEABILITY_DOC]

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
    "update_code_design": "最终产品、架构与代码设计同步",
}

PYPI_JSON_URL = "https://pypi.org/pypi/workflow-loop/json"
GITHUB_API_URL = "https://api.github.com/repos/yuzyf/workflow_loop"
GITHUB_RELEASE_URL = "https://github.com/yuzyf/workflow_loop/releases"
MAINTENANCE_USER_AGENT = "workflow-loop-maintenance"


# 打印 stdout 末尾的"下一步"指令（stdout 驱动原则的核心）
# 每条命令结束前都调这个，AI 读 stdout 知道下一步干啥
def print_next_step(instruction: str) -> None:
    # 分隔线 + 下一步指令
    print(f"\n{NEXT_STEP_SEPARATOR}\n下一步：{instruction}")


def stage_label(stage_name: str) -> str:
    """给 stage 标识补充中文含义，避免用户只看到英文代码名。"""
    label = STAGE_LABELS.get(stage_name)
    return f"{stage_name}（{label}）" if label else stage_name


def confirmation_next_step(stage_name: str) -> str:
    """第二道门通过后，用用户真正需要判断的问题说明第三道门。"""
    command = f"`workflow gate {stage_name} --confirmed`"
    if stage_name == "regression_test":
        return (
            "把刚才程序真实执行的全量测试命令、退出码和输出摘要交给用户查看，"
            f"问“这条实际结果是否可用于继续”；用户确认后由 AI 执行 {command}"
        )
    if stage_name == "overall_acceptance":
        return (
            "把全部主题验收结果和最终全量回归结果交给用户查看，"
            f"问“全部主题组合后是否已经完成这次需求”；用户确认后由 AI 执行 {command}"
        )
    if stage_name == "update_code_design":
        return (
            "把最终产品说明、代码架构设计和真实代码核对结果交给用户查看；"
            f"用户确认后由 AI 执行 {command}，随后立即执行 `workflow done`（正式收工），"
            "不再重复询问"
        )
    return (
        f"把当前 {stage_label(stage_name)}的程序检查结果和产出交给用户查看；"
        f"用户明确同意后由 AI 执行 {command}（第三道门：记录用户确认并进入下一环节）"
    )


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
            "（第一道门：只记录当前问题已经聊清楚，可以开始产出）"
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
                f"{prefix}生成或复核全部 `acceptance/<主题文件标识>_验收结果.md` 后，"
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
            f"调 `workflow gate {stage_name}`（不带选项，第二道门：程序检查固定事实）"
        )
    if not gate.user_confirmed:
        return f"{prefix}{confirmation_next_step(stage_name)}"
    return "调 `workflow status` 查看当前工作流状态"


def restore_recovery_context_from_journal(project_root: str, wf_state) -> bool:
    """为旧 state.json 从 Journal（追加式历史日志）补回退回说明。"""
    if wf_state.recovery.source_stage:
        return False

    journal_entries = journal_mod.read_all(project_root)
    handled_recovery_ids = {
        entry.get("recovery_created_at")
        for entry in journal_entries
        if entry.get("action") == "恢复提示已处理"
        and entry.get("recovery_created_at")
        and entry.get("workflow_id") in (None, wf_state.workflow_id)
    }

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

    for entry in reversed(journal_entries):
        entry_workflow_id = entry.get("workflow_id")
        if entry_workflow_id not in (None, wf_state.workflow_id):
            continue
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
        recovery_created_at = entry.get("recovery_created_at")
        if recovery_created_at and recovery_created_at in handled_recovery_ids:
            continue
        if not source_stage or target_stage not in stage_indexes:
            continue
        target_index = stage_indexes[target_stage]
        if current_index < target_index:
            continue
        # 兼容没有 recovery_created_at 的旧 Journal：源阶段已经完成时，
        # 说明这条历史原因已经处理过，不再重新恢复为当前提示。
        source_state = wf_state.stages.get(source_stage)
        if not recovery_created_at and source_state is not None and source_state.status == "done":
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
    """清除已经完成的恢复提示，并保留带关联标识的 Journal 历史。"""
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
        recovery_created_at=recovery.created_at,
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
# 安装命令（_install-project）不用这个，直接用 cwd
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


def compute_stage_material_hash(project_root: str, stage: StageStrategy) -> str:
    """计算当前阶段材料清单的内容指纹。

    指纹覆盖阶段模板、工作规范、全局写作规范、角色说明、内置阶段任务和附加材料；
    材料缺失、不是普通文件或不可读时抛 MaterialError，调用方不得登记材料记录。
    """
    return stage_materials_mod.compute_fingerprint(
        project_root,
        stage.name(),
        role_doc_mod.get_role_doc(stage.name()),
        stage.instruction(),
        stage.materials(),
    )


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
    expected_artifact_paths = [artifact_paths_mod.SPIKE_INDEX_DOC]
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
# 不带 --intent → 只读状态检查，不初始化 Run、不写任何文件
# 带 --intent → 初始化 Run（from_scratch 另循 Clean Confirm 与清场开工事务）
INTENT_LABELS = {
    "from_scratch": "从零做：几乎空着手交付新能力或新项目",
    "product_change": "改产品：在已有产品上修改设计或增加功能",
    "bugfix": "修 bug：定位并修复一个具体缺陷",
}


def refuse_if_pending_start_transaction(project_root: str) -> None:
    """未完成的清场开工事务存在时，任何日常命令都不得继续正常流程。"""
    transaction = rollback_mod.read_start_transaction(project_root)
    if transaction is None:
        return
    print("错误：发现未完成的清场开工事务，项目可能处于清场到一半的状态。")
    print_next_step(
        "由 AI 执行 `workflow start`（开工检查）：程序会按事务记录先把项目恢复到开工前状态，"
        "恢复成功后才能继续正常流程"
    )
    sys.exit(1)


def _restore_start_failure(project_root: str, workflow_id: str, manifest: dict) -> list[str]:
    """开工事务中任一步失败后，恢复受管文档、项目字段和开工前状态。

    返回未能恢复的说明列表；为空表示恢复完整（此时清理事务记录和本轮副本）。
    """
    restored, failures = rollback_mod.restore_start_baseline(project_root, workflow_id)
    try:
        project_mod.restore_managed_fields(
            project_root,
            manifest.get("project_fields") or {},
        )
    except (OSError, ValueError) as exc:
        failures.append(f"project.json 项目字段（{exc}）")

    state_path = os.path.join(project_root, WORKFLOW_LOOP_DIRNAME, "state.json")
    previous_state_raw = manifest.get("previous_state_raw")
    try:
        if previous_state_raw is None:
            if os.path.exists(state_path):
                os.remove(state_path)
        else:
            with open(state_path, "w", encoding="utf-8") as stream:
                stream.write(previous_state_raw)
    except (OSError, ValueError) as exc:
        failures.append(f"state.json（{exc}）")

    if not failures:
        rollback_mod.clear_start_transaction(project_root)
        rollback_mod.cleanup(project_root, workflow_id)
    return failures


def handle_pending_start_transaction(project_root: str) -> bool:
    """workflow start 先识别并处理未完成的开工事务；返回是否可以继续。"""
    transaction = rollback_mod.read_start_transaction(project_root)
    if transaction is None:
        return True
    if transaction.get("status") == "committed":
        # 上次开工已成功，只是事务记录没来得及删除 → 只完成清理，不回退已经启动的 Run
        rollback_mod.clear_start_transaction(project_root)
        print("上一次开工事务已经成功，只清理了遗留的事务记录。")
        return True
    workflow_id = transaction.get("workflow_id")
    print("发现未完成的清场开工事务，先把项目恢复到开工前状态...")
    manifest = rollback_mod.read_start_baseline(project_root, workflow_id or "") or {}
    failures = _restore_start_failure(project_root, workflow_id or "", manifest)
    if failures:
        print("恢复不完整，以下内容未恢复（事务记录和副本已保留）：")
        for item in failures:
            print(f"  - {item}")
        print_next_step("先人工检查上述路径，再重新执行 `workflow start`")
        return False
    print("已恢复到开工前状态。")
    return True


def cmd_start(args) -> None:
    # 定位项目根
    project_root = resolve_project_root()
    # 找不到 .workflow_loop/ → 项目未安装（异常保护，不是正常业务分支）
    if project_root is None:
        print("错误：找不到 .workflow_loop/ 目录。请先在项目根执行官方安装脚本。")
        sys.exit(1)

    # 校验完整骨架和安装版本标记；失败时立即报错，不读取或创建 state.json
    if not project_mod.is_installed(project_root):
        print("错误：项目安装骨架不完整或版本异常。请先在项目根执行官方安装脚本。")
        sys.exit(1)

    # 未完成的清场开工事务：start 负责先恢复，恢复失败则停止
    if not handle_pending_start_transaction(project_root):
        sys.exit(1)

    # 不带 --intent → 只读状态检查：只读取工作状态并指路，不写任何文件
    if args.intent is None:
        existing = state_mod.load_state(project_root)
        # 有进行中 Run → 说明须继续原流程，禁止提示开新 Run
        if existing is not None and existing.run_status == "active":
            print(f"有进行中的工作轮次（编号: {existing.workflow_id}）")
            print(f"当前环节: {stage_label(existing.current_stage)}")
            intent_label = INTENT_LABELS.get(existing.intent, existing.intent)
            print(f"工作意图: {existing.intent}（{intent_label.split('：')[0]}）")
            print_next_step(
                "由 AI 执行 `workflow status` 查看详情并继续当前环节；"
                "用户想结束本轮时，由 AI 执行 `workflow done`（正式收工）或 "
                "`workflow abort`（整轮作废并恢复项目内容）"
            )
            return
        # 无进行中 Run → 列出三种意图及一句话说明
        print("当前没有进行中的工作轮次。可选工作意图：")
        for intent in INTENT_CHOICES:
            print(f"  {intent}（{INTENT_LABELS.get(intent, intent)}）")
        print_next_step(
            "AI 根据用户需求确认工作意图后，执行 "
            "`workflow start --intent from_scratch|product_change|bugfix` 开始新一轮工作；"
            "这一步只初始化流程状态，不修改产品代码"
        )
        return

    # 带 --intent → 初始化 Run
    intent = args.intent

    # Active Run Guard：有进行中 Run → 禁止再 start
    if state_mod.is_active_run(project_root):
        print("错误：有进行中 Run。请先 `workflow done` 或 `workflow abort` 结束当前 Run。")
        sys.exit(1)

    # from_scratch 的 Clean Confirm 两段式：先探测，有产物且未确认时只打印清单
    clean_targets: list[str] = []
    if intent == "from_scratch":
        clean_targets = detect_clean_artifacts(project_root)
        if clean_targets and not args.confirm_clean:
            print("检测到以下过程产物包含内容；确认后会删除命中的整个目录及其中全部内容：")
            for item in clean_targets:
                suffix = "/" if not item.endswith(".md") else ""
                print(f"  {item}{suffix}")
            print("从零做表示真正重新做：这些目录中即使有非工作流文件也会一起删除。")
            print("本次尚未删除任何内容，也没有开始新轮次。")
            print_next_step(
                "AI 向用户说明以上将删清单；用户同意清场后，AI 执行 "
                "`workflow start --intent from_scratch --confirm-clean` 完成清场并开工"
            )
            return

    # 生成 workflow_id：YYYY-MM-DD-HHmm-<intent>
    now = state_mod.now_iso()
    date_part = now[:10]
    # 去掉冒号避免文件名问题
    time_part = now[11:16].replace(":", "")
    workflow_id = f"{date_part}-{time_part}-{intent}"

    # 新轮次第一次持久写入前：保存受管正式文档、项目字段和开工前 state.json。
    # 副本保存在本轮回退目录中，同时作为整轮作废（abort）的开工基线。
    try:
        project_fields = project_mod.snapshot_managed_fields(project_root)
    except ValueError as exc:
        print(f"错误：无法保存开工前项目配置：{exc}")
        sys.exit(1)
    state_path = os.path.join(project_root, WORKFLOW_LOOP_DIRNAME, "state.json")
    previous_state_raw = None
    if os.path.isfile(state_path):
        with open(state_path, "r", encoding="utf-8") as stream:
            previous_state_raw = stream.read()
    manifest = rollback_mod.prepare_start_baseline(
        project_root,
        workflow_id,
        project_fields,
        previous_state_raw,
        clean_paths=clean_targets if intent == "from_scratch" else None,
    )
    journal_mod.append_entry(
        project_root,
        "开工回退基线",
        "workflow.py",
        workflow_id=workflow_id,
        saved_documents=len(manifest.get("entries", {})),
    )

    # 清场属于破坏性动作：删除前写开工事务记录，成功提交后删除
    do_clean = intent == "from_scratch" and bool(clean_targets)
    if do_clean:
        rollback_mod.write_start_transaction(project_root, workflow_id, clean_targets)

    cleaned: list[str] = []
    try:
        if do_clean:
            cleaned = clean_artifacts(project_root)
        # 无论是否发现并删除旧产物，从零做都把 project_design_initialized 置为 false
        if intent == "from_scratch":
            project_mod.set_project_design_initialized(project_root, False)

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

        # 写 journal：工作流启动 / 路径生成 / 清场确认
        journal_mod.append_entry(project_root, "工作流启动", "ai",
                                workflow_id=workflow_id, intent=intent)
        journal_mod.append_entry(project_root, "路径生成", "workflow.py",
                                intent=intent, stage_path=stage_path)
        if do_clean:
            journal_mod.append_entry(project_root, "清场确认", "workflow.py",
                                    workflow_id=workflow_id, cleaned_paths=cleaned)
            # 清场、项目字段、状态和启动日志全部成功后，事务才标记已提交并删除
            rollback_mod.mark_start_transaction_committed(project_root, workflow_id)
            rollback_mod.clear_start_transaction(project_root)
    except Exception as exc:  # noqa: BLE001 - 开工事务必须兜住任何失败并恢复
        print(f"错误：开工过程失败（{exc}），正在恢复开工前状态...")
        failures = _restore_start_failure(project_root, workflow_id, manifest)
        if failures:
            print("恢复不完整，以下内容未恢复（事务记录和副本已保留，下次 start 会先恢复）：")
            for item in failures:
                print(f"  - {item}")
        else:
            print("已恢复到开工前状态；本次没有开始新轮次。")
        sys.exit(1)

    # 打印路径向开工摘要（不倾倒文档百科）
    print(f"═══ 工作流启动 ═══")
    print(f"workflow_id: {workflow_id}")
    print(f"intent: {intent}（{INTENT_LABELS.get(intent, intent).split('：')[0]}）")
    print(f"stage_path: {' → '.join(stage_path)}")
    print(f"当前 stage: {stage_label(first_stage_name)}")
    if cleaned:
        print(f"已清场: {cleaned}")
    # product_change/bugfix 显示 project_design_initialized 状态
    if intent == "product_change" or intent == "bugfix":
        pdi = project_mod.is_project_design_initialized(project_root)
        print(f"project_design_initialized: {pdi}")

    # 下一步：discuss
    print_next_step(
        "由 AI 执行 `workflow discuss`：它列出当前环节必须读取的材料文件绝对路径和用途，"
        "AI 再用文件读取工具逐份读取；用户不需要手动执行命令"
    )


# discuss 命令：给当前 AI 指出本 stage 必须读取的工作材料。
# 不重复打印文件正文：只输出经过检查的必读文件绝对路径、用途、读取顺序和产出路径。
# AI 收到清单后必须用文件读取工具逐份读取全文（Material File Reading）。
def cmd_discuss(args) -> None:
    # 定位项目根
    project_root = resolve_project_root()

    if project_root is None:
        print("错误：找不到 .workflow_loop/ 目录。")
        sys.exit(1)

    refuse_if_pending_start_transaction(project_root)

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

    # 兼容旧状态：已经进入 spike 但没有入场基线时，在加载材料前标记无法还原
    if wf_state.current_stage == "spike" and ensure_spike_baseline(project_root, wf_state):
        state_mod.save_state(project_root, wf_state)

    # 从 PathComposer 重建 stage 实例列表
    stage_instances = build_stage_path(wf_state.intent, project_root)
    # 找当前 stage 的策略
    stage = get_stage_strategy(wf_state.current_stage, wf_state, stage_instances)
    if stage is None:
        print(f"错误：找不到 stage '{wf_state.current_stage}' 的策略实现")
        sys.exit(1)

    # 组装并校验材料清单：任一文件缺失、不是普通文件或不可读时命令失败，不登记清单
    role_doc = role_doc_mod.get_role_doc(stage.name())
    try:
        checklist = stage_materials_mod.build_checklist(
            project_root,
            stage.name(),
            role_doc,
            stage.instruction(),
            stage.materials(),
        )
    except MaterialError as exc:
        print(f"═══ {stage_label(stage.name())} 材料清单检查失败 ═══")
        print(f"详情: {exc}")
        print("本次材料清单未登记。")
        print_next_step("先恢复缺失或损坏的材料文件，再重新执行 `workflow discuss`")
        sys.exit(1)

    material_hash = checklist.fingerprint
    stage_state = wf_state.stages[stage.name()]
    if (
        stage_state.discussion_material_hash is not None
        and stage_state.discussion_material_hash != material_hash
    ):
        # 材料内容变化：自动清除该阶段讨论完成和后续门禁状态，要求重读并重过第一道门。
        # 只重复列出相同内容时不走这里、不回滚状态。
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
            recovery_created_at=wf_state.recovery.created_at,
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

    # 打印材料清单（不倾倒正文）
    print(f"═══ {stage_label(stage.name())} 材料清单 ═══")
    if verification_mod.recovery_summary(wf_state):
        print("\n【为什么重新进入当前阶段】")
        print_recovery_details(wf_state)
    print("\n【角色】")
    if checklist.role_title or checklist.role_description:
        print(f"{checklist.role_title}：{checklist.role_description}")
    else:
        print("（本阶段没有角色定义）")
    print("\n【当前阶段任务】")
    print(checklist.task_text)
    print("\n【必读文件】按下列顺序用文件读取工具逐份读取全文；终端不再打印正文：")
    for material in checklist.materials:
        print(f"  {material.order}. {material.absolute_path}")
        print(f"     用途：{material.purpose}")
    if checklist.placeholders:
        print("\n【本阶段没有的材料】")
        for placeholder in checklist.placeholders:
            print(f"  - {placeholder.purpose.split('：')[0]}：{placeholder.note}")
    print("\n【约定产出路径】")
    for artifact_path in stage.artifact_paths():
        print(f"  {artifact_path}")
    if stage.name() == "topic_acceptance":
        print("\n【当前主题验收进度】")
        for line in acceptance_records_mod.acceptance_progress(project_root, wf_state):
            print(f"- {line}")

    # 写 journal：材料清单登记（记录本次清单的组成与内容指纹）
    journal_mod.append_entry(project_root, "材料清单登记", "workflow.py",
                            workflow_id=wf_state.workflow_id,
                            stage=stage.name(), prompt_doc=stage.prompt_doc_path(),
                            standard_doc=stage.standard_doc_path(),
                            additional_standard_docs=stage.additional_standard_doc_paths(),
                            global_writing_standard=GLOBAL_WRITING_STANDARD_PATH,
                            material_paths=[m.relative_path for m in checklist.materials],
                            material_hash=material_hash)
    # 写 journal：角色文档加载
    journal_mod.append_entry(project_root, "角色文档加载", "workflow.py",
                            stage=stage.name())

    print_next_step(
        "AI 必须先用文件读取工具逐份读取上面清单里的全部文件；读取失败时停下并报告，"
        "不能假装已经读取。随后按阶段工作规范调查并与用户讨论。"
        f"用户明确表示讨论完毕后，AI 执行 `workflow gate {stage.name()} --discuss-done`"
        "（只记录\"当前环节已经聊清楚，可以开始写产物\"，不代表产物已完成或已获用户认可）"
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
    try:
        current_checklist = stage_materials_mod.build_checklist(
            project_root,
            stage.name(),
            role_doc_mod.get_role_doc(stage.name()),
            stage.instruction(),
            stage.materials(),
        )
    except MaterialError:
        # 材料缺失或不可读：清单记录不能视为有效
        return False
    current_material_hash = current_checklist.fingerprint
    current_material_paths = [
        material.relative_path for material in current_checklist.materials
    ]
    saved_material_hash = workflow_state.stages.get(
        stage.name(),
        state_mod.StageState(),
    ).discussion_material_hash
    if saved_material_hash is not None and saved_material_hash != current_material_hash:
        return False
    for entry in reversed(journal_mod.read_all(project_root)):
        if entry.get("action") != "材料清单登记":
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
            and entry.get("material_paths") == current_material_paths
            and entry.get("material_hash") == current_material_hash
        ):
            return True
    return False


def _register_stage_artifact_keys(
    project_root: str,
    wf_state: state_mod.WorkflowState,
    stage_name: str,
) -> dict[str, str]:
    """在正式产物通过程序检查后登记稳定文件标识，并核对真实路径。"""
    project = project_mod.load_project(project_root)
    if project is None:
        raise ValueError("项目尚未安装，不能登记正式文件标识")

    category = ""
    paths_by_name: dict[str, str] = {}
    path_builder = None
    if stage_name == "spec":
        category = "feature"
        path_builder = artifact_paths_mod.feature_doc
        for relative_path in verification_mod.get_linked_product_design_paths(project_root):
            if relative_path == artifact_paths_mod.PRODUCT_OVERVIEW_DOC:
                continue
            with open(os.path.join(project_root, relative_path), "r", encoding="utf-8") as stream:
                title = stream.readline().strip()
            display_name = title.removeprefix("# 【功能】").strip()
            if display_name:
                paths_by_name[display_name] = relative_path.replace(os.sep, "/")
    elif stage_name == "spike" and not wf_state.spike_skipped:
        category = "spike"
        path_builder = artifact_paths_mod.spike_doc
        index_path = os.path.join(project_root, artifact_paths_mod.SPIKE_INDEX_DOC)
        _workflow_id, items, errors = spike_validation_mod.parse_spike_index(index_path)
        if errors:
            raise ValueError("穿刺清单仍有错误，不能登记文件标识: " + "；".join(errors))
        for item in items:
            link = item.fields.get("结论文档", "")
            match = re.search(r"\[[^\]]+\]\(([^)#]+)", link)
            if match is None:
                raise ValueError(f"穿刺项 {item.item_id} 的结论文档链接无效")
            target = match.group(1).strip()
            if target.startswith("./"):
                target = target[2:]
            if not target.startswith("spec/"):
                target = f"spec/{target}"
            paths_by_name[item.name] = target.replace("\\", "/")
    elif stage_name == "reproduce":
        category = "bug"
        path_builder = artifact_paths_mod.bug_doc
        bug_dir = os.path.join(project_root, "bug")
        if os.path.isdir(bug_dir):
            for filename in sorted(os.listdir(bug_dir)):
                if not filename.startswith("缺陷_") or not filename.endswith(".md"):
                    continue
                relative_path = f"bug/{filename}"
                with open(os.path.join(project_root, relative_path), "r", encoding="utf-8") as stream:
                    content = stream.read()
                if f"- 工作流编号：{wf_state.workflow_id}" not in content:
                    continue
                first_line = content.splitlines()[0].strip() if content.splitlines() else ""
                display_name = first_line.removeprefix("# 【缺陷】").strip()
                if display_name:
                    paths_by_name[display_name] = relative_path
    else:
        return {}

    if not paths_by_name or path_builder is None:
        return {}
    added = artifact_paths_mod.register_file_keys(
        project,
        category,
        list(paths_by_name),
    )
    mapping = project.artifact_file_keys.get(category, {})
    mismatches = []
    for display_name, actual_path in paths_by_name.items():
        expected_path = path_builder(mapping[display_name])
        if actual_path != expected_path:
            mismatches.append(f"{display_name!r}: 当前 {actual_path}，应为 {expected_path}")
    if mismatches:
        raise ValueError("正式文件名与稳定文件标识不一致：" + "；".join(mismatches))
    if added:
        project_mod.save_project(project_root, project)
    return added


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
    *,
    execute_regression: bool = True,
) -> tuple[bool, str]:
    """执行阶段产物校验；最终回归可由调用方控制是否实际执行。"""

    if stage_name == "regression_test" and execute_regression:
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
    return passed, details


def regression_failure_next_step() -> str:
    """回归失败时，告诉用户先归因再退回，避免无条件重复执行同一命令。"""
    return (
        "最终全量回归未通过，先查看 state.json/journal.jsonl 的命令、退出码和输出摘要，"
        "判断失败属于产品代码、测试代码、测试计划还是临时环境；"
        "确定原因后调 `workflow return --to <阶段> --reason \"具体原因\"` 返回对应阶段，"
        "不要直接重复调当前 regression_test 门禁"
    )


def _load_active_workflow_for_command(project_root: str) -> state_mod.WorkflowState:
    refuse_if_pending_start_transaction(project_root)
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
                workflow_id=wf_state.workflow_id,
                from_stage=from_stage,
                to_stage=to_stages,
                reason=wf_state.recovery.reason or "测试登记或执行前发现上游内容变化",
                recovery_created_at=wf_state.recovery.created_at,
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
    try:
        current_hash = compute_stage_material_hash(project_root, stage)
    except MaterialError:
        return False
    return (
        stage_state is not None
        and stage_state.discussion_material_hash == current_hash
    )


def cmd_test_entry(args) -> None:
    """在测试计划环节登记项目全量测试入口配置；只登记，不运行任何测试。

    仅供 AI 执行：入口按操作系统保存为命令参数数组；需要管道、重定向或
    多条命令时必须放入项目统一入口脚本。新建或修改的入口脚本先保存
    修改前内容进本轮回退清单，整轮作废时可以准确恢复。
    """
    project_root = resolve_project_root()
    if project_root is None:
        print("错误：找不到 .workflow_loop/ 目录。")
        sys.exit(1)
    wf_state = _load_active_workflow_for_command(project_root)
    if wf_state.current_stage != "test_plan":
        print(f"错误：当前环节是 {stage_label(wf_state.current_stage)}，"
              "只能在 test_plan（测试计划）环节登记项目测试入口")
        print_next_step(current_stage_next_instruction(wf_state))
        return
    stage_instances = build_stage_path(wf_state.intent, project_root)
    stage = get_stage_strategy("test_plan", wf_state, stage_instances)
    if stage is None or not _has_loaded_stage_materials(project_root, wf_state, stage):
        print("错误：还没有通过 workflow discuss 加载测试计划阶段的当前材料")
        print_next_step("先执行 `workflow discuss`，读取测试计划模板和工作规范")
        return
    stage_state = wf_state.stages.get("test_plan")
    if stage_state is None or not stage_state.gate.discussion_complete:
        print("错误：测试计划讨论还没有完成（第一道门未通过），不能登记测试入口")
        print_next_step("和用户确认测试覆盖后，先执行 `workflow gate test_plan --discuss-done`")
        return

    entry_config = {}
    for platform_key in ("default", "windows", "linux", "darwin"):
        argv = getattr(args, platform_key, None)
        if argv:
            entry_config[platform_key] = list(argv)
    if not entry_config:
        print("错误：至少提供一个平台的入口参数数组，例如 --darwin .venv/bin/python -m pytest -q")
        return

    declared_scripts = sorted(
        {
            script.replace("\\", "/")
            for script in (args.script or [])
        }
    )
    referenced_scripts = test_entry_mod.referenced_project_scripts(entry_config)
    undeclared_scripts = sorted(set(referenced_scripts) - set(declared_scripts))
    if undeclared_scripts:
        print("═══ 测试入口登记失败 ═══")
        print(f"详情: 入口参数引用了尚未登记回退依据的项目脚本: {undeclared_scripts}")
        print_next_step(
            "先对每个脚本重复使用 `--script <项目内相对路径>` 执行本命令；"
            "脚本原本不存在时必须在本命令成功后再创建"
        )
        return

    # 回退依据：project.json 原字段已由开工基线保存；声明的入口脚本先登记原内容。
    for script in declared_scripts:
        try:
            script_detail = rollback_mod.register_start_entry_script(
                project_root,
                wf_state.workflow_id,
                script,
            )
        except (ValueError, OSError) as exc:
            print("═══ 测试入口登记失败 ═══")
            print(f"详情: 无法保存入口脚本的修改前内容：{exc}")
            print_next_step("修正脚本路径后重新执行 `workflow test entry`")
            return
        print(f"入口脚本回退依据: {script}（{script_detail}）")

    try:
        project_mod.register_test_entry(project_root, entry_config)
    except ValueError as exc:
        print("═══ 测试入口登记失败 ═══")
        print(f"详情: {exc}")
        print_next_step("修正入口参数数组后重新执行 `workflow test entry`；"
                        "复杂命令请放入项目统一入口脚本")
        return

    journal_mod.append_entry(
        project_root,
        "项目测试入口登记",
        "user",
        workflow_id=wf_state.workflow_id,
        test_entry=entry_config,
        declared_scripts=declared_scripts,
    )
    print("═══ 项目全量测试入口已登记 ═══")
    for platform_key, argv in entry_config.items():
        print(f"  {platform_key}: {argv}")
    print("本命令只登记入口配置，不运行任何测试；全量测试只在最终回归阶段执行。")
    print_next_step(
        "确认测试计划文档完整后，由 AI 执行 `workflow gate test_plan` 做程序校验"
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
            cwd=args.cwd,
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
        cwd=task.cwd,
        dependencies=task.dependencies,
        timeout_seconds=task.timeout_seconds,
    )
    state_mod.save_state(project_root, wf_state)
    print("═══ 测试项任务已登记 ═══")
    print(f"主题: {args.topic}")
    print(f"测试项: {args.tc}")
    print(f"测试入口: {', '.join(task.test_entries)}")
    print(f"执行命令: {' '.join(task.command)}")
    print(f"工作目录: {task.cwd or '项目根'}")
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
            print_next_step(
                "根据当前成功记录补齐或复核各主题 "
                "`qa/<主题文件标识>_测试结果.md`，再调 `workflow gate test_execution`"
            )
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
        result_path = topic_mod.topic_paths(project_root, record.topic)["acceptance_result"]
        print_next_step(f"生成或复核 `{result_path}`，再继续其他可验收主题")
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
            if topic in stage_state.test_tasks:
                del stage_state.test_tasks[topic]
    for topic in topics:
        paths = topic_mod.topic_paths(project_root, topic)
        result_path = os.path.join(project_root, paths["test_result"])
        if os.path.exists(result_path):
            os.remove(result_path)
    acceptance_records_mod.clear_topic_records(project_root, wf_state, topics)


def cmd_return(args) -> None:
    """用户确认后把当前工作流退回指定阶段，并只清理直接受影响主题的当前状态。

    程序只验证目标是本轮实际路径中当前环节之前的真实环节；不从原因文字猜目标，
    不根据主题依赖自动扩大失效范围。
    """
    project_root = resolve_project_root()
    if project_root is None:
        print("错误：找不到 .workflow_loop/ 目录。")
        sys.exit(1)
    wf_state = _load_active_workflow_for_command(project_root)
    stage_indexes = _stage_index_map(wf_state)
    if args.to not in stage_indexes:
        print(f"错误：目标阶段不在当前工作流的实际路径中: {args.to}")
        print(f"本轮路径: {' → '.join(wf_state.stage_path)}")
        return
    if wf_state.current_stage not in stage_indexes or stage_indexes[args.to] >= stage_indexes[wf_state.current_stage]:
        print(f"错误：只能退回当前阶段之前的阶段，当前是 {stage_label(wf_state.current_stage)}")
        return
    if not args.reason.strip():
        print("错误：必须说明为什么退回")
        return

    # 直接受影响主题必须明确：已有主题时不允许含糊范围，也不自动扩大
    if args.topic and args.all_topics:
        print("错误：--topic 和 --all-topics 互斥，只能选择一种方式说明受影响主题")
        return
    if wf_state.topics:
        if args.all_topics:
            affected_topics = list(wf_state.topics)
        elif args.topic:
            affected_topics = list(dict.fromkeys(args.topic))
        else:
            print("错误：当前工作流已有验收主题，必须明确写出直接受影响的主题：")
            print("  逐个使用 --topic <主题名称>（可重复），或使用 --all-topics 表示全部主题")
            print("  程序不会根据主题依赖自动扩大范围；只有确有影响证据的主题才应列出")
            return
        unknown = sorted(set(affected_topics) - set(wf_state.topics))
        if unknown:
            print(f"错误：受影响主题不属于当前工作流: {unknown}")
            return
    else:
        # 主题尚未形成（早期阶段）：不伪造主题参数
        affected_topics = []

    # 先确认追踪表能够完成退回更新，再删除测试/验收结果。
    # 否则追踪表错误会留下“state 仍在原阶段、结果文件却已经被删”的半完成状态。
    trace_detail = ""
    if affected_topics:
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
    target_index = stage_indexes[args.to]
    downstream_names = wf_state.stage_path[target_index:]
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
    wf_state.recovery.return_target = args.to
    wf_state.recovery.affected_topics = affected_topics
    if ensure_impl_recovery_baseline(project_root, wf_state):
        state_mod.save_state(project_root, wf_state)

    def stage_index(name: str) -> int:
        return stage_indexes.get(name, len(wf_state.stage_path))

    # 各目标的精确失效内容：只清确实失效的状态，独立主题的有效记录保留
    if target_index <= stage_index("spike"):
        # 从后续环节返回穿刺：跳过标记恢复，三道门重新执行
        wf_state.spike_skipped = False
    if target_index <= stage_index("acceptance_plan"):
        wf_state.verification.acceptance_plan_hash = None
    if target_index <= stage_index("test_plan"):
        wf_state.verification.test_plan_hash = None
    if target_index <= stage_index("impl"):
        wf_state.verification.impl_hash = None
    if target_index <= stage_index("test_code"):
        wf_state.verification.test_code_hash = None
    if target_index <= stage_index("test_execution"):
        # 返回测试执行或更早：清除受影响主题的测试任务、测试结果和验收记录
        _clear_topic_test_state(project_root, wf_state, affected_topics)
        wf_state.verification.test_result_hash = None
        wf_state.verification.acceptance_result_hash = None
    elif target_index <= stage_index("topic_acceptance"):
        # 返回主题验收：保留测试记录，只清受影响主题的验收记录和结果
        acceptance_records_mod.clear_topic_records(project_root, wf_state, affected_topics)
        wf_state.verification.acceptance_result_hash = None
    if target_index <= stage_index("regression_test"):
        # 返回最终回归或更早：回归必须重新真实执行；主题结果按上面的规则保留或清除
        wf_state.verification.regression_test_result_hash = None
        wf_state.regression_test = state_mod.RegressionTestState()
    # 返回整体验收或最终设计同步：不删除已经通过的回归记录

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
        recovery_created_at=wf_state.recovery.created_at,
    )
    state_mod.save_state(project_root, wf_state)
    print("═══ 工作流已退回 ═══")
    print(f"来源环节: {stage_label(previous_stage)}")
    print(f"目标环节: {stage_label(args.to)}")
    print(f"直接受影响主题: {', '.join(affected_topics) if affected_topics else '（主题尚未形成）'}")
    print(f"原因: {args.reason.strip()}")
    if trace_detail:
        print(trace_detail)
    print("未列出的独立主题保留当前测试和验收记录。")
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
    refuse_if_pending_start_transaction(project_root)
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

    try:
        current_material_hash = compute_stage_material_hash(project_root, stage)
    except MaterialError as exc:
        print(f"═══ {stage_label(stage_name)} 材料检查失败 ═══")
        print(f"详情: {exc}")
        print_next_step("先恢复缺失或损坏的阶段材料文件，再执行 `workflow discuss` 重新登记清单")
        sys.exit(1)
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
            not gate.discussion_complete
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
                print(f"详情：还没有通过 workflow discuss 加载 {stage_label(stage_name)}的当前全部材料")
                print_next_step(
                    f"先调 `workflow discuss`，按输出路径逐份阅读 {stage_label(stage_name)}的模板和规范"
                )
            return
        if not gate.discussion_complete:
            valid, detail = stage.discussion_validate(project_root, wf_state)
            if not valid:
                print(f"═══ {stage_name} 讨论完成校验失败 ═══")
                print(f"详情: {detail}")
                print_next_step(f"补齐讨论阶段要求后重新调 `workflow gate {stage_name} --discuss-done`")
                return
        # 已经标记过了 → 提示；impl 允许在计划调整后重新确认，只更新计划确认哈希
        if gate.discussion_complete:
            if stage_name == "impl":
                try:
                    confirmed_plan_hash = rollback_mod.compute_plan_hash(
                        project_root,
                        wf_state.topics,
                    )
                except (ValueError, OSError) as exc:
                    print(f"═══ impl 讨论完成校验失败 ═══")
                    print(f"详情: 无法计算当前实施计划哈希：{exc}")
                    return
                if stage_state.plan_confirmed_hash != confirmed_plan_hash:
                    stage_state.plan_confirmed_hash = confirmed_plan_hash
                    journal_mod.append_entry(
                        project_root,
                        "实施计划重新确认",
                        "user",
                        workflow_id=wf_state.workflow_id,
                        stage=stage_name,
                        plan_confirmed_hash=confirmed_plan_hash,
                        reason="实施计划调整后用户重新确认；首次原内容副本保持不变",
                    )
                    state_mod.save_state(project_root, wf_state)
                    print("═══ impl 实施计划已重新确认 ═══")
                    print("计划确认哈希已更新；重新执行 `workflow gate impl --prepare-code` 补充新路径副本后继续实施")
                    print_next_step("调 `workflow gate impl --prepare-code`（保留已保存的首次原内容，只为新路径补副本）")
                    return
            print(f"提示：{stage_name} 的讨论已经标记完毕了")
        else:
            # 标记讨论完毕
            gate.discussion_complete = True
            stage_state.discussion_material_hash = current_material_hash
            # impl 记录用户确认的实施计划哈希；后续每次准备回退基线都必须匹配它
            if stage_name == "impl":
                try:
                    stage_state.plan_confirmed_hash = rollback_mod.compute_plan_hash(
                        project_root,
                        wf_state.topics,
                    )
                except (ValueError, OSError):
                    stage_state.plan_confirmed_hash = None
            # 写 journal：门禁讨论完毕
            journal_mod.append_entry(project_root, "门禁讨论完毕", "user",
                                    stage=stage_name, passed=True,
                                    plan_confirmed_hash=stage_state.plan_confirmed_hash
                                    if stage_name == "impl" else None)
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
                journal_mod.append_entry(
                    project_root,
                    "验证失效",
                    "workflow.py",
                    workflow_id=wf_state.workflow_id,
                    from_stage=from_stage,
                    to_stage=to_stages,
                    reason=wf_state.recovery.reason or "上游内容已变化",
                    recovery_created_at=wf_state.recovery.created_at,
                )
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

        # 跑 code_validate（第 2 道闸的核心）。
        if stage_name == "regression_test":
            print("现在真实执行一次项目全量测试入口；本次执行结果将作为最终回归事实。")
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
            if stage_name == "regression_test":
                print_next_step(regression_failure_next_step())
            elif recovery_instruction(wf_state) and recovery_command_needed:
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
        print_next_step(confirmation_next_step(stage_name))
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
                workflow_id=wf_state.workflow_id,
                from_stage=from_stage,
                to_stage=to_stages,
                reason=wf_state.recovery.reason or "用户确认前发现上游内容已变化",
                recovery_created_at=wf_state.recovery.created_at,
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
        execute_regression=False,
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
        if stage_name == "regression_test":
            print_next_step(regression_failure_next_step())
        else:
            print_next_step(f"修正文档后重新调 `workflow gate {stage_name}`")
        return

    try:
        added_file_keys = _register_stage_artifact_keys(
            project_root,
            wf_state,
            stage_name,
        )
    except (OSError, ValueError) as exc:
        print(f"═══ {stage_name} 正式文件标识登记失败 ═══")
        print(f"详情: {exc}")
        print_next_step("修正正式文档标题或文件名后重新执行当前环节第二道门")
        return
    if added_file_keys:
        journal_mod.append_entry(
            project_root,
            "正式文件标识登记",
            "workflow.py",
            workflow_id=wf_state.workflow_id,
            stage=stage_name,
            added=added_file_keys,
        )

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
            print(f"错误：没有找到 {artifact_paths_mod.ACCEPTANCE_INDEX_DOC} 中的本次验收主题")
            print_next_step(
                f"补充 `{artifact_paths_mod.ACCEPTANCE_INDEX_DOC}` 和 "
                "`acceptance/<主题文件标识>_验收计划.md` 后重新执行验收计划门禁"
            )
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

    # 只有测试代码的第三道门确认通过后，才保存可供后续实施复用的状态。
    if stage_name == "test_code":
        try:
            accepted_test_paths = rollback_mod.accept_test_code_inventory(
                project_root,
                wf_state,
            )
        except ValueError as exc:
            gate.user_confirmed = False
            state_mod.save_state(project_root, wf_state)
            print("═══ test_code 确认状态保存失败 ═══")
            print(f"详情: {exc}")
            print_next_step("修复测试代码回退记录后重新执行当前确认门")
            return
        journal_mod.append_entry(
            project_root,
            "已确认测试文件状态",
            "user",
            workflow_id=wf_state.workflow_id,
            paths=accepted_test_paths,
            manifest_hash=wf_state.rollback.manifest_hash,
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
    refuse_if_pending_start_transaction(project_root)

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
# 不再二次确认；保留正式产物；不改写 bug/索引.md
def cmd_done(args) -> None:
    # 定位项目根
    project_root = resolve_project_root()
    if project_root is None:
        print("错误：找不到 .workflow_loop/ 目录。")
        sys.exit(1)
    refuse_if_pending_start_transaction(project_root)

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
    except (OSError, ValueError) as exc:
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


# abort 命令：完整恢复本轮开工前受管内容，清理临时副本后才标记整轮已作废。
def cmd_abort(args) -> None:
    project_root = resolve_project_root()
    if project_root is None:
        print("错误：找不到 .workflow_loop/ 目录。")
        sys.exit(1)
    refuse_if_pending_start_transaction(project_root)

    wf_state = state_mod.load_state(project_root)
    if wf_state is None:
        print("错误：还没启动工作流")
        sys.exit(1)
    if wf_state.run_status != "active":
        print(
            f"错误：当前轮次状态为 {wf_state.run_status}，"
            "只有 active（仍在进行）才能执行 abort（整轮作废）"
        )
        sys.exit(1)

    restored_paths: list[str] = []
    if wf_state.rollback.restored_at is None:
        if wf_state.rollback.restore_started_at is None:
            ok, issues, abort_manifest = rollback_mod.preflight_abort(
                project_root,
                wf_state,
            )
            print("═══ 整轮作废恢复预检 ═══")
            if not ok or abort_manifest is None:
                print("预检失败，尚未修改任何项目内容：")
                for issue in issues or ["没有得到完整恢复清单"]:
                    print(f"  - {issue}")
                journal_mod.append_entry(
                    project_root,
                    "整轮作废预检失败",
                    "workflow.py",
                    workflow_id=wf_state.workflow_id,
                    issues=issues,
                )
                print_next_step(
                    "保留当前轮次为 active（仍在进行）；先解决缺失或损坏的开工副本，"
                    "再重新执行 `workflow abort`（整轮作废）"
                )
                return

            print("以下是本次会恢复或删除的受管项目：")
            for item in abort_manifest.get("items", []):
                if item.get("kind") == "file":
                    action = "恢复开工前内容" if item.get("original_exists") else "删除本轮新文件"
                    print(f"  - {item.get('path')}：{action}")
                elif item.get("kind") == "project_fields":
                    print("  - .workflow_loop/project.json：恢复本轮受管项目字段")
            print("清单外文件不会读取、恢复或删除。")
            wf_state.rollback.restore_started_at = state_mod.now_iso()
            state_mod.save_state(project_root, wf_state)
            journal_mod.append_entry(
                project_root,
                "整轮作废恢复开始",
                "workflow.py",
                workflow_id=wf_state.workflow_id,
                item_ids=[
                    item.get("id")
                    for item in abort_manifest.get("items", [])
                ],
                restore_started_at=wf_state.rollback.restore_started_at,
            )

        restored_paths, failures = rollback_mod.restore_full_run(
            project_root,
            wf_state,
        )
        if failures:
            journal_mod.append_entry(
                project_root,
                "整轮作废恢复未完成",
                "workflow.py",
                workflow_id=wf_state.workflow_id,
                restored_items=restored_paths,
                failures=failures,
            )
            print("═══ 整轮作废恢复未完成 ═══")
            if restored_paths:
                print(f"本次已恢复: {restored_paths}")
            print("未完成项目：")
            for failure in failures:
                print(f"  - {failure}")
            print_next_step(
                "回退副本和逐项进度已保留，当前轮次仍是 active（仍在进行）；"
                "处理上面的具体问题后重新执行 `workflow abort`，已完成项目不会再次覆盖"
            )
            return

        wf_state.rollback.restored_at = state_mod.now_iso()
        state_mod.save_state(project_root, wf_state)
        journal_mod.append_entry(
            project_root,
            "整轮作废项目已恢复",
            "workflow.py",
            workflow_id=wf_state.workflow_id,
            restored_items=restored_paths,
            restored_at=wf_state.rollback.restored_at,
        )

    try:
        cleaned_snapshots = rollback_mod.cleanup(project_root, wf_state.workflow_id)
    except (OSError, ValueError) as exc:
        journal_mod.append_entry(
            project_root,
            "整轮作废临时副本清理失败",
            "workflow.py",
            workflow_id=wf_state.workflow_id,
            reason=str(exc),
            restored_items=restored_paths,
        )
        print("═══ 整轮作废清理未完成 ═══")
        print(f"详情: 项目内容已经恢复，但临时回退副本清理失败：{exc}")
        print_next_step(
            "当前轮次仍是 active（仍在进行）；处理回退目录权限或路径问题后重新执行 "
            "`workflow abort`，重试只继续清理，不再恢复项目文件"
        )
        return

    wf_state.rollback.cleanup_completed_at = state_mod.now_iso()
    # 临时清单已经删除，只清空失效的清单引用；保留三段恢复时间供状态审计。
    wf_state.rollback.manifest_path = None
    wf_state.rollback.manifest_hash = None
    wf_state.rollback.prepared_at = None
    wf_state.rollback.plan_hash = None
    wf_state.rollback.code_baseline_hash = None
    wf_state.rollback.planned_paths = []
    wf_state.run_status = "aborted"
    wf_state.aborted_at = state_mod.now_iso()
    state_mod.save_state(project_root, wf_state)
    journal_mod.append_entry(
        project_root,
        "整轮已作废",
        "workflow.py",
        workflow_id=wf_state.workflow_id,
        restored_items=restored_paths,
        cleaned_rollback_paths=cleaned_snapshots,
        restore_started_at=wf_state.rollback.restore_started_at,
        restored_at=wf_state.rollback.restored_at,
        cleanup_completed_at=wf_state.rollback.cleanup_completed_at,
        aborted_at=wf_state.aborted_at,
    )

    print("═══ 工作流整轮已作废 ═══")
    print(f"workflow_id: {wf_state.workflow_id}")
    print(f"作废时间: {wf_state.aborted_at}")
    if restored_paths:
        print(f"本次调用恢复的项目: {restored_paths}")
    print("本轮正式产物副本和回退副本已经删除，只保留作废与恢复结果记录。")
    print_next_step(
        f"本轮已结束；有新需求时由 AI 执行 `workflow start --intent {wf_state.intent}` 开始新一轮"
    )


# 读取正式发布元数据；更新命令只接受 PyPI 与 GitHub Release 都存在的正式版本。
def _fetch_json(url: str) -> dict:
    request = urllib.request.Request(
        url,
        headers={"Accept": "application/json", "User-Agent": MAINTENANCE_USER_AGENT},
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError, urllib.error.URLError) as exc:
        raise ValueError(f"无法读取正式发布元数据 {url}: {exc}") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"正式发布元数据 {url} 的顶层不是 JSON 对象")
    return payload


def _resolve_update_version(requested_version: str | None) -> str:
    pypi_url = os.environ.get("WORKFLOW_LOOP_PYPI_JSON_URL", PYPI_JSON_URL)
    github_api = os.environ.get("WORKFLOW_LOOP_GITHUB_API_URL", GITHUB_API_URL).rstrip("/")
    pypi = _fetch_json(pypi_url)

    if requested_version:
        target = project_mod.stable_version(requested_version, "指定目标版本")
        releases = pypi.get("releases", {})
        files = releases.get(str(target), []) if isinstance(releases, dict) else []
        if not isinstance(files, list) or not files or not any(
            isinstance(item, dict) and not item.get("yanked", False) for item in files
        ):
            raise ValueError(f"PyPI 没有可用的正式版本 {target}")
        github = _fetch_json(f"{github_api}/releases/tags/v{target}")
    else:
        info = pypi.get("info", {})
        raw_target = info.get("version") if isinstance(info, dict) else None
        target = project_mod.stable_version(raw_target, "PyPI 最新版本")
        github = _fetch_json(f"{github_api}/releases/latest")

    tag = github.get("tag_name")
    if github.get("draft") or github.get("prerelease"):
        raise ValueError(f"GitHub Release v{target} 不是正式发布")
    if tag != f"v{target}":
        raise ValueError(
            f"PyPI 目标版本是 {target}，GitHub Release 标记是 {tag!r}，两个来源不一致"
        )
    current = project_mod.stable_version(project_mod.PRODUCT_VERSION, "电脑全局命令版本")
    if target < current:
        raise ValueError(f"目标版本 {target} 低于电脑全局命令版本 {current}，不允许降级")
    return str(target)


def _confirm_once(prompt: str) -> bool:
    try:
        answer = input(prompt).strip()
    except (EOFError, KeyboardInterrupt):
        print("")
        return False
    return answer.lower() in {"y", "yes"}


def _release_asset_url(version: str, filename: str) -> str:
    override = os.environ.get("WORKFLOW_LOOP_RELEASE_BASE_URL")
    if override:
        return f"{override.rstrip('/')}/{filename}"
    return f"{GITHUB_RELEASE_URL}/download/v{version}/{filename}"


def _download_release_asset(version: str, filename: str, destination: str) -> None:
    url = _release_asset_url(version, filename)
    request = urllib.request.Request(url, headers={"User-Agent": MAINTENANCE_USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            content = response.read()
    except (OSError, urllib.error.URLError) as exc:
        raise ValueError(f"下载正式发布脚本失败 {url}: {exc}") from exc
    if not content:
        raise ValueError(f"下载到的正式发布脚本为空: {url}")
    with open(destination, "wb") as stream:
        stream.write(content)


def _run_maintenance_script(
    filename: str,
    version: str,
    arguments: list[str],
) -> int:
    temp_dir = tempfile.mkdtemp(prefix="workflow_loop_maintenance_")
    script_path = os.path.join(temp_dir, filename)
    try:
        _download_release_asset(version, filename, script_path)
        if os.name == "nt":
            command = [
                "powershell.exe",
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                script_path,
                *arguments,
                "-WaitForProcessId",
                str(os.getpid()),
                "-CleanupDirectory",
                temp_dir,
            ]
            subprocess.Popen(command, close_fds=True)
            print("已把确认后的维护动作交给辅助 PowerShell 进程。")
            print("当前 workflow 进程退出后，辅助进程会继续并打印最终结果。")
            return 0
        completed = subprocess.run(["bash", script_path, *arguments], check=False)
        return completed.returncode
    except (OSError, ValueError) as exc:
        print(f"维护脚本启动失败：{exc}")
        return 1
    finally:
        if os.name != "nt":
            shutil.rmtree(temp_dir, ignore_errors=True)


def cmd_update(args) -> None:
    project_root = os.getcwd()
    if not os.path.isdir(os.path.join(project_root, WORKFLOW_LOOP_DIRNAME)):
        print("错误：workflow update 必须从已安装项目根目录执行；不会向父目录查找。")
        sys.exit(1)
    try:
        target_version = _resolve_update_version(args.version)
    except ValueError as exc:
        print(f"更新预检失败：{exc}")
        print("项目和电脑全局命令均未修改。")
        sys.exit(1)

    status = project_mod.inspect_skeleton_for_update(project_root, target_version)
    if status.state != "installed":
        print("更新预检失败：当前项目骨架残缺或版本方向不允许。")
        for problem in status.problems:
            print(f"  - {problem}")
        print("项目和电脑全局命令均未修改。")
        sys.exit(1)

    global_needs_update = project_mod.stable_version(
        project_mod.PRODUCT_VERSION,
        "电脑全局命令版本",
    ) != project_mod.stable_version(target_version, "目标版本")
    if not global_needs_update and not status.needs_update:
        print(f"电脑全局命令和当前项目都已经是 {target_version}，无需更新。")
        return

    print("═══ Workflow Loop 更新确认 ═══")
    print(f"项目根目录: {os.path.realpath(project_root)}")
    print(f"电脑全局命令版本: {project_mod.PRODUCT_VERSION}")
    print(f"当前项目版本: {status.installed_version}")
    print(f"目标正式版本: {target_version}")
    print("确认后按需更新电脑全局命令，并直接覆盖当前项目：")
    for path in installer_mod.UPDATE_PROJECT_PATHS:
        print(f"  {os.path.join(os.path.realpath(project_root), *path.split('/'))}")
    print("保留：当前轮次状态、Journal 历史、rollback 回退资料、业务代码和正式产物。")
    print("不创建备份；中途失败不恢复已完成部分，可以重新执行同一命令补齐。")
    if not _confirm_once("确认以上范围并开始更新？[y/N] "):
        print("已取消。项目和电脑全局命令均未修改。")
        return

    filename = "update.ps1" if os.name == "nt" else "update.sh"
    code = _run_maintenance_script(
        filename,
        target_version,
        [
            "-ProjectRoot" if os.name == "nt" else "--project-root",
            project_root,
            "-TargetVersion" if os.name == "nt" else "--version",
            target_version,
            "-ExpectedProjectVersion" if os.name == "nt" else "--expected-project-version",
            status.installed_version or "",
            "-Confirmed" if os.name == "nt" else "--confirmed",
        ],
    )
    sys.exit(code)


def _print_project_uninstall_scope(scope: installer_mod.UninstallScope) -> None:
    print("═══ Workflow Loop 项目卸载确认 ═══")
    print(f"项目根目录: {scope.project_root}")
    if scope.existing_paths:
        print("确认后删除：")
        for path in scope.existing_paths:
            print(f"  {os.path.join(scope.project_root, *path.split('/'))}")
    else:
        print("固定项目管理内容已经全部不存在。")
    print("保留：业务代码、测试、Git 数据和 spec/、acceptance/、qa/、impl/、bug/ 等正式产物。")
    print("电脑全局 workflow 命令不会修改。删除没有备份，当前轮次状态不会阻止卸载。")


def cmd_uninstall(args) -> None:
    if args.global_scope:
        print("═══ Workflow Loop 全局卸载确认 ═══")
        print("确认后删除这台电脑上的 Workflow Loop 全局命令和工具环境。")
        print("只有来源记录能证明由 Workflow Loop 添加的 PATH 项才会删除；未知来源会保留并报告。")
        print("不会查找、扫描、读取或删除任何项目目录。")
        print("警告：全局命令删除后，其它已安装项目也暂时无法运行 workflow。")
        if not _confirm_once("确认只卸载电脑全局命令？[y/N] "):
            print("已取消。电脑和项目内容均未修改。")
            return
        filename = "uninstall.ps1" if os.name == "nt" else "uninstall.sh"
        code = _run_maintenance_script(
            filename,
            project_mod.PRODUCT_VERSION,
            ["-Global" if os.name == "nt" else "--global", "-Confirmed" if os.name == "nt" else "--confirmed"],
        )
        sys.exit(code)

    project_root = os.getcwd()
    scope = installer_mod.inspect_uninstall_scope(project_root)
    _print_project_uninstall_scope(scope)
    if not scope.existing_paths:
        print("当前项目已经卸载干净，无需修改。")
        return
    if not _confirm_once("确认强制卸载当前项目？[y/N] "):
        print("已取消。当前项目未修改。")
        return
    result = installer_mod.uninstall_project(project_root)
    for path in result.changed_paths:
        print(f"已删除: {path}")
    if result.failures:
        print("项目卸载未完成，以下残留未删除：")
        for failure in result.failures:
            print(f"  - {failure}")
        print("已删除内容不会恢复；解决权限或占用后重新执行同一命令。")
        sys.exit(1)
    print("当前项目的 Workflow Loop 管理内容已全部删除。")


# _install-project 内部命令：安装当前项目（只由官方安装脚本在确认后调用）
# 不显示在普通帮助中；必须携带安装脚本生成的一次性事务文件
# 项目根用 cwd（安装脚本已让用户确认目录）
def cmd_internal_install_project(args) -> None:
    # 项目根 = 当前工作目录
    project_root = os.getcwd()
    # 调 installer 执行一次性事务安装：事务缺失、已使用、版本或路径不符都在写入前失败
    code = installer_mod.install_project_transaction(project_root, args.transaction)
    # 退出
    sys.exit(code)


def cmd_internal_update_project(args) -> None:
    project_root = os.getcwd()
    status = project_mod.inspect_skeleton_for_update(project_root, project_mod.PRODUCT_VERSION)
    if status.state != "installed":
        print("项目更新预检失败：")
        for problem in status.problems:
            print(f"  - {problem}")
        sys.exit(1)
    print(f"项目根目录: {os.path.realpath(project_root)}")
    print(f"当前项目版本: {status.installed_version}")
    print(f"目标项目版本: {project_mod.PRODUCT_VERSION}")
    for path in installer_mod.UPDATE_PROJECT_PATHS:
        print(f"  {path}")
    if args.check_only:
        return
    if not args.confirmed:
        print("内部项目更新入口缺少已确认标记，未修改项目。")
        sys.exit(1)
    result = installer_mod.update_project(
        project_root,
        expected_installed_version=args.expected_project_version,
    )
    for path in result.changed_paths:
        print(f"已更新: {path}")
    if not result.success:
        print("项目更新未完成：")
        for failure in result.failures:
            print(f"  - {failure}")
        sys.exit(1)
    if not result.changed_paths:
        print("当前项目已经是目标版本，无需修改。")
    else:
        print(f"当前项目已更新到 {project_mod.PRODUCT_VERSION}。")


def cmd_internal_uninstall_project(args) -> None:
    project_root = os.getcwd()
    scope = installer_mod.inspect_uninstall_scope(project_root)
    _print_project_uninstall_scope(scope)
    if args.check_only or not scope.existing_paths:
        return
    if not args.confirmed:
        print("内部项目卸载入口缺少已确认标记，未修改项目。")
        sys.exit(1)
    result = installer_mod.uninstall_project(project_root)
    for path in result.changed_paths:
        print(f"已删除: {path}")
    if not result.success:
        for failure in result.failures:
            print(f"  - {failure}")
        sys.exit(1)
    print("当前项目的 Workflow Loop 管理内容已全部删除。")


# Windows 下 stdout/stderr 被脚本捕获时可能退回本地西文编码，统一改成 UTF-8。
def _configure_utf8_output() -> None:
    for stream_name in ("stdout", "stderr"):
        stream = getattr(sys, stream_name, None)
        reconfigure = getattr(stream, "reconfigure", None)
        if not callable(reconfigure):
            continue
        try:
            reconfigure(encoding="utf-8")
        except (OSError, ValueError):
            pass


# CLI 入口：解析参数、分发到对应 handler
def main() -> None:
    _configure_utf8_output()
    # 创建 argparse 解析器
    parser = argparse.ArgumentParser(
        description="workflow_loop 工作流管理 CLI",
        prog="workflow",
    )
    # --version：固定产品身份查询，输出 "workflow-loop 0.1.0"
    # 安装脚本用它核对同名命令身份和兼容版本
    parser.add_argument("--version", action="version", version=PRODUCT_IDENTITY)
    # 子命令。metavar 固定列出公开命令，内部维护入口不出现在普通帮助中
    subparsers = parser.add_subparsers(
        dest="command",
        help="可用命令",
        metavar="{start,discuss,test,acceptance,gate,status,done,abort,return,update,uninstall}",
    )

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

    # test 命令：测试计划阶段登记项目入口；测试执行阶段登记并执行主题测试。
    test_parser = subparsers.add_parser("test", help="登记项目测试入口、登记或执行主题测试")
    test_subparsers = test_parser.add_subparsers(dest="test_action", required=True)
    test_entry_parser = test_subparsers.add_parser(
        "entry",
        help="在测试计划环节登记项目全量测试入口（按操作系统的参数数组；只登记不运行）",
    )
    test_entry_parser.add_argument("--default", nargs="+", help="默认入口参数数组")
    test_entry_parser.add_argument("--windows", nargs="+", help="Windows 入口参数数组")
    test_entry_parser.add_argument("--linux", nargs="+", help="Linux 入口参数数组")
    test_entry_parser.add_argument("--darwin", nargs="+", help="macOS 入口参数数组")
    test_entry_parser.add_argument(
        "--script",
        action="append",
        default=[],
        help="本轮新建或将修改的统一入口脚本路径；多个脚本时重复填写，必须在写脚本前登记",
    )
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
        "--cwd",
        default=None,
        help="测试工作目录（项目内相对路径；默认项目根）",
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
    gate_parser = subparsers.add_parser(
        "gate",
        help="推进当前环节三道门：讨论完成、程序检查、用户确认",
    )
    # stage 名（位置参数）
    gate_parser.add_argument(
        "stage",
        help="当前环节的程序标识；workflow status 会同时显示它的中文含义",
    )
    # --discuss-done：第 1 道闸
    gate_parser.add_argument("--discuss-done", action="store_true",
                             help="第一道门：记录当前问题已聊清楚，可以开始产出")
    # --confirmed：第 3 道闸
    gate_parser.add_argument("--confirmed", action="store_true",
                             help="第三道门：记录用户看过当前结果并同意，随后进入下一环节")
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
        help="退回目标阶段（必须是本轮实际路径中当前阶段之前的真实环节）",
    )
    return_parser.add_argument(
        "--topic",
        action="append",
        help="直接受影响主题；可重复填写。已有主题时必须明确填写或使用 --all-topics",
    )
    return_parser.add_argument(
        "--all-topics",
        action="store_true",
        help="明确标记当前全部主题都受影响",
    )
    return_parser.add_argument("--reason", required=True, help="退回原因")

    update_parser = subparsers.add_parser(
        "update",
        help="更新电脑全局命令和当前项目的 Workflow Loop 管理文件",
    )
    update_parser.add_argument(
        "--version",
        default=None,
        help="指定更高的正式版本；省略时使用 PyPI 与 GitHub 共同确认的最新正式版本",
    )

    uninstall_parser = subparsers.add_parser(
        "uninstall",
        help="强制卸载当前项目，或单独卸载电脑全局命令",
    )
    uninstall_parser.add_argument(
        "--global",
        dest="global_scope",
        action="store_true",
        help="只卸载电脑全局命令，绝不扫描或删除项目",
    )

    # _install-project 内部命令（只由官方安装脚本调用；不出现在普通帮助的公开命令列表中）
    internal_install_parser = subparsers.add_parser("_install-project")
    internal_install_parser.add_argument(
        "--transaction",
        required=True,
        help="官方安装脚本生成的一次性安装事务文件路径",
    )

    internal_update_parser = subparsers.add_parser("_update-project")
    internal_update_parser.add_argument("--check-only", action="store_true")
    internal_update_parser.add_argument("--confirmed", action="store_true")
    internal_update_parser.add_argument("--expected-project-version", default=None)

    internal_uninstall_parser = subparsers.add_parser("_uninstall-project")
    internal_uninstall_parser.add_argument("--check-only", action="store_true")
    internal_uninstall_parser.add_argument("--confirmed", action="store_true")

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
        if args.test_action == "entry":
            cmd_test_entry(args)
        elif args.test_action == "prepare":
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
    elif args.command == "update":
        cmd_update(args)
    elif args.command == "uninstall":
        cmd_uninstall(args)
    elif args.command == "_install-project":
        cmd_internal_install_project(args)
    elif args.command == "_update-project":
        cmd_internal_update_project(args)
    elif args.command == "_uninstall-project":
        cmd_internal_uninstall_project(args)
    else:
        # 未知命令（argparse 应该已经拦了，这是兜底）
        print(f"未知命令: {args.command}")
        parser.print_help()
        sys.exit(1)


# 脚本直接运行时调 main
if __name__ == "__main__":
    main()
