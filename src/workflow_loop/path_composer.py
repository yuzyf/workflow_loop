from .project import is_project_design_initialized
from .stages import (
    SpecStage,
    SpikeStage,
    ImplStage,
    AcceptancePlanStage,
    TopicAcceptanceStage,
    RegressionTestStage,
    OverallAcceptanceStage,
    UpdateCodeDesignStage,
    ProjectDesignInitStage,
    ReproduceStage,
)
from .stages.stages import QaStage
from .stages.base import StageStrategy

# 旧阶段只用于识别和迁移已经开始的轮次；新路径不得再次生成这些用户环节。
LEGACY_STAGE_NAMES = {
    "code_design",
    "revise_code_design",
    "test_plan",
    "test_code",
    "test_execution",
}


# from_scratch（从零做）的完整 stage 路径。最低限度实现设计属于 impl 的代码计划，
# 测试计划、测试代码和正式执行属于同一个 qa 用户环节。
FROM_SCRATCH_PATH = [
    # 产品设计阶段：产出 spec/product.md + spec/feature_*.md
    SpecStage,
    # 穿刺阶段：验证真实场景中的技术不确定性，写清单和每项结论；临时代码按需进入 spike_tmp/
    # 可选 stage，可通过 gate spike --skip 跳过
    SpikeStage,
    # 验收计划阶段：制定什么算完成，产出 traceability.md + acceptance/index.md + acceptance/<topic>_plan.md
    AcceptancePlanStage,
    # 实施阶段：先确认全部主题计划，再修改真实代码并记录实施结果
    ImplStage,
    # 单一测试验证阶段：范围确认后连续完成计划、测试代码、登记、执行和结果
    QaStage,
    # 测试通过后，按主题验收计划核对用户结果
    TopicAcceptanceStage,
    # 全部主题完成后，对合并代码执行最终全量回归
    RegressionTestStage,
    # 最终全量回归通过后，确认整个需求是否完成
    OverallAcceptanceStage,
    # 最终设计同步：更新 spec/architecture_code_design.md 反映产品、架构和真实代码映射
    # 所有意图末环同名，强制不可跳过
    UpdateCodeDesignStage,
]

# product_change（改产品）的基础 stage 路径（不含 project_design_init 前置）。
# 修改产品不再建立独立的设计期代码修订阶段，最终真实架构仍在末段同步。
PRODUCT_CHANGE_BASE = [
    # 产品设计阶段：基于现状重新设计，可新增/修改/删除功能文档
    SpecStage,
    # 穿刺阶段（可选）
    SpikeStage,
    # 验收计划阶段
    AcceptancePlanStage,
    # 实施阶段：先确认全部主题计划，再修改真实代码并记录实施结果
    ImplStage,
    # 单一测试验证阶段
    QaStage,
    TopicAcceptanceStage,
    # 最终全量回归
    RegressionTestStage,
    # 整体验收
    OverallAcceptanceStage,
    # 最终设计同步（强制）
    UpdateCodeDesignStage,
]

# bugfix（修 bug）的基础 stage 路径（不含 project_design_init 前置）
# 和 from_scratch 的差异：没有 spec/code_design，先 reproduce，再经过可选 spike；
# 在共享后半截中使用 impl 制定并执行修复实施计划
# 末段 update_code_design 即使无架构变化也必须走，在门禁中显式确认"架构未变化"
BUGFIX_BASE = [
    # 复现阶段：复现 bug + 根因分析，并确定一份缺陷记录对应的验收主题
    ReproduceStage,
    # 穿刺阶段：验证修复仍依赖的真实技术不确定性；没有时由用户确认跳过
    SpikeStage,
    # 验收计划阶段
    AcceptancePlanStage,
    # 实施阶段：先确认全部主题计划，再修改真实代码并记录实施结果
    ImplStage,
    # 单一测试验证阶段
    QaStage,
    TopicAcceptanceStage,
    # 最终全量回归
    RegressionTestStage,
    # 整体验收
    OverallAcceptanceStage,
    # 最终设计同步（强制，无架构变化也要显式确认）
    UpdateCodeDesignStage,
]

# 正式互斥意图列表（start --intent 的合法值）
INTENT_CHOICES = ["from_scratch", "product_change", "bugfix", "light_task"]


# 根据工作意图和项目设计初始化事实返回本轮阶段列表
# 取代旧的四个 Scenario 类并行流水线与 SCENARIO_REGISTRY
# 在 start --intent 时调一次，结果存入 state.stage_path，后续命令读 state.stage_path
# 不在每次命令调用时重新跑 PathComposer（条件在 start 时就固定）
def build_stage_path(intent: str, project_root: str) -> list[StageStrategy]:
    # light_task（无需开发任务）走独立简单流程，不应被伪装成空的研发阶段路径。
    if intent == "light_task":
        raise ValueError("light_task（无需开发任务）不使用研发 stage 路径")
    # 从零做：直接返回 FROM_SCRATCH_PATH 的实例列表
    # from_scratch 不走 project_design_init（那只有 product_change/bugfix 走）
    # from_scratch 只在最终 update_code_design 确认后写 project_design_initialized=true
    if intent == "from_scratch":
        # 实例化每个 stage 类
        return [cls() for cls in FROM_SCRATCH_PATH]
    # 改产品：先检查 project_design_initialized
    if intent == "product_change":
        # 收集 stage 实例
        stages = []
        # 如果项目设计未初始化，前置 project_design_init stage
        # 不能用 architecture_code_design.md 是否存在决定跳过
        if not is_project_design_initialized(project_root):
            # 前置项目设计架构初始化 stage
            stages.append(ProjectDesignInitStage())
        # 追加 product_change 的基础路径
        stages.extend(cls() for cls in PRODUCT_CHANGE_BASE)
        return stages
    # 修 bug：先检查 project_design_initialized
    if intent == "bugfix":
        # 收集 stage 实例
        stages = []
        # 如果项目设计未初始化，前置 project_design_init stage
        if not is_project_design_initialized(project_root):
            # 前置项目设计架构初始化 stage
            stages.append(ProjectDesignInitStage())
        # 追加 bugfix 的基础路径
        stages.extend(cls() for cls in BUGFIX_BASE)
        return stages
    # 未知 intent：报错并提示合法值
    raise ValueError(f"未知 intent: {intent}，可选值: {INTENT_CHOICES}")
