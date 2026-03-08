# Continuous Skill Improvement Loop

Use this skill to run the Harbor + TruLens driven loop that benchmarks a coding agent skill, scores trace quality, generates an Upskill/GEPA candidate, and produces a promotion recommendation.

## Prerequisites
- Python 3.11+
- Docker access to your Harbor harness image.
- `.env` with `OPENAI_API_KEY`, `HARBOR_DOCKER_IMAGE`, and optional GEPA overrides (copy `.env.example`).
- Editable install of this repo (`python -m pip install -e .`).
- Harbor dataset registry JSON (defaults to `benchmarks/sample_tasks.json`; only used for the simulator fallback).

## Run the loop
```bash
skillgym \
  --skill-path skills/continuous-skill-loop/SKILL.md \
  --skill-name continuous-skill-loop \
  --dataset-id sample-harbor \
  --optimizer upskill \
  --task-limit 3 \
  --env-file .env  # optional; defaults to .env in repo root
```

> If you prefer not to install the package, you can substitute `skillgym` for `python -m cli`.

Arguments:
- `--skill-path`: baseline SKILL.md to evaluate.
- `--optimizer`: `upskill` (default) or `gepa` for candidate generation backend.
- `--task-limit` / `--task-subset`: control Harbor task slices.
- `--seed`: deterministic Harbor run seed.
- `--output-dir`: where run artifacts + reports write (default `out/`).

## Outputs
- `out/runs/<run_id>/summary.json`: Harbor summary per skill version.
- `out/runs/<run_id>/task_runs.jsonl`: task-level metrics.
- `out/runs/<run_id>/gpa_scores.jsonl`: TruLens GPA diagnostics.
- `out/reports/candidate_diff.md`: baseline vs candidate metrics + decision.
- `out/generated_skills/<candidate_id>.md`: candidate SKILL.md ready for review.

## Workflow Guardrails
1. Always benchmark baseline skill first; never edit before collecting traces.
2. Capture both successful and failing traces; GPA rationales feed the optimizer.
3. Only promote candidates when pass rate, GPA, and catastrophic-failure gates pass.
4. If Harbor traces highlight tooling or format regressions, update the skill manually and rerun.
5. Archive artifacts per run to keep longitudinal history for GEPA search.
