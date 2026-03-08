from __future__ import annotations

import json
import logging
import random
import subprocess
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Tuple

from models import BenchmarkRun, SkillVersion, TaskRun
from utils.io import ensure_dir, load_jsonl

LOGGER = logging.getLogger(__name__)


class HarborRunner:
    """Run Harbor benchmarks via Docker (with a simulator fallback)."""

    def __init__(
        self,
        dataset_registry: Path,
        artifacts_root: Path,
        workspace_root: Path,
        docker_image: str | None,
        docker_command: str = "docker",
        workspace_mount: str = "/workspace",
        results_mount: str = "/harbor/artifacts",
        extra_env: Dict[str, str] | None = None,
    ) -> None:
        self.dataset_registry = dataset_registry
        self.artifacts_root = artifacts_root
        self.workspace_root = workspace_root
        self.docker_image = docker_image
        self.docker_command = docker_command
        self.workspace_mount = workspace_mount.rstrip("/")
        self.results_mount = results_mount.rstrip("/")
        self.extra_env = extra_env or {}
        ensure_dir(self.artifacts_root)
        self._simulation_mode = docker_image is None
        self._datasets = self._load_registry() if self.dataset_registry.exists() else {}

    def run_benchmark(
        self,
        dataset_id: str,
        agent_id: str,
        model_id: str,
        skill_version: SkillVersion,
        skill_file: Path,
        runtime_config: Dict[str, Any],
    ) -> Tuple[BenchmarkRun, List[TaskRun]]:
        run_id = runtime_config.get("run_id") or f"run_{uuid.uuid4().hex[:8]}"
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
        if self._simulation_mode:
            task_runs = self._run_simulation(
                dataset_id=dataset_id,
                skill_version=skill_version,
                runtime_config=runtime_config,
                artifacts_dir=artifacts_dir,
                run_id=run_id,
            )
        else:
            task_runs = self._run_harbor_docker(
                dataset_id=dataset_id,
                agent_id=agent_id,
                model_id=model_id,
                skill_version=skill_version,
                skill_file=skill_file,
                runtime_config=runtime_config,
                artifacts_dir=artifacts_dir,
                run_id=run_id,
            )
        run.completed_at = datetime.utcnow()
        run.status = "completed"
        return run, task_runs

    # ------------------------------------------------------------------
    def _run_harbor_docker(
        self,
        dataset_id: str,
        agent_id: str,
        model_id: str,
        skill_version: SkillVersion,
        skill_file: Path,
        runtime_config: Dict[str, Any],
        artifacts_dir: Path,
        run_id: str,
    ) -> List[TaskRun]:
        if not self.docker_image:
            raise RuntimeError("HARBOR_DOCKER_IMAGE is not configured.")
        skill_container_path = self._to_container_path(skill_file)
        artifacts_mount = f"{artifacts_dir}:{self.results_mount}"
        workspace_mount = f"{self.workspace_root}:{self.workspace_mount}"

        cmd = [
            self.docker_command,
            "run",
            "--rm",
            "-v",
            workspace_mount,
            "-v",
            artifacts_mount,
        ]
        for key, value in self.extra_env.items():
            cmd.extend(["-e", f"{key}={value}"])
        cmd.extend(
            [
                "-e",
                f"HARBOR_DATASET_ID={dataset_id}",
                "-e",
                f"HARBOR_AGENT_ID={agent_id}",
                "-e",
                f"HARBOR_MODEL_ID={model_id}",
                "-e",
                f"HARBOR_SKILL_PATH={skill_container_path}",
                "-e",
                f"HARBOR_OUTPUT_DIR={self.results_mount}",
                self.docker_image,
                "harbor",
                "evaluate",
                "--dataset-id",
                dataset_id,
                "--agent-id",
                agent_id,
                "--model-id",
                model_id,
                "--skill-path",
                skill_container_path,
                "--output-dir",
                self.results_mount,
            ]
        )
        if subset := runtime_config.get("task_subset"):
            for task_id in subset:
                cmd.extend(["--task-id", task_id])
        if timeout := runtime_config.get("timeout_s"):
            cmd.extend(["--timeout-s", str(timeout)])

        LOGGER.info("Running Harbor via Docker: %s", " ".join(cmd))
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            check=False,
        )
        if proc.returncode != 0:
            raise RuntimeError(
                f"Harbor Docker run failed with exit code {proc.returncode}.\nSTDOUT:\n{proc.stdout}\nSTDERR:\n{proc.stderr}"
            )
        LOGGER.debug("Harbor stdout:\n%s", proc.stdout)
        LOGGER.debug("Harbor stderr:\n%s", proc.stderr)
        task_runs_manifest = artifacts_dir / "task_runs.jsonl"
        if not task_runs_manifest.exists():
            raise FileNotFoundError(
                f"Expected Harbor to produce {task_runs_manifest}, but the file is missing."
            )
        rows = load_jsonl(task_runs_manifest)
        task_runs: List[TaskRun] = []
        for row in rows:
            task_id = row.get("task_id") or row.get("id") or "unknown-task"
            raw_trace_uri = row.get("raw_trace_uri") or row.get("raw_trace_path")
            if raw_trace_uri is None:
                raw_trace_uri = f"raw_traces/{task_id}.json"
            raw_trace_path = artifacts_dir / raw_trace_uri
            final_output = row.get("final_output") or {"answer": row.get("answer")}
            task_runs.append(
                TaskRun(
                    id=row.get("task_run_id", f"task_run_{task_id}_{run_id}"),
                    benchmark_run_id=row.get("benchmark_run_id", run_id),
                    task_id=task_id,
                    input_spec=row.get("input_spec", {}),
                    final_output=final_output or {},
                    pass_fail=bool(row.get("pass_fail", row.get("passed", False))),
                    latency_s=float(row.get("latency_s", 0.0)),
                    tokens_in=int(row.get("tokens_in", 0)),
                    tokens_out=int(row.get("tokens_out", 0)),
                    cost_usd=float(row.get("cost_usd", 0.0)),
                    raw_trace_uri=str(raw_trace_path),
                )
            )
        return task_runs

    def _run_simulation(
        self,
        dataset_id: str,
        skill_version: SkillVersion,
        runtime_config: Dict[str, Any],
        artifacts_dir: Path,
        run_id: str,
    ) -> List[TaskRun]:
        dataset = self._datasets.get(dataset_id)
        if not dataset:
            raise ValueError(
                f"Dataset '{dataset_id}' missing from registry {self.dataset_registry}. "
                "Provide HARBOR_DOCKER_IMAGE to run against real Harbor."
            )
        tasks = dataset["tasks"]
        if subset := runtime_config.get("task_subset"):
            task_lookup = {task["id"]: task for task in tasks}
            tasks = [task_lookup[task_id] for task_id in subset if task_id in task_lookup]
        task_limit = runtime_config.get("task_limit")
        if task_limit:
            tasks = tasks[:task_limit]

        task_runs: List[TaskRun] = []
        for task in tasks:
            simulation = self._simulate_task(skill_version, task, runtime_config)
            raw_trace_path = artifacts_dir / f"{task['id']}_raw_trace.json"
            raw_trace_path.write_text(json.dumps(simulation["raw_trace"], indent=2), encoding="utf-8")
            task_runs.append(
                TaskRun(
                    id=f"task_run_{task['id']}_{run_id}",
                    benchmark_run_id=run_id,
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
            )
        return task_runs

    # ------------------------------------------------------------------
    def _load_registry(self) -> Dict[str, Dict[str, Any]]:
        if not self.dataset_registry.exists():
            LOGGER.warning(
                "Dataset registry %s missing; Harbor runs require Docker configuration.",
                self.dataset_registry,
            )
            return {}
        payload = json.loads(self.dataset_registry.read_text(encoding="utf-8"))
        return {item["id"]: item for item in payload.get("datasets", [])}

    def _to_container_path(self, host_path: Path) -> str:
        try:
            rel = host_path.resolve().relative_to(self.workspace_root.resolve())
        except ValueError as exc:
            raise ValueError(
                f"Skill file {host_path} must live under the workspace root {self.workspace_root}"
            ) from exc
        return f"{self.workspace_mount}/{rel.as_posix()}"

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
