from __future__ import annotations

import uuid
from collections import Counter
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Protocol, Tuple
from models import (
    BenchmarkRun,
    GPAScore,
    NormalizedTrace,
    OptimizationContext,
    SkillVersion,
    TaskRun,
)
from normalization.trace_normalizer import TraceNormalizer
from optimization.gepa_adapter import GEPAOptimizer
from optimization.upskill_adapter import UpskillOptimizer
from promotion.decider import PromotionDecider
from scoring.trulens_adapter import TruLensGPAEvaluator
from storage.repository import InMemoryRepository
from utils.io import write_json, write_jsonl
from settings import GepaSettings


@dataclass
class LoopConfig:
    dataset_id: str
    agent_id: str
    model_id: str
    runtime_config: Dict[str, Any]
    optimizer_name: str
    skill_path: Path
    skill_name: str
    output_dir: Path


@dataclass
class RunArtifacts:
    run: BenchmarkRun
    task_runs: List[TaskRun]
    gpa_scores: List[GPAScore]
    normalized_traces: Dict[str, NormalizedTrace]
    failure_taxonomy: Dict[str, int]


class BenchmarkRunnerProtocol(Protocol):
    def run_benchmark(
        self,
        dataset_id: str,
        agent_id: str,
        model_id: str,
        skill_version: SkillVersion,
        skill_file: Path,
        runtime_config: Dict[str, Any],
    ) -> Tuple[BenchmarkRun, List[TaskRun]]:
        ...


class SkillImprovementLoop:
    def __init__(
        self,
        repository: InMemoryRepository,
        benchmark_runner: BenchmarkRunnerProtocol,
        trace_normalizer: TraceNormalizer,
        gpa_evaluator: TruLensGPAEvaluator,
        promotion_decider: PromotionDecider,
        gepa_settings: GepaSettings | None = None,
    ) -> None:
        self.repository = repository
        self.benchmark_runner = benchmark_runner
        self.trace_normalizer = trace_normalizer
        self.gpa_evaluator = gpa_evaluator
        self.promotion_decider = promotion_decider
        self.gepa_settings = gepa_settings

    # ------------------------------------------------------------------
    def run(self, config: LoopConfig) -> Dict[str, Any]:
        baseline_version = self._register_skill(
            skill_name=config.skill_name,
            content=config.skill_path.read_text(encoding="utf-8"),
            generator="manual",
        )
        baseline_artifacts = self._execute_run(config, baseline_version)

        optimizer = self._build_optimizer(config.optimizer_name)
        context = self._build_context(baseline_version, baseline_artifacts)
        candidates = optimizer.propose_candidates(baseline_version.content, context)
        if not candidates:
            raise RuntimeError("Optimizer did not return any candidates.")
        candidate = candidates[0]
        candidate_version = self._register_skill(
            skill_name=config.skill_name,
            content=candidate.content,
            generator=config.optimizer_name,
            parent_id=baseline_version.id,
            generator_config={"rationale": candidate.rationale},
        )
        candidate_artifacts = self._execute_run(config, candidate_version)

        comparison = self.promotion_decider.decide(
            baseline_metrics=baseline_artifacts.run.summary_metrics,
            candidate_metrics=candidate_artifacts.run.summary_metrics,
            baseline_skill_id=baseline_version.id,
            candidate_skill_id=candidate_version.id,
            dataset_id=config.dataset_id,
        )
        self.repository.record_comparison(comparison)

        self._write_candidate_diff(
            config.output_dir,
            baseline_version,
            candidate_version,
            baseline_artifacts,
            candidate_artifacts,
            comparison,
        )

        return {
            "baseline": baseline_artifacts.run.summary_metrics,
            "candidate": candidate_artifacts.run.summary_metrics,
            "decision": asdict(comparison),
            "candidate_skill_path": self._persist_candidate_skill(
                config.output_dir,
                candidate_version,
            ),
        }

    # ------------------------------------------------------------------
    def _execute_run(
        self,
        config: LoopConfig,
        skill_version: SkillVersion,
    ) -> RunArtifacts:
        runtime_config = dict(config.runtime_config)
        runtime_config.update({"agent_id": config.agent_id, "model_id": config.model_id})
        skill_material_path = self._materialize_skill(config, skill_version)
        run, task_runs = self.benchmark_runner.run_benchmark(
            dataset_id=config.dataset_id,
            agent_id=config.agent_id,
            model_id=config.model_id,
            skill_version=skill_version,
            skill_file=skill_material_path,
            runtime_config=runtime_config,
        )
        normalized_traces: Dict[str, NormalizedTrace] = {}
        gpa_scores: List[GPAScore] = []
        failure_taxonomy: Counter[str] = Counter()
        for task_run in task_runs:
            normalized, normalized_path = self.trace_normalizer.normalize(task_run.raw_trace_uri)
            task_run.normalized_trace_uri = normalized_path
            gpa = self.gpa_evaluator.score_trace(normalized, task_run.input_spec)
            gpa.task_run_id = task_run.id
            gpa_scores.append(gpa)
            normalized_traces[task_run.id] = normalized
            for tag in gpa.failure_tags:
                failure_taxonomy[tag] += 1
        run.summary_metrics = self._compute_summary(task_runs, gpa_scores)
        self.repository.record_benchmark_run(run, task_runs, gpa_scores)
        self._persist_run_artifacts(run, task_runs, gpa_scores)
        return RunArtifacts(
            run=run,
            task_runs=task_runs,
            gpa_scores=gpa_scores,
            normalized_traces=normalized_traces,
            failure_taxonomy=dict(failure_taxonomy),
        )

    def _compute_summary(
        self,
        task_runs: List[TaskRun],
        gpa_scores: List[GPAScore],
    ) -> Dict[str, float]:
        total = len(task_runs) or 1
        pass_rate = sum(1 for task in task_runs if task.pass_fail) / total
        avg_latency = sum(task.latency_s for task in task_runs) / total
        avg_tokens = sum(task.tokens_in + task.tokens_out for task in task_runs) / total
        avg_cost = sum(task.cost_usd for task in task_runs) / total
        avg_gpa = sum(score.aggregate_gpa for score in gpa_scores) / total
        catastrophic = sum(
            1
            for score in gpa_scores
            if score.goal_fulfillment < 0.3 or score.aggregate_gpa < 0.3
        ) / total
        return {
            "pass_rate": round(pass_rate, 3),
            "avg_latency_s": round(avg_latency, 3),
            "avg_tokens": round(avg_tokens, 1),
            "avg_cost_usd": round(avg_cost, 4),
            "avg_gpa": round(avg_gpa, 3),
            "catastrophic_failure_rate": round(catastrophic, 3),
        }

    def _persist_run_artifacts(
        self,
        run: BenchmarkRun,
        task_runs: List[TaskRun],
        gpa_scores: List[GPAScore],
    ) -> None:
        if not run.artifacts_dir:
            return
        write_json(run.artifacts_dir / "summary.json", run.summary_metrics)
        task_payload = [asdict(task) for task in task_runs]
        write_jsonl(run.artifacts_dir / "task_runs.jsonl", task_payload)
        gpa_payload = [asdict(score) for score in gpa_scores]
        write_jsonl(run.artifacts_dir / "gpa_scores.jsonl", gpa_payload)

    def _build_context(
        self,
        skill_version: SkillVersion,
        artifacts: RunArtifacts,
    ) -> OptimizationContext:
        failing = [
            artifacts.normalized_traces[task.id]
            for task in artifacts.task_runs
            if not task.pass_fail
        ]
        successful = [
            artifacts.normalized_traces[task.id]
            for task in artifacts.task_runs
            if task.pass_fail
        ]
        return OptimizationContext(
            skill_version=skill_version,
            benchmark_summary=artifacts.run.summary_metrics,
            failing_traces=failing,
            successful_traces=successful,
            gpa_breakdown=artifacts.gpa_scores,
            outcome_metrics=artifacts.run.summary_metrics,
            failure_taxonomy=artifacts.failure_taxonomy,
        )

    def _build_optimizer(self, name: str):
        normalized = name.lower()
        if normalized == "upskill":
            return UpskillOptimizer()
        if normalized == "gepa":
            if not self.gepa_settings:
                raise ValueError(
                    "GEPA settings missing. Provide GEPA_* variables in your .env file."
                )
            return GEPAOptimizer(settings=self.gepa_settings)
        raise ValueError(f"Unsupported optimizer '{name}'.")

    def _register_skill(
        self,
        skill_name: str,
        content: str,
        generator: str,
        parent_id: str | None = None,
        generator_config: Dict[str, Any] | None = None,
    ) -> SkillVersion:
        skill_id = f"{skill_name}-{uuid.uuid4().hex[:8]}"
        skill_version = SkillVersion(
            id=skill_id,
            skill_name=skill_name,
            content=content,
            parent_skill_version_id=parent_id,
            generator=generator,
            generator_config=generator_config or {},
            created_at=datetime.utcnow(),
            created_by_run_id=None,
            status="draft",
        )
        self.repository.register_skill_version(skill_version)
        return skill_version

    def _persist_candidate_skill(
        self,
        output_dir: Path,
        skill_version: SkillVersion,
    ) -> str:
        candidates_dir = output_dir / "generated_skills"
        candidates_dir.mkdir(parents=True, exist_ok=True)
        candidate_path = candidates_dir / f"{skill_version.id}.md"
        candidate_path.write_text(skill_version.content, encoding="utf-8")
        return str(candidate_path)

    def _materialize_skill(
        self,
        config: LoopConfig,
        skill_version: SkillVersion,
    ) -> Path:
        skills_cache = config.output_dir / "skills_cache"
        skills_cache.mkdir(parents=True, exist_ok=True)
        cache_path = skills_cache / f"{skill_version.id}.md"
        cache_path.write_text(skill_version.content, encoding="utf-8")
        return cache_path

    def _write_candidate_diff(
        self,
        output_dir: Path,
        baseline: SkillVersion,
        candidate: SkillVersion,
        baseline_artifacts: RunArtifacts,
        candidate_artifacts: RunArtifacts,
        comparison,
    ) -> None:
        diff_dir = output_dir / "reports"
        diff_dir.mkdir(parents=True, exist_ok=True)
        diff_path = diff_dir / "candidate_diff.md"
        lines = [
            f"# Candidate Comparison\n",
            f"Baseline: {baseline.id}\n",
            f"Candidate: {candidate.id}\n",
            "\n## Metrics\n",
        ]
        for key, value in baseline_artifacts.run.summary_metrics.items():
            candidate_value = candidate_artifacts.run.summary_metrics.get(key)
            lines.append(
                f"- {key}: baseline={value} | candidate={candidate_value}"
            )
        lines.append("\n## Decision\n")
        lines.append(f"- Outcome: {comparison.decision}\n")
        lines.append(f"- Reason: {comparison.reason}\n")
        diff_path.write_text("\n".join(lines), encoding="utf-8")
        write_json(diff_dir / "promotion_decision.json", asdict(comparison))
