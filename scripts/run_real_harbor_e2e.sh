#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
HARBOR_DATASET_PATH="${1:-${HARBOR_DATASET_PATH:-}}"

if [[ -f "${ROOT_DIR}/.env" ]]; then
  set -a
  # shellcheck disable=SC1091
  source "${ROOT_DIR}/.env"
  set +a
fi

if [[ -z "${HARBOR_DATASET_PATH}" ]]; then
  echo "Usage: $0 /absolute/path/to/harbor/task-or-dataset"
  echo "Or set HARBOR_DATASET_PATH in your environment/.env"
  exit 1
fi

if [[ ! -d "${HARBOR_DATASET_PATH}" ]]; then
  echo "Harbor dataset path does not exist: ${HARBOR_DATASET_PATH}"
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

echo "Running real SkillGym + Harbor loop"
echo "- Harbor dataset path: ${HARBOR_DATASET_PATH}"

env HARBOR_DATASET_PATH="${HARBOR_DATASET_PATH}" \
python3 "${ROOT_DIR}/src/cli.py" \
  --harness harbor \
  --harbor-path "${HARBOR_DATASET_PATH}" \
  --dataset-id harbor-real \
  --skill-path "${ROOT_DIR}/skills/e2e-poor-skill/SKILL.md" \
  --optimizer upskill \
  --strict-real \
  --task-limit 3 \
  --env-file "${ROOT_DIR}/.env" \
  --output-dir "${ROOT_DIR}/out/real-harbor"

echo "Done"
echo "- Report: ${ROOT_DIR}/out/real-harbor/reports/candidate_diff.md"
echo "- Decision: ${ROOT_DIR}/out/real-harbor/reports/promotion_decision.json"
