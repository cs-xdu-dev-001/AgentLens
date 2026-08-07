#!/usr/bin/env sh
set -eu

PACKAGE_SPEC="${KNOWFLOW_CLI_SPEC:-git+https://github.com/cs-xdu-dev-001/KnowFlow-AI.git#subdirectory=backend}"

fail() {
  printf 'KnowFlow CLI安装失败：%s\n' "$1" >&2
  exit 1
}

if [ "$(uname -s 2>/dev/null || true)" != "Linux" ]; then
  fail "当前安装器仅支持Linux。"
fi

PYTHON=""
for candidate in python3.13 python3.12 python3.11 python3.10 python3; do
  if command -v "$candidate" >/dev/null 2>&1; then
    if "$candidate" -c 'import sys; raise SystemExit(sys.version_info < (3, 10))' >/dev/null 2>&1; then
      PYTHON="$candidate"
      break
    fi
  fi
done
[ -n "$PYTHON" ] || fail "需要Python 3.10或更高版本。"

if command -v pipx >/dev/null 2>&1; then
  PIPX_EXECUTABLE="$(command -v pipx)"
  PIPX_AS_MODULE=0
elif "$PYTHON" -m pipx --version >/dev/null 2>&1; then
  PIPX_EXECUTABLE=""
  PIPX_AS_MODULE=1
else
  BOOTSTRAP_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/knowflow-ai/pipx"
  if ! "$PYTHON" -m venv "$BOOTSTRAP_DIR"; then
    rm -rf "$BOOTSTRAP_DIR"
    fail "无法创建隔离环境。Ubuntu/Debian请先安装python3-venv，再重新运行安装命令。"
  fi
  "$BOOTSTRAP_DIR/bin/python" -m pip install --disable-pip-version-check --quiet "pipx==1.16.1" \
    || fail "无法安装pipx。"
  PIPX_EXECUTABLE="$BOOTSTRAP_DIR/bin/pipx"
  PIPX_AS_MODULE=0
fi

run_pipx() {
  if [ "$PIPX_AS_MODULE" -eq 1 ]; then
    "$PYTHON" -m pipx "$@"
  else
    "$PIPX_EXECUTABLE" "$@"
  fi
}

case "$PACKAGE_SPEC" in
  git+*)
    command -v git >/dev/null 2>&1 || fail "GitHub版本安装需要git。"
    ;;
esac

printf '正在安装KnowFlow CLI...\n'
run_pipx install --force "$PACKAGE_SPEC" || fail "pipx安装失败。"
run_pipx ensurepath >/dev/null 2>&1 || true

BIN_DIR="${PIPX_BIN_DIR:-$HOME/.local/bin}"
if [ -x "$BIN_DIR/knowflow" ]; then
  "$BIN_DIR/knowflow" --help >/dev/null || fail "CLI安装后自检失败。"
elif command -v knowflow >/dev/null 2>&1; then
  knowflow --help >/dev/null || fail "CLI安装后自检失败。"
else
  fail "CLI已安装，但未找到knowflow命令。"
fi

printf '\nKnowFlow CLI安装完成。重新打开终端后运行：\n'
printf '  knowflow configure\n'
printf '  knowflow doctor --cli\n'
printf '  knowflow chat\n'
printf '\n连接已有KnowFlow服务器（可选）：\n'
printf '  knowflow auth login https://你的KnowFlow服务器\n'
printf '  knowflow chat --remote\n'
