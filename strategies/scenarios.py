"""
scenarios.py：所有场景策略实现。

4 个场景：
1. NewProjectScenario（场景 A）：完全实现，stages = [spec, spike, plan, 验收, qa, impl, 生成代码设计]
2. ExistingNoWorkflowScenario（场景 B）：stub，stages 返回 []，TODO
3. BugfixScenario（场景 C）：stub，stages 返回 []，TODO
4. ProductModScenario（场景 D）：stub，stages 返回 []，TODO

加新场景的姿势：
    class RefactorScenario(ScenarioStrategy):
        def name(self): return "refactor"
        def stages(self): return [RefactorPlanStage(), ...]
        def entry_instruction(self): return "重构入口：..."
然后在 workflow.py 的 SCENARIO_REGISTRY 里加一行映射。完事。
"""
from .base import ScenarioStrategy
from .stages import (
    SpecStage, SpikeStage, PlanStage, 验收Stage, QaStage, ImplStage, 生成代码设计Stage,
    代码设计Stage, 更新代码设计Stage, ReproduceStage, FixPlanStage,
    RequirementStage, ProductUpdateStage, FeatureSplitStage,
)


class NewProjectScenario(ScenarioStrategy):
    """新项目场景（场景 A）：spec → spike → plan → 验收 → qa → impl → 生成代码设计。
    
    完全实现。这是穿刺唯一跑通的场景。
    环节顺序硬编码在 stages() 里，加新环节时在这个列表里插入即可。"""

    def name(self) -> str:
        # 场景名，存到 state.json 的 scenario 字段
        return "new_project"

    def stages(self) -> list:
        # 按顺序返回 7 个 stage 实例
        # workflow.py 拿到这个列表，按顺序推进
        # 加新 stage = 在这个列表里插入新 stage 实例
        return [
            SpecStage(),           # 产品设计
            SpikeStage(),          # 穿刺验证风险
            PlanStage(),           # 计划拆分（主题在这里定）
            验收Stage(),            # 验收标准
            QaStage(),             # 测试计划
            ImplStage(),           # 实施计划
            生成代码设计Stage(),    # 生成代码架构设计文档
        ]

    def entry_instruction(self) -> str:
        # 进入这个场景时打印给 AI 的路线图
        # 告诉 AI 整体路线，不是只看眼前
        return "新项目入口：spec → spike → plan → 验收 → qa → impl → 生成代码设计，7 个阶段顺序推进"


class ExistingNoWorkflowScenario(ScenarioStrategy):
    """存量无 workflow_loop 场景（场景 B）：
    代码设计 → spec → spike → plan → 验收 → qa → impl → 更新代码设计。
    
    TODO: 后面实现。穿刺阶段 stages() 返回 []，不报错但不跑。"""

    def name(self) -> str:
        return "existing_no_workflow"

    def stages(self) -> list:
        # TODO: 后面实现，返回完整的 stage 序列
        # 应该是：[代码设计Stage(), SpecStage(), SpikeStage(), PlanStage(), 验收Stage(), QaStage(), ImplStage(), 更新代码设计Stage()]
        return []

    def entry_instruction(self) -> str:
        return "TODO: 存量无 workflow_loop 入口未实现（代码设计 → spec → spike → plan → 验收 → qa → impl → 更新代码设计）"


class BugfixScenario(ScenarioStrategy):
    """修 bug 场景（场景 C）：
    reproduce → fix_plan → 验收 → qa → impl → 更新代码设计。
    
    TODO: 后面实现。穿刺阶段 stages() 返回 []。"""

    def name(self) -> str:
        return "bugfix"

    def stages(self) -> list:
        # TODO: 后面实现
        # 应该是：[ReproduceStage(), FixPlanStage(), 验收Stage(), QaStage(), ImplStage(), 更新代码设计Stage()]
        return []

    def entry_instruction(self) -> str:
        return "TODO: bugfix 子流程未实现（reproduce → fix_plan → 验收 → qa → impl → 更新代码设计）"


class ProductModScenario(ScenarioStrategy):
    """改产品设计场景（场景 D）：
    requirement → product_update → feature_split → spike → plan → 验收 → qa → impl → 更新代码设计。
    
    TODO: 后面实现。穿刺阶段 stages() 返回 []。"""

    def name(self) -> str:
        return "product_mod"

    def stages(self) -> list:
        # TODO: 后面实现
        # 应该是：[RequirementStage(), ProductUpdateStage(), FeatureSplitStage(), SpikeStage(), PlanStage(), 验收Stage(), QaStage(), ImplStage(), 更新代码设计Stage()]
        return []

    def entry_instruction(self) -> str:
        return "TODO: product_mod 子流程未实现（requirement → product_update → feature_split → spike → plan → 验收 → qa → impl → 更新代码设计）"


# ── 场景注册表 ──────────────────────────────────────────
# workflow.py 用这个 dict 根据 --entry 参数找对应 scenario
# 加新 scenario = 加一个子类 + 在这里加一行映射
SCENARIO_REGISTRY = {
    "new-project": NewProjectScenario,           # 场景 A
    "existing-no-workflow": ExistingNoWorkflowScenario,  # 场景 B
    "bugfix": BugfixScenario,                    # 场景 C
    "product-mod": ProductModScenario,           # 场景 D
}
