from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any, Dict

from adapters.harbor import HarborRunner
from adapters.skillbench import SkillBenchRunner
from normalization.trace_normalizer import TraceNormalizer
from orchestrator.pipeline import LoopConfig, SkillImprovementLoop
from promotion.decider import PromotionDecider
from scoring.trulens_adapter import TruLensGPAEvaluator
from settings import load_settings
from storage.repository import InMemoryRepository


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Continuous skill improvement MVP CLI",
    )
    default_root = Path(__file__).resolve().parents[1]
    parser.add_argument(
        "--skill-path",
        required=True,
        help="Path to the baseline SKILL.md file",
    )
    parser.add_argument(
        "--skill-name",
        help="Logical skill name (defaults to parent folder name)",
    )
    parser.add_argument(
        "--dataset-id",
        help="Dataset identifier from the registry (defaults depend on harness).",
    )
    parser.add_argument(
        "--dataset-registry",
        default=str(default_root / "benchmarks" / "sample_tasks.json"),
        help="Path to Harbor dataset registry JSON",
    )
    parser.add_argument(
        "--skillbench-registry",
        default=str(default_root / "benchmarks" / "sample_skillbench.json"),
        help="Path to SkillBench dataset registry JSON",
    )
    parser.add_argument(
        "--harness",
        default="harbor",
        choices=["harbor", "skillbench"],
        help="Benchmark harness backend to execute.",
    )
    parser.add_argument(
        "--agent-id",
        default="coding-agent-a",
        help="Agent identifier passed to Harbor",
    )
    parser.add_argument(
        "--model-id",
        default="gpt-4.1-preview",
        help="Model identifier passed to Harbor",
    )
    parser.add_argument(
        "--optimizer",
        default="upskill",
        choices=["upskill", "gepa"],
        help="Optimizer backend to use",
    )
    parser.add_argument(
        "--task-limit",
        type=int,
        default=3,
        help="Limit number of tasks from the dataset",
    )
    parser.add_argument(
        "--task-subset",
        nargs="*",
        help="Explicit task IDs to run",
    )
    parser.add_argument(
        "--seed",
        default="mvp",
        help="Deterministic seed routed into Harbor",
    )
    parser.add_argument(
        "--output-dir",
        default=str(default_root / "out"),
        help="Directory for run artifacts",
    )
    parser.add_argument(
        "--strict-real",
        action="store_true",
        help="Disable simulation/fallback paths and require real Harbor/SkillBench + TruLens integrations.",
    )
    parser.add_argument(
        "--harbor-path",
        help="Path to a local Harbor task or dataset directory (used with --harness harbor).",
    )
    parser.add_argument(
        "--skillbench-path",
        help="Path to local SkillBench tasks directory (used with --harness skillbench via Harbor).",
    )
    parser.add_argument(
        "--env-file",
        help="Path to the .env file containing Harbor/OpenAI/GEPA secrets (defaults to .env in repo root).",
    )
    return parser.parse_args()


def build_runtime_config(args: argparse.Namespace) -> Dict[str, Any]:
    config: Dict[str, Any] = {
        "task_limit": args.task_limit,
        "seed": args.seed,
        "strict_real": bool(args.strict_real),
    }
    if args.task_subset:
        config["task_subset"] = args.task_subset
    if args.harbor_path:
        config["dataset_path"] = str(Path(args.harbor_path).expanduser().resolve())
    if args.skillbench_path:
        config["dataset_path"] = str(Path(args.skillbench_path).expanduser().resolve())
    return config


def main() -> None:
    args = parse_args()
    skill_path = Path(args.skill_path).expanduser().resolve()
    if not skill_path.exists():
        raise FileNotFoundError(f"Skill file {skill_path} not found.")
    skill_name = args.skill_name or skill_path.parent.name or "skill"
    output_dir = Path(args.output_dir).expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    repo_root = Path(__file__).resolve().parents[1]
    env_path = Path(args.env_file).expanduser().resolve() if args.env_file else None
    settings = load_settings(env_path)
    strict_real = bool(args.strict_real or settings.strict_real)
    dataset_id = args.dataset_id or (
        "sample-skillbench" if args.harness == "skillbench" else "sample-harbor"
    )
    harbor_path = Path(args.harbor_path).expanduser().resolve() if args.harbor_path else None
    skillbench_path = (
        Path(args.skillbench_path).expanduser().resolve()
        if args.skillbench_path
        else settings.skillbench.tasks_path
    )

    repository = InMemoryRepository()
    if args.harness == "skillbench":
        benchmark_runner = SkillBenchRunner(
            dataset_registry=Path(args.skillbench_registry).expanduser().resolve(),
            artifacts_root=output_dir / "runs",
            workspace_root=repo_root,
            docker_image=settings.skillbench.docker_image,
            docker_command=settings.skillbench.docker_command,
            workspace_mount=settings.skillbench.workspace_mount,
            results_mount=settings.skillbench.results_mount,
            extra_env=settings.skillbench.extra_env,
            command=settings.skillbench.command,
            tasks_path=skillbench_path,
            strict_real=strict_real,
        )
    else:
        benchmark_runner = HarborRunner(
            dataset_registry=Path(args.dataset_registry).expanduser().resolve(),
            artifacts_root=output_dir / "runs",
            workspace_root=repo_root,
            docker_image=settings.harbor.docker_image,
            docker_command=settings.harbor.docker_command,
            workspace_mount=settings.harbor.workspace_mount,
            results_mount=settings.harbor.results_mount,
            extra_env=settings.harbor.extra_env,
            command=settings.harbor.command,
            strict_real=strict_real,
            dataset_path=harbor_path,
        )
    loop = SkillImprovementLoop(
        repository=repository,
        benchmark_runner=benchmark_runner,
        trace_normalizer=TraceNormalizer(),
        gpa_evaluator=TruLensGPAEvaluator(
            judge_model=settings.trulens.judge_model,
            api_key=settings.trulens.openai_api_key,
            instructions=settings.trulens.judge_instructions,
            strict_mode=bool(strict_real or settings.trulens.strict),
        ),
        promotion_decider=PromotionDecider(),
        gepa_settings=settings.gepa,
        upskill_settings=settings.upskill,
    )

    runtime_config = build_runtime_config(args)
    runtime_config["strict_real"] = strict_real

    config = LoopConfig(
        dataset_id=dataset_id,
        agent_id=args.agent_id,
        model_id=args.model_id,
        runtime_config=runtime_config,
        optimizer_name=args.optimizer,
        skill_path=skill_path,
        skill_name=skill_name,
        output_dir=output_dir,
        strict_real=strict_real,
    )
    result = loop.run(config)
    print("Baseline summary:")
    for key, value in result["baseline"].items():
        print(f"  {key}: {value}")
    print("\nCandidate summary:")
    for key, value in result["candidate"].items():
        print(f"  {key}: {value}")
    print("\nDecision:")
    print(f"  Outcome: {result['decision']['decision']}")
    print(f"  Reason: {result['decision']['reason']}")
    print(f"Generated candidate skill: {result['candidate_skill_path']}")


if __name__ == "__main__":
    main()
