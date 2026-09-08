#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON_BIN="${PYTHON_BIN:-$ROOT_DIR/.venv/bin/python}"

if [[ ! -x "$PYTHON_BIN" ]]; then
  echo "错误：找不到项目测试解释器：$PYTHON_BIN" >&2
  echo "请先创建项目虚拟环境并安装开发依赖，或通过 PYTHON_BIN 指定 Python。" >&2
  exit 2
fi

cd "$ROOT_DIR"
exec "$PYTHON_BIN" -m pytest -q "$@"
