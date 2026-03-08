from __future__ import annotations

import logging
import subprocess
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Tuple

from adapters.harbor import HarborRunner
from models import BenchmarkRun, SkillVersion, TaskRun
from utils.io import ensure_dir, load_jsonl

LOGGER = logging.getLogger(__name__)


class SkillBenchRunner:
    """Run SkillBench in Docker; fall back to local simulation for quick checks."""

    def __init__(
        self,
        dataset_registry: Path,
        artifacts_root: Path,
        workspace_root: Path,
        docker_image: str | None,
        docker_command: str = "docker",
        workspace_mount: str = "/workspace",
        results_mount: str = "/skillbench/artifacts",
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
        self._simulation_runner = HarborRunner(
            dataset_registry=dataset_registry,
            artifacts_root=artifacts_root,
            workspace_root=workspace_root,
            docker_image=None,
            docker_command=docker_command,
            workspace_mount=workspace_mount,
            results_mount=results_mount,
            extra_env=extra_env,
        )

    def run_benchmark(
        self,
        dataset_id: str,
        agent_id: str,
        model_id: str,
        skill_version: SkillVersion,
        skill_file: Path,
        runtime_config: Dict[str, Any],
    ) -> Tuple[BenchmarkRun, List[TaskRun]]:
        if not self.docker_image:
            # Reuse deterministic simulation runner to keep local development fast.
            return self._simulation_runner.run_benchmark(
                dataset_id=dataset_id,
                agent_id=agent_id,
                model_id=model_id,
                skill_version=skill_version,
                skill_file=skill_file,
                runtime_config=runtime_config,
            )

        run_id = runtime_config.get("run_id") or f"skillbench_{uuid.uuid4().hex[:8]}"
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
        task_runs = self._run_skillbench_docker(
            dataset_id=dataset_id,
            agent_id=agent_id,
            model_id=model_id,
            skill_file=skill_file,
            runtime_config=runtime_config,
            artifacts_dir=artifacts_dir,
            run_id=run_id,
        )
        run.completed_at = datetime.utcnow()
        run.status = "completed"
        return run, task_runs

    def _run_skillbench_docker(
        self,
        dataset_id: str,
        agent_id: str,
        model_id: str,
        skill_file: Path,
        runtime_config: Dict[str, Any],
        artifacts_dir: Path,
        run_id: str,
    ) -> List[TaskRun]:
        assert self.docker_image is not None
        skill_container_path = self._to_container_path(skill_file)
        cmd = [
            self.docker_command,
            "run",
            "--rm",
            "-v",
            f"{self.workspace_root}:{self.workspace_mount}",
            "-v",
            f"{artifacts_dir}:{self.results_mount}",
        ]
        for key, value in self.extra_env.items():
            cmd.extend(["-e", f"{key}={value}"])
        cmd.extend(
            [
                "-e",
                f"SKILLBENCH_DATASET_ID={dataset_id}",
                "-e",
                f"SKILLBENCH_AGENT_ID={agent_id}",
                "-e",
                f"SKILLBENCH_MODEL_ID={model_id}",
                "-e",
                f"SKILLBENCH_SKILL_PATH={skill_container_path}",
                "-e",
                f"SKILLBENCH_OUTPUT_DIR={self.results_mount}",
                self.docker_image,
                "skillbench",
                "run",
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

        LOGGER.info("Running SkillBench via Docker: %s", " ".join(cmd))
        proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
        if proc.returncode != 0:
            raise RuntimeError(
                f"SkillBench Docker run failed with exit code {proc.returncode}.\n"
                f"STDOUT:\n{proc.stdout}\nSTDERR:\n{proc.stderr}"
            )

        manifest = artifacts_dir / "task_runs.jsonl"
        if not manifest.exists():
            raise FileNotFoundError(
                f"Expected SkillBench to produce {manifest}, but it is missing."
            )
        rows = load_jsonl(manifest)
        task_runs: List[TaskRun] = []
        for row in rows:
            task_id = row.get("task_id") or row.get("id") or "unknown-task"
            raw_trace_uri = row.get("raw_trace_uri") or row.get("raw_trace_path")
            if raw_trace_uri is None:
                raw_trace_uri = f"raw_traces/{task_id}.json"
            task_runs.append(
                TaskRun(
                    id=row.get("task_run_id", f"task_run_{task_id}_{run_id}"),
                    benchmark_run_id=row.get("benchmark_run_id", run_id),
                    task_id=task_id,
                    input_spec=row.get("input_spec", {}),
                    final_output=row.get("final_output") or {"answer": row.get("answer")},
                    pass_fail=bool(row.get("pass_fail", row.get("passed", False))),
                    latency_s=float(row.get("latency_s", 0.0)),
                    tokens_in=int(row.get("tokens_in", 0)),
                    tokens_out=int(row.get("tokens_out", 0)),
                    cost_usd=float(row.get("cost_usd", 0.0)),
                    raw_trace_uri=str(artifacts_dir / raw_trace_uri),
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
