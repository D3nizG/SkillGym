# SkillGym

SkillGym is a CLI that runs the full harness + TruLens + GEPA loop described in the system design doc. It supports both `harbor` and `skillbench` harnesses, uses the `trulens` OpenAI provider for GPA-style signals, and mutates SKILL.md text with the official `gepa` package.

## Setup
1. Copy `.env.example` to `.env` and fill in:
   - `OPENAI_API_KEY` (used by TruLens + GEPA reflection models).
   - Harness Docker information (`HARBOR_*` and/or `SKILLBENCH_*` variables, depending on your selected harness).
2. Install dependencies (TruLens, GEPA, python-dotenv, etc.):
   ```bash
   cd <repo-root>
   python -m pip install -e .
   ```
3. Ensure Docker can pull/run the harness image you configured. The CLI mounts the repo root at `/workspace` by default, so both Harbor and SkillBench can read skills/datasets.

## Run the loop
```bash
skillgym \
  --harness harbor \
  --skill-path skills/continuous-skill-loop/SKILL.md \
  --skill-name continuous-skill-loop \
  --dataset-id sample-harbor \
  --optimizer upskill
```

SkillBench isolated run:

```bash
skillgym \
  --harness skillbench \
  --skillbench-registry benchmarks/sample_skillbench.json \
  --dataset-id sample-skillbench \
  --skill-path skills/continuous-skill-loop/SKILL.md \
  --optimizer upskill
```

> Prefer the installed `skillgym …` command. If you bypass installation, `python -m cli …` still works as long as `PYTHONPATH=src`.

Artifacts land under `out/` by default:
- `runs/<run_id>/summary.json`: aggregated metrics per skill version
- `runs/<run_id>/task_runs.jsonl`: task-level telemetry emitted by the active harness
- `runs/<run_id>/gpa_scores.jsonl`: TruLens GPA dimensions + judge rationales
- `reports/candidate_diff.md`: baseline vs candidate comparison summary
- `reports/promotion_decision.json`: gate decision artifact
- `generated_skills/<skill_id>.md`: candidate SKILL.md ready for inspection

If `HARBOR_DOCKER_IMAGE` or `SKILLBENCH_DOCKER_IMAGE` is unset, the CLI falls back to the lightweight simulator for that harness (useful for local checks, not a replacement for real benchmark runs).

## Extending the loop
- Point either adapter at a different Docker command/mount layout with `HARBOR_*` or `SKILLBENCH_*` settings.
- TruLens already uses the OpenAI provider—swap `TRULENS_JUDGE_MODEL`/`TRULENS_JUDGE_INSTRUCTIONS` in `.env` to try different judges.
- The GEPA optimizer runs `optimize_anything` with heuristics backed by failure tags; tune `GEPA_*` env vars to control objective/background/max metric calls.
- For multi-run observability, feed the JSON/JSONL artifacts into your preferred dashboard stack.
- SkillBench-specific command/output contract lives in `integrations/skillbench/README.md`.
