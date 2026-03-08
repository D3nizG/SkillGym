from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any, Dict

from .adapters.harbor import HarborRunner
from .normalization.trace_normalizer import TraceNormalizer
from .orchestrator.pipeline import LoopConfig, SkillImprovementLoop
from .promotion.decider import PromotionDecider
from .scoring.trulens_adapter import TruLensGPAEvaluator
from .storage.repository import InMemoryRepository


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Continuous skill improvement MVP CLI",
    )
    default_root = Path(__file__).resolve().parent.parent
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
        default="sample-harbor",
        help="Dataset identifier from the registry",
    )
    parser.add_argument(
        "--dataset-registry",
        default=str(default_root / "benchmarks" / "sample_tasks.json"),
        help="Path to Harbor dataset registry JSON",
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
    return parser.parse_args()


def build_runtime_config(args: argparse.Namespace) -> Dict[str, Any]:
    config: Dict[str, Any] = {
        "task_limit": args.task_limit,
        "seed": args.seed,
    }
    if args.task_subset:
        config["task_subset"] = args.task_subset
    return config


def main() -> None:
    args = parse_args()
    skill_path = Path(args.skill_path).expanduser().resolve()
    if not skill_path.exists():
        raise FileNotFoundError(f"Skill file {skill_path} not found.")
    skill_name = args.skill_name or skill_path.parent.name or "skill"
    output_dir = Path(args.output_dir).expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    repository = InMemoryRepository()
    harbor_runner = HarborRunner(
        dataset_registry=Path(args.dataset_registry).expanduser().resolve(),
        artifacts_root=output_dir / "runs",
    )
    loop = SkillImprovementLoop(
        repository=repository,
        harbor_runner=harbor_runner,
        trace_normalizer=TraceNormalizer(),
        gpa_evaluator=TruLensGPAEvaluator(),
        promotion_decider=PromotionDecider(),
    )

    config = LoopConfig(
        dataset_id=args.dataset_id,
        agent_id=args.agent_id,
        model_id=args.model_id,
        runtime_config=build_runtime_config(args),
        optimizer_name=args.optimizer,
        skill_path=skill_path,
        skill_name=skill_name,
        output_dir=output_dir,
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
