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
    validate_product_design_documents,
    validate_project_design_feature_consistency,
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
    planned_test_source_paths,
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
    compute_impl_hash,
    compute_non_test_code_snapshot_hash,
    compute_test_code_snapshot_hash,
    get_linked_product_design_paths,
)
from .. import rollback as rollback_mod
from .. import verification as verification_mod
from .base import StageStrategy, clean_spike_tmp


def _validation_result(errors: list[str], success: str) -> tuple[bool, str]:
    """把同一阶段可独立判断的问题一次返回，避免门禁首错即停。"""
    if not errors:
        return (True, success)
    unique_errors = list(dict.fromkeys(error.strip() for error in errors if error.strip()))
    return (False, "\n".join(f"- {error}" for error in unique_errors))


def _validator_error(label: str, result: tuple[bool, str], errors: list[str]) -> bool:
    """记录下游校验结果；返回值表示该校验是否通过。"""
    ok, detail = result
    if not ok:
        errors.append(f"{label}：{detail}")
    return ok


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
        errors: list[str] = []
        overview_exists = os.path.isfile(overview_path)
        if not overview_exists:
            errors.append(f"{overview_rel} 不存在")
        # 当前有效产品功能只以产品总说明仍然链接的功能文档为准
        linked_paths = (
            [
                path
                for path in get_linked_product_design_paths(project_root)
                if path != overview_rel
            ]
            if overview_exists
            else []
        )
        if not linked_paths:
            errors.append(
                f"产品功能链接：{'未检查：产品总说明不存在' if not overview_exists else overview_rel + ' 没有链接任何 功能_*.md 功能文档'}"
            )
        missing_features = [
            path
            for path in linked_paths
            if not os.path.isfile(os.path.join(project_root, path))
        ]
        if missing_features:
            errors.append(f"产品总说明链接的功能文档不存在: {missing_features}")
        # 功能文档标题保留完整显示名称
        for path in linked_paths:
            if path in missing_features:
                continue
            with open(os.path.join(project_root, path), "r", encoding="utf-8") as stream:
                first_line = stream.readline().strip()
            if not first_line.startswith("# 【功能】") or len(first_line) <= len("# 【功能】"):
                errors.append(f"{path} 的一级标题必须是“# 【功能】<功能名称>”")
        _validator_error(
            "产品文档内容边界",
            validate_product_design_documents(project_root),
            errors,
        )

        changed_ok, changed_detail, changed_paths = changed_stage_paths(
            project_root,
            self.name(),
            self.change_tracked_paths(project_root),
        )
        if not changed_ok:
            errors.append(f"本阶段修改范围：{changed_detail}")

        state = load_state(project_root)
        if state is None:
            errors.append("工作流状态：找不到当前工作流状态")
        elif not changed_ok:
            errors.append("按需求类型检查：未检查：本阶段修改范围尚未通过")
        else:
            normalized_changed = [path.replace(os.sep, "/") for path in changed_paths]
            product_changed = overview_rel in normalized_changed
            feature_changed = any(path.startswith("spec/功能_") for path in normalized_changed)
            if state.intent == "from_scratch" and (not product_changed or not feature_changed):
                errors.append("从零创建产品时，产品总说明和至少一份功能文档都必须在本阶段新建")
            if state.intent == "product_change" and not product_changed:
                errors.append("修改产品时，产品总说明必须更新并记录本轮变化")
        return _validation_result(
            errors,
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
        errors: list[str] = []
        state_exists = load_state(project_root) is not None
        index_exists = os.path.isfile(
            os.path.join(project_root, artifact_paths_mod.SPIKE_INDEX_DOC)
        )
        if not state_exists:
            errors.append("工作流状态：找不到当前工作流状态")
        if not index_exists:
            errors.append(f"{artifact_paths_mod.SPIKE_INDEX_DOC} 不存在")
        if state_exists and index_exists:
            _validator_error(
                "穿刺清单和结论",
                validate_spike_stage(project_root),
                errors,
            )
        else:
            reasons = []
            if not state_exists:
                reasons.append("找不到当前工作流状态")
            if not index_exists:
                reasons.append(f"{artifact_paths_mod.SPIKE_INDEX_DOC} 不存在")
            errors.append(f"穿刺清单和结论：未检查：{'；'.join(reasons)}")
        return _validation_result(errors, "穿刺清单、结论和设计同步状态完整")

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
        errors: list[str] = []
        acc_dir_exists = os.path.isdir(acc_dir)
        if not acc_dir_exists:
            errors.append("acceptance/ 目录不存在")
        state = load_state(project_root)
        if state is None:
            errors.append("工作流状态：找不到当前工作流状态")
            errors.append("验收主题选择：未检查：无法取得当前需求类型和工作流编号")
            errors.append("验收计划文档内容：未检查：无法确定当前工作流和主题")
            return _validation_result(errors, "验收计划文档完整")

        topic_index_error: str | None = None
        try:
            if state.intent == "bugfix":
                topics = current_workflow_topics(project_root)
                if not topics:
                    errors.append("修 bug 的验收主题必须先在缺陷复现阶段确定")
            else:
                # 当前 Run 已记录主题时复核这些主题；否则从历史中排除旧主题，找本次新增主题。
                topics = current_workflow_topics(project_root) or candidate_topics(project_root)
        except ValueError as exc:
            topics = []
            topic_index_error = str(exc)
            errors.append(f"验收主题索引：{topic_index_error}")
        if not topics and topic_index_error is None:
            errors.append("没有找到本次新增的验收主题；主题名称不能复用项目历史中的名称")
        if not acc_dir_exists:
            errors.append("验收计划文档校验：未检查：acceptance/ 目录不存在")
        elif topic_index_error is not None:
            errors.append("验收计划文档校验：未检查：验收主题索引无法解析")
        elif not topics:
            errors.append("验收计划文档校验：未检查：没有可校验的验收主题")
        else:
            missing = missing_topic_documents(project_root, "acceptance_plan", topics)
            if missing:
                errors.append(f"缺少验收计划文档: {missing}")
            else:
                _validator_error(
                    "验收计划内容",
                    validate_acceptance_plan_documents(project_root, state.workflow_id, topics),
                    errors,
                )
        return _validation_result(errors, "验收计划文档完整")

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
        state = load_state(project_root)
        errors: list[str] = []
        if state is None:
            errors.append("工作流状态：找不到当前工作流状态")
            qa_dir = os.path.join(project_root, "qa")
            if not os.path.isdir(qa_dir):
                errors.append("qa/ 目录不存在")
            index_md = os.path.join(project_root, artifact_paths_mod.QA_INDEX_DOC)
            if not os.path.isfile(index_md):
                errors.append(f"{artifact_paths_mod.QA_INDEX_DOC} 不存在")
            argv, entry_detail = test_runner_mod.resolve_regression_entry(project_root)
            if argv is None:
                errors.append(f"项目全量测试入口未就绪：{entry_detail}")
            errors.append("实施确认和实施哈希：未检查：找不到当前工作流状态")
            errors.append("测试计划内容和追踪关系：未检查：无法确定当前工作流和主题")
            return _validation_result(errors, "测试计划、实施记录和全量入口均已就绪")
        impl_state = state.stages.get("impl")
        impl_confirmed = bool(
            impl_state is not None
            and impl_state.status == "done"
            and impl_state.gate.user_confirmed
        )
        if not impl_confirmed:
            errors.append("test_plan 的前置实施尚未完成并经用户确认；先完成 workflow gate impl --confirmed")
        impl_hash_current = False
        if state.verification.impl_hash is None:
            errors.append("缺少 impl_hash（实施内容哈希），不能证明测试计划基于当前实施")
        else:
            current_impl_hash = compute_impl_hash(project_root, state.topics)
            impl_hash_current = current_impl_hash == state.verification.impl_hash
            if not impl_hash_current:
                errors.append("实施代码或实施记录在确认后又发生变化；先返回 impl 核对，不能据此编写测试计划")
        qa_dir = os.path.join(project_root, "qa")
        qa_dir_exists = os.path.isdir(qa_dir)
        if not qa_dir_exists:
            errors.append("qa/ 目录不存在")
        index_md = os.path.join(project_root, artifact_paths_mod.QA_INDEX_DOC)
        index_exists = os.path.isfile(index_md)
        if not index_exists:
            errors.append(f"{artifact_paths_mod.QA_INDEX_DOC} 不存在")
        topics = current_workflow_topics(project_root)
        if not topics:
            errors.append("当前工作流还没有确认验收主题，请先完成 acceptance_plan")
        plan_detail = "测试计划内容完整"
        can_validate_plan = qa_dir_exists and index_exists and bool(topics)
        if not can_validate_plan:
            reasons = []
            if not qa_dir_exists:
                reasons.append("qa/ 目录不存在")
            if not index_exists:
                reasons.append(f"{artifact_paths_mod.QA_INDEX_DOC} 不存在")
            if not topics:
                reasons.append("没有验收主题")
            errors.append(f"测试计划内容和追踪关系：未检查：{'；'.join(reasons)}")
        else:
            missing = missing_topic_documents(project_root, "test_plan", topics)
            if missing:
                errors.append(f"缺少测试计划文档: {missing}")
            else:
                _validator_error(
                    "需求交付追踪关系",
                    validate_downstream_traceability(project_root, state.workflow_id, topics),
                    errors,
                )
                plan_ok = _validator_error(
                    "测试计划内容",
                    validate_test_plan_documents(project_root, state.workflow_id, topics),
                    errors,
                )
                if plan_ok:
                    plan_detail = "测试计划内容和追踪关系完整"
        # 当前操作系统必须有可用的项目全量入口参数数组；只检查配置，不执行入口
        argv, entry_detail = test_runner_mod.resolve_regression_entry(project_root)
        if argv is None:
            errors.append(f"项目全量测试入口未就绪：{entry_detail}")
        else:
            # 声明的入口脚本必须真实存在
            for part in argv:
                if ("/" in part or "\\" in part) and not part.startswith("-"):
                    script_path = os.path.join(project_root, part)
                    if not os.path.isfile(script_path):
                        errors.append(f"项目全量测试入口脚本不存在: {part}")
            project = load_project(project_root)
            configured_scripts = test_entry_mod.referenced_project_scripts(
                project.test_entry if project is not None and isinstance(project.test_entry, dict) else {}
            )
            if configured_scripts:
                start_manifest = rollback_mod.read_start_baseline(project_root, state.workflow_id)
                entries = start_manifest.get("entries", {}) if isinstance(start_manifest, dict) else {}
                missing_backups = [script for script in configured_scripts if script not in entries]
                if missing_backups:
                    errors.append("项目全量测试入口脚本没有在修改前登记回退依据: " f"{missing_backups}")
        if not impl_confirmed or not impl_hash_current:
            errors.append("测试计划依据当前实施：未检查：实施确认或实施内容哈希未通过")
        return _validation_result(errors, f"{plan_detail}；当前平台全量入口: {argv}（本阶段不执行）")

    def instruction(self) -> str:
        return (
            "测试计划阶段：读取已确认验收条件、实施记录和当前真实代码，再做测试覆盖审查，"
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
            errors = ["当前工作流还没有确认验收主题，请先完成 acceptance_plan"]
            if not os.path.isfile(os.path.join(project_root, artifact_paths_mod.IMPL_INDEX_DOC)):
                errors.append(f"{artifact_paths_mod.IMPL_INDEX_DOC} 不存在")
            errors.append("实施索引主题关系：未检查：没有已确认验收主题")
            errors.append("主题实施文档：未检查：没有已确认验收主题")
            valid, detail = _validation_result(errors, "")
            return (valid, detail, [])

        errors: list[str] = []
        index_path = os.path.join(project_root, artifact_paths_mod.IMPL_INDEX_DOC)
        if not os.path.isfile(index_path):
            errors.append(f"{artifact_paths_mod.IMPL_INDEX_DOC} 不存在")
        else:
            _validator_error(
                "实施索引",
                validate_inherited_topic_index(
                    project_root,
                    workflow_state.workflow_id,
                    topics,
                    artifact_paths_mod.IMPL_INDEX_DOC,
                    ["展示顺序", "验收主题", "前置主题", "验收计划", "实施文档"],
                    {
                        "验收计划": "../acceptance/{key}_验收计划.md",
                        "实施文档": "./{key}_实施记录.md",
                    },
                ),
                errors,
            )

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
                errors.append(f"{topic_rel} 的工作流编号与当前工作流不一致")
            if f"- 验收主题：{topic}" not in topic_content:
                errors.append(f"{topic_rel} 的验收主题显示名称必须是“{topic}”")
            if "## 1. 实施依据" not in topic_content:
                errors.append(f"{topic_rel} 缺少“实施依据”")
            if "## 2. 实施前计划" not in topic_content:
                errors.append(f"{topic_rel} 缺少“实施前计划”")
            if workflow_state.stage_path_version >= 2:
                current_structure = (
                    "### 2.2 最低实现设计",
                    "### 2.3 代码修改计划",
                )
                for heading in current_structure:
                    if heading not in topic_content:
                        errors.append(f"{topic_rel} 缺少“{heading.removeprefix('### ')}”")
            if "## 4. 计划与实际的差异" in topic_content:
                errors.append(f"{topic_rel} 不得包含“计划与实际的差异”章节")
            if "## 4. 上下游文档" not in topic_content:
                errors.append(f"{topic_rel} 缺少“上下游文档”")
            unresolved = self._subsection_text(topic_content, "2.4 未决问题")
            if unresolved is None:
                errors.append(f"{topic_rel} 缺少“2.4 未决问题”")
            elif self._has_unresolved_content(unresolved):
                errors.append(f"{topic_rel} 仍有未决问题，不能进入代码实施")
            if require_execution_record:
                if "## 3. 实施后记录" not in topic_content:
                    errors.append(f"{topic_rel} 缺少“实施后记录”")
                if workflow_state.stage_path_version >= 2:
                    current_result_structure = (
                        "### 3.1 实施动作记录",
                        "### 3.2 实施中问题与处理",
                        "#### 3.4.1 实际代码修改",
                        "#### 3.4.2 开发检查记录",
                    )
                    for heading in current_result_structure:
                        if heading not in topic_content:
                            errors.append(
                                f"{topic_rel} 缺少“{heading.lstrip('#').strip()}”"
                            )
                if "### 3.3 未完成内容" not in topic_content and "## 3.3 未完成内容" not in topic_content:
                    errors.append(f"{topic_rel} 缺少“3.3 未完成内容”")
                unfinished = self._subsection_text(topic_content, "3.3 未完成内容")
                if unfinished is not None and self._has_unresolved_content(unfinished):
                    errors.append(f"{topic_rel} 仍有未完成内容，不能通过实施门禁")
            if "测试结果：通过" in topic_content or "测试结果：失败" in topic_content:
                errors.append(f"{topic_rel} 不能提前填写正式测试结果")

        if missing_topics:
            errors.append(f"缺少主题实施文档: {missing_topics}")
        valid, detail = _validation_result(errors, "")
        return (valid, detail, topics)

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
        errors = [] if valid else [detail]
        if topics:
            _validator_error(
                "需求交付追踪关系",
                validate_downstream_traceability(project_root, workflow_state.workflow_id, topics),
                errors,
            )
        else:
            errors.append("需求交付追踪关系：未检查：没有验收主题")
        result, result_detail = _validation_result(errors, "实施文档和需求交付追踪关系完整")
        return (result, result_detail, topics)

    def discussion_validate(self, project_root: str, workflow_state) -> tuple[bool, str]:
        # 第一道门确认的是全部实施前计划。
        valid, detail, _ = self._validate_topic_documents(
            project_root,
            workflow_state,
            require_execution_record=False,
        )
        errors = [] if valid else [detail]
        stage_state = workflow_state.stages.get(self.name())
        if stage_state is None or stage_state.code_baseline_hash is None:
            errors.append("缺少进入 impl 时的代码基线，不能确认计划前没有修改代码")
            return _validation_result(errors, "全部验收主题的实施前计划已就绪，代码尚未修改")
        complete_snapshot = workflow_state.meta.get(
            rollback_mod.IMPL_COMPLETE_BASELINE_SNAPSHOT_KEY
        )
        complete_differences: dict[str, list[str]] | None = None
        complete_changed_paths: list[str] = []
        if isinstance(complete_snapshot, dict):
            try:
                complete_differences = (
                    verification_mod.compare_complete_implementation_file_snapshot(
                        project_root,
                        complete_snapshot,
                        scope="all",
                    )
                )
            except (OSError, ValueError) as exc:
                errors.append(
                    "完整实施范围基线无法比较；"
                    f"未检查未登记源码、测试、脚本和配置是否变化：{exc}"
                )
            else:
                complete_changed_paths = sorted(
                    {
                        path
                        for category, paths in complete_differences.items()
                        if category != "not_checked"
                        for path in paths
                    }
                )
        current_hash = compute_non_test_code_snapshot_hash(project_root)
        complete_scope_unchanged = (
            complete_differences is not None and not complete_changed_paths
        )
        legacy_scope_only = not isinstance(complete_snapshot, dict)
        if (
            current_hash == stage_state.code_baseline_hash
            and (complete_scope_unchanged or legacy_scope_only)
        ):
            return _validation_result(errors, "全部验收主题的实施前计划已就绪，代码尚未修改")
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
                errors.append(str(exc))
                changed = []
            planned = set()
            try:
                planned = set(rollback_mod.planned_code_paths(project_root, workflow_state.topics))
            except ValueError as exc:
                errors.append(str(exc))
            observed_changes = set(changed) | set(complete_changed_paths)
            unexpected = sorted(
                observed_changes - planned - set(manifest.get("entries", {}))
            )
            if unexpected:
                errors.append(f"实施计划确认前存在计划外的代码变化，不能通过 impl 的第一道门: {unexpected}")
            return _validation_result(
                errors,
                "实施计划重新确认：首次原内容已保存，当前变化均在计划内",
            )
        if complete_differences is not None and complete_changed_paths:
            errors.append(
                "实施计划确认前代码已经变化，不能通过 impl 的第一道门；"
                "相对入场基线的完整实施范围文件变化："
                f"{verification_mod.format_registered_differences(complete_differences)}"
            )
        else:
            baseline_snapshot = workflow_state.meta.get(
                rollback_mod.IMPL_CODE_BASELINE_SNAPSHOT_KEY
            )
        if (
            not complete_changed_paths
            and current_hash != stage_state.code_baseline_hash
            and isinstance(baseline_snapshot, dict)
        ):
            try:
                differences = verification_mod.compare_registered_file_snapshot(
                    project_root,
                    baseline_snapshot,
                    scope="product",
                )
            except (OSError, ValueError) as exc:
                errors.append(
                    "实施代码基线：整体哈希已经变化，但逐文件差异未检查；"
                    f"无法比较冻结快照：{exc}"
                )
            else:
                errors.append(
                    "实施计划确认前代码已经变化，不能通过 impl 的第一道门；"
                    "相对冻结基线的登记文件变化："
                    f"{verification_mod.format_registered_differences(differences)}"
                )
        elif (
            not complete_changed_paths
            and current_hash != stage_state.code_baseline_hash
            and not isinstance(baseline_snapshot, dict)
        ):
            errors.append(
                "实施计划确认前代码已经变化，不能通过 impl 的第一道门；"
                "当前状态只有整体 code_baseline_hash，逐文件变化未检查"
            )
        errors.append(
            "code_baseline_hash 是进入 impl 时冻结的工作区产品文件快照，不是 Git 提交；"
            "workflow discuss 和 git commit 不会重写它。先恢复未确认的遗留修改；"
            "如果用户明确确认当前代码应成为新的实施前现状，再由 AI 执行 "
            "`workflow gate impl --rebaseline`。"
        )
        return _validation_result(errors, "实施计划重新确认完成")

    def code_validation_report(self, project_root: str, workflow_state=None):
        """返回实施三方核对的原始诊断，命令层不得再从文字反推事实。"""
        state = workflow_state or load_state(project_root)
        if state is None:
            return None
        return rollback_mod.validate_implementation_changes_report(project_root, state)

    @staticmethod
    def legacy_diagnostic_prefixes_covered_by_report() -> tuple[str, ...]:
        """旧文字接口中已由结构化三方报告覆盖的顶层错误类别。"""
        return (
            "实施代码变化和计划范围：",
            "回退依据：",
            "基线后真实文件差异：",
        )

    # 门禁的代码侧校验（第 2 道闸）
    def code_validate(self, project_root: str) -> tuple[bool, str]:
        state = load_state(project_root)
        if state is None:
            return _validation_result(
                [
                    "工作流状态：找不到当前工作流状态",
                    "主题实施文档：未检查：无法确定当前工作流和主题",
                    "实施代码基线：未检查：找不到当前工作流状态",
                    "回退依据和真实差异：未检查：找不到当前工作流状态",
                    "需求交付追踪关系：未检查：无法确定当前工作流和主题",
                ],
                "实施文档、真实代码变化和需求交付追踪关系完整",
            )
        errors: list[str] = []
        valid, detail, topics = self.validate_implementation_records(project_root, state)
        if not valid:
            errors.append(detail)

        stage_state = state.stages.get(self.name())
        if stage_state is None or stage_state.code_baseline_hash is None:
            errors.append("实施代码基线：缺少进入 impl 时的代码基线，不能确认实施代码变化")

        implementation_detail = ""
        rollback_ok, rollback_detail, manifest = rollback_mod.validate_prepared(
            project_root,
            state,
        )
        if not rollback_ok:
            errors.append(f"回退依据：{rollback_detail}")
            errors.append("实施代码变化和计划范围：未检查：回退依据未通过")
        else:
            try:
                changed_paths = rollback_mod.implementation_changed_paths_since_prepare(
                    project_root,
                    manifest,
                )
            except ValueError as exc:
                changed_paths = None
                errors.append(f"基线后真实文件差异：{exc}")
                errors.append("实施代码变化和计划范围：未检查：无法计算基线后真实文件差异")

            if changed_paths is not None:
                changes_ok, changes_detail = rollback_mod.validate_implementation_changes(
                    project_root,
                    state,
                )
                if changes_ok:
                    implementation_detail = changes_detail
                elif (
                    not changed_paths
                    and stage_state is not None
                    and stage_state.existing_code_accepted_hash is not None
                ):
                    current_hash = compute_non_test_code_snapshot_hash(project_root)
                    if current_hash != stage_state.existing_code_accepted_hash:
                        errors.append(
                            "既有代码确认快照：用户确认后核心代码又发生变化，不能继续使用既有代码例外"
                        )
                    existing_ok, existing_detail = rollback_mod.validate_existing_implementation_paths(
                        project_root,
                        state,
                    )
                    if not existing_ok:
                        errors.append(f"既有实现的计划与记录：{existing_detail}")
                    implementation_detail = existing_detail
                else:
                    errors.append(f"实施代码变化和计划范围：{changes_detail}")
                    implementation_detail = ""
                    if (
                        changed_paths
                        and stage_state is not None
                        and stage_state.existing_code_accepted_hash is not None
                    ):
                        errors.append(
                            "既有代码例外不适用：实施前基线后检测到真实修改，"
                            f"必须按三方文件集合核对，变化路径：{changed_paths}"
                        )

        success_detail = f"{len(topics)} 个验收主题的实施计划和实施记录完整"
        if rollback_ok and implementation_detail:
            success_detail += f"；{implementation_detail}"

        return _validation_result(errors, success_detail)

    def instruction(self) -> str:
        return (
            "实施阶段：依据产品设计、代码设计、全部验收主题的验收计划和穿刺结论，先写完实施前计划；"
            "用户确认后再修改真实代码，并在同一份 impl/<主题文件标识>_实施记录.md 中追加实施后记录"
        )


def _test_code_paths(project_root: str) -> list[str]:
    """返回测试计划和项目入口明确登记的测试路径，不遍历项目目录。"""
    topics = current_workflow_topics(project_root)
    paths = set(planned_test_source_paths(project_root, topics)) if topics else set()
    project = load_project(project_root)
    if project is not None and isinstance(project.test_entry, dict):
        paths.update(test_entry_mod.referenced_project_scripts(project.test_entry))
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
        stage_name: str | None = None,
    ) -> tuple[bool, str]:
        state = load_state(project_root)
        if state is None:
            return _validation_result(
                [
                    "工作流状态：找不到当前工作流状态",
                    "测试代码基线和产品代码基线：未检查：找不到当前工作流状态",
                    "自动化测试项和 Workflow-Test 标识：未检查：无法确定当前工作流和主题",
                ],
                "测试代码已覆盖当前自动化测试项",
            )
        errors: list[str] = []
        state_name = stage_name or self.name()
        stage_state = state.stages.get(state_name)
        if stage_state is None or stage_state.test_code_baseline_hash is None:
            errors.append(f"缺少进入 {state_name} 时的测试代码基线")
        if stage_state is None or stage_state.non_test_code_baseline_hash is None:
            errors.append(f"缺少进入 {state_name} 时的产品代码基线，请重新完成讨论门禁")
        elif compute_non_test_code_snapshot_hash(project_root) != stage_state.non_test_code_baseline_hash:
            errors.append(f"{state_name} 的测试代码步骤不能修改产品代码；产品代码变化应返回 impl")
        topics = current_workflow_topics(project_root)
        if not topics:
            errors.append("当前工作流还没有确认验收主题")
            errors.append("自动化测试项和 Workflow-Test 标识：未检查：没有验收主题")
            errors.append("测试代码变化范围：未检查：没有验收主题")
            return _validation_result(errors, "测试代码已覆盖当前自动化测试项")
        try:
            automated_items = automated_test_items(project_root, topics)
        except ValueError as exc:
            errors.append(str(exc))
            automated_items = []
        current_test_code_hash = compute_test_code_snapshot_hash(project_root)
        accepted_hash = stage_state.existing_test_code_accepted_hash if stage_state is not None else None
        if accepted_hash is not None and current_test_code_hash != accepted_hash:
            errors.append("既有测试代码确认后又发生变化，需要重新确认或重新修改测试代码")
        if (
            automated_items
            and stage_state.test_code_baseline_hash is not None
            and current_test_code_hash == stage_state.test_code_baseline_hash
            and accepted_hash != current_test_code_hash
            and not allow_unchanged
        ):
            errors.append(
                "存在自动化测试项，但测试代码没有变化；如果当前测试代码已经覆盖最新测试计划，"
                "请由用户执行 workflow gate test_code --accept-existing-test-code 明确确认",
            )
        marker_ok, marker_detail = validate_workflow_test_markers(project_root, topics)
        if not marker_ok:
            errors.append(f"Workflow-Test 标识：{marker_detail}")
        state_ok, state_detail = validate_downstream_traceability(
            project_root,
            state.workflow_id,
            topics,
        )
        if not state_ok:
            errors.append(f"需求交付追踪关系：{state_detail}")
        if not automated_items:
            return _validation_result(errors, f"{len(topics)} 个验收主题都没有自动化测试项，无需新增测试代码")
        return _validation_result(
            errors,
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
            return _validation_result(
                [
                    "工作流状态：找不到当前工作流状态",
                    "测试代码确认哈希：未检查：找不到当前工作流状态",
                    "自动化测试项和主题测试结果：未检查：无法确定当前工作流和主题",
                    "需求交付追踪关系：未检查：无法确定当前工作流和主题",
                ],
                "主题测试结果完整",
            )
        errors: list[str] = []
        topics = current_workflow_topics(project_root)
        if not topics:
            errors.append("当前工作流还没有确认验收主题")
        if state.verification.test_code_hash is None:
            errors.append("缺少 test_code 确认后的测试代码哈希，不能执行正式测试")
        elif compute_test_code_snapshot_hash(project_root) != state.verification.test_code_hash:
            errors.append("test_code 确认后测试代码或测试配置发生变化，必须返回 test_code")
        if not topics:
            errors.append("自动化测试项和主题测试结果：未检查：没有验收主题")
            errors.append("需求交付追踪关系：未检查：没有验收主题")
            return _validation_result(errors, "主题测试结果完整")
        try:
            test_topics = automated_topics(project_root, topics)
        except ValueError as exc:
            errors.append(str(exc))
            test_topics = None
        if test_topics is not None:
            missing = missing_topic_documents(project_root, "test_result", test_topics)
            if missing:
                errors.append(f"缺少主题测试结果: {missing}；先执行测试并记录正式结果")
        _validator_error(
            "需求交付追踪关系",
            validate_downstream_traceability(project_root, state.workflow_id, topics),
            errors,
        )
        if test_topics is None:
            errors.append("主题测试执行结果：未检查：自动化测试主题解析失败")
        else:
            _validator_error(
                "主题测试执行结果",
                validate_test_execution_results(project_root, state.workflow_id, topics),
                errors,
            )
        return _validation_result(errors, "主题测试结果完整")

    def instruction(self) -> str:
        return (
            "测试执行阶段：先和用户逐项确认测试入口、前置测试项、真实命令、工作目录、运行环境和超时时间；"
            "确认后用 workflow test prepare 登记，再用 workflow test run 执行。"
            "执行失败不生成正式主题测试结果，先定位问题并按规则返回对应阶段。"
        )


# 单一测试验证 stage：把旧 test_plan、test_code、test_execution 的事实边界合并，
# 但不把测试计划、测试代码、任务登记和机器结果压成一份不可追溯的文档。
class QaStage(StageStrategy):
    """qa（测试验证）阶段策略。

    对用户只暴露一个阶段；内部仍按范围、计划、测试代码、任务、执行和结果顺序推进。
    旧三个阶段类保留给历史状态迁移和兼容读取。
    """

    def name(self) -> str:
        return "qa"

    def artifact_paths(self) -> list[str]:
        return [artifact_paths_mod.QA_INDEX_DOC, "qa/"]

    def role_doc_path(self) -> str | None:
        return None

    def prompt_doc_path(self) -> str | None:
        return "Template_Repository/qa/test_plan.md"

    def standard_doc_path(self) -> str | None:
        return "Standardized_Repository/qa/test_plan.md"

    def additional_doc_paths(self) -> list[tuple[str, str]]:
        return [
            (
                "Template_Repository/qa/test.md",
                "Standardized_Repository/qa/test.md",
            )
        ]

    def additional_standard_doc_paths(self) -> list[str]:
        return [
            "Standardized_Repository/qa/test_code.md",
            "Standardized_Repository/qa/test_code_implementation.md",
        ]

    def change_tracked_paths(self, project_root: str) -> list[str]:
        return _test_code_paths(project_root)

    def discussion_validate(self, project_root: str, workflow_state) -> tuple[bool, str]:
        # 开始确认只检查测试范围、计划结构、实施结果和真实入口，不执行测试。
        return TestPlanStage().code_validate(project_root)

    def _validate_test_code(self, project_root: str) -> tuple[bool, str]:
        # QA 正常路径允许复用符合当前计划的既有测试代码；复用不等于跳过正式执行。
        return TestCodeStage()._validate_current_test_code(
            project_root,
            allow_unchanged=True,
            stage_name="qa",
        )

    def code_validate(self, project_root: str) -> tuple[bool, str]:
        state = load_state(project_root)
        if state is None:
            return _validation_result(
                [
                    "工作流状态：找不到当前工作流状态",
                    "测试计划、测试代码、任务登记和机器结果：未检查：无法确定当前工作流",
                ],
                "qa（测试验证）内部计划、代码、任务和结果完整",
            )
        errors: list[str] = []
        plan_ok, plan_detail = TestPlanStage().code_validate(project_root)
        if not plan_ok:
            errors.append(f"测试计划和范围：{plan_detail}")
        code_ok, code_detail = self._validate_test_code(project_root)
        if not code_ok:
            errors.append(f"测试代码：{code_detail}")
        tasks_ok, tasks_detail = test_execution_mod.validate_prepared_tasks(
            project_root,
            state,
        )
        if not tasks_ok:
            errors.append(f"任务登记：{tasks_detail}")
        topics = current_workflow_topics(project_root)
        if topics:
            _validator_error(
                "主题测试执行结果",
                validate_test_execution_results(project_root, state.workflow_id, topics),
                errors,
            )
        else:
            errors.append("测试主题：未检查：没有验收主题")
        return _validation_result(
            errors,
            "qa（测试验证）内部计划、测试代码、任务登记和结果完整",
        )

    def instruction(self) -> str:
        return (
            "测试验证阶段：开始时一次确认全部主题的测试范围和通过标准；"
            "随后连续完成测试计划检查、测试代码复用或修改、文件冻结、任务登记、正式执行和结果整理；"
            "结束时只复核已有机器记录和人工待验收内容，不重新执行测试。"
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
            return _validation_result(
                [
                    "工作流状态：找不到当前工作流状态",
                    "主题测试结果：未检查：无法确定当前工作流和主题",
                    "主题验收结果：未检查：无法确定当前工作流和主题",
                    "需求交付追踪关系：未检查：无法确定当前工作流和主题",
                ],
                "主题验收结果完整",
            )
        errors: list[str] = []
        topics = current_workflow_topics(project_root)
        if not topics:
            errors.append("当前工作流还没有确认验收主题")
            errors.append("主题测试结果：未检查：没有验收主题")
            errors.append("主题验收结果：未检查：没有验收主题")
            errors.append("需求交付追踪关系：未检查：没有验收主题")
            return _validation_result(errors, "主题验收结果完整")
        test_ok, test_detail = validate_test_execution_results(
            project_root,
            state.workflow_id,
            topics,
        )
        if not test_ok:
            errors.append(f"主题测试未全部通过，不能开始主题验收: {test_detail}")
        missing = missing_topic_documents(project_root, "acceptance_result", topics)
        if missing:
            errors.append(f"缺少主题验收结果: {missing}")
        _validator_error(
            "需求交付追踪关系",
            validate_downstream_traceability(project_root, state.workflow_id, topics),
            errors,
        )
        if missing:
            errors.append("主题验收结果内容：未检查：缺少主题验收结果文档")
        else:
            _validator_error(
                "主题验收结果内容",
                validate_topic_acceptance_results(project_root, state.workflow_id, topics),
                errors,
            )
        return _validation_result(errors, "主题验收结果完整")

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
        errors: list[str] = []
        if not topics:
            errors.append("当前工作流还没有确认验收主题")
        else:
            _validator_error(
                "主题验收",
                validate_topic_acceptance_results(project_root, workflow_state.workflow_id, topics),
                errors,
            )
        argv, entry_detail = test_runner_mod.resolve_regression_entry(project_root)
        if argv is None:
            errors.append(f"项目全量测试入口未就绪：{entry_detail}")
        return _validation_result(errors, f"全部主题已通过，当前平台全量入口就绪: {argv}")

    def code_validate(self, project_root: str) -> tuple[bool, str]:
        state = load_state(project_root)
        if state is None:
            return _validation_result(
                [
                    "工作流状态：找不到当前工作流状态",
                    "需求交付追踪关系：未检查：无法确定当前工作流和主题",
                    "最终全量回归机器记录：未检查：找不到当前工作流状态",
                ],
                "最终全量回归状态有效",
            )
        errors: list[str] = []
        topics = current_workflow_topics(project_root)
        if not topics:
            errors.append("当前工作流还没有确认验收主题")
            errors.append("需求交付追踪关系：未检查：没有验收主题")
        else:
            _validator_error(
                "需求交付追踪关系",
                validate_downstream_traceability(project_root, state.workflow_id, topics),
                errors,
            )
        _validator_error(
            "最终全量回归机器记录",
            validate_final_regression_state(project_root, state.workflow_id),
            errors,
        )
        return _validation_result(errors, "最终全量回归状态有效")

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
            return _validation_result(
                [
                    "工作流状态：找不到当前工作流状态",
                    "需求交付追踪关系：未检查：无法确定当前工作流和主题",
                    "整体验收前置条件：未检查：找不到当前工作流状态",
                ],
                "整体验收前置条件有效",
            )
        errors: list[str] = []
        topics = current_workflow_topics(project_root)
        if not topics:
            errors.append("当前工作流还没有确认验收主题")
            errors.append("需求交付追踪关系：未检查：没有验收主题")
        else:
            _validator_error(
                "需求交付追踪关系",
                validate_downstream_traceability(project_root, state.workflow_id, topics),
                errors,
            )
        _validator_error(
            "整体验收前置条件",
            validate_overall_acceptance_prerequisites(project_root, state.workflow_id, topics),
            errors,
        )
        return _validation_result(errors, "整体验收前置条件有效")

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
        errors: list[str] = []
        architecture_exists = os.path.isfile(os.path.join(project_root, architecture_rel))
        if not architecture_exists:
            errors.append(f"{architecture_rel} 不存在")
        changed_ok, changed_detail, changed_paths = changed_stage_paths(
            project_root,
            self.name(),
            self.change_tracked_paths(project_root),
        )
        if not changed_ok:
            errors.append(f"本阶段修改范围：{changed_detail}")
        normalized_changed = [path.replace(os.sep, "/") for path in changed_paths]
        changed_product_docs = [
            path
            for path in normalized_changed
            if path == artifact_paths_mod.PRODUCT_OVERVIEW_DOC
            or path.startswith("spec/功能_")
        ]
        if changed_product_docs:
            errors.append(
                "产品总说明或功能文档在 update_code_design 阶段发生变化："
                f"{changed_product_docs}；功能变化必须返回 spec，不能在最终设计同步阶段直接修改",
            )
        if architecture_rel not in normalized_changed:
            errors.append(
                f"最终设计同步没有更新 {architecture_rel}；"
                "即使架构没有变化，也要写入本轮核对结论和真实代码映射",
            )
        state = load_state(project_root)
        if state is None:
            errors.append("工作流状态：找不到当前工作流状态")
            errors.append("需求交付追踪关系：未检查：无法确定当前工作流和主题")
            errors.append("最终代码架构文档内容：未检查：无法取得当前工作流编号")
            return _validation_result(errors, "最终代码设计和追踪表一致")
        topics = current_workflow_topics(project_root)
        if not topics:
            errors.append("当前工作流还没有确认验收主题")
            errors.append("需求交付追踪关系：未检查：没有验收主题")
        else:
            _validator_error(
                "需求交付追踪关系",
                validate_downstream_traceability(project_root, state.workflow_id, topics),
                errors,
            )
        if architecture_exists:
            _validator_error(
                "最终代码架构文档",
                validate_final_code_design_document(project_root, state.workflow_id),
                errors,
            )
        else:
            errors.append("最终代码架构文档内容：未检查：代码架构设计文件不存在")
        return _validation_result(errors, "最终代码设计和追踪表一致")

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
        errors: list[str] = []
        overview_exists = os.path.isfile(os.path.join(project_root, overview_rel))
        architecture_exists = os.path.isfile(os.path.join(project_root, architecture_rel))
        evidence_exists = os.path.isfile(os.path.join(project_root, PROJECT_INIT_EVIDENCE_PATH))
        missing: list[str] = []
        if not overview_exists:
            missing.append(overview_rel)
        if not architecture_exists:
            missing.append(architecture_rel)
        linked_features = (
            [
                path
                for path in get_linked_product_design_paths(project_root)
                if path != overview_rel
            ]
            if overview_exists
            else []
        )
        if not linked_features:
            missing.append("spec/功能_*.md")
        else:
            missing.extend(
                path
                for path in linked_features
                if not os.path.isfile(os.path.join(project_root, path))
            )
        if not evidence_exists:
            missing.append(PROJECT_INIT_EVIDENCE_PATH)
        if missing:
            errors.append(f"产物未就绪: {list(dict.fromkeys(missing))}")

        changed_ok, changed_detail, changed_paths = changed_stage_paths(
            project_root,
            self.name(),
            self.change_tracked_paths(project_root),
        )
        if not changed_ok:
            errors.append(f"本阶段修改范围：{changed_detail}")
            errors.append(
                "三类初始化产物变化：未检查：没有可用的阶段产物变化记录"
            )
        else:
            normalized_changed = [path.replace(os.sep, "/") for path in changed_paths]
            product_changed = any(
                path == overview_rel or path.startswith("spec/功能_")
                for path in normalized_changed
            )
            architecture_changed = architecture_rel in normalized_changed
            evidence_changed = PROJECT_INIT_EVIDENCE_PATH.replace(os.sep, "/") in normalized_changed
            if not product_changed or not architecture_changed or not evidence_changed:
                errors.append(
                    "项目设计初始化必须在本阶段更新产品设计、代码设计和调查证据三类内容；"
                    f"当前变化文件: {changed_paths}",
                )

        state = load_state(project_root)
        if state is None:
            errors.append("工作流状态：找不到当前工作流状态")
            errors.append("初始化证据内容：未检查：无法取得当前工作流编号")
        else:
            _validator_error(
                "初始化证据内容",
                validate_project_design_init_evidence(project_root, state.workflow_id),
                errors,
            )
        _validator_error(
            "产品文档内容边界",
            validate_product_design_documents(project_root),
            errors,
        )
        _validator_error(
            "初始化功能与产出一致性",
            validate_project_design_feature_consistency(project_root),
            errors,
        )
        return _validation_result(
            errors,
            "项目设计初始化产物和调查证据有效: "
            f"产品总说明 + 代码架构设计 + {[os.path.basename(f) for f in linked_features]}",
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
        # 旧状态迁移只保留阶段识别；架构文档规则统一使用当前规范。
        return "Standardized_Repository/code_design/code_design.md"

    def code_validate(self, project_root: str) -> tuple[bool, str]:
        architecture_rel = artifact_paths_mod.CODE_DESIGN_DOC
        errors: list[str] = []
        if not os.path.isfile(os.path.join(project_root, architecture_rel)):
            errors.append(f"{architecture_rel} 不存在")
        changed_ok, changed_detail, _ = changed_stage_paths(
            project_root,
            self.name(),
            self.change_tracked_paths(project_root),
        )
        if not changed_ok:
            errors.append(f"本阶段修改范围：{changed_detail}")
        return _validation_result(errors, f"{architecture_rel} 已按本阶段产品设计修改")

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
        errors: list[str] = []
        bug_dir_exists = os.path.isdir(bug_dir)
        if not bug_dir_exists:
            errors.append("bug/ 目录不存在")
        index_path = os.path.join(project_root, artifact_paths_mod.BUG_INDEX_DOC)
        index_exists = os.path.isfile(index_path)
        if not index_exists:
            errors.append(f"{artifact_paths_mod.BUG_INDEX_DOC} 不存在")
        md_files = (
            [
                f
                for f in os.listdir(bug_dir)
                if f.endswith(".md") and f != "索引.md"
            ]
            if bug_dir_exists
            else []
        )
        if not md_files:
            errors.append("bug/ 下没有缺陷记录文档")

        changed_ok, changed_detail, changed_paths = changed_stage_paths(
            project_root,
            self.name(),
            self.change_tracked_paths(project_root),
        )
        if not changed_ok:
            errors.append(f"本阶段修改范围：{changed_detail}")

        state = load_state(project_root)
        if state is None:
            errors.append("工作流状态：找不到当前工作流状态")
        if not (bug_dir_exists and index_exists and md_files and changed_ok and state is not None):
            reasons: list[str] = []
            if not bug_dir_exists:
                reasons.append("bug/ 目录不存在")
            if not index_exists:
                reasons.append(f"{artifact_paths_mod.BUG_INDEX_DOC} 不存在")
            if not md_files:
                reasons.append("没有缺陷记录文档")
            if not changed_ok:
                reasons.append("本阶段修改范围不可用")
            if state is None:
                reasons.append("找不到当前工作流状态")
            errors.append(f"缺陷记录内容：未检查：{'；'.join(reasons)}")
        else:
            _validator_error(
                "缺陷记录内容",
                validate_reproduce_documents(project_root, changed_paths, state.workflow_id),
                errors,
            )
        return _validation_result(errors, "缺陷记录、真实复现证据和根因完整")

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
