# SkillGym

SkillGym is a CLI that simulates the Harbor + TruLens + optimizer loop described in the design doc. It runs a baseline skill through the Harbor runner, scores traces with a TruLens-inspired GPA evaluator, proposes a new skill candidate (Upskill or GEPA), reruns the benchmark, and applies promotion gates.

## Quickstart
```bash
cd /Users/Thomas_1/Documents/Playground
python -m pip install -e .
python -m cli \
  --skill-path skills/continuous-skill-loop/SKILL.md \
  --skill-name continuous-skill-loop \
  --dataset-id sample-harbor \
  --optimizer upskill
```

Key outputs land under `out/` by default:
- `runs/<run_id>/summary.json`: per-skill Harbor metrics
- `runs/<run_id>/task_runs.jsonl`: task-level telemetry
- `runs/<run_id>/gpa_scores.jsonl`: TruLens GPA dimensions + tags
- `reports/candidate_diff.md`: baseline vs candidate comparison summary
- `reports/promotion_decision.json`: gate decision artifact
- `generated_skills/<skill_id>.md`: candidate SKILL.md ready for inspection

## Extending the MVP
- Plug in a real Harbor CLI by replacing `HarborRunner._simulate_task` in `src/adapters/harbor.py`.
- Swap TruLens evaluator by calling the real GPA API inside `TruLensGPAEvaluator`.
- Implement historical storage instead of the in-memory repository.
- Add dashboards by pointing to the JSON/JSONL artifacts from the CLI runs.
