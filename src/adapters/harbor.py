from __future__ import annotations

import json
import logging
import os
import random
import shlex
import shutil
import subprocess
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Tuple

from models import BenchmarkRun, SkillVersion, TaskRun
from utils.io import ensure_dir, load_jsonl

LOGGER = logging.getLogger(__name__)


class HarborRunner:
    """Run Harbor benchmarks via native CLI or Docker, with simulation fallback."""

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
        command: str = "harbor",
        strict_real: bool = False,
        dataset_path: Path | None = None,
    ) -> None:
        self.dataset_registry = dataset_registry
        self.artifacts_root = artifacts_root
        self.workspace_root = workspace_root
        self.docker_image = docker_image
        self.docker_command = docker_command
        self.workspace_mount = workspace_mount.rstrip("/")
        self.results_mount = results_mount.rstrip("/")
        self.extra_env = extra_env or {}
        self.command = command
        self.strict_real = strict_real
        self.dataset_path = dataset_path
        ensure_dir(self.artifacts_root)
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

        if self.docker_image:
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
        elif self._should_use_harbor_cli(runtime_config):
            task_runs = self._run_harbor_cli(
                dataset_id=dataset_id,
                agent_id=agent_id,
                model_id=model_id,
                skill_file=skill_file,
                runtime_config=runtime_config,
                artifacts_dir=artifacts_dir,
                run_id=run_id,
            )
        else:
            if self.strict_real or runtime_config.get("strict_real"):
                raise RuntimeError(
                    "Strict mode requires a real Harbor integration. Configure HARBOR_DOCKER_IMAGE "
                    "or provide --harbor-path with Harbor CLI installed."
                )
            task_runs = self._run_simulation(
                dataset_id=dataset_id,
                skill_version=skill_version,
                runtime_config=runtime_config,
                artifacts_dir=artifacts_dir,
                run_id=run_id,
            )

        run.completed_at = datetime.utcnow()
        run.status = "completed"
        return run, task_runs

    # ------------------------------------------------------------------
    def _should_use_harbor_cli(self, runtime_config: Dict[str, Any]) -> bool:
        return bool(
            runtime_config.get("dataset_path")
            or self.dataset_path
            or runtime_config.get("strict_real")
            or self.strict_real
        )

    def _run_harbor_cli(
        self,
        dataset_id: str,
        agent_id: str,
        model_id: str,
        skill_file: Path,
        runtime_config: Dict[str, Any],
        artifacts_dir: Path,
        run_id: str,
    ) -> List[TaskRun]:
        base_cmd = shlex.split(self.command)
        if not base_cmd:
            raise RuntimeError("HARBOR_CMD is empty.")
        if shutil.which(base_cmd[0]) is None:
            raise RuntimeError(
                f"Harbor command '{base_cmd[0]}' not found on PATH. Install Harbor or set HARBOR_CMD."
            )

        cmd = list(base_cmd)
        cmd.extend(
            [
                "run",
                "--job-name",
                run_id,
                "--jobs-dir",
                str(self.artifacts_root),
                "-a",
                agent_id,
                "-m",
                model_id,
                "--agent-kwarg",
                f"skill_path={skill_file}",
                "--agent-env",
                f"SKILL_PATH={skill_file}",
            ]
        )

        dataset_path = runtime_config.get("dataset_path") or self.dataset_path
        if dataset_path:
            cmd.extend(["-p", str(Path(dataset_path).expanduser().resolve())])
        else:
            cmd.extend(["--dataset", dataset_id])
            if self._is_probable_harbor_registry(self.dataset_registry):
                cmd.extend(["--registry-path", str(self.dataset_registry)])

        if subset := runtime_config.get("task_subset"):
            for task_id in subset:
                cmd.extend(["--task-name", task_id])
        elif task_limit := runtime_config.get("task_limit"):
            cmd.extend(["--n-tasks", str(task_limit)])

        env = os.environ.copy()
        env.update(self.extra_env)

        LOGGER.info("Running Harbor via CLI: %s", " ".join(cmd))
        proc = subprocess.run(
            cmd,
            cwd=self.workspace_root,
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )
        (artifacts_dir / "harbor_stdout.log").write_text(proc.stdout, encoding="utf-8")
        (artifacts_dir / "harbor_stderr.log").write_text(proc.stderr, encoding="utf-8")
        if proc.returncode != 0:
            raise RuntimeError(
                f"Harbor CLI run failed with exit code {proc.returncode}.\n"
                f"STDOUT:\n{proc.stdout}\nSTDERR:\n{proc.stderr}"
            )

        job_dir = self.artifacts_root / run_id
        if not job_dir.exists():
            raise FileNotFoundError(
                f"Harbor job dir {job_dir} was not created. Check Harbor logs in {artifacts_dir}."
            )
        return self._parse_harbor_job(job_dir=job_dir, run_id=run_id)

    def _parse_harbor_job(self, job_dir: Path, run_id: str) -> List[TaskRun]:
        task_runs: List[TaskRun] = []
        trial_dirs = sorted(
            path
            for path in job_dir.iterdir()
            if path.is_dir() and (path / "result.json").exists()
        )
        for index, trial_dir in enumerate(trial_dirs):
            result_payload = json.loads((trial_dir / "result.json").read_text(encoding="utf-8"))
            trajectory_payload = self._load_trajectory(trial_dir)
            task_run = self._build_task_run_from_trial(
                result=result_payload,
                trajectory=trajectory_payload,
                trial_dir=trial_dir,
                run_id=run_id,
                index=index,
            )
            task_runs.append(task_run)

        if not task_runs:
            raise RuntimeError(
                f"Harbor job {job_dir} completed but no trial result.json files were found."
            )
        return task_runs

    def _load_trajectory(self, trial_dir: Path) -> Dict[str, Any] | None:
        primary = trial_dir / "agent" / "trajectory.json"
        if primary.exists():
            return json.loads(primary.read_text(encoding="utf-8"))

        fallback = sorted((trial_dir / "agent").glob("*.trajectory.json"))
        if fallback:
            return json.loads(fallback[0].read_text(encoding="utf-8"))
        return None

    def _build_task_run_from_trial(
        self,
        result: Dict[str, Any],
        trajectory: Dict[str, Any] | None,
        trial_dir: Path,
        run_id: str,
        index: int,
    ) -> TaskRun:
        task_id = str(result.get("task_name") or result.get("trial_name") or f"task-{index + 1}")
        verifier = result.get("verifier_result") or {}
        rewards = verifier.get("rewards") if isinstance(verifier, dict) else None
        pass_fail = self._infer_success(rewards, result.get("exception_info"))

        started_at = self._parse_iso_datetime(result.get("started_at"))
        finished_at = self._parse_iso_datetime(result.get("finished_at"))
        latency_s = 0.0
        if started_at and finished_at:
            latency_s = max(0.0, (finished_at - started_at).total_seconds())

        final_metrics = (trajectory or {}).get("final_metrics") or {}
        tokens_in = int(final_metrics.get("total_prompt_tokens") or 0)
        tokens_out = int(final_metrics.get("total_completion_tokens") or 0)
        cost_usd = float(final_metrics.get("total_cost_usd") or 0.0)

        final_answer = self._extract_final_answer(trajectory)
        if not final_answer:
            if rewards:
                final_answer = json.dumps(rewards)
            elif result.get("exception_info"):
                final_answer = str(result["exception_info"].get("exception_message", "failed"))
            else:
                final_answer = "completed"

        raw_trace_payload = self._build_raw_trace(
            task_id=task_id,
            result=result,
            trajectory=trajectory,
            pass_fail=pass_fail,
            final_answer=final_answer,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            latency_s=latency_s,
        )
        raw_trace_name = f"{self._safe_filename(task_id)}_{index + 1}_raw_trace.json"
        raw_trace_path = trial_dir / raw_trace_name
        raw_trace_path.write_text(json.dumps(raw_trace_payload, indent=2), encoding="utf-8")

        task_run_id = str(result.get("id") or f"task_run_{self._safe_filename(task_id)}_{run_id}")
        return TaskRun(
            id=task_run_id,
            benchmark_run_id=run_id,
            task_id=task_id,
            input_spec={
                "task_name": task_id,
                "source": result.get("source"),
                "trial_name": result.get("trial_name"),
                "rewards": rewards or {},
            },
            final_output={
                "answer": final_answer,
                "rewards": rewards or {},
            },
            pass_fail=pass_fail,
            latency_s=round(latency_s, 3),
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            cost_usd=round(cost_usd, 6),
            raw_trace_uri=str(raw_trace_path),
        )

    def _build_raw_trace(
        self,
        task_id: str,
        result: Dict[str, Any],
        trajectory: Dict[str, Any] | None,
        pass_fail: bool,
        final_answer: str,
        tokens_in: int,
        tokens_out: int,
        latency_s: float,
    ) -> Dict[str, Any]:
        goal = self._resolve_goal(result, task_id)
        plan = self._extract_plan(trajectory, goal)
        actions = self._extract_actions(trajectory, final_answer)

        agent_info = result.get("agent_info") or {}
        model_info = agent_info.get("model_info") or {}
        metadata = {
            "model_id": model_info.get("name") or "unknown",
            "agent_id": agent_info.get("name") or "unknown",
            "skill_version_id": "unknown",
            "tokens_in": tokens_in,
            "tokens_out": tokens_out,
            "latency_s": round(latency_s, 3),
            "source": result.get("source"),
            "trial_name": result.get("trial_name"),
        }

        return {
            "task_id": task_id,
            "goal": goal,
            "initial_context": result.get("source") or "",
            "plan": plan,
            "actions": actions,
            "final_result": {
                "output": final_answer,
                "passed": pass_fail,
            },
            "metadata": metadata,
        }

    def _resolve_goal(self, result: Dict[str, Any], fallback: str) -> str:
        task_cfg = (result.get("config") or {}).get("task") or {}
        task_path = task_cfg.get("path")
        if isinstance(task_path, str) and task_path:
            candidate = Path(task_path)
            if not candidate.is_absolute():
                candidate = (self.workspace_root / candidate).resolve()
            instruction_path = candidate / "instruction.md"
            if instruction_path.exists():
                text = instruction_path.read_text(encoding="utf-8").strip()
                if text:
                    return " ".join(text.splitlines()[:6])
        return fallback

    def _extract_plan(
        self,
        trajectory: Dict[str, Any] | None,
        goal: str,
    ) -> List[Dict[str, str]]:
        steps = (trajectory or {}).get("steps") or []
        plan: List[Dict[str, str]] = []
        for step in steps:
            if step.get("source") != "agent":
                continue
            reasoning = step.get("reasoning_content")
            if not isinstance(reasoning, str) or not reasoning.strip():
                continue
            first_line = next((line.strip() for line in reasoning.splitlines() if line.strip()), "")
            if not first_line:
                continue
            plan.append(
                {
                    "step_id": f"step-{len(plan) + 1}",
                    "description": first_line[:200],
                }
            )
            if len(plan) >= 6:
                break

        if not plan:
            plan.append(
                {
                    "step_id": "step-1",
                    "description": f"Solve the task goal: {goal}",
                }
            )
        return plan

    def _extract_actions(
        self,
        trajectory: Dict[str, Any] | None,
        final_answer: str,
    ) -> List[Dict[str, Any]]:
        steps = (trajectory or {}).get("steps") or []
        actions: List[Dict[str, Any]] = []

        for step in steps:
            if step.get("source") != "agent":
                continue
            timestamp = step.get("timestamp") or datetime.utcnow().isoformat() + "Z"

            reasoning = step.get("reasoning_content")
            if isinstance(reasoning, str) and reasoning.strip():
                actions.append(
                    {
                        "timestamp": timestamp,
                        "type": "thought",
                        "content": reasoning.strip()[:2000],
                        "tool_name": None,
                        "observation": None,
                    }
                )

            message_text = self._content_to_text(step.get("message"))
            if message_text:
                actions.append(
                    {
                        "timestamp": timestamp,
                        "type": "thought",
                        "content": message_text[:2000],
                        "tool_name": None,
                        "observation": None,
                    }
                )

            tool_calls = step.get("tool_calls") or []
            for tool_call in tool_calls:
                tool_name = tool_call.get("function_name") or tool_call.get("name")
                tool_args = tool_call.get("arguments")
                if isinstance(tool_args, (dict, list)):
                    args_text = json.dumps(tool_args, ensure_ascii=True)
                else:
                    args_text = str(tool_args or "")
                observation = self._observation_to_text(step.get("observation"))
                actions.append(
                    {
                        "timestamp": timestamp,
                        "type": "tool_call",
                        "content": args_text[:2000],
                        "tool_name": tool_name,
                        "observation": observation[:2000] if observation else None,
                    }
                )

        actions.append(
            {
                "timestamp": datetime.utcnow().isoformat() + "Z",
                "type": "final_answer",
                "content": final_answer,
                "tool_name": None,
                "observation": None,
            }
        )
        return actions

    def _content_to_text(self, content: Any) -> str:
        if content is None:
            return ""
        if isinstance(content, str):
            return content.strip()
        if isinstance(content, list):
            chunks: List[str] = []
            for item in content:
                if isinstance(item, dict):
                    if item.get("type") == "text":
                        text = item.get("text")
                        if isinstance(text, str):
                            chunks.append(text)
                    elif "text" in item and isinstance(item["text"], str):
                        chunks.append(item["text"])
                elif isinstance(item, str):
                    chunks.append(item)
            return "\n".join(chunks).strip()
        if isinstance(content, dict):
            text = content.get("text")
            if isinstance(text, str):
                return text.strip()
        return str(content).strip()

    def _observation_to_text(self, observation: Any) -> str:
        if not isinstance(observation, dict):
            return ""
        results = observation.get("results") or []
        chunks: List[str] = []
        for result in results:
            if not isinstance(result, dict):
                continue
            chunks.append(self._content_to_text(result.get("content")))
        return "\n".join(filter(None, chunks)).strip()

    def _extract_final_answer(self, trajectory: Dict[str, Any] | None) -> str:
        if not trajectory:
            return ""
        steps = trajectory.get("steps") or []
        for step in reversed(steps):
            if step.get("source") == "agent":
                text = self._content_to_text(step.get("message"))
                if text:
                    return text
        return ""

    def _infer_success(self, rewards: Any, exception_info: Any) -> bool:
        if exception_info is not None:
            return False
        if not isinstance(rewards, dict) or not rewards:
            return False

        reward_value = rewards.get("reward")
        if isinstance(reward_value, (int, float)):
            return float(reward_value) >= 0.5

        numeric_values: List[float] = []
        for value in rewards.values():
            if isinstance(value, bool):
                numeric_values.append(1.0 if value else 0.0)
            elif isinstance(value, (int, float)):
                numeric_values.append(float(value))

        if not numeric_values:
            return False

        if max(numeric_values) <= 1.0 and min(numeric_values) >= 0.0:
            return min(numeric_values) >= 0.999
        return (sum(numeric_values) / len(numeric_values)) > 0.0

    def _parse_iso_datetime(self, raw: Any) -> datetime | None:
        if not isinstance(raw, str) or not raw:
            return None
        try:
            return datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except ValueError:
            return None

    def _safe_filename(self, value: str) -> str:
        return "".join(ch if ch.isalnum() or ch in {"-", "_", "."} else "_" for ch in value)

    def _is_probable_harbor_registry(self, path: Path) -> bool:
        if not path.exists() or not path.is_file():
            return False
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return False
        datasets = payload.get("datasets") if isinstance(payload, dict) else None
        if not isinstance(datasets, list) or not datasets:
            return False
        first = datasets[0]
        return isinstance(first, dict) and "name" in first and "tasks" in first

    # ------------------------------------------------------------------
    # Legacy Docker contract mode
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

    def _to_container_path(self, host_path: Path) -> str:
        try:
            rel = host_path.resolve().relative_to(self.workspace_root.resolve())
        except ValueError as exc:
            raise ValueError(
                f"Skill file {host_path} must live under the workspace root {self.workspace_root}"
            ) from exc
        return f"{self.workspace_mount}/{rel.as_posix()}"

    # ------------------------------------------------------------------
    # Local simulation mode (legacy dev convenience)
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
                "Provide real Harbor configuration to run against actual benchmarks."
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

    def _load_registry(self) -> Dict[str, Dict[str, Any]]:
        if not self.dataset_registry.exists():
            LOGGER.warning(
                "Dataset registry %s missing; simulation mode is unavailable.",
                self.dataset_registry,
            )
            return {}
        payload = json.loads(self.dataset_registry.read_text(encoding="utf-8"))
        return {item["id"]: item for item in payload.get("datasets", []) if "id" in item}

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
