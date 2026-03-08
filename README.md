# SkillGym

SkillGym is an MVP CLI for continuous improvement of agent skills (`SKILL.md`) using benchmark execution + trace quality scoring.

## Big picture (gym analogy)

Treat your skill as an athlete:

- The skill enters **SkillGym** to get fitter.
- SkillGym runs structured **workouts** and measures performance.
- The skill is rewritten, re-tested, and promoted only if it improves.

Current workouts:

- **SkillBench workout (isolation):** test and optimize the skill by itself.
- **GPA workout (in-agent behavior):** use TruLens GPA to score how the agent used the skill (goal fulfillment, planning quality, adherence, efficiency, consistency).
- **Extensible program:** add more harnesses, scorers, and optimizers later for a more complete "full body" optimization loop.

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

## External integrations

- SkillBench (isolation harness): [benchflow-ai/skillsbench](https://github.com/benchflow-ai/skillsbench)
- SkillGym consumes SkillBench via Docker (`--harness skillbench`) and expects `task_runs.jsonl` output.
- Full contract and expected fields: `integrations/skillbench/README.md`
- TruLens GPA (behavior scoring): [pypi.org/project/trulens](https://pypi.org/project/trulens/)

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

For SkillBench, set `SKILLBENCH_DOCKER_IMAGE` to an image built from or published by [benchflow-ai/skillsbench](https://github.com/benchflow-ai/skillsbench).

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

## How to use SkillGym with SkillBench

1. Start with your baseline `SKILL.md`.
2. Run SkillGym with `--harness skillbench` to benchmark the skill in isolation.
3. SkillGym scores traces with TruLens GPA and generates a candidate skill (`upskill` or `gepa`).
4. SkillGym re-runs the same benchmark slice and compares baseline vs candidate.
5. Keep the candidate only if promotion gates pass (`pass_rate`, catastrophic failures, GPA, token budget).

## Reproducible Docker E2E demo

This repo includes a deterministic SkillBench-compatible Docker harness for local demo runs.
It works without `OPENAI_API_KEY` (SkillGym falls back to heuristic GPA scoring).

Run:

```bash
./scripts/run_e2e_skillbench_demo.sh
```

What it does:

1. Builds `integrations/skillbench/mock` as a local Docker image.
2. Runs SkillGym on `skills/e2e-poor-skill/SKILL.md` with `--harness skillbench`.
3. Generates a candidate skill via `upskill`, re-runs the benchmark, and writes a promotion report.

Key demo assets:

- Baseline weak skill: `skills/e2e-poor-skill/SKILL.md`
- Demo dataset: `benchmarks/e2e_skillbench.json`
- Docker harness implementation: `integrations/skillbench/mock/skillbench.py`

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
