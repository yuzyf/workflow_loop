#!/usr/bin/env bash
# workflow_loop 官方安装脚本（macOS / Linux）
# 职责：终端确认、无写入预检、固定版本 uv 下载校验、全局命令安装、PATH 处理，
# 以及通过一次性事务调用包内项目安装入口。项目文件写入全部由 Python 内部入口完成。
set -euo pipefail

# ─── 固定版本与固定资产（不可变发布，不使用 latest） ───
PRODUCT_NAME="workflow-loop"
PRODUCT_VERSION="0.3.7"
PRODUCT_IDENTITY="${PRODUCT_NAME} ${PRODUCT_VERSION}"
# 经过发布测试的安装工具版本；脚本内置各平台官方资产的 SHA-256 预期摘要
UV_VERSION="0.11.33"
UV_BASE_URL="https://github.com/astral-sh/uv/releases/download/${UV_VERSION}"
# 各平台资产的固定摘要（来自官方不可变发布；macOS ARM64 已在穿刺中实际校验）
SHA_DARWIN_ARM64="d75e3d2bfc203d17388edaabd3aa37958edbcbfc36219e3ee0d31bb080b4baa2"
SHA_DARWIN_X64="f1b919f740bd6be1d014ff58c4271b0779a32198adfb19ad9c5d1c4d9b2b4301"
SHA_LINUX_X64="aa9fca823c03289fb6e3460b3dc864f3ea895cafaf9b99247701a67b17d1b018"
SHA_LINUX_ARM64="9ed88a9a42de3102f9704d021ab186fdf8a69a7ad9a1d3f3486ac6b1e55d6141"

# ─── 基本路径 ───
PROJECT_ROOT="$(pwd)"
WF_DIR="${PROJECT_ROOT}/.workflow_loop"
AGENTS_MD="${PROJECT_ROOT}/AGENTS.md"

# 工具环境与命令目录：显式固定并导出，保证确认时披露的位置就是实际写入位置
UV_TOOL_BIN_DIR="${UV_TOOL_BIN_DIR:-${XDG_BIN_HOME:-$HOME/.local/bin}}"
UV_TOOL_DIR="${UV_TOOL_DIR:-${XDG_DATA_HOME:-$HOME/.local/share}/uv/tools}"
INSTALL_RECORD="${WORKFLOW_LOOP_INSTALL_RECORD:-${XDG_DATA_HOME:-$HOME/.local/share}/workflow-loop/install.json}"
export UV_TOOL_BIN_DIR UV_TOOL_DIR

# 临时目录（确认后才创建和使用；结束时删除）
TMP_DIR=""
# 本次是否新装了全局命令 / 修改了 Shell 配置（失败回滚范围）
INSTALLED_GLOBAL="no"
SHELL_CONFIG_BACKUP=""
SHELL_CONFIG_FILE=""
SHELL_CONFIG_ORIGIN=""
PATH_CONFIG_LINE=""
INSTALL_RECORD_BACKUP=""
INSTALL_RECORD_ORIGIN=""

cleanup() {
    if [ -n "${TMP_DIR}" ] && [ -d "${TMP_DIR}" ]; then
        rm -rf "${TMP_DIR}"
    fi
}
trap cleanup EXIT

fail() {
    echo "错误：$1" >&2
    exit 1
}

# 全局命令回滚：删除本次新装的工具环境和命令入口，恢复本次修改的 Shell 配置。
# 安装前已经存在的内容不删除。
rollback_global() {
    if [ "${INSTALLED_GLOBAL}" = "yes" ]; then
        echo "回滚本次新装的全局命令..."
        rm -rf "${UV_TOOL_DIR}/${PRODUCT_NAME}"
        rm -f "${UV_TOOL_BIN_DIR}/workflow"
    fi
    if [ "${SHELL_CONFIG_ORIGIN}" = "existing" ] && [ -f "${SHELL_CONFIG_BACKUP}" ]; then
        echo "恢复本次修改的终端配置 ${SHELL_CONFIG_FILE}..."
        cp "${SHELL_CONFIG_BACKUP}" "${SHELL_CONFIG_FILE}"
    elif [ "${SHELL_CONFIG_ORIGIN}" = "missing" ]; then
        echo "删除本次新建的终端配置 ${SHELL_CONFIG_FILE}..."
        rm -f "${SHELL_CONFIG_FILE}"
    fi
    if [ "${INSTALL_RECORD_ORIGIN}" = "existing" ] && [ -f "${INSTALL_RECORD_BACKUP}" ]; then
        mkdir -p "$(dirname "${INSTALL_RECORD}")"
        cp "${INSTALL_RECORD_BACKUP}" "${INSTALL_RECORD}"
    elif [ "${INSTALL_RECORD_ORIGIN}" = "missing" ]; then
        rm -f "${INSTALL_RECORD}"
        rmdir "$(dirname "${INSTALL_RECORD}")" 2>/dev/null || true
    fi
}

echo "═══ ${PRODUCT_NAME} ${PRODUCT_VERSION} 安装脚本 ═══"
echo ""

# ─────────────────────────────────────────────
# 无写入预检：以下检查不修改任何文件
# ─────────────────────────────────────────────

# 1. 兼容 Python：安装动作和项目写入前必须确认 Python 3.11+；没有时只说明，不代装
PYTHON_BIN=""
for candidate in python3 python; do
    if command -v "${candidate}" >/dev/null 2>&1; then
        if "${candidate}" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)' >/dev/null 2>&1; then
            PYTHON_BIN="$(command -v "${candidate}")"
            break
        fi
    fi
done
if [ -z "${PYTHON_BIN}" ]; then
    echo "错误：没有找到 Python 3.11 或更高版本。" >&2
    echo "workflow 命令需要兼容的 Python 运行。请先自行安装，例如：" >&2
    echo "  macOS:  brew install python@3.12" >&2
    echo "  Debian/Ubuntu:  sudo apt install python3.12" >&2
    echo "安装脚本不会自动替你安装 Python。本次未修改任何文件。" >&2
    exit 1
fi
PYTHON_VERSION="$("${PYTHON_BIN}" -c 'import sys; print("%d.%d.%d" % sys.version_info[:3])')"

# 2. 已有同名命令身份核对：只有兼容的 Workflow Loop 才能复用
EXISTING_WORKFLOW=""
GLOBAL_NEEDED="yes"
if command -v workflow >/dev/null 2>&1; then
    EXISTING_WORKFLOW="$(command -v workflow)"
    EXISTING_IDENTITY="$("${EXISTING_WORKFLOW}" --version 2>/dev/null || true)"
    if [ "${EXISTING_IDENTITY}" = "${PRODUCT_IDENTITY}" ]; then
        GLOBAL_NEEDED="no"
    else
        echo "错误：PATH 中已有名为 workflow 的其它命令，安装已停止。" >&2
        echo "  命令位置：${EXISTING_WORKFLOW}" >&2
        echo "  检测到的身份：${EXISTING_IDENTITY:-（无法取得版本输出）}" >&2
        echo "  本安装器只接受身份严格为 \"${PRODUCT_IDENTITY}\" 的命令。" >&2
        echo "处理方法：改名或移除该命令，或调整 PATH 后重新运行安装脚本。" >&2
        echo "本次未修改任何文件。" >&2
        exit 1
    fi
fi

# 3. 平台资产选择（全局命令需要安装时才用到）
UV_ASSET=""
UV_SHA=""
OS_NAME="$(uname -s)"
ARCH_NAME="$(uname -m)"
case "${OS_NAME}-${ARCH_NAME}" in
    Darwin-arm64)  UV_ASSET="uv-aarch64-apple-darwin.tar.gz";      UV_SHA="${SHA_DARWIN_ARM64}" ;;
    Darwin-x86_64) UV_ASSET="uv-x86_64-apple-darwin.tar.gz";       UV_SHA="${SHA_DARWIN_X64}" ;;
    Linux-x86_64)  UV_ASSET="uv-x86_64-unknown-linux-gnu.tar.gz";  UV_SHA="${SHA_LINUX_X64}" ;;
    Linux-aarch64) UV_ASSET="uv-aarch64-unknown-linux-gnu.tar.gz"; UV_SHA="${SHA_LINUX_ARM64}" ;;
    *)
        if [ "${GLOBAL_NEEDED}" = "yes" ]; then
            fail "暂不支持的平台组合：${OS_NAME} ${ARCH_NAME}。本次未修改任何文件。"
        fi
        ;;
esac

# 4. SHA-256 校验工具
SHA_CMD=""
if command -v sha256sum >/dev/null 2>&1; then
    SHA_CMD="sha256sum"
elif command -v shasum >/dev/null 2>&1; then
    SHA_CMD="shasum -a 256"
else
    [ "${GLOBAL_NEEDED}" = "yes" ] && fail "找不到 sha256sum 或 shasum，无法校验下载文件。本次未修改任何文件。"
fi

# 5. 已有兼容 uv 检测（版本完全相同才复用；不覆盖用户已有的其它 uv）
REUSE_UV=""
if command -v uv >/dev/null 2>&1; then
    if [ "$(uv --version 2>/dev/null | awk '{print $2}')" = "${UV_VERSION}" ]; then
        REUSE_UV="$(command -v uv)"
    fi
fi

# 6. PATH 与终端配置：确定写入前的实际持久修改位置
PATH_CHANGE_NEEDED="no"
case ":${PATH}:" in
    *":${UV_TOOL_BIN_DIR}:"*) ;;
    *) [ "${GLOBAL_NEEDED}" = "yes" ] && PATH_CHANGE_NEEDED="yes" ;;
esac
if [ "${PATH_CHANGE_NEEDED}" = "yes" ]; then
    case "${SHELL:-}" in
        */zsh)  SHELL_CONFIG_FILE="${HOME}/.zshrc" ;;
        */bash) SHELL_CONFIG_FILE="${HOME}/.bashrc" ;;
        */fish) SHELL_CONFIG_FILE="${HOME}/.config/fish/config.fish" ;;
        *)
            fail "无法确定你的 Shell 启动配置文件（SHELL=${SHELL:-未设置}），不能在写入前确定 PATH 修改位置。本次未修改任何文件。"
            ;;
    esac
fi

# ─────────────────────────────────────────────
# 完整写入范围披露 + 一次确认
# ─────────────────────────────────────────────
echo "当前项目根目录（安装器严格使用当前目录，不向上猜测）："
echo "  ${PROJECT_ROOT}"
echo ""
echo "本机 Python：${PYTHON_BIN}（${PYTHON_VERSION}）"
echo ""
echo "本次安装的检查与可能写入范围："
echo "  项目侧由安装包内的 Python 入口统一检查，不由 Shell 根据目录或文字猜测："
echo "    已完整安装 ${PRODUCT_VERSION}：项目文件零修改"
echo "    干净未安装：写入以下固定范围"
echo "      ${AGENTS_MD}（存在则整份覆盖，不合并；失败时由安装事务恢复）"
echo "      ${WF_DIR}/（写入模板仓库、规范仓库和安装版本标记）"
echo "      ${PROJECT_ROOT}/.workflow_loop_install_tx/（一次性安装事务目录，成功后删除）"
echo "    骨架残缺或版本异常：在写入项目文件前停止"
if [ "${GLOBAL_NEEDED}" = "yes" ]; then
    echo "  电脑侧："
    echo "    全局工具环境：${UV_TOOL_DIR}/${PRODUCT_NAME}/"
    echo "    workflow 可执行文件：${UV_TOOL_BIN_DIR}/workflow"
    if [ -n "${REUSE_UV}" ]; then
        echo "    安装工具：复用本机已有的 uv ${UV_VERSION}（${REUSE_UV}）"
    else
        echo "    安装工具：下载固定版本 uv ${UV_VERSION}（${UV_ASSET}）到本次临时目录，校验后使用，结束时删除"
    fi
    if [ "${PATH_CHANGE_NEEDED}" = "yes" ]; then
        echo "    PATH 修改：把 ${UV_TOOL_BIN_DIR} 加入 ${SHELL_CONFIG_FILE}"
    else
        echo "    PATH 修改：无需修改（命令目录已在 PATH 中）"
    fi
else
    echo "  电脑侧：全局命令无修改（已存在兼容的 ${PRODUCT_IDENTITY}）"
fi
echo ""
echo "临时下载目录只在确认后创建，安装结束时删除。"
echo ""

# 从当前终端读取确认；通过管道执行时不能读取承载脚本正文的标准输入
if [ ! -e /dev/tty ] || [ ! -r /dev/tty ]; then
    fail "无法取得交互终端（/dev/tty），不能读取安装确认。请在交互终端中运行安装命令。本次未修改任何文件。"
fi
printf "确认以上完整写入范围并开始安装？[y/N] "
read -r response < /dev/tty
case "${response}" in
    [yY][eE][sS]|[yY]) echo "确认通过，开始安装..." ;;
    *)
        echo "已取消。未下载任何内容，未修改任何文件。"
        exit 0
        ;;
esac
echo ""

# ─────────────────────────────────────────────
# 确认后：准备临时目录与安装工具
# ─────────────────────────────────────────────
TMP_DIR="$(mktemp -d "${TMPDIR:-/tmp}/workflow_loop_install.XXXXXX")"

UV_BIN=""
if [ "${GLOBAL_NEEDED}" = "yes" ]; then
    echo "─── 安装全局 workflow 命令 ───"
    if [ -n "${REUSE_UV}" ]; then
        UV_BIN="${REUSE_UV}"
        echo "复用本机已有的 uv ${UV_VERSION}。"
    else
        echo "下载 uv ${UV_VERSION}（${UV_ASSET}）..."
        curl -fsSL --proto '=https' -o "${TMP_DIR}/${UV_ASSET}" "${UV_BASE_URL}/${UV_ASSET}" \
            || fail "uv 下载失败。已删除临时内容，本次未修改任何文件。"
        echo "${UV_SHA}  ${UV_ASSET}" >"${TMP_DIR}/${UV_ASSET}.sha256"
        (cd "${TMP_DIR}" && ${SHA_CMD} -c "${UV_ASSET}.sha256" >/dev/null 2>&1) \
            || fail "uv 下载文件的 SHA-256 与脚本内置摘要不符。已删除临时内容，本次未修改任何文件。"
        tar -xzf "${TMP_DIR}/${UV_ASSET}" -C "${TMP_DIR}" \
            || fail "uv 解压失败。已删除临时内容，本次未修改任何文件。"
        UV_BIN="$(find "${TMP_DIR}" -type f -name uv | head -1)"
        [ -n "${UV_BIN}" ] || fail "解压后找不到 uv 可执行文件。已删除临时内容，本次未修改任何文件。"
        ACTUAL_UV_VERSION="$("${UV_BIN}" --version | awk '{print $2}')"
        [ "${ACTUAL_UV_VERSION}" = "${UV_VERSION}" ] \
            || fail "下载的 uv 版本是 ${ACTUAL_UV_VERSION}，期望 ${UV_VERSION}。已删除临时内容，本次未修改任何文件。"
    fi

    # 显式使用已检查的本机 Python；禁止 uv 托管或下载 Python
    echo "安装 ${PRODUCT_NAME}==${PRODUCT_VERSION}..."
    if ! "${UV_BIN}" tool install "${PRODUCT_NAME}==${PRODUCT_VERSION}" \
        --python "${PYTHON_BIN}" --no-managed-python --no-python-downloads; then
        rollback_global
        fail "全局命令安装失败。已删除临时内容，项目保持未修改。"
    fi
    INSTALLED_GLOBAL="yes"

    # 从实际命令目录复核身份；不要求用户重开终端
    ACTUAL_BIN_DIR="$("${UV_BIN}" tool dir --bin)"
    if [ "${ACTUAL_BIN_DIR}" != "${UV_TOOL_BIN_DIR}" ]; then
        rollback_global
        fail "实际命令目录 ${ACTUAL_BIN_DIR} 与确认时披露的 ${UV_TOOL_BIN_DIR} 不一致。已回滚，项目保持未修改。"
    fi
    WORKFLOW_BIN="${UV_TOOL_BIN_DIR}/workflow"
    INSTALLED_IDENTITY="$("${WORKFLOW_BIN}" --version 2>/dev/null || true)"
    if [ "${INSTALLED_IDENTITY}" != "${PRODUCT_IDENTITY}" ]; then
        rollback_global
        fail "安装后的身份复核失败：得到 \"${INSTALLED_IDENTITY}\"，期望 \"${PRODUCT_IDENTITY}\"。已回滚，项目保持未修改。"
    fi
    echo "全局命令已安装：${WORKFLOW_BIN}（${INSTALLED_IDENTITY}）"

    # PATH 处理：写入预检时已经确定的配置文件，不再让安装工具二次猜测 Shell。
    if [ "${PATH_CHANGE_NEEDED}" = "yes" ]; then
        if [ -f "${SHELL_CONFIG_FILE}" ]; then
            SHELL_CONFIG_BACKUP="${TMP_DIR}/shell_config.bak"
            cp "${SHELL_CONFIG_FILE}" "${SHELL_CONFIG_BACKUP}"
            SHELL_CONFIG_ORIGIN="existing"
        else
            SHELL_CONFIG_ORIGIN="missing"
        fi

        case "${SHELL_CONFIG_FILE}" in
            */config.fish)
                FISH_BIN_DIR="${UV_TOOL_BIN_DIR//\\/\\\\}"
                FISH_BIN_DIR="${FISH_BIN_DIR//\'/\\\'}"
                PATH_CONFIG_LINE="fish_add_path '${FISH_BIN_DIR}'"
                ;;
            *)
                printf -v QUOTED_BIN_DIR '%q' "${UV_TOOL_BIN_DIR}"
                PATH_CONFIG_LINE="export PATH=${QUOTED_BIN_DIR}:\"\$PATH\""
                ;;
        esac
        if ! printf '\n# workflow-loop %s\n%s\n' "${PRODUCT_VERSION}" "${PATH_CONFIG_LINE}" >>"${SHELL_CONFIG_FILE}"; then
            rollback_global
            fail "PATH 更新失败。已回滚本次全局安装，项目保持未修改。"
        fi
        echo "已把 ${UV_TOOL_BIN_DIR} 加入 ${SHELL_CONFIG_FILE}（对后续新终端生效）。"
    fi

    # 记录 PATH 来源。只有 path_added=true 且配置仍精确匹配时，全局卸载才删除该 PATH 项。
    if [ -e "${INSTALL_RECORD}" ]; then
        [ -f "${INSTALL_RECORD}" ] && [ ! -L "${INSTALL_RECORD}" ] \
            || { rollback_global; fail "安装来源记录不是可安全覆盖的普通文件：${INSTALL_RECORD}"; }
        INSTALL_RECORD_BACKUP="${TMP_DIR}/install_record.bak"
        cp "${INSTALL_RECORD}" "${INSTALL_RECORD_BACKUP}"
        INSTALL_RECORD_ORIGIN="existing"
    else
        INSTALL_RECORD_ORIGIN="missing"
    fi
    mkdir -p "$(dirname "${INSTALL_RECORD}")"
    export INSTALL_RECORD PRODUCT_NAME PRODUCT_VERSION UV_TOOL_DIR UV_TOOL_BIN_DIR
    export PATH_CHANGE_NEEDED SHELL_CONFIG_FILE PATH_CONFIG_LINE
    if ! "${PYTHON_BIN}" - <<'PY'
import json
import os
import tempfile
from datetime import datetime, timezone

path = os.environ["INSTALL_RECORD"]
data = {
    "product": os.environ["PRODUCT_NAME"],
    "version": os.environ["PRODUCT_VERSION"],
    "tool_dir": os.environ["UV_TOOL_DIR"],
    "tool_bin_dir": os.environ["UV_TOOL_BIN_DIR"],
    "path_added": os.environ["PATH_CHANGE_NEEDED"] == "yes",
    "path_scope": "shell_config",
    "path_config_file": os.environ.get("SHELL_CONFIG_FILE", ""),
    "path_marker_line": f"# workflow-loop {os.environ['PRODUCT_VERSION']}",
    "path_config_line": os.environ.get("PATH_CONFIG_LINE", ""),
    "recorded_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
}
directory = os.path.dirname(path)
fd, temporary = tempfile.mkstemp(prefix=".workflow-install-", dir=directory)
try:
    with os.fdopen(fd, "w", encoding="utf-8") as stream:
        json.dump(data, stream, ensure_ascii=False, indent=2)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)
finally:
    if os.path.exists(temporary):
        os.remove(temporary)
PY
    then
        rollback_global
        fail "安装来源记录写入失败；已回滚本次全局安装，项目保持未修改。"
    fi
else
    WORKFLOW_BIN="${EXISTING_WORKFLOW}"
    echo "─── 全局命令无修改 ───"
    echo "复用已有命令：${WORKFLOW_BIN}"
fi
echo ""

# ─────────────────────────────────────────────
# 项目检查与安装：始终由一次性事务调用包内 Python 权威入口。
# 重复安装时，该入口确认骨架完整后直接返回，项目文件保持零修改。
# ─────────────────────────────────────────────
echo "─── 检查并安装当前项目 ───"
TX_FILE="${TMP_DIR}/install_transaction.json"
cat >"${TX_FILE}" <<EOF
{
  "product": "${PRODUCT_NAME}",
  "version": "${PRODUCT_VERSION}",
  "project_root": "${PROJECT_ROOT}",
  "created_at": "$(date -u +%Y-%m-%dT%H:%M:%S+00:00)",
  "used": false,
  "allowed_paths": ["AGENTS.md", ".workflow_loop"]
}
EOF
if ! (cd "${PROJECT_ROOT}" && "${WORKFLOW_BIN}" _install-project --transaction "${TX_FILE}"); then
    rollback_global
    fail "项目检查或安装失败。本次电脑侧修改已回滚；项目侧由安装事务负责恢复。"
fi

echo ""
echo "═══ 安装完成 ═══"
echo "启动 Codex / OpenCode 并提出需求即可。"
echo "智能体会读取 AGENTS.md 并自动调用 workflow start。"
