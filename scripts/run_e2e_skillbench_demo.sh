#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
IMAGE_TAG="${SKILLBENCH_IMAGE_TAG:-skillgym-skillbench-mock:local}"

echo "[1/3] Building mock SkillBench Docker image: ${IMAGE_TAG}"
docker build -t "${IMAGE_TAG}" "${ROOT_DIR}/integrations/skillbench/mock"

echo "[2/3] Running SkillGym E2E loop with SkillBench harness"
export SKILLBENCH_DOCKER_IMAGE="${IMAGE_TAG}"
export SKILLBENCH_EXTRA_ENV="SKILLBENCH_DATASET_REGISTRY=/workspace/benchmarks/e2e_skillbench.json,SKILLBENCH_SEED=e2e"

python3 "${ROOT_DIR}/src/cli.py" \
  --harness skillbench \
  --skillbench-registry "${ROOT_DIR}/benchmarks/e2e_skillbench.json" \
  --dataset-id e2e-skillbench \
  --skill-path "${ROOT_DIR}/skills/e2e-poor-skill/SKILL.md" \
  --optimizer upskill \
  --seed e2e \
  --output-dir "${ROOT_DIR}/out/e2e-skillbench"

echo "[3/3] Done"
echo "- Report: ${ROOT_DIR}/out/e2e-skillbench/reports/candidate_diff.md"
echo "- Decision: ${ROOT_DIR}/out/e2e-skillbench/reports/promotion_decision.json"
echo "- Candidate skill: ${ROOT_DIR}/out/e2e-skillbench/generated_skills/"
