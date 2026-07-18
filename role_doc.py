"""
role_doc.py：文档概览硬编码模块。

职责：
- 给 AI 和用户讲解项目文档结构（spec/plan/bug/qa/acceptance/impl 各是啥、命名规则、index.md 角色）
- 给每个 stage 提供角色定义（该 stage AI 该干啥、产出什么文件）
- 穿刺阶段：硬编码在代码里；后面可做成 .workflow_loop/roles/<stage>.md 配置文件

设计模式：
- 用 dict 做 stage → 角色定义的映射表，简单直接
- 加新 stage 的角色定义时，在 ROLE_MAP 里加一行即可
- 后面想做配置化，把 ROLE_MAP 改成从 .md 文件读取即可，接口不变

注意：
- role_doc 不是提示词（提示词在 Template_Repository/）
- role_doc 不是规范词（规范词在 Standardized_Repository/）
- role_doc 是"这个 stage 的角色是什么、要产出什么文件"的结构化定义
"""

# ── 文档概览（overview 命令打印的内容）──────────────────

# 整个文档系统的结构说明，给 AI 和用户看
# AI 读完这个，理解项目文档的全貌，后面每个 stage 都基于这个理解工作
DOC_OVERVIEW = """═══ 文档概览 ═══

本项目使用 workflow_loop 工作流管理。文档结构：

【spec/】产品设计说明手册
  - product.md：产品设计说明书 + 功能路由
  - 功能*.md：按功能拆分的功能设计文档
  - architecture_code_design.md：代码架构设计文档

【plan/】计划册
  - YYYY-MM-DD_HHmm-主题.md：单个计划
  - index.md：计划索引表

【bug/】bug 册（沉淀已解决问题）
  - YYYY-MM-DD_HHmm-主题.md：单个 bug 记录
  - index.md：bug 索引表

【qa/】测试检查清单
  - YYYY-MM-DD_HHmm-主题.md：单个测试计划
  - index.md：测试索引表

【acceptance/】acceptance criteria
  - YYYY-MM-DD_HHmm-主题.md：单个 acceptance criteria

【impl/】实施计划
  - YYYY-MM-DD_HHmm-主题.md：单个实施计划

文件命名规则：YYYY-MM-DD_HHmm-<主题>.md
主题在 plan stage 定下，acceptance/qa/impl 复用。"""


# ── 每个 stage 的角色定义 ────────────────────────────────

# role_doc_map：stage 名 → 该 stage 的角色定义
# 角色定义告诉 AI："这个 stage 你是什么角色、要产出什么文件、文件放哪"
# 加新 stage 时，在这里加一行映射即可
ROLE_DOC_MAP = {
    # spec stage：产品设计师角色，产出产品设计文档 + 功能拆分文档
    "spec": {
        "role": "产品设计师",
        "description": "和用户讨论产品要做什么、功能路由、功能拆分。产出 spec/product.md 和每个功能的 spec/功能<名>.md。",
    },
    # spike stage：风险验证者角色，产出穿刺结论文档，throwaway 代码进 spike_tmp/
    "spike": {
        "role": "风险验证者",
        "description": "问用户哪些功能要穿刺、提前识别风险。写 throwaway 代码到 .workflow_loop/spike_tmp/ 验证风险，写结论文档 spec/spike_<临时名>.md。",
    },
    # plan stage：计划制定者角色，产出计划文档，主题在这里定下
    "plan": {
        "role": "计划制定者",
        "description": "和用户讨论怎么拆分计划。产出 plan/<主题>.md + plan/index.md。主题在这里定下，后面 stage 复用。",
    },
    # acceptance stage：acceptance criteria 制定者角色，产出acceptance文档，复用 plan 的主题
    "acceptance": {
        "role": "acceptance criteria 制定者",
        "description": "和用户讨论acceptance criteria（什么算完成）。产出 acceptance/<主题>.md（和 plan 同主题）。",
    },
    # qa stage：测试计划制定者角色，产出测试清单，复用主题
    "qa": {
        "role": "测试计划制定者",
        "description": "和用户讨论测试清单。产出 qa/<主题>.md + qa/index.md（和 plan/acceptance 同主题）。",
    },
    # impl stage：实施计划制定者角色，产出实施计划，复用主题
    "impl": {
        "role": "实施计划制定者",
        "description": "和用户讨论实施方案。产出 impl/<主题>.md（和 plan/acceptance/qa 同主题）。",
    },
    # generate_code_design stage：架构文档撰写者角色，第一次写 architecture_code_design.md
    "generate_code_design": {
        "role": "架构文档撰写者",
        "description": "impl 完成后，第一次写 spec/architecture_code_design.md（代码架构设计文档）。product.md 里的路由链接这时才指向有效文件。",
    },
    # update_code_design stage：架构文档更新者角色，更新已存在的 architecture_code_design.md
    "update_code_design": {
        "role": "架构文档更新者",
        "description": "impl 完成后，更新 spec/architecture_code_design.md，把实施过程中的新理解写回去。",
    },
    # code_design stage（场景 B 专用）：代码阅读者角色，看代码+跑项目，反推 architecture_code_design.md
    "code_design": {
        "role": "代码阅读者",
        "description": "看项目代码 + 能跑就跑。产出 spec/architecture_code_design.md（从代码反推架构）。",
    },
    # reproduce stage（场景 C 专用）：bug 复现者角色，复现问题+根因分析
    "reproduce": {
        "role": "bug 复现者",
        "description": "和用户讨论 bug 现象、复现步骤。产出 bug/<YYYY-MM-DD_HHmm-<bug描述>>.md + 更新 bug/index.md。",
    },
    # fix_plan stage（场景 C 专用）：修复计划制定者角色，定主题（从 bug 反推）
    "fix_plan": {
        "role": "修复计划制定者",
        "description": "和用户讨论修复方案。产出 plan/<主题>.md + 更新 plan/index.md。主题在这里定下（从 bug 反推）。",
    },
    # requirement stage（场景 D 专用）：需求分析师角色，对需求
    "requirement": {
        "role": "需求分析师",
        "description": "和用户讨论新需求/变更。产出 spec/requirement_<临时名>.md。",
    },
    # product_update stage（场景 D 专用）：产品设计更新者角色，更新 product.md
    "product_update": {
        "role": "产品设计更新者",
        "description": "和用户讨论怎么改 product.md。更新 spec/product.md（不是新建，是修改）。",
    },
    # feature_split stage（场景 D 专用）：功能拆分者角色，产出新功能文档
    "feature_split": {
        "role": "功能拆分者",
        "description": "和用户讨论功能怎么拆。产出 spec/功能<新>.md（可能多个）。",
    },
}


def get_role_doc(stage_name: str) -> dict | None:
    """根据 stage 名拿角色定义。
    返回 {role, description} dict，或 None（stage 没有角色定义时）。
    调用方（discuss 命令）用这个拿到角色定义，打印给 AI 看。"""
    # 从 ROLE_DOC_MAP 查找，找不到返回 None
    return ROLE_DOC_MAP.get(stage_name)


def get_overview() -> str:
    """返回文档概览文本，供 overview 命令打印。
    这个文本给 AI 和用户都看，AI 读完理解项目文档全貌。"""
    return DOC_OVERVIEW
