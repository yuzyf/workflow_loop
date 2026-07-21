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
  - <topic>.md：单个计划
  - index.md：计划索引表

【bug/】bug 册（沉淀已解决问题）
  - YYYY-MM-DD_HHmm-<bug描述>.md：单个 bug 记录
  - index.md：bug 索引表

【qa/】测试与验收
  - <topic>_plan.md：测试计划
  - <topic>_result.md：测试执行结果
  - index.md：测试索引表

【acceptance/】验收
  - <topic>_plan.md：验收计划
  - <topic>_result.md：验收执行结果

【impl/】实施记录
  - <topic>.md：单个实施记录

文件命名规则：<folder>/<topic>.md 或 <folder>/<topic>_<plan|result>.md
主题在 plan/fix_plan stage 定下，后续 stage 复用。"""

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
    # 穿刺阶段：验证设计风险，throwaway 代码进 spike_tmp/
    "spike": {
        "role": "风险验证者",
        "description": "问用户哪些功能要穿刺、提前识别风险。写 throwaway 代码到 .workflow_loop/spike_tmp/ 验证风险，写结论文档 spec/spike_<临时名>.md。",
    },
    # 存量项目首次初始化：一次建立产品+功能+架构三类产物
    "project_design_init": {
        "role": "存量产品与架构分析师",
        "description": "首次处理已有代码项目时，必须查看代码和测试，具备安全条件时实际运行，一次建立相互一致的 spec/product.md、spec/feature_*.md 和 spec/architecture_code_design.md。",
    },
    # 改产品设计期架构修订：按新设计改架构图
    "revise_code_design": {
        "role": "架构文档修订者",
        "description": "改产品路径上，按变更后的产品设计修改 spec/architecture_code_design.md。",
    },
    # 末段详细架构收尾：反映最终被验证和接受的真实结构
    "update_code_design": {
        "role": "架构文档更新者（详细）",
        "description": "测试与最终验收通过后，更新/写全 spec/architecture_code_design.md，反映最终真实结构。",
    },
    # 计划制定阶段：定主题
    "plan": {
        "role": "计划制定者",
        "description": "和用户讨论怎么拆分计划。产出 plan/<主题>.md + plan/index.md。主题在这里定下。",
    },
    # 修复计划阶段：定主题（从 bug 反推）
    "fix_plan": {
        "role": "修复计划制定者",
        "description": "和用户讨论修复方案。产出 plan/<主题>.md + 更新 plan/index.md。主题从 bug 反推。",
    },
    # 验收计划制定阶段
    "acceptance_plan": {
        "role": "验收计划制定者",
        "description": "制定什么算完成的验收计划。产出 acceptance/<topic>_plan.md。",
    },
    # 测试计划制定阶段
    "test_plan": {
        "role": "测试计划制定者",
        "description": "把验收条件转换为可执行测试范围。产出 qa/<topic>_plan.md + 更新 qa/index.md。",
    },
    # 实施执行阶段：改真实代码
    "impl": {
        "role": "实施执行者",
        "description": "执行已确认的实施/修复计划并修改真实代码。产出 impl/<topic>.md 实施记录。",
    },
    # 测试执行阶段：按计划执行测试并记录证据
    "test": {
        "role": "测试执行者",
        "description": "按照 qa/<topic>_plan.md 执行全部必要测试并记录证据。产出 qa/<topic>_result.md。",
    },
    # 最终验收执行阶段：必须由用户确认，AI 不得代验收
    "acceptance": {
        "role": "验收执行者",
        "description": "在测试通过后，按照 acceptance/<topic>_plan.md 执行最终验收。产出 acceptance/<topic>_result.md。",
    },
    # bug 复现阶段：复现+根因分析
    "reproduce": {
        "role": "bug 复现者",
        "description": "和用户讨论 bug 现象、复现步骤。产出 bug/<YYYY-MM-DD_HHmm-<bug描述>>.md + 更新 bug/index.md。",
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
