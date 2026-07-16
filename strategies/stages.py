"""
stages.py：所有具体环节策略实现。

每个类对应一个 stage，继承 StageStrategy，实现所有 abstract 方法。

分两组：
1. 场景 A（新项目）的 7 个 stage：完全实现
   - SpecStage / SpikeStage / PlanStage / 验收Stage / QaStage / ImplStage / 生成代码设计Stage

2. 场景 B/C/D 的 7 个 stage：stub（留口子，后面填）
   - 代码设计Stage / 更新代码设计Stage / ReproduceStage / FixPlanStage
   - RequirementStage / ProductUpdateStage / FeatureSplitStage

加新 stage 的姿势（用户说的"还可能加环节"）：
    class ReviewStage(StageStrategy):
        def name(self): return "review"
        def artifact_paths(self): return ["review/<主题>.md"]
        def role_doc_path(self): return None
        def prompt_doc_path(self): return "Template_Repository/review/prompt.md"
        def standard_doc_path(self): return "Standardized_Repository/review/standard.md"
        def instruction(self): return "评审阶段：产出 review/<主题>.md"
    然后在对应 scenario 的 stages() 列表里插入。完事，零改动 workflow.py。
"""
import os
from .base import StageStrategy, clean_spike_tmp


# ════════════════════════════════════════════════════════
# 场景 A 的 7 个 stage（完全实现）
# ════════════════════════════════════════════════════════

class SpecStage(StageStrategy):
    """产品设计阶段：产出 spec/product.md + spec/功能*.md。
    
    AI 和用户讨论产品要做什么、功能路由、功能拆分。
    讨论完毕后写 product.md 和每个功能的 功能.md。
    不定主题（spec 是整体设计，主题在 plan 定）。"""

    def name(self) -> str:
        # stage 标识，存到 state.json
        return "spec"

    def artifact_paths(self) -> list[str]:
        # 产出文件列表：product.md 是主文档
        # 功能*.md 的具体文件名由讨论决定，这里只列 product.md 作为最低要求
        # code_validate 至少检查 product.md 存在；功能.md 的检查后面加
        return ["spec/product.md"]

    def role_doc_path(self) -> str | None:
        # 穿刺：role_doc.py 硬编码，不读独立角色文件
        return None

    def prompt_doc_path(self) -> str | None:
        # 提示词文档路径（相对 .workflow_loop/）
        return "Template_Repository/spec/spec.md"

    def standard_doc_path(self) -> str | None:
        # 规范词文档路径（相对 .workflow_loop/）
        return "Standardized_Repository/spec/spec.md"

    def instruction(self) -> str:
        # 打印给 AI 的指令：这个 stage 干啥、产出什么
        return "产品设计阶段：产出 spec/product.md（产品设计说明书 + 功能路由）+ spec/功能*.md（功能拆分）"


class SpikeStage(StageStrategy):
    """穿刺阶段：验证设计风险，产出结论文档，throwaway 代码进 spike_tmp/。
    
    AI 问用户哪些功能要穿刺、提前识别风险。
    写 throwaway 代码到 .workflow_loop/spike_tmp/ 验证风险。
    写结论文档 spec/spike_<临时名>.md。
    on_advance 时清理 spike_tmp/（删除 throwaway 代码，只保留结论文档）。
    不定主题（主题在 plan 定）。"""

    def name(self) -> str:
        return "spike"

    def artifact_paths(self) -> list[str]:
        # 结论文档路径；临时名由讨论决定，这里用通配占位
        # code_validate 检查 spec/ 下是否有 spike_*.md 文件存在
        # 穿刺简化：只检查 spec/spike_ 目录存在（后面加具体文件检查）
        return ["spec/"]

    def role_doc_path(self) -> str | None:
        return None

    def prompt_doc_path(self) -> str | None:
        # 穿刺提示词：教 AI 怎么问用户、怎么识别风险、怎么写 throwaway 代码
        return "Template_Repository/spike/spike.md"

    def standard_doc_path(self) -> str | None:
        return "Standardized_Repository/spike/spike.md"

    def code_validate(self, project_root: str) -> tuple[bool, str]:
        """重写 code_validate：spike stage 的校验逻辑特殊。
        不检查具体文件（临时名不定），只检查 spec/ 目录下有 spike_ 开头的 .md 文件。"""
        # spec 目录路径
        spec_dir = os.path.join(project_root, "spec")
        # 目录不存在 → 不通过
        if not os.path.exists(spec_dir):
            return (False, "spec/ 目录不存在")
        # 检查 spec/ 下有没有 spike_ 开头的 .md 文件
        spike_files = [f for f in os.listdir(spec_dir) if f.startswith("spike_") and f.endswith(".md")]
        # 没有结论文档 → 不通过
        if not spike_files:
            return (False, "spec/ 下没有 spike_*.md 结论文档")
        # 通过
        return (True, f"穿刺结论文档存在: {spike_files}")

    def on_advance(self, project_root: str) -> None:
        """重写 on_advance：清理 throwaway 代码。
        spike stage 推进到 plan 前，删除 .workflow_loop/spike_tmp/ 下所有内容。
        只保留 spec/spike_*.md 结论文档。"""
        # 调用 base.py 的清理函数
        cleaned = clean_spike_tmp(project_root)
        # cleaned 列表供 journal 记录（workflow.py 的 gate --confirmed 命令会拿这个写 journal）

    def instruction(self) -> str:
        return "穿刺阶段：问用户哪些功能要穿刺、识别风险、写 throwaway 代码到 .workflow_loop/spike_tmp/、写结论文档 spec/spike_<临时名>.md"


class PlanStage(StageStrategy):
    """计划阶段：产出 plan/<主题>.md + plan/index.md。
    
    AI 和用户讨论怎么拆分计划。
    主题在这里定下（写入 state.topic），后面 stage 复用。"""

    def name(self) -> str:
        return "plan"

    def artifact_paths(self) -> list[str]:
        # 产出两个文件：主题计划文档 + 索引表
        # 主题文件名在讨论时定，这里用占位（code_validate 会做宽松检查）
        return ["plan/index.md"]

    def role_doc_path(self) -> str | None:
        return None

    def prompt_doc_path(self) -> str | None:
        return "Template_Repository/plan/plan.md"

    def standard_doc_path(self) -> str | None:
        return "Standardized_Repository/plan/plan.md"

    def instruction(self) -> str:
        return "计划阶段：产出 plan/<主题>.md + plan/index.md（主题在这里定下，后面 stage 复用）"


class 验收Stage(StageStrategy):
    """验收标准阶段：产出 验收/<主题>.md。
    
    AI 和用户讨论验收标准（什么算完成）。
    复用 plan stage 定下的主题做文件名。"""

    def name(self) -> str:
        return "验收"

    def artifact_paths(self) -> list[str]:
        # 验收文档路径（主题复用 plan 的）
        # 穿刺简化：只检查 验收/ 目录存在
        return ["验收/"]

    def role_doc_path(self) -> str | None:
        return None

    def prompt_doc_path(self) -> str | None:
        return "Template_Repository/qa/acceptance.md"

    def standard_doc_path(self) -> str | None:
        return "Standardized_Repository/qa/acceptance.md"

    def code_validate(self, project_root: str) -> tuple[bool, str]:
        """重写：验收 stage 检查 验收/ 目录下有 .md 文件。"""
        # 验收目录路径
        dir_path = os.path.join(project_root, "验收")
        # 目录不存在 → 不通过
        if not os.path.exists(dir_path):
            return (False, "验收/ 目录不存在")
        # 检查有没有 .md 文件
        md_files = [f for f in os.listdir(dir_path) if f.endswith(".md")]
        # 没有 → 不通过
        if not md_files:
            return (False, "验收/ 下没有 .md 文件")
        return (True, f"验收文档存在: {md_files}")

    def instruction(self) -> str:
        return "验收阶段：产出 验收/<主题>.md（和 plan 同主题，定义什么算完成）"


class QaStage(StageStrategy):
    """测试计划阶段：产出 qa/<主题>.md + qa/index.md。
    
    AI 和用户讨论测试清单。
    复用主题做文件名。"""

    def name(self) -> str:
        return "qa"

    def artifact_paths(self) -> list[str]:
        return ["qa/index.md"]

    def role_doc_path(self) -> str | None:
        return None

    def prompt_doc_path(self) -> str | None:
        return "Template_Repository/qa/qa.md"

    def standard_doc_path(self) -> str | None:
        return "Standardized_Repository/qa/qa.md"

    def instruction(self) -> str:
        return "测试阶段：产出 qa/<主题>.md + qa/index.md（和 plan/验收 同主题，测试检查清单）"


class ImplStage(StageStrategy):
    """实施计划阶段：产出 impl/<主题>.md。
    
    AI 和用户讨论实施方案。
    复用主题做文件名。"""

    def name(self) -> str:
        return "impl"

    def artifact_paths(self) -> list[str]:
        return ["impl/"]

    def role_doc_path(self) -> str | None:
        return None

    def prompt_doc_path(self) -> str | None:
        return "Template_Repository/impl/impl.md"

    def standard_doc_path(self) -> str | None:
        return "Standardized_Repository/impl/impl.md"

    def code_validate(self, project_root: str) -> tuple[bool, str]:
        """重写：impl stage 检查 impl/ 目录下有 .md 文件。"""
        dir_path = os.path.join(project_root, "impl")
        if not os.path.exists(dir_path):
            return (False, "impl/ 目录不存在")
        md_files = [f for f in os.listdir(dir_path) if f.endswith(".md")]
        if not md_files:
            return (False, "impl/ 下没有 .md 文件")
        return (True, f"实施计划文档存在: {md_files}")

    def instruction(self) -> str:
        return "实施阶段：产出 impl/<主题>.md（和 plan/验收/qa 同主题，实施方案）"


class 生成代码设计Stage(StageStrategy):
    """生成代码设计阶段：产出 spec/architecture_code_design.md（第一次写）。
    
    impl 完成后，第一次写代码架构设计文档。
    product.md 里的路由链接这时才指向有效文件。"""

    def name(self) -> str:
        return "生成代码设计"

    def artifact_paths(self) -> list[str]:
        # architecture_code_design.md 是第一次生成
        return ["spec/architecture_code_design.md"]

    def role_doc_path(self) -> str | None:
        return None

    def prompt_doc_path(self) -> str | None:
        return "Template_Repository/code_design/generate_code_design.md"

    def standard_doc_path(self) -> str | None:
        return "Standardized_Repository/code_design/generate_code_design.md"

    def instruction(self) -> str:
        return "生成代码设计阶段：产出 spec/architecture_code_design.md（第一次写代码架构设计文档）"


# ════════════════════════════════════════════════════════
# 场景 B/C/D 的 7 个 stage（stub，留口子）
# 这些 stage 的 stages() 列表在对应 scenario 里返回 []，后面实现时填上
# ════════════════════════════════════════════════════════

class 代码设计Stage(StageStrategy):
    """代码设计阶段（场景 B 专用）：看代码+跑项目，反推 architecture_code_design.md。
    TODO: 后面实现具体的看代码/跑项目逻辑。"""

    def name(self) -> str:
        return "代码设计"

    def artifact_paths(self) -> list[str]:
        return ["spec/architecture_code_design.md"]

    def role_doc_path(self) -> str | None:
        return None

    def prompt_doc_path(self) -> str | None:
        return "Template_Repository/code_design/code_design.md"

    def standard_doc_path(self) -> str | None:
        return "Standardized_Repository/code_design/code_design.md"

    def instruction(self) -> str:
        return "代码设计阶段：看代码 + 能跑就跑，产出 spec/architecture_code_design.md（从代码反推架构）"


class 更新代码设计Stage(StageStrategy):
    """更新代码设计阶段（场景 B/C/D）：impl 后更新 architecture_code_design.md。
    TODO: 后面实现具体的更新逻辑。"""

    def name(self) -> str:
        return "更新代码设计"

    def artifact_paths(self) -> list[str]:
        return ["spec/architecture_code_design.md"]

    def role_doc_path(self) -> str | None:
        return None

    def prompt_doc_path(self) -> str | None:
        return "Template_Repository/code_design/update_code_design.md"

    def standard_doc_path(self) -> str | None:
        return "Standardized_Repository/code_design/update_code_design.md"

    def instruction(self) -> str:
        return "更新代码设计阶段：更新 spec/architecture_code_design.md（把实施过程中的新理解写回去）"


class ReproduceStage(StageStrategy):
    """复现阶段（场景 C 专用）：复现 bug + 根因分析。
    TODO: 后面实现。"""

    def name(self) -> str:
        return "reproduce"

    def artifact_paths(self) -> list[str]:
        return ["bug/"]

    def role_doc_path(self) -> str | None:
        return None

    def prompt_doc_path(self) -> str | None:
        return "Template_Repository/reproduce/reproduce.md"

    def standard_doc_path(self) -> str | None:
        return "Standardized_Repository/reproduce/reproduce.md"

    def code_validate(self, project_root: str) -> tuple[bool, str]:
        """重写：reproduce stage 检查 bug/ 目录下有 .md 文件。"""
        dir_path = os.path.join(project_root, "bug")
        if not os.path.exists(dir_path):
            return (False, "bug/ 目录不存在")
        md_files = [f for f in os.listdir(dir_path) if f.endswith(".md") and f != "index.md"]
        if not md_files:
            return (False, "bug/ 下没有 bug 记录 .md 文件")
        return (True, f"bug 记录存在: {md_files}")

    def instruction(self) -> str:
        return "复现阶段：和用户讨论 bug 现象、复现步骤，产出 bug/<YYYY-MM-DD_HHmm-<bug描述>>.md + 更新 bug/index.md"


class FixPlanStage(StageStrategy):
    """修复计划阶段（场景 C 专用）：定主题（从 bug 反推）。
    TODO: 后面实现。"""

    def name(self) -> str:
        return "fix_plan"

    def artifact_paths(self) -> list[str]:
        return ["plan/index.md"]

    def role_doc_path(self) -> str | None:
        return None

    def prompt_doc_path(self) -> str | None:
        return "Template_Repository/plan/fix_plan.md"

    def standard_doc_path(self) -> str | None:
        return "Standardized_Repository/plan/fix_plan.md"

    def instruction(self) -> str:
        return "修复计划阶段：和用户讨论修复方案，产出 plan/<主题>.md + 更新 plan/index.md（主题从 bug 反推）"


class RequirementStage(StageStrategy):
    """需求分析阶段（场景 D 专用）：对需求。
    TODO: 后面实现。"""

    def name(self) -> str:
        return "requirement"

    def artifact_paths(self) -> list[str]:
        return ["spec/"]

    def role_doc_path(self) -> str | None:
        return None

    def prompt_doc_path(self) -> str | None:
        return "Template_Repository/spec/requirement.md"

    def standard_doc_path(self) -> str | None:
        return "Standardized_Repository/spec/requirement.md"

    def code_validate(self, project_root: str) -> tuple[bool, str]:
        """重写：requirement stage 检查 spec/ 下有 requirement_ 开头的 .md 文件。"""
        spec_dir = os.path.join(project_root, "spec")
        if not os.path.exists(spec_dir):
            return (False, "spec/ 目录不存在")
        req_files = [f for f in os.listdir(spec_dir) if f.startswith("requirement_") and f.endswith(".md")]
        if not req_files:
            return (False, "spec/ 下没有 requirement_*.md 文件")
        return (True, f"需求文档存在: {req_files}")

    def instruction(self) -> str:
        return "需求分析阶段：和用户讨论新需求/变更，产出 spec/requirement_<临时名>.md"


class ProductUpdateStage(StageStrategy):
    """产品更新阶段（场景 D 专用）：更新 product.md。
    TODO: 后面实现。"""

    def name(self) -> str:
        return "product_update"

    def artifact_paths(self) -> list[str]:
        # 更新已存在的 product.md
        return ["spec/product.md"]

    def role_doc_path(self) -> str | None:
        return None

    def prompt_doc_path(self) -> str | None:
        return "Template_Repository/spec/product_update.md"

    def standard_doc_path(self) -> str | None:
        return "Standardized_Repository/spec/product_update.md"

    def instruction(self) -> str:
        return "产品更新阶段：和用户讨论怎么改 product.md，更新 spec/product.md（不是新建，是修改）"


class FeatureSplitStage(StageStrategy):
    """功能拆分阶段（场景 D 专用）：产出新功能文档。
    TODO: 后面实现。"""

    def name(self) -> str:
        return "feature_split"

    def artifact_paths(self) -> list[str]:
        # 产出多个功能文档，具体文件名由讨论决定
        return ["spec/"]

    def role_doc_path(self) -> str | None:
        return None

    def prompt_doc_path(self) -> str | None:
        return "Template_Repository/spec/feature_split.md"

    def standard_doc_path(self) -> str | None:
        return "Standardized_Repository/spec/feature_split.md"

    def code_validate(self, project_root: str) -> tuple[bool, str]:
        """重写：feature_split stage 检查 spec/ 下有新的功能 .md 文件。"""
        spec_dir = os.path.join(project_root, "spec")
        if not os.path.exists(spec_dir):
            return (False, "spec/ 目录不存在")
        # 检查 spec/ 下有"功能"开头的 .md 文件
        func_files = [f for f in os.listdir(spec_dir) if f.startswith("功能") and f.endswith(".md")]
        if not func_files:
            return (False, "spec/ 下没有 功能*.md 文件")
        return (True, f"功能文档存在: {func_files}")

    def instruction(self) -> str:
        return "功能拆分阶段：和用户讨论功能怎么拆，产出 spec/功能<新>.md（可能多个）"
