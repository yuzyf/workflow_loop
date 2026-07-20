# 导入阶段基类与公共工具，供所有阶段子类继承和复用
from .base import StageStrategy, clean_spike_tmp
# 导入工作流中各阶段策略类，按 spec → design → spike → plan → impl → test → acceptance 流水线组织
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

# 对外公开的阶段 API 清单，约束 from workflow_loop.stages import * 的导出范围，避免内部实现泄露
__all__ = [
    "StageStrategy",
    "clean_spike_tmp",
    "SpecStage",
    "CodeDesignStage",
    "SpikeStage",
    "PlanStage",
    "AcceptancePlanStage",
    "TestPlanStage",
    "ImplStage",
    "TestStage",
    "AcceptanceStage",
    "UpdateCodeDesignStage",
    "ProjectDesignInitStage",
    "ReviseCodeDesignStage",
    "ReproduceStage",
    "FixPlanStage",
]
