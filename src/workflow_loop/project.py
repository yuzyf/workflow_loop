import copy
import json
import os
import tempfile
from dataclasses import dataclass, asdict, field
from datetime import datetime, timezone

# 统一产品身份：版本常量只在包 __init__ 定义一份，安装、CLI 和项目检查共用
from . import __version__ as PRODUCT_VERSION

# project.json 的相对路径（相对于项目根）
# 放在 .workflow_loop/ 下，和 state.json、journal.jsonl 同级
# 但 project.json 是项目级持久字段，跨 Run 不被新 Run 覆盖
PROJECT_FILE = os.path.join(".workflow_loop", "project.json")

# 安装器版本号，用于重复安装保护判断
# 严格等于产品版本 0.1.0，不存在兼容版本范围
INSTALLER_VERSION = PRODUCT_VERSION
# 项目全量测试入口是"操作系统 → 命令参数数组"的映射；新安装项目默认为空。
# 旧开发状态可能仍是字符串脚本路径；读取时原样保留，由受控迁移转换。
DEFAULT_TEST_ENTRY: dict = {}
DEFAULT_TEST_PARALLELISM = 2

# 完整项目骨架的组成部分：安装时一次写入，日常检查必须全部存在
WORKFLOW_LOOP_DIRNAME = ".workflow_loop"
TEMPLATE_DIRNAME = "Template_Repository"
STANDARDIZED_DIRNAME = "Standardized_Repository"
AGENTS_MD_FILENAME = "AGENTS.md"
MANAGED_PROJECT_FIELDS = (
    "project_design_initialized",
    "topic_history",
    "test_entry",
    "test_parallelism",
    "artifact_file_keys",
)


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
    # 项目统一全量测试入口：操作系统（windows/linux/darwin/default）到参数数组的映射。
    # 不再把当前仓库脚本当成所有项目默认；旧字符串配置读取时原样保留，等待受控迁移。
    test_entry: dict | str = field(default_factory=dict)
    # 主题测试执行阶段最多同时运行多少个独立主题；同一主题内仍按测试项依赖顺序执行。
    test_parallelism: int = DEFAULT_TEST_PARALLELISM
    # 显示名称到稳定中文文件标识的项目级映射，按 feature/topic/spike/bug 分组。
    # 显示名称仍写入正文；文件标识只进入文件名。跨轮次保存，不随新 Run 覆盖。
    artifact_file_keys: dict[str, dict[str, str]] = field(default_factory=dict)


# 项目骨架检查结果：
# state 取值 "installed"（完整安装 0.1.0）/ "uninstalled"（干净未安装）/ "broken"（残缺或版本异常）
# problems 保存 broken 时的具体缺项，供安装脚本和日常命令直接打印
@dataclass
class SkeletonStatus:
    state: str
    problems: list[str] = field(default_factory=list)


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
    raw_keys = data.get("artifact_file_keys", {})
    artifact_file_keys = {
        category: dict(mapping)
        for category, mapping in raw_keys.items()
        if isinstance(mapping, dict)
    }
    return ProjectState(
        installer_version=data.get("installer_version", ""),
        installed_at=data.get("installed_at", ""),
        project_design_initialized=data.get("project_design_initialized", False),
        topic_history=data.get("topic_history", []),
        test_entry=data.get("test_entry", DEFAULT_TEST_ENTRY),
        test_parallelism=max(1, int(data.get("test_parallelism", DEFAULT_TEST_PARALLELISM))),
        artifact_file_keys=artifact_file_keys,
    )


def _atomic_write_json(path: str, data: dict) -> None:
    """在目标文件同目录写完整临时文件，再原子替换目标。"""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    handle = tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        prefix=".project-",
        suffix=".tmp",
        dir=os.path.dirname(path),
        delete=False,
    )
    temp_path = handle.name
    try:
        with handle:
            json.dump(data, handle, ensure_ascii=False, indent=2)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_path, path)
    finally:
        if os.path.exists(temp_path):
            os.remove(temp_path)


# 把 ProjectState 写到被管理项目的 .workflow_loop/project.json
# ensure_ascii=False 让中文不被转义；indent=2 让文件可读
def save_project(project_root: str, project: ProjectState) -> None:
    path = os.path.join(project_root, PROJECT_FILE)
    # 保留未来版本或项目扩展写入的未知字段；当前版本只更新自己拥有的键。
    data = {}
    if os.path.isfile(path):
        try:
            with open(path, "r", encoding="utf-8") as stream:
                existing = json.load(stream)
            if isinstance(existing, dict):
                data.update(existing)
        except (OSError, json.JSONDecodeError):
            data = {}
    data.update(asdict(project))
    _atomic_write_json(path, data)


def _validate_managed_fields(fields: dict) -> None:
    if not isinstance(fields, dict):
        raise ValueError("项目受管字段快照必须是 JSON 对象")
    missing = [name for name in MANAGED_PROJECT_FIELDS if name not in fields]
    if missing:
        raise ValueError(f"项目受管字段快照缺少字段: {missing}")
    if not isinstance(fields["project_design_initialized"], bool):
        raise ValueError("project_design_initialized（项目设计已初始化）必须是布尔值")
    if (
        not isinstance(fields["topic_history"], list)
        or not all(isinstance(item, str) for item in fields["topic_history"])
    ):
        raise ValueError("topic_history（历史主题）必须是字符串数组")
    if not isinstance(fields["test_entry"], (dict, str)):
        raise ValueError("test_entry（项目全量测试入口）必须是平台映射或旧字符串")
    if (
        not isinstance(fields["test_parallelism"], int)
        or isinstance(fields["test_parallelism"], bool)
        or fields["test_parallelism"] < 1
    ):
        raise ValueError("test_parallelism（主题测试最大并行数）必须是正整数")
    mappings = fields["artifact_file_keys"]
    if not isinstance(mappings, dict):
        raise ValueError("artifact_file_keys（正式文件标识映射）必须是对象")
    for category, mapping in mappings.items():
        if not isinstance(category, str) or not isinstance(mapping, dict):
            raise ValueError("正式文件标识映射的分类和值必须是对象")
        if not all(
            isinstance(display_name, str) and isinstance(file_key, str)
            for display_name, file_key in mapping.items()
        ):
            raise ValueError("正式文件标识映射的显示名称和文件标识必须是字符串")


def snapshot_managed_fields(project_root: str) -> dict:
    """保存本轮可能修改的项目级字段，不包含安装身份等无关字段。"""
    project = load_project(project_root)
    if project is None:
        raise ValueError(f"缺少 {PROJECT_FILE}，不能保存项目受管字段")
    fields = {
        "project_design_initialized": project.project_design_initialized,
        "topic_history": list(project.topic_history),
        "test_entry": copy.deepcopy(project.test_entry),
        "test_parallelism": project.test_parallelism,
        "artifact_file_keys": copy.deepcopy(project.artifact_file_keys),
    }
    _validate_managed_fields(fields)
    return fields


def restore_managed_fields(project_root: str, fields: dict) -> None:
    """只恢复本轮受管字段，保留安装身份和未知扩展字段。"""
    _validate_managed_fields(fields)
    path = os.path.join(project_root, PROJECT_FILE)
    if not os.path.isfile(path):
        raise ValueError(f"缺少 {PROJECT_FILE}，不能恢复项目受管字段")
    try:
        with open(path, "r", encoding="utf-8") as stream:
            data = json.load(stream)
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"{PROJECT_FILE} 无法读取，不能恢复项目受管字段: {exc}") from exc
    if not isinstance(data, dict):
        raise ValueError(f"{PROJECT_FILE} 必须是 JSON 对象")

    for name in MANAGED_PROJECT_FIELDS:
        data[name] = copy.deepcopy(fields[name])
    _atomic_write_json(path, data)
    if snapshot_managed_fields(project_root) != fields:
        raise ValueError("项目受管字段写回后复核不一致")


def register_artifact_names(
    project_root: str,
    category: str,
    display_names: list[str],
) -> dict[str, str]:
    """登记正式产物的显示名称到稳定文件标识，并在有新增时落盘。"""
    from . import artifact_paths as artifact_paths_mod

    project = load_project(project_root)
    if project is None:
        raise ValueError("项目尚未安装，不能登记正式文件标识")
    added = artifact_paths_mod.register_file_keys(project, category, display_names)
    if added:
        save_project(project_root, project)
    return added


def _required_repository_files(dirname: str) -> list[str]:
    """返回当前产品发布要求目标项目具备的仓库文件。"""
    source_root = os.path.join(os.path.dirname(__file__), "data", dirname)
    required: list[str] = []
    if not os.path.isdir(source_root):
        return required
    for root, _dirs, files in os.walk(source_root):
        for filename in files:
            relative = os.path.relpath(os.path.join(root, filename), source_root)
            required.append(relative.replace(os.sep, "/"))
    return sorted(required)


# 检查项目骨架完整性，区分三种状态：
# - installed：项目标记、模板仓库、规范仓库和 AGENTS.md 共同构成完整骨架，且版本严格等于 0.1.0
# - uninstalled：.workflow_loop/ 完全不存在（干净目录，可以首次安装）
# - broken：骨架部分存在、版本不符或 project.json 无法读取；任何写入前必须停止
def check_skeleton(project_root: str) -> SkeletonStatus:
    wf_dir = os.path.join(project_root, WORKFLOW_LOOP_DIRNAME)
    project_json = os.path.join(project_root, PROJECT_FILE)

    # .workflow_loop/ 完全不存在 → 干净未安装
    if not os.path.exists(wf_dir):
        return SkeletonStatus(state="uninstalled")

    problems: list[str] = []

    # project.json：必须存在、可解析、版本严格等于 0.1.0
    if not os.path.isfile(project_json):
        problems.append(f"缺少安装版本标记 {PROJECT_FILE}")
    else:
        try:
            with open(project_json, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, json.JSONDecodeError) as exc:
            problems.append(f"{PROJECT_FILE} 无法读取: {exc}")
        else:
            if not isinstance(data, dict):
                problems.append(f"{PROJECT_FILE} 顶层必须是 JSON 对象")
            else:
                version = data.get("installer_version")
                if version != INSTALLER_VERSION:
                    problems.append(
                        f"安装版本标记是 {version!r}，当前产品只接受 {INSTALLER_VERSION!r}"
                    )
                if not isinstance(data.get("project_design_initialized", False), bool):
                    problems.append("project_design_initialized（项目设计已初始化）字段无效")
                if not isinstance(data.get("topic_history", []), list):
                    problems.append("topic_history（历史主题）字段无效")
                if not isinstance(data.get("test_entry", {}), (dict, str)):
                    problems.append("test_entry（项目全量测试入口）字段无效")
                if not isinstance(data.get("artifact_file_keys", {}), dict):
                    problems.append("artifact_file_keys（正式文件标识映射）字段无效")

    # 模板仓库和规范仓库：当前产品发布中的每一份必需材料都必须存在。
    # 允许项目增加其它文件，也允许在工作流内按规则修改正文，但不能缺文件。
    for dirname in (TEMPLATE_DIRNAME, STANDARDIZED_DIRNAME):
        dir_path = os.path.join(wf_dir, dirname)
        if not os.path.isdir(dir_path):
            problems.append(f"缺少 .workflow_loop/{dirname}/")
            continue
        required_files = _required_repository_files(dirname)
        if not required_files:
            problems.append(f"当前安装包没有携带 {dirname} 文件清单")
            continue
        for relative_path in required_files:
            full_path = os.path.join(dir_path, *relative_path.split("/"))
            if not os.path.isfile(full_path):
                problems.append(f"缺少 .workflow_loop/{dirname}/{relative_path}")

    # 最小代理契约：必须存在于项目根
    if not os.path.isfile(os.path.join(project_root, AGENTS_MD_FILENAME)):
        problems.append(f"缺少项目根 {AGENTS_MD_FILENAME}")

    if problems:
        return SkeletonStatus(state="broken", problems=problems)
    return SkeletonStatus(state="installed")


# 判断项目设计架构是否已初始化（PathComposer 用）
# true → product_change/bugfix 跳过 project_design_init stage
# false → 必须执行 project_design_init
# 不用架构文档是否存在决定跳过（CONTEXT.md "Project Design Init Skip"）
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
    """原子登记本次主题历史及对应的稳定正式文件标识。"""
    from . import artifact_paths as artifact_paths_mod

    project = load_project(project_root)
    if project is None:
        project = ProjectState(installed_at=_now_iso())

    duplicates = sorted(set(topics) & set(project.topic_history))
    if duplicates:
        raise ValueError(f"主题名称已经使用过: {duplicates}")

    artifact_paths_mod.register_file_keys(project, "topic", topics)
    project.topic_history.extend(topic for topic in topics if topic not in project.topic_history)
    save_project(project_root, project)


def register_test_entry(project_root: str, entry_config: dict) -> None:
    """更新项目全量测试入口配置；只应由入口登记命令在测试计划阶段调用。"""
    from . import test_entry as test_entry_mod

    normalized = test_entry_mod.normalized_entry_config(entry_config)
    project = load_project(project_root)
    if project is None:
        raise ValueError("项目尚未安装，不能登记测试入口")
    project.test_entry = normalized
    save_project(project_root, project)


# 判断项目是否已安装（安装事务和 start 命令用）
# 完整骨架 + 版本严格等于 0.1.0 才算已安装；残缺骨架不算
# 未安装时 start 命令报错，提示用户先跑官方安装脚本
def is_installed(project_root: str) -> bool:
    return check_skeleton(project_root).state == "installed"


# 创建项目级状态（installer.py 在安装事务中调用）
# 只写精简项目级字段；不创建正式产物目录，也不下发全量测试脚本
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
