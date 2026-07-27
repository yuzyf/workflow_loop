import os
import shutil
from abc import ABC, abstractmethod

# spike stage 的临时代码、样本和原始输出目录（相对项目根）
# spike stage on_advance 时删除这个目录下的所有内容
SPIKE_TMP_DIR = os.path.join(".workflow_loop", "spike_tmp")


# Stage 策略基类（ABC）
# 每个 stage = 一个工作流环节（如 spec、acceptance_plan、topic_execution）
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
    # 默认 no-op；spike stage 重写：删除 .workflow_loop/spike_tmp/ 下所有临时内容
    def on_advance(self, project_root: str) -> list[str]:
        return []

    # 需要证明“本阶段确实修改过”的文件范围。
    # 第一道门记录这些文件的哈希，第二道门比较当前内容；默认阶段不要求变化校验。
    def change_tracked_paths(self, project_root: str) -> list[str]:
        return []

    # 附加阶段材料路径列表（discuss 命令额外加载）
    # 默认空列表；project_design_init 和 topic_execution 按需加载共享材料。
    def additional_doc_paths(self) -> list[tuple[str, str]]:
        return []

    # 该 stage 的指令文本，打印给 AI 看
    @abstractmethod
    def instruction(self) -> str: ...


# 清理 spike stage 的临时代码、样本和原始输出
# 删除 .workflow_loop/spike_tmp/ 下的所有内容（保留目录本身）
# 在 spike stage 的 on_advance 里调用（gate spike --confirmed 时）
# 这样临时代码在推进到 acceptance_plan 前被自动清理，只保留穿刺清单和结论文档
def clean_spike_tmp(project_root: str) -> list[str]:
    # 拼出 spike_tmp 的完整路径
    tmp_dir = os.path.join(project_root, SPIKE_TMP_DIR)
    # 目录不存在 → 没啥可清理的
    if not os.path.exists(tmp_dir):
        return []
    # 收集被清理的路径
    cleaned = []
    # 遍历 spike_tmp 下的所有条目
    for entry in os.listdir(tmp_dir):
        # 拼出条目路径
        entry_path = os.path.join(tmp_dir, entry)
        # 是目录 → 递归删
        if os.path.isdir(entry_path):
            shutil.rmtree(entry_path)
        # 是文件 → 删单个文件
        else:
            os.remove(entry_path)
        # 记录被清理的条目名
        cleaned.append(entry)
    # 返回被清理的路径列表（供 journal 记录）
    return cleaned
