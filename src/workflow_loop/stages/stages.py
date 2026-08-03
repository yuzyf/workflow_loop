import os
import re

from ..artifact_validation import (
    PROJECT_INIT_EVIDENCE_PATH,
    changed_stage_paths,
    validate_acceptance_plan_documents,
    validate_downstream_traceability,
    validate_final_code_design_document,
    validate_final_regression_state,
    validate_inherited_topic_index,
    validate_overall_acceptance_prerequisites,
    validate_project_design_init_evidence,
    validate_reproduce_documents,
    validate_test_plan_documents,
    validate_test_execution_results,
    validate_topic_acceptance_results,
    validate_topic_execution_results,
)
from .. import artifact_paths as artifact_paths_mod
from ..spike_validation import validate_spike_stage
from .. import test_execution as test_execution_mod
from .. import test_runner as test_runner_mod
from .. import test_entry as test_entry_mod
from ..project import load_project
from ..state import load_state
from ..test_mapping import (
    automated_test_items,
    automated_topics,
    validate_workflow_test_markers,
)
from ..topic import (
    candidate_topics,
    current_workflow_topics,
    missing_topic_documents,
    topic_paths,
)
from ..verification import (
    compute_code_snapshot_hash,
    compute_non_test_code_snapshot_hash,
    compute_test_code_snapshot_hash,
    get_linked_product_design_paths,
)
from .. import rollback as rollback_mod
from .base import StageStrategy, clean_spike_tmp


# 产品设计 stage：工作流第一个环节，产出 spec/产品总说明.md + spec/功能_*.md
# 把用户需求拆成产品说明书 + 功能清单，后续 stage 都基于这里定的功能
class SpecStage(StageStrategy):
    def name(self) -> str:
        return "spec"

    def artifact_paths(self) -> list[str]:
        return [artifact_paths_mod.PRODUCT_OVERVIEW_DOC]

    def role_doc_path(self) -> str | None:
        return None

    def prompt_doc_path(self) -> str | None:
        return "Template_Repository/spec/spec.md"

    def standard_doc_path(self) -> str | None:
        return "Standardized_Repository/spec/spec.md"

    # 门禁的代码侧校验（第 2 道闸）
    # 检查产品总说明存在 + 当前链接的功能文档存在且属于本阶段修改
    def code_validate(self, project_root: str) -> tuple[bool, str]:
        overview_rel = artifact_paths_mod.PRODUCT_OVERVIEW_DOC
        overview_path = os.path.join(project_root, overview_rel)
        if not os.path.exists(overview_path):
            return (False, f"{overview_rel} 不存在")
        # 当前有效产品功能只以产品总说明仍然链接的功能文档为准
        linked_paths = [
            path
            for path in get_linked_product_design_paths(project_root)
            if path != overview_rel
        ]
        if not linked_paths:
            return (False, f"{overview_rel} 没有链接任何 功能_*.md 功能文档")
        missing_features = [
            path
            for path in linked_paths
            if not os.path.isfile(os.path.join(project_root, path))
        ]
        if missing_features:
            return (False, f"产品总说明链接的功能文档不存在: {missing_features}")
        # 功能文档标题保留完整显示名称
        for path in linked_paths:
            with open(os.path.join(project_root, path), "r", encoding="utf-8") as stream:
                first_line = stream.readline().strip()
            if not first_line.startswith("# 【功能】") or len(first_line) <= len("# 【功能】"):
                return (False, f"{path} 的一级标题必须是“# 【功能】<功能名称>”")

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
        normalized_changed = [path.replace(os.sep, "/") for path in changed_paths]
        product_changed = overview_rel in normalized_changed
        feature_changed = any(
            path.startswith("spec/功能_") for path in normalized_changed
        )
        if state.intent == "from_scratch" and (not product_changed or not feature_changed):
            return (False, "从零创建产品时，产品总说明和至少一份功能文档都必须在本阶段新建")
        if state.intent == "product_change" and not product_changed:
            return (
                False,
                "修改产品时，产品总说明必须更新并记录本轮变化",
            )
        return (
            True,
            f"产品设计文档存在并且属于本阶段修改: 产品总说明 + {[os.path.basename(p) for p in linked_paths]}",
        )

    def change_tracked_paths(self, project_root: str) -> list[str]:
        return get_linked_product_design_paths(project_root)

    def instruction(self) -> str:
        return (
            "产品设计阶段：产出 spec/产品总说明.md（产品设计说明书 + 功能清单）"
            "和 spec/功能_<功能文件标识>.md（功能拆分）；文档标题写完整功能名称"
        )


# 初步代码架构 stage：从已确认产品设计推导代码设计
class CodeDesignStage(StageStrategy):
    def name(self) -> str:
        return "code_design"

    def artifact_paths(self) -> list[str]:
        return [artifact_paths_mod.CODE_DESIGN_DOC]

    def role_doc_path(self) -> str | None:
        return None

    def prompt_doc_path(self) -> str | None:
        return "Template_Repository/code_design/code_design.md"

    def standard_doc_path(self) -> str | None:
        return "Standardized_Repository/code_design/code_design.md"

    def instruction(self) -> str:
        return (
            "初步代码架构阶段：从已确认产品设计推导代码分层、关键节点和功能代码过程，"
            f"产出 {artifact_paths_mod.CODE_DESIGN_DOC}"
        )


# 穿刺 stage：识别并验证真实场景中的技术不确定性
class SpikeStage(StageStrategy):
    def name(self) -> str:
        return "spike"

    def artifact_paths(self) -> list[str]:
        return [artifact_paths_mod.SPIKE_INDEX_DOC]

    def role_doc_path(self) -> str | None:
        return None

    def prompt_doc_path(self) -> str | None:
        return "Template_Repository/spike/spike.md"

    def standard_doc_path(self) -> str | None:
        return "Standardized_Repository/spike/spike.md"

    def code_validate(self, project_root: str) -> tuple[bool, str]:
        return validate_spike_stage(project_root)

    def on_advance(self, project_root: str) -> list[str]:
        return clean_spike_tmp(project_root)

    def instruction(self) -> str:
        return (
            "穿刺阶段：先查产品设计、代码设计、相关代码和运行事实，识别真实场景中的技术不确定性；"
            f"用户决定执行清单或全部跳过。正常执行时写 {artifact_paths_mod.SPIKE_INDEX_DOC} 和每项结论文档，"
            "需要临时代码时放入 .workflow_loop/spike_tmp/，并在进入验收计划前同步受影响的设计文档。"
        )


# 验收计划 stage：制定什么算完成的验收计划
class AcceptancePlanStage(StageStrategy):
    def name(self) -> str:
        return "acceptance_plan"

    def artifact_paths(self) -> list[str]:
        return [
            artifact_paths_mod.TRACEABILITY_DOC,
            artifact_paths_mod.ACCEPTANCE_INDEX_DOC,
            "acceptance/",
        ]

    def role_doc_path(self) -> str | None:
        return None

    def prompt_doc_path(self) -> str | None:
        return "Template_Repository/acceptance/acceptance_plan.md"

    def standard_doc_path(self) -> str | None:
        return "Standardized_Repository/acceptance/acceptance_plan.md"

    def code_validate(self, project_root: str) -> tuple[bool, str]:
        acc_dir = os.path.join(project_root, "acceptance")
        if not os.path.exists(acc_dir):
            return (False, "acceptance/ 目录不存在")
        state = load_state(project_root)
        if state is None:
            return (False, "找不到当前工作流状态")

        if state.intent == "bugfix":
            topics = current_workflow_topics(project_root)
            if not topics:
                return (False, "修 bug 的验收主题必须先在缺陷复现阶段确定")
        else:
            # 当前 Run 已记录主题时复核这些主题；否则从历史中排除旧主题，找本次新增主题。
            topics = current_workflow_topics(project_root) or candidate_topics(project_root)
        if not topics:
            return (False, "没有找到本次新增的验收主题；主题名称不能复用项目历史中的名称")
        missing = missing_topic_documents(project_root, "acceptance_plan", topics)
        if missing:
            return (False, f"缺少验收计划文档: {missing}")
        return validate_acceptance_plan_documents(
            project_root,
            state.workflow_id,
            topics,
        )

    def instruction(self) -> str:
        return (
            "验收计划阶段：从零开发和修改产品先确定本次需求的全部验收主题；"
            "修 bug 复用缺陷复现阶段已经确认的主题。为每个主题写清什么算完成，"
            f"确认主题关系，产出 {artifact_paths_mod.TRACEABILITY_DOC}、"
            f"{artifact_paths_mod.ACCEPTANCE_INDEX_DOC} 和 acceptance/<主题文件标识>_验收计划.md。"
        )


# 测试计划 stage：对验收条件做测试覆盖审查，登记项目全量入口
class TestPlanStage(StageStrategy):
    def name(self) -> str:
        return "test_plan"

    def artifact_paths(self) -> list[str]:
        return [artifact_paths_mod.QA_INDEX_DOC]

    def role_doc_path(self) -> str | None:
        return None

    def prompt_doc_path(self) -> str | None:
        return "Template_Repository/qa/test_plan.md"

    def standard_doc_path(self) -> str | None:
        return "Standardized_Repository/qa/test_plan.md"

    # 门禁的代码侧校验（第 2 道闸）：结构、环境和入口检查，不执行任何测试
    def code_validate(self, project_root: str) -> tuple[bool, str]:
        qa_dir = os.path.join(project_root, "qa")
        if not os.path.exists(qa_dir):
            return (False, "qa/ 目录不存在")
        index_md = os.path.join(project_root, artifact_paths_mod.QA_INDEX_DOC)
        if not os.path.isfile(index_md):
            return (False, f"{artifact_paths_mod.QA_INDEX_DOC} 不存在")
        topics = current_workflow_topics(project_root)
        if not topics:
            return (False, "当前工作流还没有确认验收主题，请先完成 acceptance_plan")
        missing = missing_topic_documents(project_root, "test_plan", topics)
        if missing:
            return (False, f"缺少测试计划文档: {missing}")
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
        plan_ok, plan_detail = validate_test_plan_documents(
            project_root,
            state.workflow_id,
            topics,
        )
        if not plan_ok:
            return (False, plan_detail)
        # 当前操作系统必须有可用的项目全量入口参数数组；只检查配置，不执行入口
        argv, entry_detail = test_runner_mod.resolve_regression_entry(project_root)
        if argv is None:
            return (False, f"项目全量测试入口未就绪：{entry_detail}")
        # 声明的入口脚本必须真实存在
        for part in argv:
            if ("/" in part or "\\" in part) and not part.startswith("-"):
                script_path = os.path.join(project_root, part)
                if not os.path.isfile(script_path):
                    return (False, f"项目全量测试入口脚本不存在: {part}")
        project = load_project(project_root)
        configured_scripts = test_entry_mod.referenced_project_scripts(
            project.test_entry if project is not None and isinstance(project.test_entry, dict) else {}
        )
        if configured_scripts:
            start_manifest = rollback_mod.read_start_baseline(
                project_root,
                state.workflow_id,
            )
            entries = start_manifest.get("entries", {}) if isinstance(start_manifest, dict) else {}
            missing_backups = [
                script for script in configured_scripts if script not in entries
            ]
            if missing_backups:
                return (
                    False,
                    "项目全量测试入口脚本没有在修改前登记回退依据: "
                    f"{missing_backups}",
                )
        return (True, f"{plan_detail}；当前平台全量入口: {argv}（本阶段不执行）")

    def instruction(self) -> str:
        return (
            "测试计划阶段：对已确认验收条件做测试覆盖审查，"
            "调查项目真实测试工具链并用 workflow test entry 登记按操作系统的全量入口参数数组；"
            f"产出 qa/<主题文件标识>_测试计划.md + {artifact_paths_mod.QA_INDEX_DOC}；"
            "本阶段不执行修改前全量测试"
        )


# 实施 stage：按验收主题承接实施前计划和真实代码实施。
class ImplStage(StageStrategy):
    def name(self) -> str:
        return "impl"

    def artifact_paths(self) -> list[str]:
        return [artifact_paths_mod.IMPL_INDEX_DOC]

    def role_doc_path(self) -> str | None:
        return None

    def prompt_doc_path(self) -> str | None:
        return "Template_Repository/impl/impl.md"

    def standard_doc_path(self) -> str | None:
        return "Standardized_Repository/impl/impl.md"

    def additional_standard_doc_paths(self) -> list[str]:
        return ["Standardized_Repository/impl/code_implementation.md"]

    def _validate_topic_documents(
        self,
        project_root: str,
        workflow_state,
        *,
        require_execution_record: bool,
    ) -> tuple[bool, str, list[str]]:
        topics = current_workflow_topics(project_root)
        if not topics:
            return (False, "当前工作流还没有确认验收主题，请先完成 acceptance_plan", [])

        qa_ok, qa_detail = validate_inherited_topic_index(
            project_root,
            workflow_state.workflow_id,
            topics,
            artifact_paths_mod.QA_INDEX_DOC,
            ["展示顺序", "验收主题", "前置主题", "验收计划", "测试计划", "测试结果"],
            {
                "验收计划": "../acceptance/{key}_验收计划.md",
                "测试计划": "./{key}_测试计划.md",
                "测试结果": "./{key}_测试结果.md",
            },
            {"测试结果": {"无自动化测试项"}},
        )
        if not qa_ok:
            return (False, qa_detail, topics)

        index_path = os.path.join(project_root, artifact_paths_mod.IMPL_INDEX_DOC)
        if not os.path.isfile(index_path):
            return (False, f"{artifact_paths_mod.IMPL_INDEX_DOC} 不存在", topics)
        index_ok, index_detail = validate_inherited_topic_index(
            project_root,
            workflow_state.workflow_id,
            topics,
            artifact_paths_mod.IMPL_INDEX_DOC,
            ["展示顺序", "验收主题", "前置主题", "验收计划", "测试计划", "实施文档"],
            {
                "验收计划": "../acceptance/{key}_验收计划.md",
                "测试计划": "../qa/{key}_测试计划.md",
                "实施文档": "./{key}_实施记录.md",
            },
        )
        if not index_ok:
            return (False, index_detail, topics)

        missing_topics = []
        for topic in topics:
            topic_rel = topic_paths(project_root, topic)["impl_doc"]
            topic_path = os.path.join(project_root, topic_rel)
            if not os.path.isfile(topic_path):
                missing_topics.append(topic_rel)
                continue
            with open(topic_path, "r", encoding="utf-8") as stream:
                topic_content = stream.read()
            if f"- 工作流编号：{workflow_state.workflow_id}" not in topic_content:
                return (False, f"{topic_rel} 的工作流编号与当前工作流不一致", topics)
            if f"- 验收主题：{topic}" not in topic_content:
                return (False, f"{topic_rel} 的验收主题显示名称必须是“{topic}”", topics)
            if "## 1. 实施依据" not in topic_content:
                return (False, f"{topic_rel} 缺少“实施依据”", topics)
            if "## 2. 实施前计划" not in topic_content:
                return (False, f"{topic_rel} 缺少“实施前计划”", topics)
            if "## 4. 计划与实际的差异" in topic_content:
                return (False, f"{topic_rel} 不得包含“计划与实际的差异”章节", topics)
            if "## 4. 上下游文档" not in topic_content:
                return (False, f"{topic_rel} 缺少“上下游文档”", topics)
            unresolved = self._subsection_text(topic_content, "2.4 未决问题")
            if unresolved is None:
                return (False, f"{topic_rel} 缺少“2.4 未决问题”", topics)
            if self._has_unresolved_content(unresolved):
                return (False, f"{topic_rel} 仍有未决问题，不能进入代码实施", topics)
            if require_execution_record:
                if "## 3. 实施后记录" not in topic_content:
                    return (False, f"{topic_rel} 缺少“实施后记录”", topics)
                if "### 3.3 未完成内容" not in topic_content and "## 3.3 未完成内容" not in topic_content:
                    return (False, f"{topic_rel} 缺少“3.3 未完成内容”", topics)
                unfinished = self._subsection_text(topic_content, "3.3 未完成内容")
                if unfinished is None or self._has_unresolved_content(unfinished):
                    return (False, f"{topic_rel} 仍有未完成内容，不能通过实施门禁", topics)
            if "测试结果：通过" in topic_content or "测试结果：失败" in topic_content:
                return (False, f"{topic_rel} 不能提前填写正式测试结果", topics)

        if missing_topics:
            return (False, f"缺少主题实施文档: {missing_topics}", topics)
        return (True, "", topics)

    @staticmethod
    def _subsection_text(content: str, heading: str) -> str | None:
        match = re.search(
            rf"^###\s+{re.escape(heading)}\s*$\n(.*?)(?=^###\s+|^##\s+|\Z)",
            content,
            re.MULTILINE | re.DOTALL,
        )
        return match.group(1).strip() if match else None

    @staticmethod
    def _has_unresolved_content(content: str) -> bool:
        normalized = re.sub(r"[\s`*_-]", "", content)
        return normalized not in {"暂无", "无"}

    def validate_implementation_records(
        self,
        project_root: str,
        workflow_state,
    ) -> tuple[bool, str, list[str]]:
        """只校验实施文档和追踪关系，不判断代码是否变化。"""
        valid, detail, topics = self._validate_topic_documents(
            project_root,
            workflow_state,
            require_execution_record=True,
        )
        if not valid:
            return (False, detail, topics)
        trace_ok, trace_detail = validate_downstream_traceability(
            project_root,
            workflow_state.workflow_id,
            topics,
        )
        if not trace_ok:
            return (False, trace_detail, topics)
        return (True, "实施文档和需求交付追踪关系完整", topics)

    def discussion_validate(self, project_root: str, workflow_state) -> tuple[bool, str]:
        # 第一道门确认的是全部实施前计划。
        valid, detail, _ = self._validate_topic_documents(
            project_root,
            workflow_state,
            require_execution_record=False,
        )
        if not valid:
            return (False, detail)

        stage_state = workflow_state.stages.get(self.name())
        if stage_state is None or stage_state.code_baseline_hash is None:
            return (False, "缺少进入 impl 时的代码基线，不能确认计划前没有修改代码")
        current_hash = compute_non_test_code_snapshot_hash(project_root)
        if current_hash == stage_state.code_baseline_hash:
            return (True, "全部验收主题的实施前计划已就绪，代码尚未修改")
        # 实施中重新确认计划：已经保存首次原内容且全部实际变化都在计划内时，
        # 允许在代码已变化的情况下重新通过讨论门（不覆盖首次副本）。
        prepared_ok, prepared_detail, manifest = rollback_mod.validate_prepared(
            project_root,
            workflow_state,
            require_current_plan=False,
        )
        if prepared_ok and manifest is not None:
            try:
                changed = rollback_mod.changed_paths_since_prepare(project_root, manifest)
            except ValueError as exc:
                return (False, str(exc))
            planned = set()
            try:
                planned = set(rollback_mod.planned_code_paths(project_root, workflow_state.topics))
            except ValueError as exc:
                return (False, str(exc))
            unexpected = sorted(set(changed) - planned - set(manifest.get("entries", {})))
            if unexpected:
                return (
                    False,
                    f"实施计划确认前存在计划外的代码变化，不能通过 impl 的第一道门: {unexpected}",
                )
            return (
                True,
                "实施计划重新确认：首次原内容已保存，当前变化均在计划内",
            )
        return (False, "实施计划确认前代码已经变化，不能通过 impl 的第一道门")

    # 门禁的代码侧校验（第 2 道闸）
    def code_validate(self, project_root: str) -> tuple[bool, str]:
        state = load_state(project_root)
        if state is None:
            return (False, "找不到当前工作流状态")
        valid, detail, topics = self.validate_implementation_records(project_root, state)
        if not valid:
            return (False, detail)

        stage_state = state.stages.get(self.name())
        if stage_state is None or stage_state.code_baseline_hash is None:
            return (False, "缺少进入 impl 时的代码基线，不能确认实施代码变化")
        rollback_ok, rollback_detail, _ = rollback_mod.validate_prepared(
            project_root,
            state,
        )
        if not rollback_ok:
            return (False, rollback_detail)
        current_hash = compute_non_test_code_snapshot_hash(project_root)
        if stage_state.existing_code_accepted_hash is not None:
            if current_hash != stage_state.existing_code_accepted_hash:
                return (False, "用户确认既有代码后代码又发生变化，不能通过实施门禁")
            return (True, f"{len(topics)} 个验收主题的实施计划和实施记录完整，既有代码未发生变化")
        if current_hash == stage_state.code_baseline_hash:
            recovery = getattr(state, "recovery", None)
            if (
                recovery is not None
                and recovery.source_stage
                and "impl" in recovery.affected_stages
            ):
                return (
                    False,
                    "当前代码相对恢复基线没有变化；如果现有代码已经是本次实施结果，"
                    "请先调 workflow gate impl --accept-existing-code 明确确认，"
                    "否则修改代码后再调 workflow gate impl",
                )
            return (False, "实施代码没有相对计划确认时的代码基线发生变化")

        changes_ok, changes_detail = rollback_mod.validate_implementation_changes(
            project_root,
            state,
        )
        if not changes_ok:
            return (False, changes_detail)

        trace_ok, trace_detail = validate_downstream_traceability(
            project_root,
            state.workflow_id,
            topics,
        )
        if not trace_ok:
            return (False, trace_detail)
        return (
            True,
            f"{len(topics)} 个验收主题的实施计划和实施记录完整；{changes_detail}",
        )

    def instruction(self) -> str:
        return (
            "实施阶段：依据全部验收主题的验收计划和测试计划，先写完实施前计划；"
            "用户确认后再修改真实代码，并在同一份 impl/<主题文件标识>_实施记录.md 中追加实施后记录"
        )


def _test_code_paths(project_root: str) -> list[str]:
    """找出项目中现有的测试代码路径，供 test_code 阶段建立变更基线。"""
    code_suffixes = {".py", ".ts", ".tsx", ".js", ".jsx", ".go", ".rs", ".java", ".kt", ".swift", ".ets"}
    paths: list[str] = []
    for root, dirs, files in os.walk(project_root):
        dirs[:] = [
            directory
            for directory in dirs
            if directory not in {".git", ".workflow_loop", "__pycache__", ".venv", "node_modules"}
        ]
        for filename in files:
            relative_path = os.path.relpath(os.path.join(root, filename), project_root)
            parts = relative_path.replace(os.sep, "/").split("/")
            lowered = filename.lower()
            if os.path.splitext(filename)[1].lower() not in code_suffixes:
                continue
            if (
                "tests" in parts
                or "test" in parts
                or lowered.startswith("test_")
                or lowered.endswith(("_test.py", ".test.js", ".test.ts", ".spec.js", ".spec.ts"))
            ):
                paths.append(relative_path)
    return sorted(paths)


# 测试代码编写阶段：调查真实代码并写测试代码。
# 可以运行与当前修改直接相关的局部测试作为开发反馈，但不产出正式测试结果。
class TestCodeStage(StageStrategy):
    def name(self) -> str:
        return "test_code"

    def artifact_paths(self) -> list[str]:
        # 不同语言和框架的测试目录不同；具体测试文件由真实代码调查决定。
        return []

    def role_doc_path(self) -> str | None:
        return None

    def prompt_doc_path(self) -> str | None:
        return None

    def standard_doc_path(self) -> str | None:
        return "Standardized_Repository/qa/test_code.md"

    def additional_standard_doc_paths(self) -> list[str]:
        return ["Standardized_Repository/qa/test_code_implementation.md"]

    def change_tracked_paths(self, project_root: str) -> list[str]:
        return _test_code_paths(project_root)

    def _validate_current_test_code(
        self,
        project_root: str,
        *,
        allow_unchanged: bool,
    ) -> tuple[bool, str]:
        state = load_state(project_root)
        if state is None:
            return (False, "找不到当前工作流状态")
        stage_state = state.stages.get(self.name())
        if stage_state is None or stage_state.test_code_baseline_hash is None:
            return (False, "缺少进入 test_code 时的测试代码基线")
        if stage_state.non_test_code_baseline_hash is None:
            return (False, "缺少进入 test_code 时的产品代码基线，请重新完成 test_code 讨论门禁")
        if compute_non_test_code_snapshot_hash(project_root) != stage_state.non_test_code_baseline_hash:
            return (False, "test_code 阶段不能修改产品代码；产品代码变化应返回 impl")
        topics = current_workflow_topics(project_root)
        if not topics:
            return (False, "当前工作流还没有确认验收主题")
        try:
            automated_items = automated_test_items(project_root, topics)
        except ValueError as exc:
            return (False, str(exc))
        current_test_code_hash = compute_test_code_snapshot_hash(project_root)
        accepted_hash = stage_state.existing_test_code_accepted_hash
        if accepted_hash is not None and current_test_code_hash != accepted_hash:
            return (False, "既有测试代码确认后又发生变化，需要重新确认或重新修改测试代码")
        if (
            automated_items
            and current_test_code_hash == stage_state.test_code_baseline_hash
            and accepted_hash != current_test_code_hash
            and not allow_unchanged
        ):
            return (
                False,
                "存在自动化测试项，但测试代码没有变化；如果当前测试代码已经覆盖最新测试计划，"
                "请由用户执行 workflow gate test_code --accept-existing-test-code 明确确认",
            )
        marker_ok, marker_detail = validate_workflow_test_markers(project_root, topics)
        if not marker_ok:
            return (False, marker_detail)
        state_ok, state_detail = validate_downstream_traceability(
            project_root,
            state.workflow_id,
            topics,
        )
        if not state_ok:
            return (False, state_detail)
        if not automated_items:
            return (True, f"{len(topics)} 个验收主题都没有自动化测试项，无需新增测试代码")
        return (
            True,
            f"测试代码已覆盖 {len(automated_items)} 个自动化测试项；{marker_detail}",
        )

    def validate_existing_test_code(self, project_root: str) -> tuple[bool, str]:
        """校验当前测试代码是否可以作为最新测试计划的既有实现继续使用。"""
        return self._validate_current_test_code(project_root, allow_unchanged=True)

    def code_validate(self, project_root: str) -> tuple[bool, str]:
        return self._validate_current_test_code(project_root, allow_unchanged=False)

    def instruction(self) -> str:
        return (
            "测试代码阶段：先读取验收计划、测试计划、实施记录和真实代码，和用户确认每个测试项的代码落点；"
            "再编写带 Workflow-Test 标识的测试代码。可以运行与当前编写内容直接相关的单个测试作为开发反馈，"
            "但不生成正式机器记录、不写主题测试结果，也不写主题验收结果；正式执行只发生在 test_execution 阶段"
        )


# 测试执行阶段：运行已写好的测试代码，并留下主题测试结果。
class TestExecutionStage(StageStrategy):
    def name(self) -> str:
        return "test_execution"

    def artifact_paths(self) -> list[str]:
        return ["qa/"]

    def role_doc_path(self) -> str | None:
        return None

    def prompt_doc_path(self) -> str | None:
        return "Template_Repository/qa/test.md"

    def standard_doc_path(self) -> str | None:
        return "Standardized_Repository/qa/test.md"

    def discussion_validate(self, project_root: str, workflow_state) -> tuple[bool, str]:
        """第一道门只确认测试任务已经登记，不在这里执行测试。"""
        return test_execution_mod.validate_prepared_tasks(project_root, workflow_state)

    def code_validate(self, project_root: str) -> tuple[bool, str]:
        state = load_state(project_root)
        if state is None:
            return (False, "找不到当前工作流状态")
        topics = current_workflow_topics(project_root)
        if not topics:
            return (False, "当前工作流还没有确认验收主题")
        if state.verification.test_code_hash is None:
            return (False, "缺少 test_code 确认后的测试代码哈希，不能执行正式测试")
        if compute_test_code_snapshot_hash(project_root) != state.verification.test_code_hash:
            return (False, "test_code 确认后测试代码或测试配置发生变化，必须返回 test_code")
        try:
            test_topics = automated_topics(project_root, topics)
        except ValueError as exc:
            return (False, str(exc))
        missing = missing_topic_documents(project_root, "test_result", test_topics)
        if missing:
            return (False, f"缺少主题测试结果: {missing}；先执行测试并记录正式结果")
        trace_ok, trace_detail = validate_downstream_traceability(
            project_root,
            state.workflow_id,
            topics,
        )
        if not trace_ok:
            return (False, trace_detail)
        return validate_test_execution_results(project_root, state.workflow_id, topics)

    def instruction(self) -> str:
        return (
            "测试执行阶段：先和用户逐项确认测试入口、前置测试项、真实命令、工作目录、运行环境和超时时间；"
            "确认后用 workflow test prepare 登记，再用 workflow test run 执行。"
            "执行失败不生成正式主题测试结果，先定位问题并按规则返回对应阶段。"
        )


# 主题验收阶段：测试结果通过后，按验收条件核对用户结果。
class TopicAcceptanceStage(StageStrategy):
    def name(self) -> str:
        return "topic_acceptance"

    def artifact_paths(self) -> list[str]:
        return ["acceptance/"]

    def role_doc_path(self) -> str | None:
        return None

    def prompt_doc_path(self) -> str | None:
        return "Template_Repository/acceptance/acceptance_result.md"

    def standard_doc_path(self) -> str | None:
        return "Standardized_Repository/acceptance/acceptance.md"

    def code_validate(self, project_root: str) -> tuple[bool, str]:
        state = load_state(project_root)
        if state is None:
            return (False, "找不到当前工作流状态")
        topics = current_workflow_topics(project_root)
        if not topics:
            return (False, "当前工作流还没有确认验收主题")
        test_ok, test_detail = validate_test_execution_results(
            project_root,
            state.workflow_id,
            topics,
        )
        if not test_ok:
            return (False, f"主题测试未全部通过，不能开始主题验收: {test_detail}")
        missing = missing_topic_documents(project_root, "acceptance_result", topics)
        if missing:
            return (False, f"缺少主题验收结果: {missing}")
        trace_ok, trace_detail = validate_downstream_traceability(
            project_root,
            state.workflow_id,
            topics,
        )
        if not trace_ok:
            return (False, trace_detail)
        return validate_topic_acceptance_results(project_root, state.workflow_id, topics)

    def instruction(self) -> str:
        return (
            "主题验收阶段：先确认对应主题的测试结果已经通过，再按主题验收计划逐条核对用户结果；"
            "只有全部验收条件通过后才产出 acceptance/<主题文件标识>_验收结果.md；"
            "任一条件未通过、无法验证或阻塞时不生成正式结果，调查原因后返回对应阶段；"
            "只取消一个功能时退回 spec 并定向删除对应代码，只有整个工作流不再继续时才执行 workflow abort"
        )


# 兼容旧代码导入；正式路径只使用 test_execution 和 topic_acceptance。
TestStage = TestExecutionStage
AcceptanceStage = TopicAcceptanceStage


class RegressionTestStage(StageStrategy):
    """全部主题完成后，对合并后的完整代码执行最终全量回归。"""

    def name(self) -> str:
        return "regression_test"

    def artifact_paths(self) -> list[str]:
        return []

    def role_doc_path(self) -> str | None:
        return None

    def prompt_doc_path(self) -> str | None:
        return None

    def standard_doc_path(self) -> str | None:
        return None

    def discussion_validate(self, project_root: str, workflow_state) -> tuple[bool, str]:
        """第一道门只确认全部主题通过、当前系统入口和运行条件，不执行回归。"""
        topics = current_workflow_topics(project_root)
        acceptance_ok, acceptance_detail = validate_topic_acceptance_results(
            project_root,
            workflow_state.workflow_id,
            topics,
        )
        if not acceptance_ok:
            return (False, f"主题验收尚未全部通过，不能进入最终全量回归: {acceptance_detail}")
        argv, entry_detail = test_runner_mod.resolve_regression_entry(project_root)
        if argv is None:
            return (False, f"项目全量测试入口未就绪：{entry_detail}")
        return (True, f"全部主题已通过，当前平台全量入口就绪: {argv}")

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
        return validate_final_regression_state(project_root, state.workflow_id)

    def instruction(self) -> str:
        return (
            "最终全量回归阶段：全部主题完成后，程序在最新完整代码上执行一次项目配置的统一测试入口；"
            "退出码为 0 才算回归通过，完整机器事实写入 state.json、journal 和需求交付追踪表。"
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
            "再由用户确认全部主题组合后是否完成需求；本阶段不生成新的结果文档。"
        )


# 最终设计同步 stage：核对产品、功能、架构和真实代码，并更新最终架构文档
class UpdateCodeDesignStage(StageStrategy):
    def name(self) -> str:
        return "update_code_design"

    def artifact_paths(self) -> list[str]:
        return [artifact_paths_mod.CODE_DESIGN_DOC]

    def role_doc_path(self) -> str | None:
        return None

    def prompt_doc_path(self) -> str | None:
        return "Template_Repository/code_design/code_design.md"

    def standard_doc_path(self) -> str | None:
        return "Standardized_Repository/code_design/update_code_design.md"

    def code_validate(self, project_root: str) -> tuple[bool, str]:
        architecture_rel = artifact_paths_mod.CODE_DESIGN_DOC
        if not os.path.isfile(os.path.join(project_root, architecture_rel)):
            return (False, f"{architecture_rel} 不存在")
        changed_ok, changed_detail, changed_paths = changed_stage_paths(
            project_root,
            self.name(),
            self.change_tracked_paths(project_root),
        )
        if not changed_ok:
            return (False, changed_detail)
        normalized_changed = [path.replace(os.sep, "/") for path in changed_paths]
        changed_product_docs = [
            path
            for path in normalized_changed
            if path == artifact_paths_mod.PRODUCT_OVERVIEW_DOC
            or path.startswith("spec/功能_")
        ]
        if changed_product_docs:
            return (
                False,
                "产品总说明或功能文档在 update_code_design 阶段发生变化："
                f"{changed_product_docs}；功能变化必须返回 spec，不能在最终设计同步阶段直接修改",
            )
        if architecture_rel not in normalized_changed:
            return (
                False,
                f"最终设计同步没有更新 {architecture_rel}；"
                "即使架构没有变化，也要写入本轮核对结论和真实代码映射",
            )
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
        document_ok, document_detail = validate_final_code_design_document(
            project_root,
            state.workflow_id,
        )
        if not document_ok:
            return (False, document_detail)
        return (True, f"{document_detail}；追踪表已准备好记录最终代码设计")

    def change_tracked_paths(self, project_root: str) -> list[str]:
        return [
            artifact_paths_mod.CODE_DESIGN_DOC,
            *get_linked_product_design_paths(project_root),
        ]

    def instruction(self) -> str:
        return (
            "最终设计同步：逐项核对所有当前产品功能、真实代码符号和验证依据；"
            "架构有变化时更新架构和功能到代码的映射，架构无变化时记录核对结论；"
            "发现功能变化返回 spec，发现代码未实现返回 impl；确认无未处理差异后，"
            f"写入/更新 {artifact_paths_mod.CODE_DESIGN_DOC}"
        )


# 项目设计架构初始化 stage：根据现有代码及可运行行为一次建立设计文档
class ProjectDesignInitStage(StageStrategy):
    def name(self) -> str:
        return "project_design_init"

    def artifact_paths(self) -> list[str]:
        return [
            artifact_paths_mod.PRODUCT_OVERVIEW_DOC,
            artifact_paths_mod.CODE_DESIGN_DOC,
            PROJECT_INIT_EVIDENCE_PATH,
        ]

    def role_doc_path(self) -> str | None:
        return None

    def prompt_doc_path(self) -> str | None:
        return "Template_Repository/code_design/project_design_init_evidence.md"

    def standard_doc_path(self) -> str | None:
        return "Standardized_Repository/code_design/project_design_init.md"

    def additional_doc_paths(self) -> list[tuple[str, str]]:
        return [
            ("Template_Repository/spec/spec.md", "Standardized_Repository/spec/spec.md"),
            ("Template_Repository/code_design/code_design.md", "Standardized_Repository/code_design/code_design.md"),
        ]

    def code_validate(self, project_root: str) -> tuple[bool, str]:
        overview_rel = artifact_paths_mod.PRODUCT_OVERVIEW_DOC
        architecture_rel = artifact_paths_mod.CODE_DESIGN_DOC
        missing = []
        if not os.path.exists(os.path.join(project_root, overview_rel)):
            missing.append(overview_rel)
        if not os.path.exists(os.path.join(project_root, architecture_rel)):
            missing.append(architecture_rel)
        linked_features = [
            path
            for path in get_linked_product_design_paths(project_root)
            if path != overview_rel
        ]
        if not linked_features:
            missing.append("spec/功能_*.md")
        if not os.path.exists(os.path.join(project_root, PROJECT_INIT_EVIDENCE_PATH)):
            missing.append(PROJECT_INIT_EVIDENCE_PATH)
        if missing:
            return (False, f"产物未就绪: {missing}")

        changed_ok, changed_detail, changed_paths = changed_stage_paths(
            project_root,
            self.name(),
            self.change_tracked_paths(project_root),
        )
        if not changed_ok:
            return (False, changed_detail)

        normalized_changed = [path.replace(os.sep, "/") for path in changed_paths]
        product_changed = any(
            path == overview_rel or path.startswith("spec/功能_")
            for path in normalized_changed
        )
        architecture_changed = architecture_rel in normalized_changed
        evidence_changed = PROJECT_INIT_EVIDENCE_PATH.replace(os.sep, "/") in normalized_changed
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
            f"产品总说明 + 代码架构设计 + {[os.path.basename(f) for f in linked_features]}; "
            f"{evidence_detail}",
        )

    def change_tracked_paths(self, project_root: str) -> list[str]:
        return [
            artifact_paths_mod.CODE_DESIGN_DOC,
            PROJECT_INIT_EVIDENCE_PATH,
            *get_linked_product_design_paths(project_root),
        ]

    def instruction(self) -> str:
        return (
            "已有项目设计初始化：必须查看代码和测试，具备安全条件时实际运行；"
            f"一次建立相互一致的产品文档、代码架构文档和 {PROJECT_INIT_EVIDENCE_PATH} 调查证据"
        )


# 设计期架构修订 stage：按变更后的产品设计改代码架构设计
class ReviseCodeDesignStage(StageStrategy):
    def name(self) -> str:
        return "revise_code_design"

    def artifact_paths(self) -> list[str]:
        return [artifact_paths_mod.CODE_DESIGN_DOC]

    def role_doc_path(self) -> str | None:
        return None

    def prompt_doc_path(self) -> str | None:
        return "Template_Repository/code_design/code_design.md"

    def standard_doc_path(self) -> str | None:
        return "Standardized_Repository/code_design/revise_code_design.md"

    def code_validate(self, project_root: str) -> tuple[bool, str]:
        architecture_rel = artifact_paths_mod.CODE_DESIGN_DOC
        if not os.path.isfile(os.path.join(project_root, architecture_rel)):
            return (False, f"{architecture_rel} 不存在")
        changed_ok, changed_detail, _ = changed_stage_paths(
            project_root,
            self.name(),
            self.change_tracked_paths(project_root),
        )
        if not changed_ok:
            return (False, changed_detail)
        return (True, f"{architecture_rel} 已按本阶段产品设计修改")

    def change_tracked_paths(self, project_root: str) -> list[str]:
        return [artifact_paths_mod.CODE_DESIGN_DOC]

    def instruction(self) -> str:
        return f"设计期架构修订：按变更后的产品设计改 {artifact_paths_mod.CODE_DESIGN_DOC}"


# 复现 stage：和用户讨论 bug 现象、复现步骤
class ReproduceStage(StageStrategy):
    def name(self) -> str:
        return "reproduce"

    def artifact_paths(self) -> list[str]:
        return [artifact_paths_mod.BUG_INDEX_DOC, "bug/"]

    def role_doc_path(self) -> str | None:
        return None

    def prompt_doc_path(self) -> str | None:
        return "Template_Repository/reproduce/reproduce.md"

    def standard_doc_path(self) -> str | None:
        return "Standardized_Repository/reproduce/reproduce.md"

    def code_validate(self, project_root: str) -> tuple[bool, str]:
        bug_dir = os.path.join(project_root, "bug")
        if not os.path.exists(bug_dir):
            return (False, "bug/ 目录不存在")
        index_path = os.path.join(project_root, artifact_paths_mod.BUG_INDEX_DOC)
        if not os.path.isfile(index_path):
            return (False, f"{artifact_paths_mod.BUG_INDEX_DOC} 不存在")
        md_files = [
            f
            for f in os.listdir(bug_dir)
            if f.endswith(".md") and f != "索引.md"
        ]
        if not md_files:
            return (False, "bug/ 下没有缺陷记录文档")

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
                if filename.endswith(".md") and filename != "索引.md"
            ]
        return [artifact_paths_mod.BUG_INDEX_DOC, *bug_paths]

    def instruction(self) -> str:
        return (
            "缺陷复现阶段：使用真实环境和真实输入复现缺陷并确认根因，"
            f"产出 bug/缺陷_<缺陷文件标识>.md 并更新 {artifact_paths_mod.BUG_INDEX_DOC}"
        )
