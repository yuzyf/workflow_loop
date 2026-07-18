"""
base.py：策略模式的基类定义。

这是整个 workflow_loop 系统的核心——两个 ABC（抽象基类）：
1. ScenarioStrategy：场景策略，定义一条 stage 序列 + 进入指令
2. StageStrategy：环节策略，定义单个 stage 的产出、校验、推进行为

设计模式：策略模式
- 基类定义接口（abstract 方法），子类实现具体行为
- workflow.py 只跟基类打交道，不关心具体是哪个子类
- 加新 stage = 加一个 StageStrategy 子类，零改动 workflow.py
- 加新 scenario = 加一个 ScenarioStrategy 子类，零改动 workflow.py

ABC（AbstractBaseClass）的作用：
- 用 @abstractmethod 标记的方法，子类必须实现，否则不能实例化
- ABC 本身不能被实例化（因为它是抽象的、不完整的）
- Python 强制你实现所有必要方法，不会出现"忘了实现某方法"的 bug
"""
import os
import shutil
from abc import ABC, abstractmethod


class ScenarioStrategy(ABC):
    """场景策略基类。
    
    一个场景 = 一条完整的 stage 序列 + 进入时给 AI 的指令。
    例：新项目场景的 stage 序列 = [spec, spike, plan, acceptance, qa, impl, generate_code_design]
        修 bug 场景的 stage 序列 = [reproduce, fix_plan, acceptance, qa, impl, update_code_design]
    
    加新场景 = 加一个子类，实现 name() / stages() / entry_instruction() 即可。
    这是扩展点之一，但用户说扩展性主轴是环节（stages），不是场景。
    """

    @abstractmethod
    def name(self) -> str:
        """场景名，存到 state.json 的 scenario 字段。如 'new_project' / 'bugfix'。"""
        ...

    @abstractmethod
    def stages(self) -> list:
        """返回该场景的 stage 策略实例列表，按顺序。
        workflow.py 拿到这个列表，按顺序推进每个 stage。
        例：[SpecStage(), SpikeStage(), PlanStage(), ...]"""
        ...

    @abstractmethod
    def entry_instruction(self) -> str:
        """进入这个场景时打印给 AI 的路线图指令。
        告诉 AI 这个场景要走哪些 stage、整体路线是啥。
        AI 读完知道全局，不是只看眼前。"""
        ...


class StageStrategy(ABC):
    """环节策略基类。
    
    一个 stage = 一个工作流环节（spec / plan / acceptance / qa / impl / spike / code_design / ...）。
    
    每个 stage 知道：
    - 自己叫什么（name）
    - 期望产出什么文件（artifact_paths，可能多个）
    - 加载哪个角色文档（role_doc_path，穿刺返回 None）
    - 加载哪个提示词文档（prompt_doc_path，从 Template_Repository/）
    - 加载哪个规范词文档（standard_doc_path，从 Standardized_Repository/）
    - 怎么校验产出是否合格（code_validate，有默认实现：查文件存在）
    - 推进时要做啥额外动作（on_advance，默认 no-op，spike stage 重写清理 throwaway 代码）
    - 该打印什么指令给 AI（instruction）
    
    加新环节 = 加一个子类。这是用户说的"还可能加环节"的主扩展点。
    """

    @abstractmethod
    def name(self) -> str:
        """环节名，存到 state.json 的 stage 标识。如 'spec' / 'plan' / 'acceptance'。"""
        ...

    @abstractmethod
    def artifact_paths(self) -> list[str]:
        """期望产出的文件路径列表（相对项目根）。
        注意是 list 不是单个，因为 spec stage 产出 product.md + 多个 功能*.md。
        
        用途：① code_validate 检查所有文件存在 ② discuss 命令打印"需产出 xxx"
        """
        ...

    @abstractmethod
    def role_doc_path(self) -> str | None:
        """该 stage 的角色文档路径（相对 .workflow_loop/）。
        穿刺返回 None——role_doc.py 把角色定义硬编码了。
        后面想做 per-stage 角色文档，返回路径即可（如 'roles/spec.md'）。"""
        ...

    @abstractmethod
    def prompt_doc_path(self) -> str | None:
        """该 stage 的提示词文档路径（相对 .workflow_loop/）。
        如 'Template_Repository/spec_prompt.md'。
        workflow.py 加载这个文档内容，打印给 AI 用。"""
        ...

    @abstractmethod
    def standard_doc_path(self) -> str | None:
        """该 stage 的规范词文档路径（相对 .workflow_loop/）。
        如 'Standardized_Repository/spec_规范.md'。
        workflow.py 加载这个文档内容，打印给 AI 用。"""
        ...

    def code_validate(self, project_root: str) -> tuple[bool, str]:
        """门禁的【代码侧校验】（第 2 道闸）。
        
        默认实现：检查 artifact_paths() 里的所有文件是否都存在。
        - 全部存在 → (True, "所有期望文件存在: <paths>")
        - 任一不存在 → (False, "文件未产出: <missing_paths>")
        
        这是策略模式的"钩子方法"（Template Method 模式）：
        - 基类提供默认实现（查文件存在）
        - 子类可以重写做更复杂校验（查内容结构、查文件大小、查 git 状态等）
        - 不重写就用默认
        
        后面想给某 stage 加内容校验——比如 spec stage 要校验 product.md
        里有"功能路由"这一节——重写这个方法即可，零改动 workflow.py。
        """
        # 收集所有不存在的文件路径
        missing = []
        for rel_path in self.artifact_paths():
            # 拼出完整路径（项目根 + 相对路径）
            full_path = os.path.join(project_root, rel_path)
            if not os.path.exists(full_path):
                missing.append(rel_path)
        # 全部存在 → 通过
        if not missing:
            return (True, f"所有期望文件存在: {self.artifact_paths()}")
        # 有缺失 → 不通过，列出哪些文件没产出
        return (False, f"文件未产出: {missing}")

    def on_advance(self, project_root: str) -> None:
        """stage 推进时的钩子（gate --confirmed 通过后、推进到下一 stage 前调用）。
        
        默认 no-op（啥都不做）。
        
        子类重写示例：
        - spike stage 重写：删除 .workflow_loop/spike_tmp/ 下所有 throwaway 代码
        - 后面某 stage 推进时要通知/迁移/清理，重写这个方法
        
        这是另一个扩展点——加新 on_advance 行为 = 重写这个方法，零改动 workflow.py。
        """
        # 默认啥都不做，子类按需重写
        pass

    @abstractmethod
    def instruction(self) -> str:
        """该 stage 该做什么的指令文本，打印给 AI 看。
        告诉 AI "这个 stage 你的任务是 xxx，产出 yyy"。"""
        ...


# ── spike stage 专用的 on_advance 清理逻辑 ──────────────

# spike stage 的 on_advance 需要清理 throwaway 代码
# 单独定义成一个函数，SpikeStage 的 on_advance 调它
# 这样清理逻辑可复用、可测试，不藏在子类里
SPIKE_TMP_DIR = os.path.join(".workflow_loop", "spike_tmp")  # throwaway 代码的存放目录


def clean_spike_tmp(project_root: str) -> list[str]:
    """清理 spike stage 的 throwaway 代码。
    
    删除 .workflow_loop/spike_tmp/ 下的所有内容（但保留目录本身）。
    返回被清理的路径列表，供 journal 记录。
    
    在 spike stage 的 on_advance 里调用（gate spike --confirmed 时）。
    这样 throwaway 代码在推进到 plan 前被自动清理，只保留结论文档。
    """
    # 拼出 spike_tmp 的完整路径
    tmp_dir = os.path.join(project_root, SPIKE_TMP_DIR)
    # 目录不存在 → 没啥可清理的，返回空列表
    if not os.path.exists(tmp_dir):
        return []
    # 收集被清理的路径（记录到 journal）
    cleaned = []
    # 遍历 spike_tmp 下的所有条目
    for entry in os.listdir(tmp_dir):
        entry_path = os.path.join(tmp_dir, entry)
        # 删除文件或目录
        if os.path.isdir(entry_path):
            shutil.rmtree(entry_path)  # 递归删目录
        else:
            os.remove(entry_path)  # 删单个文件
        cleaned.append(entry)
    return cleaned
