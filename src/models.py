from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional


@dataclass
class SkillVersion:
    id: str
    skill_name: str
    content: str
    parent_skill_version_id: Optional[str]
    generator: str
    generator_config: Dict[str, Any]
    created_at: datetime
    created_by_run_id: Optional[str]
    status: str = "draft"


@dataclass
class BenchmarkRun:
    id: str
    dataset_id: str
    agent_id: str
    model_id: str
    skill_version_id: str
    started_at: datetime
    completed_at: Optional[datetime]
    runtime_config: Dict[str, Any]
    summary_metrics: Dict[str, float] = field(default_factory=dict)
    status: str = "pending"
    artifacts_dir: Optional[Path] = None


@dataclass
class TaskRun:
    id: str
    benchmark_run_id: str
    task_id: str
    input_spec: Dict[str, Any]
    final_output: Dict[str, Any]
    pass_fail: bool
    latency_s: float
    tokens_in: int
    tokens_out: int
    cost_usd: float
    raw_trace_uri: Optional[str]
    normalized_trace_uri: Optional[str] = None


@dataclass
class GPAScore:
    task_run_id: str
    goal_fulfillment: float
    plan_quality: float
    plan_adherence: float
    execution_efficiency: float
    logical_consistency: float
    aggregate_gpa: float
    rationale: str
    failure_tags: List[str]


@dataclass
class CandidateComparison:
    baseline_skill_version_id: str
    candidate_skill_version_id: str
    dataset_id: str
    comparison_metrics: Dict[str, float]
    decision: str
    reason: str


@dataclass
class NormalizedTrace:
    task_id: str
    goal: str
    initial_context: str
    plan: List[Dict[str, Any]]
    actions: List[Dict[str, Any]]
    final_result: Dict[str, Any]
    metadata: Dict[str, Any]


@dataclass
class OptimizationContext:
    skill_version: SkillVersion
    benchmark_summary: Dict[str, Any]
    failing_traces: List[NormalizedTrace]
    successful_traces: List[NormalizedTrace]
    gpa_breakdown: List[GPAScore]
    outcome_metrics: Dict[str, Any]
    failure_taxonomy: Dict[str, int]
    prior_candidates: List[SkillVersion] = field(default_factory=list)
