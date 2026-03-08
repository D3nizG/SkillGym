# SkillGym

SkillGym is an MVP CLI for continuous improvement of agent skills (`SKILL.md`) using benchmark execution + trace quality scoring.

## Core loop

1. Run benchmark tasks with a harness (`harbor` or `skillbench`).
2. Normalize traces and score behavior with TruLens GPA dimensions.
3. Generate a candidate skill with an optimizer (`upskill` or `gepa`).
4. Re-run the same benchmark slice and apply promotion gates.

## Project structure

- `src/cli.py` — CLI entrypoint and wiring.
- `src/orchestrator/pipeline.py` — end-to-end baseline/candidate workflow.
- `src/adapters/` — harness backends (`harbor.py`, `skillbench.py`).
- `src/normalization/trace_normalizer.py` — raw trace -> normalized trace schema.
- `src/scoring/trulens_adapter.py` — TruLens-based GPA scoring.
- `src/optimization/` — optimizer adapters (`upskill_adapter.py`, `gepa_adapter.py`).
- `src/promotion/decider.py` — promotion gate policy.
- `src/storage/repository.py` — in-memory run/skill bookkeeping.
- `benchmarks/` — sample dataset registries.
- `integrations/skillbench/` — SkillBench interface contract and schema.
- `skills/` — example skills used as baseline inputs.

## Prerequisites

- Python `>=3.11`
- Docker (for real harness execution)
- OpenAI API key (`OPENAI_API_KEY`)
- At least one harness image:
  - `HARBOR_DOCKER_IMAGE`, or
  - `SKILLBENCH_DOCKER_IMAGE`

## Setup

```bash
cp .env.example .env
python -m pip install -e .
```

Then edit `.env` (see `.env.example`) with your OpenAI key and harness settings.

## Quick start

Run Harbor:

```bash
skillgym \
  --harness harbor \
  --dataset-id sample-harbor \
  --skill-path skills/continuous-skill-loop/SKILL.md \
  --optimizer upskill
```

Run SkillBench (isolated skill benchmark):

```bash
skillgym \
  --harness skillbench \
  --skillbench-registry benchmarks/sample_skillbench.json \
  --dataset-id sample-skillbench \
  --skill-path skills/continuous-skill-loop/SKILL.md \
  --optimizer upskill
```

Use `skillgym --help` for all flags.

## Output artifacts

Runs write to `out/`:

- `out/runs/<run_id>/summary.json`
- `out/runs/<run_id>/task_runs.jsonl`
- `out/runs/<run_id>/gpa_scores.jsonl`
- `out/reports/candidate_diff.md`
- `out/reports/promotion_decision.json`
- `out/generated_skills/<candidate_id>.md`

## Contributing

1. Make changes in `src/` (and integration docs if interfaces change).
2. Validate syntax:
   ```bash
   python3 -m compileall src
   ```
3. Run one smoke command for the harness/optimizer you touched.
4. Keep docs current (`README.md`, `integrations/`, and example skill docs).
