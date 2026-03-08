# SkillGym

SkillGym is a CLI that runs the full Harbor + TruLens + GEPA loop described in the system design doc. The Harbor adapter now shells out to a Dockerized harness, the TruLens evaluator calls the `trulens` OpenAI provider for GPA-style signals, and GEPA mutates the SKILL.md text using the official `gepa` Python package.

## Setup
1. Copy `.env.example` to `.env` and fill in:
   - `OPENAI_API_KEY` (used by TruLens + GEPA reflection models).
   - Harbor Docker information (`HARBOR_DOCKER_IMAGE`, workspace/results mounts, any extra env vars the container needs).
2. Install dependencies (TruLens, GEPA, python-dotenv, etc.):
   ```bash
   cd /Users/Thomas_1/Documents/Playground
   python -m pip install -e .
   ```
3. Ensure Docker can pull/run the Harbor image you configured. The CLI mounts the repo root at `/workspace` by default, so Harbor access to source/skills happens through that path.

## Run the loop
```bash
skillgym \
  --skill-path skills/continuous-skill-loop/SKILL.md \
  --skill-name continuous-skill-loop \
  --dataset-id sample-harbor \
  --optimizer upskill
```

> Prefer the installed `skillgym …` command. If you bypass installation, `python -m cli …` still works as long as `PYTHONPATH=src`.

Harbor artifacts land under `out/` by default:
- `runs/<run_id>/summary.json`: Harbor metrics per skill version
- `runs/<run_id>/task_runs.jsonl`: task-level telemetry emitted by Harbor
- `runs/<run_id>/gpa_scores.jsonl`: TruLens GPA dimensions + judge rationales
- `reports/candidate_diff.md`: baseline vs candidate comparison summary
- `reports/promotion_decision.json`: gate decision artifact
- `generated_skills/<skill_id>.md`: candidate SKILL.md ready for inspection

If `HARBOR_DOCKER_IMAGE` is unset the CLI falls back to the lightweight simulator that ships with the repo (useful for unit tests, but not a replacement for real Harbor runs).

## Extending the loop
- Point the Harbor adapter at a different Docker command (`HARBOR_DOCKER_CMD`) or mount layout if you run remote clusters.
- TruLens already uses the OpenAI provider—swap `TRULENS_JUDGE_MODEL`/`TRULENS_JUDGE_INSTRUCTIONS` in `.env` to try different judges.
- The GEPA optimizer runs `optimize_anything` with heuristics backed by Harbor failure tags; tune `GEPA_*` env vars to control objective/background/max metric calls.
- For multi-run observability, feed the JSON/JSONL artifacts into your preferred dashboard stack.
