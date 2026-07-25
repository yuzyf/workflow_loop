import glob
import os

from ..artifact_validation import (
    PROJECT_INIT_EVIDENCE_PATH,
    changed_stage_paths,
    validate_acceptance_plan_documents,
    validate_downstream_traceability,
    validate_final_regression_result,
    validate_overall_acceptance_prerequisites,
    validate_project_design_init_evidence,
    validate_reproduce_documents,
    validate_test_plan_documents,
    validate_topic_execution_results,
)
from ..spike_validation import validate_spike_stage
from ..state import load_state
from ..topic import (
    candidate_topics,
    current_workflow_topics,
    list_acceptance_plan_topics,
    missing_topic_files,
)
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
        changed_ok, changed_detail, changed_paths = changed_stage_paths(
            project_root,
            self.name(),
            self.change_tracked_paths(project_root),
        )
        if not changed_ok:
            return (False, changed_detail)

        state = load_state(project_root)
        if state is None:
            return (False, "找不到当前工作流状态")
        product_path = os.path.join("spec", "product.md")
        product_changed = product_path in changed_paths
        feature_changed = any(
            path.startswith(os.path.join("spec", "feature_"))
            for path in changed_paths
        )
        if state.intent == "from_scratch" and (not product_changed or not feature_changed):
            return (False, "从零创建产品时，product.md 和至少一份功能文档都必须在本阶段新建")
        if state.intent == "product_change" and (not product_changed or not feature_changed):
            return (
                False,
                "修改产品时，product.md 必须更新，并且至少一份功能文档必须新增、修改或删除",
            )
        return (
            True,
            f"产品设计文档存在并且属于本阶段修改: product.md + {[os.path.basename(f) for f in func_files]}",
        )

    def change_tracked_paths(self, project_root: str) -> list[str]:
        feature_paths = [
            os.path.relpath(path, project_root)
            for path in glob.glob(os.path.join(project_root, "spec", "feature_*.md"))
        ]
        return [os.path.join("spec", "product.md"), *feature_paths]

    # 该 stage 的指令文本，打印给 AI 看
    def instruction(self) -> str:
        return "产品设计阶段：产出 spec/product.md（产品设计说明书 + 功能路由）+ spec/feature_*.md（功能拆分）"


# 初步代码架构 stage：从已确认产品设计推导代码设计
# 产出 spec/architecture_code_design.md，后续 spike/plan 基于这个设计
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
        return "初步代码架构阶段：从已确认产品设计推导代码分层、关键节点和功能代码过程，产出 spec/architecture_code_design.md"


# 穿刺 stage：识别并验证真实场景中的技术不确定性
# 正常执行时写清单和结论文档；需要临时代码时放入 spike_tmp，推进时自动清理
class SpikeStage(StageStrategy):
    # stage 标识名，存到 state.json 的 stage_path
    def name(self) -> str:
        return "spike"

    # 期望产出的文件路径列表（相对项目根）
    # 清单是正常穿刺的固定入口；选择全部跳过时由 gate spike --skip 绕过
    def artifact_paths(self) -> list[str]:
        return ["spec/spike_index.md"]

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
    # 检查清单、每份结论文档、固定字段、阻塞状态和设计文档哈希
    def code_validate(self, project_root: str) -> tuple[bool, str]:
        return validate_spike_stage(project_root)

    # stage 推进时的钩子（gate --confirmed 通过后、推进到下一 stage 前调用）
    # spike stage 重写：删除 .workflow_loop/spike_tmp/ 下所有临时内容
    def on_advance(self, project_root: str) -> list[str]:
        return clean_spike_tmp(project_root)

    # 该 stage 的指令文本，打印给 AI 看
    def instruction(self) -> str:
        return (
            "穿刺阶段：先查产品设计、代码设计、相关代码和运行事实，识别真实场景中的技术不确定性；"
            "用户决定执行清单或全部跳过。正常执行时写 spec/spike_index.md 和每项结论文档，"
            "需要临时代码时放入 .workflow_loop/spike_tmp/，并在进入计划前同步受影响的设计文档。"
        )


# 计划 stage：根据已确认的验收主题和测试计划制定实施计划
# 产出 plan/ 下的实施计划文档 + plan/index.md；不在这里重新确定主题
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
        state = load_state(project_root)
        if state is None:
            return (False, "找不到当前工作流状态")
        topics = current_workflow_topics(project_root)
        if not topics:
            return (False, "当前工作流还没有确认验收主题，请先完成 acceptance_plan")
        trace_ok, trace_detail = validate_downstream_traceability(
            project_root,
            state.workflow_id,
            topics,
        )
        if not trace_ok:
            return (False, trace_detail)
        # 找到计划文件 → 通过，列出文件名
        return (True, f"计划文档存在: {plan_files}")

    # 该 stage 的指令文本，打印给 AI 看
    def instruction(self) -> str:
        return "实施计划阶段：根据已确认的验收主题和测试计划，产出实施计划文档 + plan/index.md；不在这里新增、删除或改名主题"


# 验收计划 stage：制定什么算完成的验收计划
# 产出 traceability.md + acceptance/<topic>_plan.md
class AcceptancePlanStage(StageStrategy):
    # stage 标识名，存到 state.json 的 stage_path
    def name(self) -> str:
        return "acceptance_plan"

    # 期望产出的文件路径列表（相对项目根）
    # traceability.md 是跨阶段追踪入口；acceptance/ 下保存每个主题的验收计划
    def artifact_paths(self) -> list[str]:
        return ["traceability.md", "acceptance/"]

    # 角色文档路径（相对 .workflow_loop/），acceptance_plan 无角色文档返回 None
    def role_doc_path(self) -> str | None:
        return None

    # 提示词文档路径，discuss 命令加载这个文档内容打印给 AI 用
    def prompt_doc_path(self) -> str | None:
        return "Template_Repository/acceptance/acceptance_plan.md"

    # 规范词文档路径，discuss 命令加载这个文档内容打印给 AI 用
    def standard_doc_path(self) -> str | None:
        return "Standardized_Repository/acceptance/acceptance_plan.md"

    # 门禁的代码侧校验（第 2 道闸）
    # 检查 acceptance/ 目录存在 + 本次至少新增一个未使用过的主题计划
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
        state = load_state(project_root)
        if state is None:
            return (False, "找不到当前工作流状态")

        if state.intent == "bugfix":
            topics = current_workflow_topics(project_root)
            if not topics:
                return (False, "修 bug 的验收主题必须先在缺陷复现阶段确定")
            plan_topics = list_acceptance_plan_topics(project_root)
            if sorted(plan_topics) != sorted(topics):
                return (
                    False,
                    f"修 bug 的验收计划主题必须与缺陷记录一致；缺陷主题 {topics}，计划主题 {plan_topics}",
                )
        else:
            # 当前 Run 已记录主题时复核这些主题；否则从历史中排除旧主题，找本次新增主题。
            topics = candidate_topics(project_root)
        if not topics:
            return (False, "没有找到本次新增的验收主题；主题名称不能复用项目历史中的名称")
        missing = missing_topic_files(project_root, "acceptance", "_plan.md", topics)
        if missing:
            return (False, f"缺少验收计划文档: {missing}")
        return validate_acceptance_plan_documents(
            project_root,
            state.workflow_id,
            topics,
        )

    # 该 stage 的指令文本，打印给 AI 看
    def instruction(self) -> str:
        return (
            "验收计划阶段：从零开发和修改产品先确定本次需求的全部验收主题；"
            "修 bug 复用缺陷复现阶段已经确认的主题。为每个主题写清什么算完成，"
            "产出 traceability.md + acceptance/<topic>_plan.md。"
        )


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
    # 检查 qa/ 目录存在 + 每个已确认主题都有同名测试计划
    def code_validate(self, project_root: str) -> tuple[bool, str]:
        # 拼出 qa/ 目录的完整路径
        qa_dir = os.path.join(project_root, "qa")
        # qa/ 目录不存在 → 直接判失败
        if not os.path.exists(qa_dir):
            return (False, "qa/ 目录不存在")
        index_md = os.path.join(qa_dir, "index.md")
        if not os.path.isfile(index_md):
            return (False, "qa/index.md 不存在")
        # 列出 qa/ 下所有 *_plan.md 文件
        plan_files = [f for f in os.listdir(qa_dir) if f.endswith("_plan.md")]
        # 没有任何 *_plan.md → 判失败
        if not plan_files:
            return (False, "qa/ 下没有 *_plan.md 文件")
        topics = current_workflow_topics(project_root)
        if not topics:
            return (False, "当前工作流还没有确认验收主题，请先完成 acceptance_plan")
        missing = missing_topic_files(project_root, "qa", "_plan.md", topics)
        if missing:
            return (False, f"缺少测试计划文档: {missing}")
        with open(index_md, "r", encoding="utf-8") as f:
            index_content = f.read()
        missing_index_links = [
            f"{topic}_plan.md"
            for topic in topics
            if f"{topic}_plan.md" not in index_content
        ]
        if missing_index_links:
            return (False, f"qa/index.md 缺少主题测试计划链接: {missing_index_links}")
        state = load_state(project_root)
        if state is None:
            return (False, "找不到当前工作流状态")
        trace_ok, trace_detail = validate_downstream_traceability(
            project_root,
            state.workflow_id,
            topics,
        )
        if not trace_ok:
            return (False, trace_detail)
        return validate_test_plan_documents(
            project_root,
            state.workflow_id,
            topics,
        )

    # 该 stage 的指令文本，打印给 AI 看
    def instruction(self) -> str:
        return "测试计划阶段：把验收条件转换为可执行测试范围，产出 qa/<topic>_plan.md + 更新 qa/index.md"


# 旧版独立实施 stage，保留用于读取历史状态；新顶层路径由 topic_execution 统筹。
# 实施记录按实施任务命名，不要求与验收主题一一对应。
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
        return "实施阶段：执行已确认的实施/修复计划并修改真实代码，按实施任务产出 impl/ 下的实施记录"


# 旧版独立测试 stage，保留用于读取历史状态；新顶层路径在 topic_execution 内执行主题测试。
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
        # 最终全量回归有独立文件，不得冒充主题测试结果。
        result_files = [
            f for f in os.listdir(qa_dir)
            if f.endswith("_result.md") and f != "final_regression_result.md"
        ]
        # 没有任何 *_result.md → 判失败
        if not result_files:
            return (False, "qa/ 下没有 *_result.md 文件")
        topics = current_workflow_topics(project_root)
        if topics:
            missing = missing_topic_files(project_root, "qa", "_result.md", topics)
            if missing:
                return (False, f"缺少主题测试结果: {missing}")
        return (True, f"主题测试结果存在: {result_files}")

    # 该 stage 的指令文本，打印给 AI 看
    def instruction(self) -> str:
        return "测试执行阶段：按照 qa/<topic>_plan.md 执行全部必要测试并记录证据，产出 qa/<topic>_result.md"


# 旧版独立验收 stage，保留用于读取历史状态；新顶层路径在 topic_execution 内执行主题验收。
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
        return "Template_Repository/acceptance/acceptance_result.md"

    # 规范词文档路径，discuss 命令加载这个文档内容打印给 AI 用
    def standard_doc_path(self) -> str | None:
        return "Standardized_Repository/acceptance/acceptance.md"

    # 门禁的代码侧校验（第 2 道闸）
    # 检查 acceptance/ 目录存在 + 至少有一个 *_result.md 验收结果文件
    def code_validate(self, project_root: str) -> tuple[bool, str]:
        # 拼出 acceptance/ 目录的完整路径
        acc_dir = os.path.join(project_root, "acceptance")
        # acceptance/ 目录不存在 → 直接判失败
        if not os.path.exists(acc_dir):
            return (False, "acceptance/ 目录不存在")
        result_files = [
            f for f in os.listdir(acc_dir)
            if f.endswith("_result.md")
        ]
        # 没有任何 *_result.md → 判失败
        if not result_files:
            return (False, "acceptance/ 下没有 *_result.md 文件")
        topics = current_workflow_topics(project_root)
        if topics:
            missing = missing_topic_files(project_root, "acceptance", "_result.md", topics)
            if missing:
                return (False, f"缺少主题验收结果: {missing}")
        return (True, f"主题验收结果存在: {result_files}")

    # 该 stage 的指令文本，打印给 AI 看
    def instruction(self) -> str:
        return "主题验收阶段：每个主题测试通过后，按照 acceptance/<topic>_plan.md 执行该主题验收，产出 acceptance/<topic>_result.md"


class TopicExecutionStage(StageStrategy):
    """统筹各主题分别实施、测试和验收；不强制所有主题走同一步。"""

    def name(self) -> str:
        return "topic_execution"

    def artifact_paths(self) -> list[str]:
        return ["impl/", "qa/", "acceptance/"]

    def role_doc_path(self) -> str | None:
        return None

    def prompt_doc_path(self) -> str | None:
        return None

    def standard_doc_path(self) -> str | None:
        return "Standardized_Repository/execution/topic_execution.md"

    def additional_doc_paths(self) -> list[tuple[str, str]]:
        return [
            (
                "Template_Repository/acceptance/acceptance_result.md",
                "Standardized_Repository/acceptance/acceptance.md",
            ),
        ]

    def code_validate(self, project_root: str) -> tuple[bool, str]:
        topics = current_workflow_topics(project_root)
        if not topics:
            return (False, "当前工作流还没有确认验收主题")

        impl_dir = os.path.join(project_root, "impl")
        if not os.path.isdir(impl_dir) or not any(
            filename.endswith(".md") for filename in os.listdir(impl_dir)
        ):
            return (False, "impl/ 下没有实施记录 .md 文件")

        missing_tests = missing_topic_files(project_root, "qa", "_result.md", topics)
        missing_acceptance = missing_topic_files(
            project_root,
            "acceptance",
            "_result.md",
            topics,
        )
        if missing_tests or missing_acceptance:
            return (
                False,
                f"主题执行结果不完整: 测试缺失={missing_tests}, 验收缺失={missing_acceptance}",
            )
        state = load_state(project_root)
        if state is None:
            return (False, "找不到当前工作流状态")
        trace_ok, trace_detail = validate_downstream_traceability(
            project_root,
            state.workflow_id,
            topics,
        )
        if not trace_ok:
            return (False, trace_detail)
        result_ok, result_detail = validate_topic_execution_results(
            project_root,
            state.workflow_id,
            topics,
        )
        if not result_ok:
            return (False, result_detail)
        return (True, f"全部主题已经分别完成实施、测试和验收: {topics}")

    def instruction(self) -> str:
        return (
            "按主题执行阶段：按照实施计划推进各主题的实施、测试和验收；"
            "独立主题可以分别推进，全部主题完成后才能通过本阶段"
        )


class RegressionTestStage(StageStrategy):
    """全部主题完成后，对合并后的完整代码执行最终全量回归。"""

    def name(self) -> str:
        return "regression_test"

    def artifact_paths(self) -> list[str]:
        return ["qa/final_regression_result.md"]

    def role_doc_path(self) -> str | None:
        return None

    def prompt_doc_path(self) -> str | None:
        return "Template_Repository/qa/final_regression.md"

    def standard_doc_path(self) -> str | None:
        return None

    def code_validate(self, project_root: str) -> tuple[bool, str]:
        state = load_state(project_root)
        if state is None:
            return (False, "找不到当前工作流状态")
        topics = current_workflow_topics(project_root)
        trace_ok, trace_detail = validate_downstream_traceability(
            project_root,
            state.workflow_id,
            topics,
        )
        if not trace_ok:
            return (False, trace_detail)
        return validate_final_regression_result(project_root, state.workflow_id)

    def instruction(self) -> str:
        return (
            "最终全量回归阶段：全部主题完成后，对全部已合并代码运行全量回归；"
            "产出 qa/final_regression_result.md，并明确写当前工作流编号和“回归状态：通过”。"
            "未通过时门禁拒绝进入整体验收。"
        )


class OverallAcceptanceStage(StageStrategy):
    """最终全量回归通过后，由用户确认整个需求的结果。"""

    def name(self) -> str:
        return "overall_acceptance"

    def artifact_paths(self) -> list[str]:
        return []

    def role_doc_path(self) -> str | None:
        return None

    def prompt_doc_path(self) -> str | None:
        return None

    def standard_doc_path(self) -> str | None:
        return None

    def code_validate(self, project_root: str) -> tuple[bool, str]:
        state = load_state(project_root)
        if state is None:
            return (False, "找不到当前工作流状态")
        topics = current_workflow_topics(project_root)
        trace_ok, trace_detail = validate_downstream_traceability(
            project_root,
            state.workflow_id,
            topics,
        )
        if not trace_ok:
            return (False, trace_detail)
        return validate_overall_acceptance_prerequisites(
            project_root,
            state.workflow_id,
            topics,
        )

    def instruction(self) -> str:
        return (
            "整体验收阶段：代码复核全部主题验收和最终全量回归已经通过，"
            "再由用户确认整个需求是否完成；本阶段不生成新的结果文档。"
        )


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
        return "Template_Repository/code_design/code_design.md"

    # 规范词文档路径，discuss 命令加载这个文档内容打印给 AI 用
    def standard_doc_path(self) -> str | None:
        return "Standardized_Repository/code_design/update_code_design.md"

    def code_validate(self, project_root: str) -> tuple[bool, str]:
        architecture_path = os.path.join(project_root, "spec", "architecture_code_design.md")
        if not os.path.isfile(architecture_path):
            return (False, "spec/architecture_code_design.md 不存在")
        changed_ok, changed_detail, _ = changed_stage_paths(
            project_root,
            self.name(),
            self.change_tracked_paths(project_root),
        )
        if not changed_ok:
            return (False, changed_detail)
        state = load_state(project_root)
        if state is None:
            return (False, "找不到当前工作流状态")
        topics = current_workflow_topics(project_root)
        trace_ok, trace_detail = validate_downstream_traceability(
            project_root,
            state.workflow_id,
            topics,
        )
        if not trace_ok:
            return (False, trace_detail)
        return (True, "最终代码设计文档已在本阶段更新，追踪表已准备好记录最终代码设计")

    def change_tracked_paths(self, project_root: str) -> list[str]:
        return [os.path.join("spec", "architecture_code_design.md")]

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
        return [
            "spec/product.md",
            "spec/architecture_code_design.md",
            PROJECT_INIT_EVIDENCE_PATH,
        ]

    # 角色文档路径（相对 .workflow_loop/），project_design_init 无角色文档返回 None
    def role_doc_path(self) -> str | None:
        return None

    # 提示词文档路径，discuss 命令加载这个文档内容打印给 AI 用
    def prompt_doc_path(self) -> str | None:
        return "Template_Repository/code_design/project_design_init_evidence.md"

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
        if not os.path.exists(os.path.join(project_root, PROJECT_INIT_EVIDENCE_PATH)):
            missing.append(PROJECT_INIT_EVIDENCE_PATH)
        # 有缺失 → 判失败，列出缺失项
        if missing:
            return (False, f"产物未就绪: {missing}")

        changed_ok, changed_detail, changed_paths = changed_stage_paths(
            project_root,
            self.name(),
            self.change_tracked_paths(project_root),
        )
        if not changed_ok:
            return (False, changed_detail)

        product_changed = any(
            path == os.path.join("spec", "product.md")
            or path.startswith(os.path.join("spec", "feature_"))
            for path in changed_paths
        )
        architecture_changed = os.path.join("spec", "architecture_code_design.md") in changed_paths
        evidence_changed = PROJECT_INIT_EVIDENCE_PATH in changed_paths
        if not product_changed or not architecture_changed or not evidence_changed:
            return (
                False,
                "项目设计初始化必须在本阶段更新产品设计、代码设计和调查证据三类内容；"
                f"当前变化文件: {changed_paths}",
            )

        state = load_state(project_root)
        if state is None:
            return (False, "找不到当前工作流状态")
        evidence_ok, evidence_detail = validate_project_design_init_evidence(
            project_root,
            state.workflow_id,
        )
        if not evidence_ok:
            return (False, evidence_detail)
        return (
            True,
            "项目设计初始化产物和调查证据有效: "
            f"product.md + architecture_code_design.md + {[os.path.basename(f) for f in func_files]}; "
            f"{evidence_detail}",
        )

    def change_tracked_paths(self, project_root: str) -> list[str]:
        feature_paths = [
            os.path.relpath(path, project_root)
            for path in glob.glob(os.path.join(project_root, "spec", "feature_*.md"))
        ]
        return [
            os.path.join("spec", "product.md"),
            os.path.join("spec", "architecture_code_design.md"),
            PROJECT_INIT_EVIDENCE_PATH,
            *feature_paths,
        ]

    # 该 stage 的指令文本，打印给 AI 看
    def instruction(self) -> str:
        return (
            "已有项目设计初始化：必须查看代码和测试，具备安全条件时实际运行；"
            "一次建立相互一致的产品文档、代码架构文档和 spec/project_design_init_evidence.md 调查证据"
        )


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
        return "Template_Repository/code_design/code_design.md"

    # 规范词文档路径，discuss 命令加载这个文档内容打印给 AI 用
    def standard_doc_path(self) -> str | None:
        return "Standardized_Repository/code_design/revise_code_design.md"

    def code_validate(self, project_root: str) -> tuple[bool, str]:
        architecture_path = os.path.join("spec", "architecture_code_design.md")
        if not os.path.isfile(os.path.join(project_root, architecture_path)):
            return (False, f"{architecture_path} 不存在")
        changed_ok, changed_detail, _ = changed_stage_paths(
            project_root,
            self.name(),
            self.change_tracked_paths(project_root),
        )
        if not changed_ok:
            return (False, changed_detail)
        return (True, f"{architecture_path} 已按本阶段产品设计修改")

    def change_tracked_paths(self, project_root: str) -> list[str]:
        return [os.path.join("spec", "architecture_code_design.md")]

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
        return ["bug/index.md", "bug/"]

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
        index_path = os.path.join(bug_dir, "index.md")
        if not os.path.isfile(index_path):
            return (False, "bug/index.md 不存在")
        # 列出 bug/ 下所有 .md 文件（排除 index.md 索引文件）
        md_files = [f for f in os.listdir(bug_dir) if f.endswith(".md") and f != "index.md"]
        # 没有任何 bug 记录 → 判失败
        if not md_files:
            return (False, "bug/ 下没有 bug 记录 .md 文件（非 index.md）")

        changed_ok, changed_detail, changed_paths = changed_stage_paths(
            project_root,
            self.name(),
            self.change_tracked_paths(project_root),
        )
        if not changed_ok:
            return (False, changed_detail)

        state = load_state(project_root)
        if state is None:
            return (False, "找不到当前工作流状态")
        return validate_reproduce_documents(project_root, changed_paths, state.workflow_id)

    def change_tracked_paths(self, project_root: str) -> list[str]:
        bug_dir = os.path.join(project_root, "bug")
        bug_paths = []
        if os.path.isdir(bug_dir):
            bug_paths = [
                os.path.join("bug", filename)
                for filename in os.listdir(bug_dir)
                if filename.endswith(".md") and filename != "index.md"
            ]
        return [os.path.join("bug", "index.md"), *bug_paths]

    # 该 stage 的指令文本，打印给 AI 看
    def instruction(self) -> str:
        return (
            "缺陷复现阶段：使用真实环境和真实输入复现缺陷并确认根因，"
            "产出 bug/<YYYY-MM-DD_HHmm-缺陷描述>.md 并更新 bug/index.md"
        )


# 修复计划 stage：根据已确认的验收主题和测试计划制定修复实施计划
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
        state = load_state(project_root)
        if state is None:
            return (False, "找不到当前工作流状态")
        topics = current_workflow_topics(project_root)
        if not topics:
            return (False, "当前工作流还没有确认验收主题，请先完成 acceptance_plan")
        trace_ok, trace_detail = validate_downstream_traceability(
            project_root,
            state.workflow_id,
            topics,
        )
        if not trace_ok:
            return (False, trace_detail)
        # 找到修复计划文件 → 通过，列出文件名
        return (True, f"修复计划文档存在: {plan_files}")

    # 该 stage 的指令文本，打印给 AI 看
    def instruction(self) -> str:
        return "修复实施计划阶段：根据已确认的验收主题和测试计划制定修复步骤，产出计划文档 + plan/index.md；不在这里重新确定主题"
