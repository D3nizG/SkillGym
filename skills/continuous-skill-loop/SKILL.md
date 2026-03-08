---
name: continuous-skill-loop
description: Run SkillGym benchmark loops with Harbor or SkillBench, score traces with TruLens GPA, generate candidates with Upskill or GEPA, and apply promotion gates.
---

# Continuous Skill Improvement Loop

Use this skill to run the full SkillGym loop:
1. benchmark baseline,
2. score execution behavior (GPA),
3. generate a candidate skill,
4. re-benchmark and decide promote/reject.

## Prerequisites

- Python 3.11+
- Docker (for local containerized demo mode)
- `.env` from `.env.example`
- `OPENAI_API_KEY` for real TruLens/Upskill execution
- `python -m pip install -e .`

## Recommended runs

### Reproducible Docker demo

```bash
./scripts/run_e2e_skillbench_demo.sh
```

### Strict real SkillBench path

```bash
./scripts/run_real_skillbench_e2e.sh /absolute/path/to/skillsbench/tasks
```

### Strict real Harbor path

```bash
./scripts/run_real_harbor_e2e.sh /absolute/path/to/harbor/task-or-dataset
```

## Direct CLI usage

```bash
skillgym \
  --harness skillbench \
  --skillbench-path /absolute/path/to/skillsbench/tasks \
  --dataset-id skillsbench-real \
  --skill-path skills/e2e-poor-skill/SKILL.md \
  --optimizer upskill \
  --strict-real \
  --task-limit 3 \
  --env-file .env \
  --output-dir out/my-run
```

## Output artifacts

- `out/*/runs/<run_id>/summary.json`
- `out/*/runs/<run_id>/task_runs.jsonl`
- `out/*/runs/<run_id>/gpa_scores.jsonl`
- `out/*/reports/candidate_diff.md`
- `out/*/reports/promotion_decision.json`
- `out/*/generated_skills/*.md`

## Guardrails

1. Never promote without baseline-vs-candidate comparison on the same task slice.
2. Use strict mode when you need real integration only (`--strict-real`).
3. Block promotion if catastrophic failures increase.
4. Prefer concise skill edits that improve plan quality and execution efficiency.
