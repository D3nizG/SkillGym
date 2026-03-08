#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SKILLBENCH_TASKS_PATH="${1:-${SKILLBENCH_TASKS_PATH:-}}"

if [[ -f "${ROOT_DIR}/.env" ]]; then
  set -a
  # shellcheck disable=SC1091
  source "${ROOT_DIR}/.env"
  set +a
fi

if [[ -z "${SKILLBENCH_TASKS_PATH}" ]]; then
  echo "Usage: $0 /absolute/path/to/skillsbench/tasks"
  echo "Or set SKILLBENCH_TASKS_PATH in your environment/.env"
  exit 1
fi

if [[ ! -d "${SKILLBENCH_TASKS_PATH}" ]]; then
  echo "SkillBench tasks path does not exist: ${SKILLBENCH_TASKS_PATH}"
  exit 1
fi

if ! command -v harbor >/dev/null 2>&1; then
  echo "Harbor CLI is required. Install with: uv tool install harbor"
  exit 1
fi

if [[ -z "${OPENAI_API_KEY:-}" ]]; then
  echo "OPENAI_API_KEY is required for strict real TruLens/Upskill evaluation."
  exit 1
fi

echo "Running real SkillGym + SkillBench (Harbor-backed) loop"
echo "- SkillBench tasks: ${SKILLBENCH_TASKS_PATH}"

env SKILLBENCH_TASKS_PATH="${SKILLBENCH_TASKS_PATH}" \
python3 "${ROOT_DIR}/src/cli.py" \
  --harness skillbench \
  --skillbench-path "${SKILLBENCH_TASKS_PATH}" \
  --dataset-id skillsbench-real \
  --skill-path "${ROOT_DIR}/skills/e2e-poor-skill/SKILL.md" \
  --optimizer upskill \
  --strict-real \
  --task-limit 3 \
  --env-file "${ROOT_DIR}/.env" \
  --output-dir "${ROOT_DIR}/out/real-skillbench"

echo "Done"
echo "- Report: ${ROOT_DIR}/out/real-skillbench/reports/candidate_diff.md"
echo "- Decision: ${ROOT_DIR}/out/real-skillbench/reports/promotion_decision.json"
