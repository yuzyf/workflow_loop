import json
import os
from dataclasses import dataclass, asdict, field
from datetime import datetime, timezone

# project.json 的相对路径（相对于项目根）
# 放在 .workflow_loop/ 下，和 state.json、journal.jsonl 同级
# 但 project.json 是项目级持久字段，跨 Run 不被新 Run 覆盖
PROJECT_FILE = os.path.join(".workflow_loop", "project.json")

# 安装器版本号，用于重复安装保护判断
# installer.py 在安装时写入这个版本；is_installed 检查版本是否匹配
INSTALLER_VERSION = "0.1.0"
# 项目没有单独配置测试入口时使用的默认脚本
DEFAULT_TEST_ENTRY = "scripts/test_all.sh"
DEFAULT_TEST_PARALLELISM = 2


# 项目级持久状态（跨 Run 不被覆盖）
# 和 WorkflowState（单次 Run 快照，新 Run 整份覆盖）分离
# project_design_initialized 不放 state.json，因为它跨 Run 持久
@dataclass
class ProjectState:
    # 安装器版本号，安装时写入
    # is_installed() 检查这个字段判断项目是否已安装
    installer_version: str = INSTALLER_VERSION
    # 安装时间 ISO 8601 UTC，用于追溯项目何时接入 workflow_loop
    installed_at: str = ""
    # 项目设计架构初始化标记
    # 安装时 false；project_design_init stage --confirmed 后置 true
    # from_scratch 在 spec + code_design 都 --confirmed 后置 true
    # PathComposer 用这个字段决定 product_change/bugfix 是否前置 project_design_init
    project_design_initialized: bool = False
    # 已经确认过的验收主题名称。修 bug 在 reproduce 确认，其他意图在 acceptance_plan 确认。
    topic_history: list[str] = field(default_factory=list)
    # 项目统一全量测试入口；可以是脚本路径或不带 shell 运算符的命令文本
    test_entry: str = DEFAULT_TEST_ENTRY
    # 主题测试执行阶段最多同时运行多少个独立主题；同一主题内仍按测试项依赖顺序执行。
    test_parallelism: int = DEFAULT_TEST_PARALLELISM


# 生成 ISO 8601 UTC 时间戳（内部用，不对外暴露）
# 和 state.py 的 now_iso() 逻辑一致，但独立定义避免循环导入
def _now_iso() -> str:
    # datetime.now(timezone.utc) 拿到 UTC 时间
    # .replace(microsecond=0) 去掉微秒
    # .isoformat() 转 ISO 8601 字符串
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


# 从被管理项目的 .workflow_loop/project.json 读取项目级状态
# 如果文件不存在（还没安装），返回 None
def load_project(project_root: str) -> ProjectState | None:
    # 拼出 project.json 的完整路径
    path = os.path.join(project_root, PROJECT_FILE)
    # 文件不存在说明项目还没安装
    if not os.path.exists(path):
        return None
    # 读文件、解析 JSON
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    # 重建 ProjectState dataclass
    return ProjectState(
        installer_version=data.get("installer_version", INSTALLER_VERSION),
        installed_at=data.get("installed_at", ""),
        project_design_initialized=data.get("project_design_initialized", False),
        topic_history=data.get("topic_history", []),
        test_entry=data.get("test_entry", DEFAULT_TEST_ENTRY),
        test_parallelism=max(1, int(data.get("test_parallelism", DEFAULT_TEST_PARALLELISM))),
    )


# 把 ProjectState 写到被管理项目的 .workflow_loop/project.json
# ensure_ascii=False 让中文不被转义；indent=2 让文件可读
def save_project(project_root: str, project: ProjectState) -> None:
    # 拼出 project.json 的完整路径
    path = os.path.join(project_root, PROJECT_FILE)
    # 确保目录存在
    os.makedirs(os.path.dirname(path), exist_ok=True)
    # 序列化 dataclass → dict
    data = asdict(project)
    # 写盘
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


# 判断项目设计架构是否已初始化（PathComposer 用）
# true → product_change/bugfix 跳过 project_design_init stage
# false → 必须执行 project_design_init
# 不用 architecture_code_design.md 是否存在决定跳过（CONTEXT.md "Project Design Init Skip"）
def is_project_design_initialized(project_root: str) -> bool:
    # 读 project.json
    project = load_project(project_root)
    # project 存在且 project_design_initialized 为 true 才返回 True
    return project is not None and project.project_design_initialized


# 设置项目设计架构初始化标记
# 在 project_design_init stage --confirmed 后置 true
# 在 from_scratch 的 spec + code_design 都 --confirmed 后置 true
# 在 from_scratch start 时重置为 false（清场后重新做）
def set_project_design_initialized(project_root: str, value: bool) -> None:
    # 读当前 project 状态
    project = load_project(project_root)
    # project 不存在（异常情况）→ 新建一个，带当前时间戳
    if project is None:
        project = ProjectState(installed_at=_now_iso())
    # 更新标记
    project.project_design_initialized = value
    # 写回 project.json
    save_project(project_root, project)


def register_topics(project_root: str, topics: list[str]) -> None:
    """把本次确认的主题写入项目历史；重复主题直接拒绝。"""
    project = load_project(project_root)
    if project is None:
        project = ProjectState(installed_at=_now_iso())

    duplicates = sorted(set(topics) & set(project.topic_history))
    if duplicates:
        raise ValueError(f"主题名称已经使用过: {duplicates}")

    project.topic_history.extend(topic for topic in topics if topic not in project.topic_history)
    save_project(project_root, project)


# 判断项目是否已安装（install-project 和 start 命令用）
# 检查 project.json 存在且 installer_version 匹配
# 未安装时 start 命令报错，提示用户先跑官方安装脚本
def is_installed(project_root: str) -> bool:
    # 读 project.json
    project = load_project(project_root)
    # project 存在且 installer_version 匹配当前版本才算已安装
    return project is not None and project.installer_version == INSTALLER_VERSION


# 创建项目级状态（installer.py 在安装时调用）
# 初始 project_design_initialized=false，后续由 project_design_init stage 更新
def create_project(project_root: str) -> ProjectState:
    # 新建 ProjectState，带当前版本号和时间戳
    project = ProjectState(
        installer_version=INSTALLER_VERSION,
        installed_at=_now_iso(),
        # 初始为 false，需要走 project_design_init stage 才置 true
        project_design_initialized=False,
    )
    # 写到 project.json
    save_project(project_root, project)
    # 返回新建的 project，供调用方使用
    return project
