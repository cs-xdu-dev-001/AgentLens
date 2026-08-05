#!/usr/bin/env bash
set -Eeuo pipefail

TARGET_REF="${1:-}"
APP_DIR="${KNOWFLOW_DEPLOY_DIR:-/opt/knowflow-ai/app}"
REPOSITORY="${KNOWFLOW_GITHUB_REPOSITORY:-cs-xdu-dev-001/KnowFlow-AI}"
SERVICE="${KNOWFLOW_SYSTEMD_SERVICE:-knowflow-ai.service}"
VENV_DIR="${KNOWFLOW_VENV_DIR:-/opt/knowflow-ai/venv}"
HEALTH_URL="${KNOWFLOW_HEALTH_URL:-http://127.0.0.1:8010/api/health}"

fail() {
  printf 'fast-deploy: %s\n' "$*" >&2
  exit 1
}

require_command() {
  command -v "$1" >/dev/null 2>&1 || fail "required command is unavailable: $1"
}

[[ -n "${TARGET_REF}" ]] || fail "usage: fast-deploy.sh <commit>"
[[ "${TARGET_REF}" =~ ^[0-9a-fA-F]{40}$ ]] \
  || fail "target must be a full 40-character commit SHA"
[[ "${EUID}" -eq 0 ]] || fail "run this script through sudo"

for command in git python3 npm curl systemctl sha256sum; do
  require_command "${command}"
done

[[ -x "${VENV_DIR}/bin/python" ]] || fail "KnowFlow virtual environment is unavailable"
[[ -d "${APP_DIR}/.git" ]] || fail "deployment directory is not a Git worktree: ${APP_DIR}"

cd "${APP_DIR}"
[[ -z "$(git status --porcelain --untracked-files=all)" ]] \
  || fail "worktree is not clean; refusing to deploy"

git fetch origin main
TARGET_SHA="$(git rev-parse --verify --end-of-options "${TARGET_REF}^{commit}")"
ORIGIN_MAIN="$(git rev-parse --verify 'origin/main^{commit}')"
git merge-base --is-ancestor "${TARGET_SHA}" "${ORIGIN_MAIN}" \
  || fail "target commit is not part of origin/main"

python3 - "${REPOSITORY}" "${TARGET_SHA}" <<'PY'
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request

repository, commit = sys.argv[1:]
query = urllib.parse.urlencode({"head_sha": commit, "event": "push", "per_page": 10})
request = urllib.request.Request(
    f"https://api.github.com/repos/{repository}/actions/runs?{query}",
    headers={
        "Accept": "application/vnd.github+json",
        "User-Agent": "KnowFlow-fast-deploy",
        "X-GitHub-Api-Version": "2022-11-28",
    },
)
token = os.getenv("GITHUB_TOKEN", "").strip()
if token:
    request.add_header("Authorization", f"Bearer {token}")
try:
    with urllib.request.urlopen(request, timeout=20) as response:
        payload = json.load(response)
except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
    raise SystemExit(f"fast-deploy: unable to verify GitHub Actions: {type(exc).__name__}")
runs = [run for run in payload.get("workflow_runs", []) if run.get("name") == "CI"]
if not runs:
    raise SystemExit("fast-deploy: no push CI run exists for the target commit")
run = max(runs, key=lambda item: int(item.get("id", 0)))
if run.get("status") != "completed" or run.get("conclusion") != "success":
    raise SystemExit(
        "fast-deploy: target CI is not successful "
        f"(status={run.get('status')}, conclusion={run.get('conclusion')})"
    )
print(f"ci=success run={run.get('id')}")
PY

STATE_DIR="${APP_DIR}/.git/knowflow-deploy-state"
mkdir -p "${STATE_DIR}"
chmod 700 "${STATE_DIR}"

requirements_hash="$(git show "${TARGET_SHA}:backend/requirements.txt" | sha256sum | cut -d' ' -f1)"
lock_hash="$(git show "${TARGET_SHA}:frontend/package-lock.json" | sha256sum | cut -d' ' -f1)"
frontend_hash="$(git ls-tree -r "${TARGET_SHA}" -- frontend | sha256sum | cut -d' ' -f1)"
previous_sha="$(git rev-parse HEAD)"

git checkout --detach "${TARGET_SHA}"

if [[ ! -f "${STATE_DIR}/requirements.sha256" ]] \
  || [[ "$(<"${STATE_DIR}/requirements.sha256")" != "${requirements_hash}" ]]; then
  "${VENV_DIR}/bin/python" -m pip install -r backend/requirements.txt
  printf '%s\n' "${requirements_hash}" > "${STATE_DIR}/requirements.sha256"
  dependencies_backend="installed"
else
  dependencies_backend="unchanged"
fi

if [[ ! -d frontend/node_modules ]] \
  || [[ ! -f "${STATE_DIR}/package-lock.sha256" ]] \
  || [[ "$(<"${STATE_DIR}/package-lock.sha256")" != "${lock_hash}" ]]; then
  (cd frontend && npm ci)
  printf '%s\n' "${lock_hash}" > "${STATE_DIR}/package-lock.sha256"
  dependencies_frontend="installed"
else
  dependencies_frontend="unchanged"
fi

if [[ ! -s frontend/dist/index.html ]] \
  || [[ ! -f "${STATE_DIR}/frontend.sha256" ]] \
  || [[ "$(<"${STATE_DIR}/frontend.sha256")" != "${frontend_hash}" ]]; then
  (cd frontend && npm run build)
  frontend_build="built"
else
  frontend_build="unchanged"
fi

find frontend/dist -type d -exec chmod 755 {} +
find frontend/dist -type f -exec chmod 644 {} +

systemctl restart "${SERVICE}"
systemctl is-active --quiet "${SERVICE}" \
  || fail "service did not become active after restart"
curl --fail --silent --show-error --retry 10 --retry-connrefused \
  --retry-delay 1 "${HEALTH_URL}" >/dev/null \
  || fail "health check failed after restart"

printf '%s\n' "${frontend_hash}" > "${STATE_DIR}/frontend.sha256"
printf '%s\n' "${TARGET_SHA}" > "${STATE_DIR}/deployed-commit"

printf 'previous=%s\n' "${previous_sha}"
printf 'deployed=%s\n' "${TARGET_SHA}"
printf 'backend_dependencies=%s\n' "${dependencies_backend}"
printf 'frontend_dependencies=%s\n' "${dependencies_frontend}"
printf 'frontend_build=%s\n' "${frontend_build}"
printf 'service=active\nhealth=ok\n'
