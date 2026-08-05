#!/usr/bin/env bash
# Workflow Loop project/global uninstall entry for macOS and Linux.
set -euo pipefail

PRODUCT_NAME="workflow-loop"
PRODUCT_VERSION="0.1.0"
UV_VERSION="0.11.33"
UV_BASE_URL="https://github.com/astral-sh/uv/releases/download/${UV_VERSION}"
SHA_DARWIN_ARM64="d75e3d2bfc203d17388edaabd3aa37958edbcbfc36219e3ee0d31bb080b4baa2"
SHA_DARWIN_X64="f1b919f740bd6be1d014ff58c4271b0779a32198adfb19ad9c5d1c4d9b2b4301"
SHA_LINUX_X64="aa9fca823c03289fb6e3460b3dc864f3ea895cafaf9b99247701a67b17d1b018"
SHA_LINUX_ARM64="9ed88a9a42de3102f9704d021ab186fdf8a69a7ad9a1d3f3486ac6b1e55d6141"

MODE="project"
PROJECT_ROOT="$(pwd)"
CONFIRMED="no"
WAIT_FOR_PID=""
TMP_DIR=""

while [ "$#" -gt 0 ]; do
    case "$1" in
        --global) MODE="global"; shift ;;
        --project-root) PROJECT_ROOT="$2"; shift 2 ;;
        --confirmed) CONFIRMED="yes"; shift ;;
        --wait-for-pid) WAIT_FOR_PID="$2"; shift 2 ;;
        *) echo "错误：未知参数 $1" >&2; exit 2 ;;
    esac
done

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

PYTHON_BIN=""
for candidate in python3 python; do
    if command -v "${candidate}" >/dev/null 2>&1 \
        && "${candidate}" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)' >/dev/null 2>&1; then
        PYTHON_BIN="$(command -v "${candidate}")"
        break
    fi
done
[ -n "${PYTHON_BIN}" ] || fail "没有找到 Python 3.11 或更高版本；本次未修改任何内容。"

UV_TOOL_BIN_DIR="${UV_TOOL_BIN_DIR:-${XDG_BIN_HOME:-$HOME/.local/bin}}"
UV_TOOL_DIR="${UV_TOOL_DIR:-${XDG_DATA_HOME:-$HOME/.local/share}/uv/tools}"
INSTALL_RECORD="${WORKFLOW_LOOP_INSTALL_RECORD:-${XDG_DATA_HOME:-$HOME/.local/share}/workflow-loop/install.json}"
export UV_TOOL_BIN_DIR UV_TOOL_DIR
TMP_DIR="$(mktemp -d "${TMPDIR:-/tmp}/workflow_loop_uninstall.XXXXXX")"

UV_BIN=""
if command -v uv >/dev/null 2>&1 && [ "$(uv --version 2>/dev/null | awk '{print $2}')" = "${UV_VERSION}" ]; then
    UV_BIN="$(command -v uv)"
else
    case "$(uname -s)-$(uname -m)" in
        Darwin-arm64) UV_ASSET="uv-aarch64-apple-darwin.tar.gz"; UV_SHA="${SHA_DARWIN_ARM64}" ;;
        Darwin-x86_64) UV_ASSET="uv-x86_64-apple-darwin.tar.gz"; UV_SHA="${SHA_DARWIN_X64}" ;;
        Linux-x86_64) UV_ASSET="uv-x86_64-unknown-linux-gnu.tar.gz"; UV_SHA="${SHA_LINUX_X64}" ;;
        Linux-aarch64) UV_ASSET="uv-aarch64-unknown-linux-gnu.tar.gz"; UV_SHA="${SHA_LINUX_ARM64}" ;;
        *) fail "暂不支持的平台组合：$(uname -s) $(uname -m)。" ;;
    esac
    command -v curl >/dev/null 2>&1 || fail "找不到 curl，无法取得固定版本 uv。"
    curl -fsSL --proto '=https' -o "${TMP_DIR}/${UV_ASSET}" "${UV_BASE_URL}/${UV_ASSET}" \
        || fail "uv 下载失败。"
    if command -v sha256sum >/dev/null 2>&1; then
        echo "${UV_SHA}  ${TMP_DIR}/${UV_ASSET}" | sha256sum -c - >/dev/null
    elif command -v shasum >/dev/null 2>&1; then
        [ "$(shasum -a 256 "${TMP_DIR}/${UV_ASSET}" | awk '{print $1}')" = "${UV_SHA}" ]
    else
        fail "找不到 sha256sum 或 shasum，无法校验 uv。"
    fi
    tar -xzf "${TMP_DIR}/${UV_ASSET}" -C "${TMP_DIR}"
    UV_BIN="$(find "${TMP_DIR}" -type f -name uv | head -1)"
    [ -n "${UV_BIN}" ] || fail "解压后找不到 uv。"
    [ "$("${UV_BIN}" --version | awk '{print $2}')" = "${UV_VERSION}" ] \
        || fail "下载的 uv 版本不等于 ${UV_VERSION}。"
fi

if [ "${MODE}" = "project" ]; then
    [ "$(pwd -P)" = "$(cd "${PROJECT_ROOT}" 2>/dev/null && pwd -P)" ] \
        || fail "项目卸载必须从目标项目根目录执行，不会向父目录查找。"
    echo "─── 项目卸载预检 ───"
    (cd "${PROJECT_ROOT}" && "${UV_BIN}" tool run --isolated \
        --from "${PRODUCT_NAME}==${PRODUCT_VERSION}" --python "${PYTHON_BIN}" \
        --no-managed-python --no-python-downloads workflow _uninstall-project --check-only) \
        || fail "无法确认当前项目的固定卸载范围。"
    if [ "${CONFIRMED}" != "yes" ]; then
        echo "删除没有备份；当前轮次状态不会阻止卸载，业务代码和正式产物保持不变。"
        [ -r /dev/tty ] || fail "无法取得交互终端，不能读取项目卸载确认。"
        printf "确认强制卸载当前项目？[y/N] "
        read -r response < /dev/tty
        case "${response}" in
            [yY]|[yY][eE][sS]) ;;
            *) echo "已取消。当前项目未修改。"; exit 0 ;;
        esac
    fi
    (cd "${PROJECT_ROOT}" && "${UV_BIN}" tool run --isolated \
        --from "${PRODUCT_NAME}==${PRODUCT_VERSION}" --python "${PYTHON_BIN}" \
        --no-managed-python --no-python-downloads workflow _uninstall-project --confirmed) \
        || fail "项目卸载未完成；已删除内容不会恢复，解决残留后重新执行同一命令。"
    exit 0
fi

# Global mode deliberately does not inspect PROJECT_ROOT or any project directory.
WORKFLOW_BIN="${UV_TOOL_BIN_DIR}/workflow"
GLOBAL_IDENTITY=""
if [ -x "${WORKFLOW_BIN}" ]; then
    GLOBAL_IDENTITY="$("${WORKFLOW_BIN}" --version 2>/dev/null || true)"
    case "${GLOBAL_IDENTITY}" in
        "workflow-loop "*) ;;
        *) fail "${WORKFLOW_BIN} 不是可确认的 Workflow Loop 命令，已保留。" ;;
    esac
fi

if [ "${CONFIRMED}" != "yes" ]; then
    echo "═══ Workflow Loop 全局卸载确认 ═══"
    echo "全局命令: ${WORKFLOW_BIN}"
    echo "全局工具环境: ${UV_TOOL_DIR}/${PRODUCT_NAME}"
    echo "PATH 来源记录: ${INSTALL_RECORD}"
    echo "只删除来源记录能证明由 Workflow Loop 添加的 PATH 项；未知来源会保留并报告。"
    echo "不会查找、扫描、读取或删除任何项目；其它项目将暂时无法运行 workflow。"
    [ -r /dev/tty ] || fail "无法取得交互终端，不能读取全局卸载确认。"
    printf "确认只卸载电脑全局命令？[y/N] "
    read -r response < /dev/tty
    case "${response}" in
        [yY]|[yY][eE][sS]) ;;
        *) echo "已取消。电脑和项目内容均未修改。"; exit 0 ;;
    esac
fi

if [ -n "${WAIT_FOR_PID}" ]; then
    while kill -0 "${WAIT_FOR_PID}" >/dev/null 2>&1; do sleep 0.2; done
fi

if [ -x "${WORKFLOW_BIN}" ] || [ -d "${UV_TOOL_DIR}/${PRODUCT_NAME}" ]; then
    "${UV_BIN}" tool uninstall "${PRODUCT_NAME}" \
        || fail "全局工具删除失败；已完成内容不恢复，可以重新执行同一命令。"
fi

PATH_RESULT="来源记录不存在；PATH 保留"
if [ -f "${INSTALL_RECORD}" ]; then
    set +e
    PATH_RESULT="$("${PYTHON_BIN}" - "${INSTALL_RECORD}" <<'PY'
import json
import os
import sys
import tempfile

record_path = sys.argv[1]
try:
    with open(record_path, encoding="utf-8") as stream:
        record = json.load(stream)
except (OSError, ValueError) as exc:
    print(f"来源记录无法读取；PATH 保留: {exc}")
    raise SystemExit(0)

if record.get("product") != "workflow-loop" or record.get("path_added") is not True:
    print("来源记录未证明 PATH 由 Workflow Loop 添加；PATH 保留")
    raise SystemExit(0)
config = record.get("path_config_file")
marker = record.get("path_marker_line")
path_line = record.get("path_config_line")
if not all(isinstance(value, str) and value for value in (config, marker, path_line)):
    print("来源记录不完整；PATH 保留")
    raise SystemExit(0)
try:
    with open(config, encoding="utf-8") as stream:
        lines = stream.read().splitlines(keepends=True)
except FileNotFoundError:
    print(f"终端配置已经不存在，无需删除 PATH: {config}")
    raise SystemExit(0)
except OSError as exc:
    print(f"终端配置暂时无法读取，来源记录已保留以便重试: {exc}")
    raise SystemExit(2)

matches = [index for index in range(len(lines) - 1) if lines[index].rstrip("\r\n") == marker and lines[index + 1].rstrip("\r\n") == path_line]
if len(matches) != 1:
    print("终端配置与来源记录不再精确匹配；PATH 保留")
    raise SystemExit(0)
start = matches[0]
if start > 0 and lines[start - 1].strip() == "":
    start -= 1
del lines[start:matches[0] + 2]
directory = os.path.dirname(config) or "."
fd, temporary = tempfile.mkstemp(prefix=".workflow-path-", dir=directory)
try:
    with os.fdopen(fd, "w", encoding="utf-8") as stream:
        stream.writelines(lines)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, config)
except OSError as exc:
    print(f"终端配置修改失败，来源记录已保留以便重试: {exc}")
    raise SystemExit(2)
finally:
    if os.path.exists(temporary):
        os.remove(temporary)
print(f"已删除 Workflow Loop 写入的 PATH 配置: {config}")
PY
)"
    PATH_EXIT=$?
    set -e
    if [ "${PATH_EXIT}" -ne 0 ]; then
        fail "全局命令已删除，但 PATH 清理未完成。${PATH_RESULT}"
    fi
    rm -f "${INSTALL_RECORD}" || fail "全局命令已删除，但来源记录清理失败：${INSTALL_RECORD}"
    rmdir "$(dirname "${INSTALL_RECORD}")" 2>/dev/null || true
fi

echo "${PATH_RESULT}"
echo "═══ 电脑全局 Workflow Loop 命令卸载完成 ═══"
echo "没有扫描或修改任何项目目录。"
