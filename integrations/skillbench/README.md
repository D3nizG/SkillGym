# SkillBench Integration

This directory documents the SkillGym <-> SkillBench integration used for isolated skill optimization runs.

Official SkillBench project: [benchflow-ai/skillsbench](https://github.com/benchflow-ai/skillsbench)

## How SkillGym invokes SkillBench

When `--harness skillbench` is set, SkillGym executes a Docker command equivalent to:

```bash
skillbench run \
  --dataset-id <dataset_id> \
  --agent-id <agent_id> \
  --model-id <model_id> \
  --skill-path <mounted_skill_file> \
  --output-dir <mounted_results_dir>
```

The exact image/command/mounts come from `.env` (`SKILLBENCH_*` variables).
Set `SKILLBENCH_DOCKER_IMAGE` to an image built from or published by the SkillBench project.

## Output contract expected by SkillGym

SkillBench must write the following files under `--output-dir`:

1. `task_runs.jsonl` (required)
2. Raw trace files referenced by each row in `task_runs.jsonl`

Each `task_runs.jsonl` row should include:

- `task_id`
- `pass_fail` or `passed`
- `latency_s`
- `tokens_in`
- `tokens_out`
- `cost_usd`
- `raw_trace_uri` or `raw_trace_path`
- Optional: `input_spec`, `final_output`, `task_run_id`, `benchmark_run_id`

## Local smoke run

```bash
skillgym \
  --harness skillbench \
  --skillbench-registry benchmarks/sample_skillbench.json \
  --dataset-id sample-skillbench \
  --skill-path skills/continuous-skill-loop/SKILL.md \
  --optimizer upskill
```

If `SKILLBENCH_DOCKER_IMAGE` is not set, SkillGym reuses the local simulation runner with the SkillBench registry.
