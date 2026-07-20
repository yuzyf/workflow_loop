#!/usr/bin/env bash
# 启用严格模式：命令失败即退出（-e）、未定义变量报错（-u）、管道任一环节失败即失败（-o pipefail）
set -euo pipefail

# 记录当前工作目录作为项目根目录，后续所有路径都基于此变量派生
PROJECT_ROOT="$(pwd)"
# 拼接出 workflow_loop 的运行骨架目录绝对路径，用于存放状态机和会话数据
WF_DIR="${PROJECT_ROOT}/.workflow_loop"
# 拼接出 AGENTS.md 的绝对路径，这是智能体读取的契约文件
AGENTS_MD="${PROJECT_ROOT}/AGENTS.md"

# 打印安装脚本标题横幅，让用户清楚知道当前运行的是哪个安装器
echo "═══ workflow_loop 安装脚本 ═══"
# 打印空行作为视觉分隔，提升可读性
echo ""
# 提示即将输出项目根目录信息
echo "当前项目根目录："
# 打印实际的项目根目录绝对路径，供用户核对是否在正确目录运行
echo "  ${PROJECT_ROOT}"
# 打印空行作为视觉分隔
echo ""
# 提示即将列出会被检查或修改的文件清单
echo "将检查或修改的文件："
# 说明 AGENTS.md 的处理策略：存在则整份覆盖，不做合并不做备份，避免用户误以为旧内容会保留
echo "  ${AGENTS_MD}（存在则整份覆盖，不合并不备份）"
# 说明 .workflow_loop/ 目录的用途：创建运行骨架，承载状态机和会话数据
echo "  ${WF_DIR}/（创建运行骨架）"
# 打印空行作为视觉分隔
echo ""

# 读取用户输入以确认当前目录确实是项目根目录，-r 防止反斜杠转义，-p 直接输出提示语
read -r -p "确认当前目录是项目根目录？[y/N] " response
# 根据用户响应进入不同分支，决定继续安装还是中止
case "$response" in
    # 匹配 yes/y（大小写不敏感），表示用户确认目录正确
    [yY][eE][sS]|[yY])
        # 确认通过，告知用户即将继续后续安装步骤
        echo "目录确认通过，继续安装..."
        # 结束 case 的确认分支
        ;;
    # 匹配其他任意输入，视为用户取消安装
    *)
        # 告知用户已取消，且未修改任何文件，避免用户担心副作用
        echo "已取消。未修改任何文件。"
        # 以成功状态码退出脚本，因为取消是用户主动行为而非错误
        exit 0
        # 结束 case 的取消分支
        ;;
# 结束 case 语句
esac

# 打印空行作为视觉分隔
echo ""
# 打印阶段分隔横幅，进入"检查全局 workflow 命令"阶段
echo "─── 检查全局 workflow 命令 ───"
# 检测 workflow 命令是否已在 PATH 中可用，输出重定向到 /dev/null 并屏蔽错误，仅用于判断存在性
if command -v workflow >/dev/null 2>&1; then
    # 告知用户 workflow 全局命令已存在，将直接复用，避免重复安装
    echo "workflow 全局命令已存在，复用。"
    # 将 workflow 命令名赋值给变量，后续统一通过变量调用，便于维护
    WORKFLOW_CMD="workflow"
# 进入 else 分支：workflow 命令不存在，需要安装
else
    # 告知用户 workflow 全局命令不存在，即将开始安装流程
    echo "workflow 全局命令不存在，开始安装..."
    # 优先检测 pipx 是否可用，pipx 是 Python CLI 工具的推荐安装方式，能隔离依赖避免污染系统环境
    if command -v pipx >/dev/null 2>&1; then
        # 告知用户选择 pipx 作为安装工具
        echo "使用 pipx 安装..."
        # 通过 pipx 安装 workflow-loop 包，pipx 会将其放入隔离虚拟环境并暴露 workflow 命令到 PATH
        pipx install workflow-loop
    # 若 pipx 不可用，退而检测 uv 是否可用，uv 是更快的 Python 工具链管理器
    elif command -v uv >/dev/null 2>&1; then
        # 告知用户选择 uv 作为安装工具
        echo "使用 uv tool 安装..."
        # 通过 uv tool 安装 workflow-loop 包，uv 会将其放入隔离环境并暴露 workflow 命令
        uv tool install workflow-loop
    # pipx 和 uv 都不可用，无法继续安装
    else
        # 打印错误信息：找不到任一可用的安装工具，需要用户先安装前置依赖
        echo "错误：找不到 pipx 或 uv，请先安装 pipx（推荐）或 uv。"
        # 给出安装 pipx 的具体命令，方便用户直接复制执行
        echo "  安装 pipx: python3 -m pip install --user pipx && python3 -m pipx ensurepath"
        # 给出安装 uv 的具体命令，作为 pipx 的替代方案
        echo "  安装 uv:   curl -LsSf https://astral.sh/uv/install.sh | sh"
        # 以失败状态码退出，因为缺少前置依赖无法继续
        exit 1
    # 结束安装工具选择 if
    fi
    # 安装完成后将 workflow 命令名赋值给变量，统一后续调用入口
    WORKFLOW_CMD="workflow"
    # 再次检测 workflow 命令是否真正可用，因为某些情况下安装后 PATH 尚未刷新
    if ! command -v workflow >/dev/null 2>&1; then
        # 警告用户：安装已完成但命令不在 PATH 中，需要重新加载 shell 或手动添加 PATH
        echo "警告：安装完成但 workflow 命令不在 PATH 中。请重新打开终端或手动添加 PATH。"
        # 提示 pipx ensurepath 可能需要重新加载 shell 才能生效，帮助用户排查
        echo "  pipx ensurepath 可能需要重新加载 shell。"
        # 以失败状态码退出，因为命令不可用则后续步骤无法执行
        exit 1
    # 结束 PATH 检查 if
    fi
# 结束 workflow 命令存在性检查 if
fi

# 打印空行作为视觉分隔
echo ""
# 打印阶段分隔横幅，进入"安装当前项目"阶段
echo "─── 安装当前项目 ───"
# 调用 workflow install-project 在当前项目下创建 .workflow_loop/ 运行骨架并写入 AGENTS.md 契约
"${WORKFLOW_CMD}" install-project

# 打印空行作为视觉分隔
echo ""
# 打印安装完成横幅，告知用户整个安装流程已结束
echo "═══ 安装完成 ═══"
# 提示用户下一步：启动 Codex 或 OpenCode 智能体并提出需求即可开始使用
echo "启动 Codex / OpenCode 并提出需求即可。"
# 说明智能体的工作原理：读取 AGENTS.md 契约后自动调用 workflow start 进入工作流循环
echo "智能体会读取 AGENTS.md 并自动调用 workflow start。"
