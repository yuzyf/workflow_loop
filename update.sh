#!/usr/bin/env bash
# Workflow Loop update entry for macOS and Linux.
set -euo pipefail

PRODUCT_NAME="workflow-loop"
SCRIPT_VERSION="0.3.6"
UV_VERSION="0.11.33"
UV_BASE_URL="https://github.com/astral-sh/uv/releases/download/${UV_VERSION}"
SHA_DARWIN_ARM64="d75e3d2bfc203d17388edaabd3aa37958edbcbfc36219e3ee0d31bb080b4baa2"
SHA_DARWIN_X64="f1b919f740bd6be1d014ff58c4271b0779a32198adfb19ad9c5d1c4d9b2b4301"
SHA_LINUX_X64="aa9fca823c03289fb6e3460b3dc864f3ea895cafaf9b99247701a67b17d1b018"
SHA_LINUX_ARM64="9ed88a9a42de3102f9704d021ab186fdf8a69a7ad9a1d3f3486ac6b1e55d6141"
PYPI_JSON_URL="${WORKFLOW_LOOP_PYPI_JSON_URL:-https://pypi.org/pypi/workflow-loop/json}"
GITHUB_API_URL="${WORKFLOW_LOOP_GITHUB_API_URL:-https://api.github.com/repos/yuzyf/workflow_loop}"

PROJECT_ROOT="$(pwd)"
REQUESTED_VERSION=""
EXPECTED_PROJECT_VERSION=""
CONFIRMED="no"
TMP_DIR=""

while [ "$#" -gt 0 ]; do
    case "$1" in
        --project-root) PROJECT_ROOT="$2"; shift 2 ;;
        --version) REQUESTED_VERSION="$2"; shift 2 ;;
        --expected-project-version) EXPECTED_PROJECT_VERSION="$2"; shift 2 ;;
        --confirmed) CONFIRMED="yes"; shift ;;
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

[ "$(pwd -P)" = "$(cd "${PROJECT_ROOT}" 2>/dev/null && pwd -P)" ] \
    || fail "更新脚本必须从目标项目根目录执行，不会向父目录查找。"
[ -d "${PROJECT_ROOT}/.workflow_loop" ] \
    || fail "当前目录缺少 .workflow_loop/，不是已安装项目根目录。"

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
export UV_TOOL_BIN_DIR UV_TOOL_DIR
TMP_DIR="$(mktemp -d "${TMPDIR:-/tmp}/workflow_loop_update.XXXXXX")"

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

export REQUESTED_VERSION PYPI_JSON_URL GITHUB_API_URL
TARGET_VERSION="$("${UV_BIN}" run --no-project --with 'packaging>=24.0' \
    --python "${PYTHON_BIN}" --no-managed-python --no-python-downloads python - <<'PY'
import json
import os
import urllib.request
from packaging.version import Version, InvalidVersion

def load(url):
    req = urllib.request.Request(url, headers={"Accept": "application/json", "User-Agent": "workflow-loop-maintenance"})
    with urllib.request.urlopen(req, timeout=30) as response:
        value = json.loads(response.read().decode("utf-8"))
    if not isinstance(value, dict):
        raise SystemExit(f"元数据顶层不是对象: {url}")
    return value

requested = os.environ.get("REQUESTED_VERSION", "").strip()
pypi = load(os.environ["PYPI_JSON_URL"])
raw = requested or pypi.get("info", {}).get("version", "")
try:
    target = Version(raw)
except InvalidVersion:
    raise SystemExit(f"目标版本无效: {raw!r}")
if target.is_prerelease or target.is_devrelease or target.local is not None:
    raise SystemExit(f"目标版本不是正式版本: {target}")
files = pypi.get("releases", {}).get(str(target), [])
if not files or not any(not item.get("yanked", False) for item in files if isinstance(item, dict)):
    raise SystemExit(f"PyPI 没有可用的正式版本 {target}")
suffix = f"releases/tags/v{target}" if requested else "releases/latest"
github = load(os.environ["GITHUB_API_URL"].rstrip("/") + "/" + suffix)
if github.get("draft") or github.get("prerelease") or github.get("tag_name") != f"v{target}":
    raise SystemExit(f"PyPI {target} 与 GitHub Release {github.get('tag_name')!r} 不一致")
print(target)
PY
)" || fail "无法确认目标正式版本；本次未修改任何内容。"

CURRENT_PROJECT_VERSION="$("${PYTHON_BIN}" - "${PROJECT_ROOT}/.workflow_loop/project.json" <<'PY'
import json, sys
with open(sys.argv[1], encoding="utf-8") as stream:
    value = json.load(stream)
print(value.get("installer_version", ""))
PY
)" || fail "无法读取项目安装版本。"
if [ -n "${EXPECTED_PROJECT_VERSION}" ] && [ "${CURRENT_PROJECT_VERSION}" != "${EXPECTED_PROJECT_VERSION}" ]; then
    fail "项目版本在确认后发生变化：确认时是 ${EXPECTED_PROJECT_VERSION}，现在是 ${CURRENT_PROJECT_VERSION}。"
fi

echo "─── 项目更新预检 ───"
(cd "${PROJECT_ROOT}" && "${UV_BIN}" tool run --isolated \
    --from "${PRODUCT_NAME}==${TARGET_VERSION}" --python "${PYTHON_BIN}" \
    --no-managed-python --no-python-downloads workflow _update-project --check-only) \
    || fail "目标版本拒绝更新当前项目；项目和全局命令均未修改。"

EXISTING_WORKFLOW=""
EXISTING_GLOBAL_VERSION="未安装"
if command -v workflow >/dev/null 2>&1; then
    EXISTING_WORKFLOW="$(command -v workflow)"
elif [ -x "${UV_TOOL_BIN_DIR}/workflow" ]; then
    EXISTING_WORKFLOW="${UV_TOOL_BIN_DIR}/workflow"
fi
if [ -n "${EXISTING_WORKFLOW}" ]; then
    EXISTING_IDENTITY="$("${EXISTING_WORKFLOW}" --version 2>/dev/null || true)"
    case "${EXISTING_IDENTITY}" in
        "workflow-loop "*) EXISTING_GLOBAL_VERSION="${EXISTING_IDENTITY#workflow-loop }" ;;
        *) fail "PATH 中的 workflow 不是 Workflow Loop：${EXISTING_WORKFLOW}。" ;;
    esac
fi
if [ "${EXISTING_GLOBAL_VERSION}" != "未安装" ]; then
    export EXISTING_GLOBAL_VERSION TARGET_VERSION
    "${UV_BIN}" run --no-project --with 'packaging>=24.0' \
        --python "${PYTHON_BIN}" --no-managed-python --no-python-downloads python - <<'PY' \
        || fail "目标版本低于电脑全局命令版本，Workflow Loop 不允许降级。"
import os
from packaging.version import Version
raise SystemExit(0 if Version(os.environ["TARGET_VERSION"]) >= Version(os.environ["EXISTING_GLOBAL_VERSION"]) else 1)
PY
fi

if [ "${CONFIRMED}" != "yes" ]; then
    echo ""
    echo "═══ Workflow Loop 更新确认 ═══"
    echo "项目根目录: $(cd "${PROJECT_ROOT}" && pwd -P)"
    echo "电脑全局命令版本: ${EXISTING_GLOBAL_VERSION}"
    echo "当前项目版本: ${CURRENT_PROJECT_VERSION}"
    echo "目标正式版本: ${TARGET_VERSION}"
    echo "直接覆盖 AGENTS.md、两套静态仓库和 project.json 的安装版本字段；不备份。"
    echo "保留当前轮次、历史、回退资料、业务代码和正式产物。"
    [ -r /dev/tty ] || fail "无法取得交互终端，不能读取更新确认。"
    printf "确认以上范围并开始更新？[y/N] "
    read -r response < /dev/tty
    case "${response}" in
        [yY]|[yY][eE][sS]) ;;
        *) echo "已取消。项目和电脑全局命令均未修改。"; exit 0 ;;
    esac
fi

if [ "${EXISTING_GLOBAL_VERSION}" != "${TARGET_VERSION}" ]; then
    echo "更新电脑全局命令到 ${TARGET_VERSION}..."
    "${UV_BIN}" tool install --force "${PRODUCT_NAME}==${TARGET_VERSION}" \
        --python "${PYTHON_BIN}" --no-managed-python --no-python-downloads \
        || fail "全局命令更新失败；项目尚未更新，可以重新执行同一命令。"
fi

WORKFLOW_BIN="${UV_TOOL_BIN_DIR}/workflow"
[ -x "${WORKFLOW_BIN}" ] || fail "更新后找不到 ${WORKFLOW_BIN}；项目尚未更新。"
ACTUAL_IDENTITY="$("${WORKFLOW_BIN}" --version 2>/dev/null || true)"
[ "${ACTUAL_IDENTITY}" = "workflow-loop ${TARGET_VERSION}" ] \
    || fail "全局命令复核失败：得到 ${ACTUAL_IDENTITY:-空输出}。"

echo "更新当前项目到 ${TARGET_VERSION}..."
(cd "${PROJECT_ROOT}" && "${WORKFLOW_BIN}" _update-project --confirmed \
    --expected-project-version "${CURRENT_PROJECT_VERSION}") \
    || fail "项目更新未完成；全局命令保留实际结果，可以重新执行同一命令。"

FINAL_PROJECT_VERSION="$("${PYTHON_BIN}" - "${PROJECT_ROOT}/.workflow_loop/project.json" <<'PY'
import json, sys
with open(sys.argv[1], encoding="utf-8") as stream:
    print(json.load(stream).get("installer_version", ""))
PY
)"
echo "═══ 更新完成 ═══"
echo "电脑全局命令版本: ${TARGET_VERSION}"
echo "当前项目版本: ${FINAL_PROJECT_VERSION}"
