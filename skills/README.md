# Skills

This folder contains skill assets used by SkillGym.

- `continuous-skill-loop/SKILL.md`: primary skill that tells an agent how to run the benchmark -> GPA -> optimize -> promote loop.
- `e2e-poor-skill/SKILL.md`: intentionally weak baseline skill for reproducible end-to-end demos.

## Quick start

Use the same setup as the root README:

1. Install dependencies and create `.env`
2. Run a demo loop:
   - Docker demo: `./scripts/run_e2e_skillbench_demo.sh`
   - Strict real SkillBench path: `./scripts/run_real_skillbench_e2e.sh /path/to/skillsbench/tasks`
   - Strict real Harbor path: `./scripts/run_real_harbor_e2e.sh /path/to/harbor/task-or-dataset`

## Notes

- Keep skill docs concise and operational.
- Real integration behavior and environment variables are documented in the root `README.md`.
