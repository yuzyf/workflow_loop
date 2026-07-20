from .project import is_project_design_initialized
from .stages import (
    SpecStage,
    CodeDesignStage,
    SpikeStage,
    PlanStage,
    AcceptancePlanStage,
    TestPlanStage,
    ImplStage,
    TestStage,
    AcceptanceStage,
    UpdateCodeDesignStage,
    ProjectDesignInitStage,
    ReviseCodeDesignStage,
    ReproduceStage,
    FixPlanStage,
)
from .stages.base import StageStrategy

# from_scratch（从零做）的完整 stage 路径
# 顺序固定：先产品设计与功能拆分、后初步架构（先定做什么，再定怎么搭）
# 然后穿刺验证风险 → 制定计划 → 验收计划 → 测试计划 → 实施 → 测试 → 验收 → 详细架构收尾
# 共享后半截：plan → acceptance_plan → test_plan → impl → test → acceptance → update_code_design
FROM_SCRATCH_PATH = [
    # 产品设计阶段：产出 spec/product.md + spec/功能*.md
    SpecStage,
    # 初步架构阶段：产出 spec/architecture_code_design.md（从零做的初步架构）
    CodeDesignStage,
    # 穿刺阶段：验证设计风险，throwaway 代码进 spike_tmp/，结论文档进 spec/spike_*.md
    # 可选 stage，可通过 gate spike --skip 跳过
    SpikeStage,
    # 计划阶段：产出 plan/<主题>.md + plan/index.md（主题在这里定下）
    PlanStage,
    # 验收计划阶段：制定什么算完成，产出 acceptance/<topic>_plan.md
    AcceptancePlanStage,
    # 测试计划阶段：把验收条件转为可执行测试范围，产出 qa/<topic>_plan.md
    TestPlanStage,
    # 实施阶段：执行已确认的计划并改代码，产出 impl/<topic>.md
    ImplStage,
    # 测试执行阶段：按测试计划执行测试并记录证据，产出 qa/<topic>_result.md
    # 强制 Stage，不提供 --skip
    TestStage,
    # 最终验收阶段：按验收计划执行验收，产出 acceptance/<topic>_result.md
    # 强制 Stage，门3必须由用户确认，AI 不得代验收
    AcceptanceStage,
    # 详细架构收尾：更新 spec/architecture_code_design.md 反映最终真实结构
    # 所有意图末环同名，强制不可跳过
    UpdateCodeDesignStage,
]

# product_change（改产品）的基础 stage 路径（不含 project_design_init 前置）
# 和 from_scratch 的差异：用 ReviseCodeDesignStage 替代 CodeDesignStage
# spec 之后必须经过 revise_code_design（设计期改架构），不能只改产品不改架构
PRODUCT_CHANGE_BASE = [
    # 产品设计阶段：基于现状重新设计，可新增/修改/删除功能文档
    SpecStage,
    # 设计期架构修订：按变更后的产品设计改架构图
    # 与末段 update_code_design（详细落地）名称分离，避免同一 Run 内 stage 名冲突
    ReviseCodeDesignStage,
    # 穿刺阶段（可选）
    SpikeStage,
    # 计划阶段（定主题）
    PlanStage,
    # 验收计划阶段
    AcceptancePlanStage,
    # 测试计划阶段
    TestPlanStage,
    # 实施阶段
    ImplStage,
    # 测试执行阶段（强制）
    TestStage,
    # 最终验收阶段（强制）
    AcceptanceStage,
    # 详细架构收尾（强制）
    UpdateCodeDesignStage,
]

# bugfix（修 bug）的基础 stage 路径（不含 project_design_init 前置）
# 和 from_scratch 的差异：没有 spec/spike/plan，换成 reproduce/fix_plan
# 主题在 fix_plan 定（从 bug 反推），不复用 plan
# 末段 update_code_design 即使无结构变化也必须走，在门禁中显式确认"无结构变化"
BUGFIX_BASE = [
    # 复现阶段：复现 bug + 根因分析，产出 bug/<...>.md + 更新 bug/index.md
    ReproduceStage,
    # 修复计划阶段：定主题（从 bug 反推），产出 plan/<主题>.md
    FixPlanStage,
    # 验收计划阶段
    AcceptancePlanStage,
    # 测试计划阶段
    TestPlanStage,
    # 实施阶段（修代码）
    ImplStage,
    # 测试执行阶段（强制）
    TestStage,
    # 最终验收阶段（强制）
    AcceptanceStage,
    # 详细架构收尾（强制，无结构变化也要显式确认）
    UpdateCodeDesignStage,
]

# 正式互斥意图列表（start --intent 的合法值）
# docs_only 暂不作为正式意图
INTENT_CHOICES = ["from_scratch", "product_change", "bugfix"]


# 根据 intent 和项目事实返回 stage 列表（CONTEXT.md "Path Composer"）
# 取代旧的四个 Scenario 类并行流水线与 SCENARIO_REGISTRY
# 在 start --intent 时调一次，结果存入 state.stage_path，后续命令读 state.stage_path
# 不在每次命令调用时重新跑 PathComposer（条件在 start 时就固定）
def build_stage_path(intent: str, project_root: str) -> list[StageStrategy]:
    # 从零做：直接返回 FROM_SCRATCH_PATH 的实例列表
    # from_scratch 不走 project_design_init（那只有 product_change/bugfix 走）
    # from_scratch 在 spec + code_design 都 --confirmed 后写 project_design_initialized=true
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
