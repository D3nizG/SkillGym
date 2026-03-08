from __future__ import annotations

import json
import random
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Tuple

from ..models import BenchmarkRun, SkillVersion, TaskRun
from ..utils.io import ensure_dir


class HarborRunner:
    """Simulated Harbor adapter for the MVP CLI."""

    def __init__(self, dataset_registry: Path, artifacts_root: Path) -> None:
        self.dataset_registry = dataset_registry
        self.artifacts_root = artifacts_root
        ensure_dir(self.artifacts_root)
        self._datasets = self._load_registry()

    def _load_registry(self) -> Dict[str, Dict[str, Any]]:
        if not self.dataset_registry.exists():
            raise FileNotFoundError(
                f"Dataset registry {self.dataset_registry} does not exist."
            )
        payload = json.loads(self.dataset_registry.read_text(encoding="utf-8"))
        datasets = {item["id"]: item for item in payload.get("datasets", [])}
        if not datasets:
            raise ValueError("Dataset registry must contain at least one dataset entry.")
        return datasets

    def run_benchmark(
        self,
        dataset_id: str,
        agent_id: str,
        model_id: str,
        skill_version: SkillVersion,
        runtime_config: Dict[str, Any],
    ) -> Tuple[BenchmarkRun, List[TaskRun]]:
        dataset = self._datasets.get(dataset_id)
        if dataset is None:
            raise ValueError(f"Unknown dataset_id '{dataset_id}'.")
        tasks = dataset["tasks"]
        if subset := runtime_config.get("task_subset"):
            task_lookup = {task["id"]: task for task in tasks}
            tasks = [task_lookup[task_id] for task_id in subset if task_id in task_lookup]
        task_limit = runtime_config.get("task_limit")
        if task_limit:
            tasks = tasks[:task_limit]

        run_id = runtime_config.get("run_id") or f"run_{random.randint(1000, 9999)}"
        artifacts_dir = ensure_dir(self.artifacts_root / run_id)
        run = BenchmarkRun(
            id=run_id,
            dataset_id=dataset_id,
            agent_id=agent_id,
            model_id=model_id,
            skill_version_id=skill_version.id,
            started_at=datetime.utcnow(),
            completed_at=None,
            runtime_config=runtime_config,
            status="running",
            artifacts_dir=artifacts_dir,
        )

        task_runs: List[TaskRun] = []
        for task in tasks:
            simulation = self._simulate_task(skill_version, task, runtime_config)
            raw_trace_path = artifacts_dir / f"{task['id']}_raw_trace.json"
            raw_trace_path.write_text(json.dumps(simulation["raw_trace"], indent=2), encoding="utf-8")
            task_run = TaskRun(
                id=f"task_run_{task['id']}_{run_id}",
                benchmark_run_id=run.id,
                task_id=task["id"],
                input_spec=task,
                final_output={
                    "answer": simulation["final_answer"],
                    "notes": simulation["notes"],
                },
                pass_fail=simulation["passed"],
                latency_s=simulation["latency_s"],
                tokens_in=simulation["tokens_in"],
                tokens_out=simulation["tokens_out"],
                cost_usd=simulation["cost_usd"],
                raw_trace_uri=str(raw_trace_path),
            )
            task_runs.append(task_run)

        run.completed_at = datetime.utcnow()
        run.status = "completed"
        return run, task_runs

    # ------------------------------------------------------------------
    def _simulate_task(
        self,
        skill_version: SkillVersion,
        task: Dict[str, Any],
        runtime_config: Dict[str, Any],
    ) -> Dict[str, Any]:
        seed_material = f"{skill_version.id}-{task['id']}-{runtime_config.get('seed', 'mvp')}"
        rng = random.Random(seed_material)
        base_difficulty = task.get("difficulty", 0.5)
        skill_effect = self._estimate_skill_effect(skill_version.content, task)
        pass_probability = max(0.05, min(0.95, 0.55 + skill_effect - base_difficulty * 0.3))
        passed = rng.random() < pass_probability

        plan_steps = max(2, int(4 + (skill_effect * 10)))
        plan = [
            {"step_id": f"step-{idx+1}", "description": f"Subtask {idx+1} for {task['id']}"}
            for idx in range(plan_steps)
        ]
        action_count = plan_steps + rng.randint(1, 3)
        actions = []
        for idx in range(action_count):
            actions.append(
                {
                    "timestamp": datetime.utcnow().isoformat() + "Z",
                    "type": "tool_call" if idx % 2 == 0 else "thought",
                    "content": f"Action {idx+1} reasoning around {task['goal']}",
                    "tool_name": "shell" if idx % 3 == 0 else "editor",
                    "observation": "ok" if passed else "needs improvement",
                }
            )

        tokens_in = int(600 + rng.randint(0, 150) + (plan_steps * 10))
        tokens_out = int(200 + rng.randint(0, 100) + (action_count * 5))
        latency_s = round(40 + rng.random() * 20 + (0.5 if not passed else 0.0), 2)
        token_cost = (tokens_in + tokens_out) / 1000 * 0.002
        failure_reason = ""
        if not passed:
            failure_reason = rng.choice(
                [
                    "Incorrect formatting",
                    "Missed assertion",
                    "Inefficient plan",
                    "Hallucinated state",
                ]
            )

        raw_trace = {
            "task_id": task["id"],
            "goal": task["goal"],
            "initial_context": task.get("context", ""),
            "plan": plan,
            "actions": actions,
            "final_result": {
                "output": "success" if passed else failure_reason,
                "passed": passed,
            },
            "metadata": {
                "model_id": runtime_config.get("model_id"),
                "agent_id": runtime_config.get("agent_id"),
                "skill_version_id": skill_version.id,
                "tokens_in": tokens_in,
                "tokens_out": tokens_out,
                "latency_s": latency_s,
            },
        }

        final_answer = task.get("success_template", "Produced deliverable")
        if not passed:
            final_answer = f"Partial result: {failure_reason}"

        return {
            "raw_trace": raw_trace,
            "passed": passed,
            "final_answer": final_answer,
            "notes": failure_reason or "Completed successfully",
            "tokens_in": tokens_in,
            "tokens_out": tokens_out,
            "latency_s": latency_s,
            "cost_usd": round(token_cost, 4),
        }

    def _estimate_skill_effect(self, skill_text: str, task: Dict[str, Any]) -> float:
        skill_text_lower = skill_text.lower()
        score = 0.0
        keywords = [
            "harbor",
            "trulens",
            "gpa",
            "upskill",
            "gepa",
            "plan",
            "trace",
            "benchmark",
            task["goal"].split()[0].lower(),
        ]
        for keyword in keywords:
            if keyword and keyword in skill_text_lower:
                score += 0.03
        score += min(0.15, len(skill_text.splitlines()) / 200)
        score = min(0.3, score)
        return score
