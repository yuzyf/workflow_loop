import glob
import os

from .base import StageStrategy, clean_spike_tmp


# 产品设计 stage：工作流第一个环节，产出 spec/product.md + spec/feature_*.md
# 把用户需求拆成产品说明书 + 功能路由，后续 stage 都基于这里定的功能
class SpecStage(StageStrategy):
    # stage 标识名，存到 state.json 的 stage_path
    def name(self) -> str:
        return "spec"

    # 期望产出的文件路径列表（相对项目根）
    # code_validate 检查这些文件存在
    def artifact_paths(self) -> list[str]:
        return ["spec/product.md"]

    # 角色文档路径（相对 .workflow_loop/），spec 无角色文档返回 None
    def role_doc_path(self) -> str | None:
        return None

    # 提示词文档路径，discuss 命令加载这个文档内容打印给 AI 用
    def prompt_doc_path(self) -> str | None:
        return "Template_Repository/spec/spec.md"

    # 规范词文档路径，discuss 命令加载这个文档内容打印给 AI 用
    def standard_doc_path(self) -> str | None:
        return "Standardized_Repository/spec/spec.md"

    # 门禁的代码侧校验（第 2 道闸）
    # 检查 spec/product.md 存在 + spec/ 下至少有一个 feature_*.md
    def code_validate(self, project_root: str) -> tuple[bool, str]:
        # 拼出 spec/product.md 的完整路径
        product_md = os.path.join(project_root, "spec", "product.md")
        # product.md 不存在 → 直接判失败
        if not os.path.exists(product_md):
            return (False, "spec/product.md 不存在")
        # 用 glob 找 spec/ 下所有 feature_*.md 文件
        func_files = glob.glob(os.path.join(project_root, "spec", "feature_*.md"))
        # 没有任何 feature_*.md → 判失败
        if not func_files:
            return (False, "spec/ 下没有 feature_*.md 文件")
        # 全部就绪 → 通过，列出找到的功能文件名
        return (True, f"产品设计文档存在: product.md + {[os.path.basename(f) for f in func_files]}")

    # 该 stage 的指令文本，打印给 AI 看
    def instruction(self) -> str:
        return "产品设计阶段：产出 spec/product.md（产品设计说明书 + 功能路由）+ spec/feature_*.md（功能拆分）"


# 初步架构 stage：从零做的初步架构设计
# 产出 spec/architecture_code_design.md，后续 spike/plan 基于这个架构
class CodeDesignStage(StageStrategy):
    # stage 标识名，存到 state.json 的 stage_path
    def name(self) -> str:
        return "code_design"

    # 期望产出的文件路径列表（相对项目根）
    # code_validate 检查这些文件存在
    def artifact_paths(self) -> list[str]:
        return ["spec/architecture_code_design.md"]

    # 角色文档路径（相对 .workflow_loop/），code_design 无角色文档返回 None
    def role_doc_path(self) -> str | None:
        return None

    # 提示词文档路径，discuss 命令加载这个文档内容打印给 AI 用
    def prompt_doc_path(self) -> str | None:
        return "Template_Repository/code_design/code_design.md"

    # 规范词文档路径，discuss 命令加载这个文档内容打印给 AI 用
    def standard_doc_path(self) -> str | None:
        return "Standardized_Repository/code_design/code_design.md"

    # 该 stage 的指令文本，打印给 AI 看
    def instruction(self) -> str:
        return "初步架构阶段：产出 spec/architecture_code_design.md（从零做的初步架构设计）"


# 穿刺 stage：识别风险、写 throwaway 代码到 .workflow_loop/spike_tmp/
# 写结论文档 spec/spike_<临时名>.md，推进时自动清理 throwaway 代码
class SpikeStage(StageStrategy):
    # stage 标识名，存到 state.json 的 stage_path
    def name(self) -> str:
        return "spike"

    # 期望产出的文件路径列表（相对项目根）
    # 这里只列 spec/ 目录，code_validate 会查 spike_*.md
    def artifact_paths(self) -> list[str]:
        return ["spec/"]

    # 角色文档路径（相对 .workflow_loop/），spike 无角色文档返回 None
    def role_doc_path(self) -> str | None:
        return None

    # 提示词文档路径，discuss 命令加载这个文档内容打印给 AI 用
    def prompt_doc_path(self) -> str | None:
        return "Template_Repository/spike/spike.md"

    # 规范词文档路径，discuss 命令加载这个文档内容打印给 AI 用
    def standard_doc_path(self) -> str | None:
        return "Standardized_Repository/spike/spike.md"

    # 门禁的代码侧校验（第 2 道闸）
    # 检查 spec/ 目录存在 + 至少有一个 spike_*.md 结论文档
    def code_validate(self, project_root: str) -> tuple[bool, str]:
        # 拼出 spec/ 目录的完整路径
        spec_dir = os.path.join(project_root, "spec")
        # spec/ 目录不存在 → 直接判失败
        if not os.path.exists(spec_dir):
            return (False, "spec/ 目录不存在")
        # 列出 spec/ 下所有 spike_*.md 结论文档
        spike_files = [f for f in os.listdir(spec_dir) if f.startswith("spike_") and f.endswith(".md")]
        # 没有任何 spike_*.md → 判失败
        if not spike_files:
            return (False, "spec/ 下没有 spike_*.md 结论文档")
        # 找到结论文档 → 通过，列出文件名
        return (True, f"穿刺结论文档存在: {spike_files}")

    # stage 推进时的钩子（gate --confirmed 通过后、推进到下一 stage 前调用）
    # spike stage 重写：删除 .workflow_loop/spike_tmp/ 下所有 throwaway 代码
    def on_advance(self, project_root: str) -> None:
        clean_spike_tmp(project_root)

    # 该 stage 的指令文本，打印给 AI 看
    def instruction(self) -> str:
        return "穿刺阶段：问用户哪些功能要穿刺、识别风险、写 throwaway 代码到 .workflow_loop/spike_tmp/、写结论文档 spec/spike_<临时名>.md"


# 计划 stage：把穿刺结论转成可执行计划
# 产出 plan/<主题>.md + plan/index.md，主题在这里定下后面 stage 复用
class PlanStage(StageStrategy):
    # stage 标识名，存到 state.json 的 stage_path
    def name(self) -> str:
        return "plan"

    # 期望产出的文件路径列表（相对项目根）
    # code_validate 检查这些文件存在
    def artifact_paths(self) -> list[str]:
        return ["plan/index.md"]

    # 角色文档路径（相对 .workflow_loop/），plan 无角色文档返回 None
    def role_doc_path(self) -> str | None:
        return None

    # 提示词文档路径，discuss 命令加载这个文档内容打印给 AI 用
    def prompt_doc_path(self) -> str | None:
        return "Template_Repository/plan/plan.md"

    # 规范词文档路径，discuss 命令加载这个文档内容打印给 AI 用
    def standard_doc_path(self) -> str | None:
        return "Standardized_Repository/plan/plan.md"

    # 门禁的代码侧校验（第 2 道闸）
    # 检查 plan/index.md 存在 + plan/ 下至少有一个非 index.md 的计划文件
    def code_validate(self, project_root: str) -> tuple[bool, str]:
        # 拼出 plan/index.md 的完整路径
        index_md = os.path.join(project_root, "plan", "index.md")
        # index.md 不存在 → 直接判失败
        if not os.path.exists(index_md):
            return (False, "plan/index.md 不存在")
        # 列出 plan/ 下所有 .md 文件（排除 index.md）
        plan_files = [f for f in os.listdir(os.path.join(project_root, "plan")) if f.endswith(".md") and f != "index.md"]
        # 没有任何计划文件 → 判失败
        if not plan_files:
            return (False, "plan/ 下没有计划 .md 文件")
        # 找到计划文件 → 通过，列出文件名
        return (True, f"计划文档存在: {plan_files}")

    # 该 stage 的指令文本，打印给 AI 看
    def instruction(self) -> str:
        return "计划阶段：产出 plan/<主题>.md + plan/index.md（主题在这里定下，后面 stage 复用）"


# 验收计划 stage：制定什么算完成的验收计划
# 产出 acceptance/<topic>_plan.md，后续 acceptance stage 按这个执行验收
class AcceptancePlanStage(StageStrategy):
    # stage 标识名，存到 state.json 的 stage_path
    def name(self) -> str:
        return "acceptance_plan"

    # 期望产出的文件路径列表（相对项目根）
    # 这里只列 acceptance/ 目录，code_validate 会查 *_plan.md
    def artifact_paths(self) -> list[str]:
        return ["acceptance/"]

    # 角色文档路径（相对 .workflow_loop/），acceptance_plan 无角色文档返回 None
    def role_doc_path(self) -> str | None:
        return None

    # 提示词文档路径，discuss 命令加载这个文档内容打印给 AI 用
    def prompt_doc_path(self) -> str | None:
        return "Template_Repository/qa/acceptance_plan.md"

    # 规范词文档路径，discuss 命令加载这个文档内容打印给 AI 用
    def standard_doc_path(self) -> str | None:
        return "Standardized_Repository/qa/acceptance_plan.md"

    # 门禁的代码侧校验（第 2 道闸）
    # 检查 acceptance/ 目录存在 + 至少有一个 *_plan.md 文件
    def code_validate(self, project_root: str) -> tuple[bool, str]:
        # 拼出 acceptance/ 目录的完整路径
        acc_dir = os.path.join(project_root, "acceptance")
        # acceptance/ 目录不存在 → 直接判失败
        if not os.path.exists(acc_dir):
            return (False, "acceptance/ 目录不存在")
        # 列出 acceptance/ 下所有 *_plan.md 文件
        plan_files = [f for f in os.listdir(acc_dir) if f.endswith("_plan.md")]
        # 没有任何 *_plan.md → 判失败
        if not plan_files:
            return (False, "acceptance/ 下没有 *_plan.md 文件")
        # 找到验收计划文件 → 通过，列出文件名
        return (True, f"验收计划文档存在: {plan_files}")

    # 该 stage 的指令文本，打印给 AI 看
    def instruction(self) -> str:
        return "验收计划阶段：制定什么算完成的验收计划，产出 acceptance/<topic>_plan.md"


# 测试计划 stage：把验收条件转换为可执行测试范围
# 产出 qa/<topic>_plan.md + 更新 qa/index.md，后续 test stage 按这个执行
class TestPlanStage(StageStrategy):
    # stage 标识名，存到 state.json 的 stage_path
    def name(self) -> str:
        return "test_plan"

    # 期望产出的文件路径列表（相对项目根）
    # code_validate 检查这些文件存在
    def artifact_paths(self) -> list[str]:
        return ["qa/index.md"]

    # 角色文档路径（相对 .workflow_loop/），test_plan 无角色文档返回 None
    def role_doc_path(self) -> str | None:
        return None

    # 提示词文档路径，discuss 命令加载这个文档内容打印给 AI 用
    def prompt_doc_path(self) -> str | None:
        return "Template_Repository/qa/test_plan.md"

    # 规范词文档路径，discuss 命令加载这个文档内容打印给 AI 用
    def standard_doc_path(self) -> str | None:
        return "Standardized_Repository/qa/test_plan.md"

    # 门禁的代码侧校验（第 2 道闸）
    # 检查 qa/ 目录存在 + 至少有一个 *_plan.md 文件
    def code_validate(self, project_root: str) -> tuple[bool, str]:
        # 拼出 qa/ 目录的完整路径
        qa_dir = os.path.join(project_root, "qa")
        # qa/ 目录不存在 → 直接判失败
        if not os.path.exists(qa_dir):
            return (False, "qa/ 目录不存在")
        # 列出 qa/ 下所有 *_plan.md 文件
        plan_files = [f for f in os.listdir(qa_dir) if f.endswith("_plan.md")]
        # 没有任何 *_plan.md → 判失败
        if not plan_files:
            return (False, "qa/ 下没有 *_plan.md 文件")
        # 找到测试计划文件 → 通过，列出文件名
        return (True, f"测试计划文档存在: {plan_files}")

    # 该 stage 的指令文本，打印给 AI 看
    def instruction(self) -> str:
        return "测试计划阶段：把验收条件转换为可执行测试范围，产出 qa/<topic>_plan.md + 更新 qa/index.md"


# 实施 stage：执行已确认的实施/修复计划并修改真实代码
# 产出 impl/<topic>.md 实施记录，后续 test stage 验证实施结果
class ImplStage(StageStrategy):
    # stage 标识名，存到 state.json 的 stage_path
    def name(self) -> str:
        return "impl"

    # 期望产出的文件路径列表（相对项目根）
    # 这里只列 impl/ 目录，code_validate 会查 .md 文件
    def artifact_paths(self) -> list[str]:
        return ["impl/"]

    # 角色文档路径（相对 .workflow_loop/），impl 无角色文档返回 None
    def role_doc_path(self) -> str | None:
        return None

    # 提示词文档路径，discuss 命令加载这个文档内容打印给 AI 用
    def prompt_doc_path(self) -> str | None:
        return "Template_Repository/impl/impl.md"

    # 规范词文档路径，discuss 命令加载这个文档内容打印给 AI 用
    def standard_doc_path(self) -> str | None:
        return "Standardized_Repository/impl/impl.md"

    # 门禁的代码侧校验（第 2 道闸）
    # 检查 impl/ 目录存在 + 至少有一个 .md 实施记录文件
    def code_validate(self, project_root: str) -> tuple[bool, str]:
        # 拼出 impl/ 目录的完整路径
        impl_dir = os.path.join(project_root, "impl")
        # impl/ 目录不存在 → 直接判失败
        if not os.path.exists(impl_dir):
            return (False, "impl/ 目录不存在")
        # 列出 impl/ 下所有 .md 文件
        md_files = [f for f in os.listdir(impl_dir) if f.endswith(".md")]
        # 没有任何 .md → 判失败
        if not md_files:
            return (False, "impl/ 下没有 .md 文件")
        # 找到实施记录文件 → 通过，列出文件名
        return (True, f"实施记录文档存在: {md_files}")

    # 该 stage 的指令文本，打印给 AI 看
    def instruction(self) -> str:
        return "实施阶段：执行已确认的实施/修复计划并修改真实代码，产出 impl/<topic>.md 实施记录"


# 测试执行 stage：按 qa/<topic>_plan.md 执行全部必要测试并记录证据
# 产出 qa/<topic>_result.md，后续 acceptance stage 做最终验收
class TestStage(StageStrategy):
    # stage 标识名，存到 state.json 的 stage_path
    def name(self) -> str:
        return "test"

    # 期望产出的文件路径列表（相对项目根）
    # 这里只列 qa/ 目录，code_validate 会查 *_result.md
    def artifact_paths(self) -> list[str]:
        return ["qa/"]

    # 角色文档路径（相对 .workflow_loop/），test 无角色文档返回 None
    def role_doc_path(self) -> str | None:
        return None

    # 提示词文档路径，discuss 命令加载这个文档内容打印给 AI 用
    def prompt_doc_path(self) -> str | None:
        return "Template_Repository/qa/test.md"

    # 规范词文档路径，discuss 命令加载这个文档内容打印给 AI 用
    def standard_doc_path(self) -> str | None:
        return "Standardized_Repository/qa/test.md"

    # 门禁的代码侧校验（第 2 道闸）
    # 检查 qa/ 目录存在 + 至少有一个 *_result.md 测试结果文件
    def code_validate(self, project_root: str) -> tuple[bool, str]:
        # 拼出 qa/ 目录的完整路径
        qa_dir = os.path.join(project_root, "qa")
        # qa/ 目录不存在 → 直接判失败
        if not os.path.exists(qa_dir):
            return (False, "qa/ 目录不存在")
        # 列出 qa/ 下所有 *_result.md 文件
        result_files = [f for f in os.listdir(qa_dir) if f.endswith("_result.md")]
        # 没有任何 *_result.md → 判失败
        if not result_files:
            return (False, "qa/ 下没有 *_result.md 文件")
        # 找到测试结果文件 → 通过，列出文件名
        return (True, f"测试结果文档存在: {result_files}")

    # 该 stage 的指令文本，打印给 AI 看
    def instruction(self) -> str:
        return "测试执行阶段：按照 qa/<topic>_plan.md 执行全部必要测试并记录证据，产出 qa/<topic>_result.md"


# 最终验收 stage：测试通过后按 acceptance/<topic>_plan.md 执行最终验收
# 产出 acceptance/<topic>_result.md，验收通过后整个工作流闭环
class AcceptanceStage(StageStrategy):
    # stage 标识名，存到 state.json 的 stage_path
    def name(self) -> str:
        return "acceptance"

    # 期望产出的文件路径列表（相对项目根）
    # 这里只列 acceptance/ 目录，code_validate 会查 *_result.md
    def artifact_paths(self) -> list[str]:
        return ["acceptance/"]

    # 角色文档路径（相对 .workflow_loop/），acceptance 无角色文档返回 None
    def role_doc_path(self) -> str | None:
        return None

    # 提示词文档路径，discuss 命令加载这个文档内容打印给 AI 用
    def prompt_doc_path(self) -> str | None:
        return "Template_Repository/qa/acceptance.md"

    # 规范词文档路径，discuss 命令加载这个文档内容打印给 AI 用
    def standard_doc_path(self) -> str | None:
        return "Standardized_Repository/qa/acceptance.md"

    # 门禁的代码侧校验（第 2 道闸）
    # 检查 acceptance/ 目录存在 + 至少有一个 *_result.md 验收结果文件
    def code_validate(self, project_root: str) -> tuple[bool, str]:
        # 拼出 acceptance/ 目录的完整路径
        acc_dir = os.path.join(project_root, "acceptance")
        # acceptance/ 目录不存在 → 直接判失败
        if not os.path.exists(acc_dir):
            return (False, "acceptance/ 目录不存在")
        # 列出 acceptance/ 下所有 *_result.md 文件
        result_files = [f for f in os.listdir(acc_dir) if f.endswith("_result.md")]
        # 没有任何 *_result.md → 判失败
        if not result_files:
            return (False, "acceptance/ 下没有 *_result.md 文件")
        # 找到验收结果文件 → 通过，列出文件名
        return (True, f"验收结果文档存在: {result_files}")

    # 该 stage 的指令文本，打印给 AI 看
    def instruction(self) -> str:
        return "最终验收阶段：在测试通过后，按照 acceptance/<topic>_plan.md 执行最终验收，产出 acceptance/<topic>_result.md"


# 详细架构收尾 stage：写入/更新 spec/architecture_code_design.md
# 反映最终被验证和接受的真实结构，让架构文档和实际代码对齐
class UpdateCodeDesignStage(StageStrategy):
    # stage 标识名，存到 state.json 的 stage_path
    def name(self) -> str:
        return "update_code_design"

    # 期望产出的文件路径列表（相对项目根）
    # code_validate 检查这些文件存在
    def artifact_paths(self) -> list[str]:
        return ["spec/architecture_code_design.md"]

    # 角色文档路径（相对 .workflow_loop/），update_code_design 无角色文档返回 None
    def role_doc_path(self) -> str | None:
        return None

    # 提示词文档路径，discuss 命令加载这个文档内容打印给 AI 用
    def prompt_doc_path(self) -> str | None:
        return "Template_Repository/code_design/update_code_design.md"

    # 规范词文档路径，discuss 命令加载这个文档内容打印给 AI 用
    def standard_doc_path(self) -> str | None:
        return "Standardized_Repository/code_design/update_code_design.md"

    # 该 stage 的指令文本，打印给 AI 看
    def instruction(self) -> str:
        return "详细架构收尾：写入/更新 spec/architecture_code_design.md，反映最终被验证和接受的真实结构"


# 项目设计架构初始化 stage：根据现有代码及可运行行为一次建立设计文档
# 一次性产出 spec/product.md + spec/feature_*.md + spec/architecture_code_design.md
# 用于已有代码项目接入 workflow_loop 时的初始化
class ProjectDesignInitStage(StageStrategy):
    # stage 标识名，存到 state.json 的 stage_path
    def name(self) -> str:
        return "project_design_init"

    # 期望产出的文件路径列表（相对项目根）
    # code_validate 检查这些文件存在
    def artifact_paths(self) -> list[str]:
        return ["spec/product.md", "spec/architecture_code_design.md"]

    # 角色文档路径（相对 .workflow_loop/），project_design_init 无角色文档返回 None
    def role_doc_path(self) -> str | None:
        return None

    # 提示词文档路径，discuss 命令加载这个文档内容打印给 AI 用
    def prompt_doc_path(self) -> str | None:
        return "Template_Repository/code_design/project_design_init.md"

    # 规范词文档路径，discuss 命令加载这个文档内容打印给 AI 用
    def standard_doc_path(self) -> str | None:
        return "Standardized_Repository/code_design/project_design_init.md"

    # 附加提示词/规范路径列表（discuss 命令额外加载）
    # project_design_init 重写：加载 spec + code_design 两组文档
    def additional_doc_paths(self) -> list[tuple[str, str]]:
        return [
            # spec 阶段的提示词 + 规范词，让 AI 知道怎么写产品文档
            ("Template_Repository/spec/spec.md", "Standardized_Repository/spec/spec.md"),
            # code_design 阶段的提示词 + 规范词，让 AI 知道怎么写架构文档
            ("Template_Repository/code_design/code_design.md", "Standardized_Repository/code_design/code_design.md"),
        ]

    # 门禁的代码侧校验（第 2 道闸）
    # 检查 product.md + architecture_code_design.md + feature_*.md 三类产物都就绪
    def code_validate(self, project_root: str) -> tuple[bool, str]:
        # 拼出 spec/product.md 的完整路径
        product_md = os.path.join(project_root, "spec", "product.md")
        # 拼出 spec/architecture_code_design.md 的完整路径
        arch_md = os.path.join(project_root, "spec", "architecture_code_design.md")
        # 收集不存在的文件
        missing = []
        # product.md 不存在 → 加入 missing
        if not os.path.exists(product_md):
            missing.append("spec/product.md")
        # architecture_code_design.md 不存在 → 加入 missing
        if not os.path.exists(arch_md):
            missing.append("spec/architecture_code_design.md")
        # 用 glob 找 spec/ 下所有 feature_*.md 文件
        func_files = glob.glob(os.path.join(project_root, "spec", "feature_*.md"))
        # 没有任何 feature_*.md → 加入 missing
        if not func_files:
            missing.append("spec/feature_*.md")
        # 有缺失 → 判失败，列出缺失项
        if missing:
            return (False, f"产物未就绪: {missing}")
        # 全部就绪 → 通过，列出找到的功能文件名
        return (True, f"项目设计初始化产物就绪: product.md + architecture_code_design.md + {[os.path.basename(f) for f in func_files]}")

    # 该 stage 的指令文本，打印给 AI 看
    def instruction(self) -> str:
        return "项目设计架构初始化：根据现有代码及可运行行为一次建立 spec/product.md + spec/feature_*.md + spec/architecture_code_design.md"


# 设计期架构修订 stage：按变更后的产品设计改 spec/architecture_code_design.md
# 产品设计变更后同步修订架构，保持设计和实际代码一致
class ReviseCodeDesignStage(StageStrategy):
    # stage 标识名，存到 state.json 的 stage_path
    def name(self) -> str:
        return "revise_code_design"

    # 期望产出的文件路径列表（相对项目根）
    # code_validate 检查这些文件存在
    def artifact_paths(self) -> list[str]:
        return ["spec/architecture_code_design.md"]

    # 角色文档路径（相对 .workflow_loop/），revise_code_design 无角色文档返回 None
    def role_doc_path(self) -> str | None:
        return None

    # 提示词文档路径，discuss 命令加载这个文档内容打印给 AI 用
    def prompt_doc_path(self) -> str | None:
        return "Template_Repository/code_design/revise_code_design.md"

    # 规范词文档路径，discuss 命令加载这个文档内容打印给 AI 用
    def standard_doc_path(self) -> str | None:
        return "Standardized_Repository/code_design/revise_code_design.md"

    # 该 stage 的指令文本，打印给 AI 看
    def instruction(self) -> str:
        return "设计期架构修订：按变更后的产品设计改 spec/architecture_code_design.md"


# 复现 stage：和用户讨论 bug 现象、复现步骤
# 产出 bug/<YYYY-MM-DD_HHmm-<bug描述>>.md + 更新 bug/index.md，后续 fix_plan 基于此
class ReproduceStage(StageStrategy):
    # stage 标识名，存到 state.json 的 stage_path
    def name(self) -> str:
        return "reproduce"

    # 期望产出的文件路径列表（相对项目根）
    # 这里只列 bug/ 目录，code_validate 会查 .md 文件
    def artifact_paths(self) -> list[str]:
        return ["bug/"]

    # 角色文档路径（相对 .workflow_loop/），reproduce 无角色文档返回 None
    def role_doc_path(self) -> str | None:
        return None

    # 提示词文档路径，discuss 命令加载这个文档内容打印给 AI 用
    def prompt_doc_path(self) -> str | None:
        return "Template_Repository/reproduce/reproduce.md"

    # 规范词文档路径，discuss 命令加载这个文档内容打印给 AI 用
    def standard_doc_path(self) -> str | None:
        return "Standardized_Repository/reproduce/reproduce.md"

    # 门禁的代码侧校验（第 2 道闸）
    # 检查 bug/ 目录存在 + 至少有一个非 index.md 的 bug 记录文件
    def code_validate(self, project_root: str) -> tuple[bool, str]:
        # 拼出 bug/ 目录的完整路径
        bug_dir = os.path.join(project_root, "bug")
        # bug/ 目录不存在 → 直接判失败
        if not os.path.exists(bug_dir):
            return (False, "bug/ 目录不存在")
        # 列出 bug/ 下所有 .md 文件（排除 index.md 索引文件）
        md_files = [f for f in os.listdir(bug_dir) if f.endswith(".md") and f != "index.md"]
        # 没有任何 bug 记录 → 判失败
        if not md_files:
            return (False, "bug/ 下没有 bug 记录 .md 文件（非 index.md）")
        # 找到 bug 记录文件 → 通过，列出文件名
        return (True, f"bug 记录存在: {md_files}")

    # 该 stage 的指令文本，打印给 AI 看
    def instruction(self) -> str:
        return "复现阶段：和用户讨论 bug 现象、复现步骤，产出 bug/<YYYY-MM-DD_HHmm-<bug描述>>.md + 更新 bug/index.md"


# 修复计划 stage：和用户讨论修复方案
# 产出 plan/<主题>.md + 更新 plan/index.md，主题从 bug 反推，后续 impl 执行
class FixPlanStage(StageStrategy):
    # stage 标识名，存到 state.json 的 stage_path
    def name(self) -> str:
        return "fix_plan"

    # 期望产出的文件路径列表（相对项目根）
    # code_validate 检查这些文件存在
    def artifact_paths(self) -> list[str]:
        return ["plan/index.md"]

    # 角色文档路径（相对 .workflow_loop/），fix_plan 无角色文档返回 None
    def role_doc_path(self) -> str | None:
        return None

    # 提示词文档路径，discuss 命令加载这个文档内容打印给 AI 用
    def prompt_doc_path(self) -> str | None:
        return "Template_Repository/plan/fix_plan.md"

    # 规范词文档路径，discuss 命令加载这个文档内容打印给 AI 用
    def standard_doc_path(self) -> str | None:
        return "Standardized_Repository/plan/fix_plan.md"

    # 门禁的代码侧校验（第 2 道闸）
    # 检查 plan/ 目录存在 + plan/index.md 存在 + 至少有一个非 index.md 的修复计划文件
    def code_validate(self, project_root: str) -> tuple[bool, str]:
        # 拼出 plan/ 目录的完整路径
        plan_dir = os.path.join(project_root, "plan")
        # plan/ 目录不存在 → 直接判失败
        if not os.path.exists(plan_dir):
            return (False, "plan/ 目录不存在")
        # 拼出 plan/index.md 的完整路径
        index_md = os.path.join(plan_dir, "index.md")
        # index.md 不存在 → 判失败
        if not os.path.exists(index_md):
            return (False, "plan/index.md 不存在")
        # 列出 plan/ 下所有 .md 文件（排除 index.md 索引文件）
        plan_files = [f for f in os.listdir(plan_dir) if f.endswith(".md") and f != "index.md"]
        # 没有任何修复计划文件 → 判失败
        if not plan_files:
            return (False, "plan/ 下没有修复计划 .md 文件")
        # 找到修复计划文件 → 通过，列出文件名
        return (True, f"修复计划文档存在: {plan_files}")

    # 该 stage 的指令文本，打印给 AI 看
    def instruction(self) -> str:
        return "修复计划阶段：和用户讨论修复方案，产出 plan/<主题>.md + 更新 plan/index.md（主题从 bug 反推）"
