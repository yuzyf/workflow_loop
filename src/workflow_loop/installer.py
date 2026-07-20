import os
import shutil
import sys

# importlib.resources 用于访问包内打包的数据文件（Template_Repository 等）
# Python 3.9+ 自带 importlib.resources.files；旧版本需要 importlib_resources 后备包
try:
    from importlib.resources import files as resource_files
except ImportError:
    from importlib_resources import files as resource_files

from .project import load_project, create_project, INSTALLER_VERSION, ProjectState

# AGENTS.md 的固定内容（薄契约）
# 唯一薄契约文件名，告诉 AI "调 workflow start，跟着 stdout 走"
# 安装时直接整份覆盖，不询问、不合并、不备份（CONTEXT.md "Agent Contract File"）
AGENTS_MD_CONTENT = """# Agent 契约

本项目由 workflow_loop 管理。用户提出需求后，调 `workflow start`，
之后严格按每条命令 stdout 打印的"下一步"执行。
"""

# .workflow_loop 目录名
WORKFLOW_LOOP_DIRNAME = ".workflow_loop"
# Template_Repository 目录名（提示词模板仓库）
TEMPLATE_DIRNAME = "Template_Repository"
# Standardized_Repository 目录名（规范词仓库）
STANDARDIZED_DIRNAME = "Standardized_Repository"


# 递归复制包内资源树到目标文件系统路径
# importlib.resources 的 Traversable 对象不能直接用 shutil.copytree
# 所以手动递归遍历，遇到目录就递归，遇到文件就复制
def _copy_resource_tree(src_root, dst_root: str) -> None:
    # 确保目标目录存在
    os.makedirs(dst_root, exist_ok=True)
    # 遍历源目录下的每个子项
    for child in src_root.iterdir():
        # 拼出目标路径
        dst_path = os.path.join(dst_root, child.name)
        # 子项是目录 → 递归复制
        if child.is_dir():
            _copy_resource_tree(child, dst_path)
        # 子项是文件 → 复制文件内容
        else:
            # 打开包内资源文件（二进制）
            with child.open("rb") as src_f:
                # 写到目标路径
                with open(dst_path, "wb") as dst_f:
                    shutil.copyfileobj(src_f, dst_f)


# 写 AGENTS.md 到项目根（整份覆盖）
# 存在则覆盖，不存在则新建；不询问、不合并、不备份
def _write_agents_md(project_root: str) -> None:
    # 拼出 AGENTS.md 的完整路径
    path = os.path.join(project_root, "AGENTS.md")
    # 写薄契约内容
    with open(path, "w", encoding="utf-8") as f:
        f.write(AGENTS_MD_CONTENT)


# 安装当前项目（由 install.sh 调用，非日常命令）
# 创建 .workflow_loop/ 骨架：复制 Template/Standardized、写 AGENTS.md、写 project.json
# 重复安装保护：已安装则直接退出，零修改
def install_project(project_root: str) -> int:
    # 检查是否已安装（project.json 存在且 installer_version 匹配）
    existing = load_project(project_root)
    # 已安装 → 按 Repeat Installation 直接退出，不覆盖任何文件
    if existing is not None and existing.installer_version == INSTALLER_VERSION:
        print("当前项目已经安装，未修改任何文件。")
        print("启动 Codex/OpenCode 并提出需求即可。")
        return 0

    # 拼出 .workflow_loop 目录路径
    wf_dir = os.path.join(project_root, WORKFLOW_LOOP_DIRNAME)
    # 创建 .workflow_loop/（exist_ok=True 避免已存在时报错）
    os.makedirs(wf_dir, exist_ok=True)

    # 定位包内 data/ 目录（importlib.resources）
    pkg_root = resource_files("workflow_loop")
    data_root = pkg_root.joinpath("data")

    # 包内 Template_Repository 和 Standardized_Repository 的源路径
    template_src = data_root.joinpath(TEMPLATE_DIRNAME)
    standardized_src = data_root.joinpath(STANDARDIZED_DIRNAME)

    # 目标路径（.workflow_loop/Template_Repository 和 .workflow_loop/Standardized_Repository）
    template_dst = os.path.join(wf_dir, TEMPLATE_DIRNAME)
    standardized_dst = os.path.join(wf_dir, STANDARDIZED_DIRNAME)

    # 如果目标已存在（旧版本安装），先删掉再复制新的
    if os.path.exists(template_dst):
        shutil.rmtree(template_dst)
    if os.path.exists(standardized_dst):
        shutil.rmtree(standardized_dst)

    # 从包内资源复制到项目 .workflow_loop/
    _copy_resource_tree(template_src, template_dst)
    _copy_resource_tree(standardized_src, standardized_dst)

    # 写薄契约 AGENTS.md（覆盖已有）
    _write_agents_md(project_root)

    # 创建 project.json（installer_version + installed_at + project_design_initialized=false）
    create_project(project_root)

    # 打印安装完成信息
    print("项目安装完成。")
    print(f"  .workflow_loop/{TEMPLATE_DIRNAME}/")
    print(f"  .workflow_loop/{STANDARDIZED_DIRNAME}/")
    print(f"  AGENTS.md")
    print(f"  .workflow_loop/project.json")
    print("启动 Codex/OpenCode 并提出需求即可。")
    return 0
