import os
import re
import shutil
from abc import ABC, abstractmethod
from dataclasses import dataclass

from .. import state as state_mod

# spike stage 的代码、最小非敏感依赖和未登记临时内容目录（相对项目根）。
# 已登记资产按工作流和穿刺项隔离，阶段推进时只删除当前工作流未登记内容。
SPIKE_TMP_DIR = os.path.join(".workflow_loop", "spike_tmp")
_WORKFLOW_ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*")
_SPIKE_ITEM_KEY_RE = re.compile(r"[A-Za-z0-9_\-一-鿿㐀-䶿]+")
_WINDOWS_RESERVED_NAMES = {
    "CON",
    "PRN",
    "AUX",
    "NUL",
    *(f"COM{index}" for index in range(1, 10)),
    *(f"LPT{index}" for index in range(1, 10)),
}


# 阶段材料说明：relative_path 相对 .workflow_loop/；None 表示该阶段没有这类材料，
# missing_note 用直白话明示"无"，不打印不存在的伪路径。
@dataclass
class MaterialSpec:
    relative_path: str | None
    purpose: str
    missing_note: str = ""


# Stage 策略基类（ABC）
# 每个 stage = 一个工作流环节（如 spec、acceptance_plan、test_code）
# 知道：自己叫什么、期望产出什么文件、加载哪些阶段材料、怎么校验产出、推进时做啥
# 加新 stage = 加一个子类，在 path_composer.py 的路径列表里插入
class StageStrategy(ABC):
    # stage 标识名，存到 state.json 的 stage_path 和 stages 的 key
    @abstractmethod
    def name(self) -> str: ...

    # 期望产出的文件路径列表（相对项目根），可能多个
    # 用途：code_validate 检查文件存在 + discuss 打印"需产出 xxx"
    @abstractmethod
    def artifact_paths(self) -> list[str]: ...

    # 角色文档路径（相对 .workflow_loop/），穿刺返回 None（role_doc.py 硬编码）
    @abstractmethod
    def role_doc_path(self) -> str | None: ...

    # 阶段主文档路径（相对 .workflow_loop/）。已校准阶段指向产物文档模板；
    # 方法名保留 prompt_doc_path 兼容旧代码，后续全仓迁移时统一重命名。
    @abstractmethod
    def prompt_doc_path(self) -> str | None: ...

    # 阶段规范文档路径（相对 .workflow_loop/）。已校准阶段指向阶段工作规范。
    @abstractmethod
    def standard_doc_path(self) -> str | None: ...

    # 第一道门的额外校验。默认阶段只记录讨论完成；impl 用它检查
    # 全部实施前计划和“计划确认前代码没有变化”。
    def discussion_validate(self, project_root: str, workflow_state) -> tuple[bool, str]:
        return (True, "")

    # 门禁的代码侧校验（第 2 道闸）
    # 默认实现：检查 artifact_paths() 里的所有文件是否都存在
    # 子类可重写做更复杂校验（查目录下有特定文件、查内容哈希等）
    def code_validate(self, project_root: str) -> tuple[bool, str]:
        # 收集不存在的文件
        missing = []
        # 遍历期望产出路径
        for rel_path in self.artifact_paths():
            # 拼完整路径
            full_path = os.path.join(project_root, rel_path)
            # 文件不存在 → 加入 missing
            if not os.path.exists(full_path):
                missing.append(rel_path)
        # 全部存在 → 通过
        if not missing:
            return (True, f"所有期望文件存在: {self.artifact_paths()}")
        # 有缺失 → 不通过
        return (False, f"文件未产出: {missing}")

    # stage 推进时的钩子（gate --confirmed 通过后、推进到下一 stage 前调用）
    # 默认 no-op；spike stage 重写：只删除当前工作流未登记的穿刺临时内容。
    def on_advance(self, project_root: str) -> list[str]:
        return []

    # 需要证明“本阶段确实修改过”的文件范围。
    # 第一道门记录这些文件的哈希，第二道门比较当前内容；默认阶段不要求变化校验。
    def change_tracked_paths(self, project_root: str) -> list[str]:
        return []

    # 附加阶段材料路径列表（discuss 命令额外加载）
    # 默认空列表；project_design_init 和特定阶段按需加载共享材料。
    def additional_doc_paths(self) -> list[tuple[str, str]]:
        return []

    # 附加阶段规范路径（只有规范，没有对应产物模板时使用）。
    # 例如 impl 阶段在实施计划之外，还要加载代码开发规范。
    def additional_standard_doc_paths(self) -> list[str]:
        return []

    # 统一阶段材料清单：按当前阶段配置生成模板、工作规范和附加材料的说明。
    # 没有模板或规范时返回明示"无"的项，不创建伪路径。
    # 所有环节共用这一个接口；新增环节不需要在命令入口复制拼接逻辑。
    def materials(self) -> list[MaterialSpec]:
        specs: list[MaterialSpec] = []
        template_path = self.prompt_doc_path()
        specs.append(
            MaterialSpec(
                relative_path=template_path,
                purpose="当前阶段产物文档模板：规定最终文档应有的章节、字段和内容边界",
                missing_note="" if template_path else "本阶段没有产物文档模板（不生成独立正式产物）",
            )
        )
        standard_path = self.standard_doc_path()
        specs.append(
            MaterialSpec(
                relative_path=standard_path,
                purpose="当前阶段工作规范：规定 AI 怎样调查、讨论、执行和检查",
                missing_note="" if standard_path else "本阶段没有阶段工作规范",
            )
        )
        for extra_template, extra_standard in self.additional_doc_paths():
            specs.append(
                MaterialSpec(
                    relative_path=extra_template,
                    purpose="附加产物文档模板",
                )
            )
            specs.append(
                MaterialSpec(
                    relative_path=extra_standard,
                    purpose="附加阶段工作规范",
                )
            )
        for extra_standard in self.additional_standard_doc_paths():
            specs.append(
                MaterialSpec(
                    relative_path=extra_standard,
                    purpose="附加开发规范：本阶段动手实现时必须遵守的代码写法",
                )
            )
        return specs

    # 该 stage 的指令文本，打印给 AI 看
    @abstractmethod
    def instruction(self) -> str: ...


def _validated_workflow_id(workflow_id: str) -> str:
    if (
        not isinstance(workflow_id, str)
        or workflow_id in {".", ".."}
        or _WORKFLOW_ID_RE.fullmatch(workflow_id) is None
    ):
        raise ValueError(f"工作流编号不能用于穿刺目录：{workflow_id!r}")
    return workflow_id


def _validated_spike_item_key(item_key: str) -> str:
    if (
        not isinstance(item_key, str)
        or item_key in {".", ".."}
        or _SPIKE_ITEM_KEY_RE.fullmatch(item_key) is None
        or item_key.split(".", 1)[0].upper() in _WINDOWS_RESERVED_NAMES
        or item_key.endswith((" ", "."))
    ):
        raise ValueError(f"穿刺项文件标识不能用于资产目录：{item_key!r}")
    return item_key


def expected_spike_asset_path(workflow_id: str, item_key: str) -> str:
    """返回一项穿刺资产唯一允许使用的项目内相对目录。"""

    workflow_id = _validated_workflow_id(workflow_id)
    item_key = _validated_spike_item_key(item_key)
    return "/".join((".workflow_loop", "spike_tmp", workflow_id, item_key))


def _registered_asset_paths(
    workflow_state: state_mod.WorkflowState,
) -> list[str]:
    workflow_id = _validated_workflow_id(workflow_state.workflow_id)
    registered: list[str] = []
    for asset in workflow_state.spike_assets:
        if asset.workflow_id != workflow_id:
            continue
        raw_path = asset.relative_path.strip().strip("`").replace("\\", "/")
        parts = raw_path.split("/")
        if len(parts) != 4:
            raise ValueError(f"已登记穿刺资产路径层级无效：{asset.relative_path!r}")
        expected = expected_spike_asset_path(workflow_id, parts[-1])
        if raw_path != expected:
            raise ValueError(
                "已登记穿刺资产必须位于当前工作流和穿刺项隔离目录："
                f"{asset.relative_path!r}"
            )
        if asset.status not in {"registered", "needs_revision"}:
            raise ValueError(
                f"已登记穿刺资产状态无效：{asset.relative_path}={asset.status!r}"
            )
        registered.append(expected)
    if len(registered) != len(set(registered)):
        raise ValueError("当前工作流重复登记了同一穿刺资产目录")
    return sorted(registered)


def _validate_directory_boundary(path: str, *, label: str) -> None:
    if os.path.islink(path):
        raise ValueError(f"{label}不能是符号链接：{path}")
    if os.path.exists(path) and not os.path.isdir(path):
        raise ValueError(f"{label}必须是普通目录：{path}")


def plan_spike_tmp_cleanup(
    project_root: str,
    workflow_state: state_mod.WorkflowState | None = None,
) -> dict[str, list[str]]:
    """先完整核对边界，再给出当前工作流的保留和删除清单。"""

    state = workflow_state or state_mod.load_state(project_root)
    if state is None:
        raise ValueError("找不到当前工作流状态，不能清理穿刺临时目录")
    workflow_id = _validated_workflow_id(state.workflow_id)
    registered = _registered_asset_paths(state)

    tmp_root = os.path.join(project_root, SPIKE_TMP_DIR)
    _validate_directory_boundary(tmp_root, label="穿刺临时目录")
    current_root = os.path.join(tmp_root, workflow_id)
    _validate_directory_boundary(current_root, label="当前工作流穿刺目录")

    preserved: list[str] = []
    for relative_path in registered:
        full_path = os.path.join(project_root, *relative_path.split("/"))
        if not os.path.isdir(full_path) or os.path.islink(full_path):
            raise ValueError(f"已登记穿刺资产目录不存在或不安全：{relative_path}")
        preserved.append(relative_path)

    remove: list[str] = []
    if os.path.isdir(current_root):
        registered_set = set(registered)
        for entry in sorted(os.listdir(current_root)):
            relative_path = "/".join(
                (".workflow_loop", "spike_tmp", workflow_id, entry)
            )
            entry_path = os.path.join(current_root, entry)
            if relative_path in registered_set:
                continue
            # 未登记内容可以是文件、目录或符号链接；删除动作只命中当前工作流
            # 的直接子项，不跟随符号链接，也不检查其它工作流目录。
            if not os.path.lexists(entry_path):
                continue
            remove.append(relative_path)
    return {"preserved": preserved, "remove": remove}


def clean_spike_tmp(
    project_root: str,
    workflow_state: state_mod.WorkflowState | None = None,
    *,
    cleanup_plan: dict[str, list[str]] | None = None,
) -> list[str]:
    """删除当前工作流未登记半成品，保留已登记资产和其它工作流目录。"""

    state = workflow_state or state_mod.load_state(project_root)
    if state is None:
        raise ValueError("找不到当前工作流状态，不能清理穿刺临时目录")
    current_plan = plan_spike_tmp_cleanup(project_root, state)
    plan = current_plan
    if cleanup_plan is not None:
        if not isinstance(cleanup_plan, dict):
            raise ValueError("穿刺清理计划必须是对象")
        preserved = cleanup_plan.get("preserved")
        remove = cleanup_plan.get("remove")
        if (
            not isinstance(preserved, list)
            or not isinstance(remove, list)
            or not all(isinstance(path, str) for path in preserved + remove)
        ):
            raise ValueError("穿刺清理计划必须包含 preserved（保留）和 remove（删除）路径数组")
        if preserved != sorted(set(preserved)) or remove != sorted(set(remove)):
            raise ValueError("穿刺清理计划路径必须去重并按字典序保存")
        if preserved != current_plan["preserved"]:
            raise ValueError("穿刺清理计划中的已登记资产与当前状态不一致")

        workflow_id = _validated_workflow_id(state.workflow_id)
        expected_prefix = f".workflow_loop/spike_tmp/{workflow_id}/"
        current_removable = set(current_plan["remove"])
        unexpected = sorted(current_removable - set(remove))
        if unexpected:
            raise ValueError(
                "穿刺清理计划冻结后出现新的未登记内容，不能把它遗漏在本次清理之外："
                f"{unexpected}"
            )
        for relative_path in remove:
            if not relative_path.startswith(expected_prefix):
                raise ValueError(f"穿刺清理计划路径不属于当前工作流：{relative_path}")
            entry = relative_path[len(expected_prefix) :]
            if not entry or "/" in entry or entry in {".", ".."}:
                raise ValueError(f"穿刺清理计划只能删除当前工作流的直接子项：{relative_path}")
            full_path = os.path.join(project_root, *relative_path.split("/"))
            if os.path.lexists(full_path) and relative_path not in current_removable:
                raise ValueError(f"穿刺清理计划试图删除当前不可删除的路径：{relative_path}")
        plan = {"preserved": preserved, "remove": remove}

    cleaned: list[str] = []
    for relative_path in plan["remove"]:
        full_path = os.path.join(project_root, *relative_path.split("/"))
        if os.path.islink(full_path) or os.path.isfile(full_path):
            os.unlink(full_path)
        elif os.path.isdir(full_path):
            shutil.rmtree(full_path)
        elif os.path.lexists(full_path):
            raise ValueError(f"待清理穿刺路径类型不受支持：{relative_path}")
        cleaned.append(relative_path)

    current_root = os.path.join(project_root, SPIKE_TMP_DIR, state.workflow_id)
    if os.path.isdir(current_root) and not os.listdir(current_root):
        os.rmdir(current_root)
    return cleaned
