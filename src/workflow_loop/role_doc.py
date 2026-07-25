# 文档概览文本（start 命令和 status 命令可能打印）
# 给 AI 和用户介绍项目文档结构：spec/plan/bug/qa/acceptance/impl 各是什么、命名规则
# AI 读完理解项目文档全貌，后面每个 stage 基于这个理解工作
DOC_OVERVIEW = """═══ 文档概览 ═══

本项目使用 workflow_loop 工作流管理。文档结构：

【spec/】产品设计说明手册
  - product.md：产品设计说明书 + 功能路由
  - feature_*.md：按功能拆分的功能设计文档，文件名使用英文，正文使用中文
  - architecture_code_design.md：代码架构设计文档

【plan/】计划册
  - 一个实施任务一份 .md：文件名由实施计划确定，不要求与验收主题同名
  - index.md：计划索引表

【bug/】bug 册（沉淀已解决问题）
  - YYYY-MM-DD_HHmm-<bug描述>.md：单个 bug 记录
  - index.md：bug 索引表

【qa/】测试
  - <topic>_plan.md：测试计划
  - <topic>_result.md：测试执行结果
  - final_regression_result.md：全部主题完成后的最终全量回归结果
  - index.md：测试索引表

【acceptance/】验收
  - <topic>_plan.md：验收计划
  - <topic>_result.md：验收执行结果

【traceability.md】需求交付追踪表
  - 按工作流编号记录需求、验收主题、验收条件和后续阶段的对应位置

【impl/】实施记录
  - 一个实施任务一份 .md：文件名由实施计划确定，不要求与验收主题同名

验收计划、测试计划和主题测试/验收结果使用同一个主题名。
从零开发和修改产品在 acceptance_plan stage 确定主题；修 bug 在 reproduce stage 确定主题。实施计划和实施记录围绕这些验收主题组织，但不要求一一对应。"""

# stage 名 → 角色定义的映射表
# discuss 命令用 get_role_doc(stage_name) 拿角色定义，打印给 AI 看
# 角色定义告诉 AI："这个 stage 你是什么角色、要产出什么文件、文件放哪"
# 加新 stage 时在这里加一行映射即可
ROLE_DOC_MAP = {
    # 产品设计阶段：从零建立或改产品重新设计
    "spec": {
        "role": "产品设计师",
        "description": "和用户讨论产品要做什么、功能路由、功能拆分。产出 spec/product.md 和每个功能的 spec/feature_<english-name>.md。",
    },
    # 从零做的初步代码架构阶段：从已确认产品设计推导代码设计
    "code_design": {
        "role": "代码架构设计师（初步）",
        "description": "从已确认的产品设计推导代码分层、架构关键节点和各功能的完整代码过程，产出 spec/architecture_code_design.md。",
    },
    # 穿刺阶段：验证真实场景中的技术不确定性
    "spike": {
        "role": "技术不确定性验证工程师",
        "description": "先查看产品设计、代码设计、相关代码和运行事实，找出必须用真实场景确认的技术不确定性。用户决定执行哪些穿刺项；验证完成后记录真实证据，并把结论同步到受影响的设计文档。",
    },
    # 存量项目首次初始化：一次建立产品+功能+架构三类产物
    "project_design_init": {
        "role": "存量产品与架构分析师",
        "description": "首次处理已有代码项目时，必须查看代码和测试，具备安全条件时实际运行，一次建立相互一致的产品文档、代码架构文档和调查证据。",
    },
    # 改产品设计期架构修订：按新设计改架构图
    "revise_code_design": {
        "role": "架构文档修订者",
        "description": "改产品路径上，按变更后的产品设计修改 spec/architecture_code_design.md。",
    },
    # 末段详细架构收尾：反映最终被验证和接受的真实结构
    "update_code_design": {
        "role": "架构文档更新者（详细）",
        "description": "最终全量回归和整体验收通过后，更新/写全 spec/architecture_code_design.md，反映最终真实结构。",
    },
    # 实施计划制定阶段：使用验收计划已经确认的主题
    "plan": {
        "role": "实施计划制定者",
        "description": "根据已确认的验收主题和测试计划制定实施步骤，产出计划文档和 plan/index.md，不在这里重新确定主题。",
    },
    # 修复实施计划阶段：使用验收计划已经确认的主题
    "fix_plan": {
        "role": "修复实施计划制定者",
        "description": "根据已确认的验收主题和测试计划制定修复步骤，产出计划文档和 plan/index.md，不在这里重新确定主题。",
    },
    # 验收计划制定阶段
    "acceptance_plan": {
        "role": "验收计划制定者",
        "description": "根据已确认需求确定或复用全部验收主题，并为每个主题制定什么算完成。产出 traceability.md 和 acceptance/<topic>_plan.md。",
    },
    # 测试计划制定阶段
    "test_plan": {
        "role": "测试计划制定者",
        "description": "把验收条件转换为可执行测试范围。产出 qa/<topic>_plan.md + 更新 qa/index.md。",
    },
    # 实施执行阶段：改真实代码
    "impl": {
        "role": "实施执行者",
        "description": "执行已确认的实施/修复计划并修改真实代码。按实施任务产出 impl/ 下的实施记录，不要求与验收主题同名。",
    },
    # 测试执行阶段：按计划执行测试并记录证据
    "test": {
        "role": "测试执行者",
        "description": "按照 qa/<topic>_plan.md 执行全部必要测试并记录证据。产出 qa/<topic>_result.md。",
    },
    # 最终验收执行阶段：必须由用户确认，AI 不得代验收
    "acceptance": {
        "role": "主题验收执行者",
        "description": "某个主题测试通过后，按照 acceptance/<topic>_plan.md 执行该主题验收。产出 acceptance/<topic>_result.md。",
    },
    "topic_execution": {
        "role": "按主题执行协调者",
        "description": "按照实施计划分别推进各主题的实施、测试和验收。独立主题可以分别推进；全部主题完成后进入最终全量回归。",
    },
    "regression_test": {
        "role": "最终回归测试执行者",
        "description": "全部主题完成后，对全部已合并代码执行最终全量回归。产出 qa/final_regression_result.md；只有代码门禁确认“回归状态：通过”后才能继续。",
    },
    "overall_acceptance": {
        "role": "整体验收执行者",
        "description": "代码先复核全部主题验收和最终全量回归已经通过，再由用户确认整个需求是否完成。本阶段不生成新的结果文档。",
    },
    # bug 复现阶段：复现+根因分析
    "reproduce": {
        "role": "bug 复现者",
        "description": "使用真实场景复现缺陷并确认根因，根据修复后用户应该恢复得到的结果确定一个验收主题，产出缺陷记录并更新 bug/index.md。",
    },
}


# 根据 stage 名拿角色定义
# discuss 命令调用：拿到 {role, description} dict，打印给 AI 看
# 返回 None 表示该 stage 没有角色定义（discuss 会打印"无角色定义"）
def get_role_doc(stage_name: str) -> dict | None:
    # 从映射表查找，找不到返回 None
    return ROLE_DOC_MAP.get(stage_name)


# 返回文档概览文本
# start 命令和其它命令可能调用，打印给 AI 和用户看
def get_overview() -> str:
    return DOC_OVERVIEW
