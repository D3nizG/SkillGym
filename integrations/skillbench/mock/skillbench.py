#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import random
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="skillbench")
    subparsers = parser.add_subparsers(dest="command", required=True)

    run = subparsers.add_parser("run", help="Run a SkillBench benchmark slice")
    run.add_argument("--dataset-id", required=True)
    run.add_argument("--agent-id", required=True)
    run.add_argument("--model-id", required=True)
    run.add_argument("--skill-path", required=True)
    run.add_argument("--output-dir", required=True)
    run.add_argument("--task-id", action="append", default=[])
    run.add_argument("--timeout-s", type=int, default=0)
    return parser.parse_args()


def load_registry(path: Path) -> Dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    return {dataset["id"]: dataset for dataset in payload.get("datasets", [])}


def skill_quality_score(skill_text: str) -> float:
    text = skill_text.lower()
    score = 0.0
    keywords = [
        "plan",
        "trace",
        "checklist",
        "failure",
        "validation",
        "tool",
        "format",
        "benchmark",
        "adherence",
        "efficiency",
    ]
    for keyword in keywords:
        if keyword in text:
            score += 0.055
    score += min(0.2, len(skill_text.splitlines()) / 140.0)
    return min(0.92, score)


def stable_roll(seed_text: str) -> float:
    digest = hashlib.sha256(seed_text.encode("utf-8")).hexdigest()[:12]
    value = int(digest, 16)
    return (value % 1_000_000) / 1_000_000.0


def build_plan(task_id: str, quality: float) -> List[Dict[str, str]]:
    # Higher-quality skills plan a bit better, but not excessively.
    steps = max(2, int(3 + quality * 3))
    return [
        {"step_id": f"step-{idx+1}", "description": f"{task_id} subtask {idx+1}"}
        for idx in range(steps)
    ]


def build_actions(
    task_goal: str,
    plan_steps: int,
    passed: bool,
    seed_text: str,
) -> List[Dict[str, Any]]:
    rng = random.Random(seed_text)
    # Lower-quality skills tend to wander with redundant actions.
    extra = rng.randint(0, 2)
    action_count = max(plan_steps, plan_steps + extra)
    actions: List[Dict[str, Any]] = []
    for idx in range(action_count):
        action_type = "tool_call" if idx % 2 == 0 else "thought"
        actions.append(
            {
                "timestamp": datetime.utcnow().isoformat() + "Z",
                "type": action_type,
                "content": f"Action {idx+1} for {task_goal}",
                "tool_name": "shell" if action_type == "tool_call" else None,
                "observation": "ok" if passed else "rework needed",
            }
        )
    return actions


def main() -> int:
    args = parse_args()
    if args.command != "run":
        print("Unsupported command", file=sys.stderr)
        return 2

    registry_path = Path(
        os.environ.get(
            "SKILLBENCH_DATASET_REGISTRY",
            "/workspace/benchmarks/e2e_skillbench.json",
        )
    )
    if not registry_path.exists():
        print(f"Dataset registry not found: {registry_path}", file=sys.stderr)
        return 1

    datasets = load_registry(registry_path)
    dataset = datasets.get(args.dataset_id)
    if dataset is None:
        print(f"Dataset id '{args.dataset_id}' missing in {registry_path}", file=sys.stderr)
        return 1

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    skill_path = Path(args.skill_path)
    skill_text = skill_path.read_text(encoding="utf-8")
    quality = skill_quality_score(skill_text)

    seed = os.environ.get("SKILLBENCH_SEED", "skillgym-e2e")
    tasks = dataset.get("tasks", [])
    if args.task_id:
        task_ids = set(args.task_id)
        tasks = [task for task in tasks if task.get("id") in task_ids]

    run_id = f"skillbench_{hashlib.sha256((seed + args.dataset_id).encode()).hexdigest()[:8]}"
    rows = []

    for task in tasks:
        task_id = task["id"]
        difficulty = float(task.get("difficulty", 0.5))
        pass_probability = max(0.05, min(0.98, 0.22 + quality - difficulty * 0.22))
        roll = stable_roll(f"{seed}:{task_id}")
        passed = roll < pass_probability

        plan = build_plan(task_id, quality)
        actions = build_actions(task.get("goal", task_id), len(plan), passed, f"{seed}:{task_id}")
        inefficiency = 1.0 - quality
        tokens_in = int(380 + (len(plan) * 22) + inefficiency * 260)
        tokens_out = int(120 + (len(actions) * 16) + inefficiency * 180)
        latency_s = round(
            7.0 + len(actions) * 1.5 + inefficiency * 4.0 + (0.8 if not passed else 0.0),
            3,
        )
        cost_usd = round((tokens_in + tokens_out) / 1_000_000 * 2.5, 6)

        raw_trace_filename = f"{task_id}_raw_trace.json"
        raw_trace_path = output_dir / raw_trace_filename
        raw_trace = {
            "task_id": task_id,
            "goal": task.get("goal", ""),
            "initial_context": task.get("context", ""),
            "plan": plan,
            "actions": actions,
            "final_result": {
                "output": task.get("success_template", "done") if passed else "contract violation",
                "passed": passed,
            },
            "metadata": {
                "agent_id": args.agent_id,
                "model_id": args.model_id,
                "skill_path": str(skill_path),
                "dataset_id": args.dataset_id,
                "tokens_in": tokens_in,
                "tokens_out": tokens_out,
                "latency_s": latency_s,
            },
        }
        raw_trace_path.write_text(json.dumps(raw_trace, indent=2), encoding="utf-8")

        rows.append(
            {
                "task_run_id": f"task_run_{task_id}_{run_id}",
                "benchmark_run_id": run_id,
                "task_id": task_id,
                "input_spec": task,
                "final_output": {
                    "answer": raw_trace["final_result"]["output"],
                    "status": "ok" if passed else "failed",
                },
                "pass_fail": passed,
                "latency_s": latency_s,
                "tokens_in": tokens_in,
                "tokens_out": tokens_out,
                "cost_usd": cost_usd,
                "raw_trace_uri": raw_trace_filename,
            }
        )

    manifest_path = output_dir / "task_runs.jsonl"
    with manifest_path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row) + "\n")

    summary = {
        "dataset_id": args.dataset_id,
        "tasks": len(rows),
        "quality": round(quality, 3),
        "note": "Mock SkillBench execution completed",
    }
    (output_dir / "skillbench_summary.json").write_text(
        json.dumps(summary, indent=2),
        encoding="utf-8",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
