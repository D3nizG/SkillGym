from __future__ import annotations

from dataclasses import dataclass
from typing import Dict

from ..models import CandidateComparison


@dataclass
class PromotionGates:
    min_pass_rate_delta: float = 0.03
    max_catastrophic_delta: float = 0.0
    min_gpa_delta: float = 0.0
    max_token_ratio: float = 1.10


class PromotionDecider:
    """Applies baseline vs candidate comparisons with explicit gates."""

    def __init__(self, gates: PromotionGates | None = None) -> None:
        self.gates = gates or PromotionGates()

    def decide(
        self,
        baseline_metrics: Dict[str, float],
        candidate_metrics: Dict[str, float],
        baseline_skill_id: str,
        candidate_skill_id: str,
        dataset_id: str,
    ) -> CandidateComparison:
        deltas = self._compute_deltas(baseline_metrics, candidate_metrics)
        decision, reason = self._evaluate_gates(deltas, baseline_metrics, candidate_metrics)
        return CandidateComparison(
            baseline_skill_version_id=baseline_skill_id,
            candidate_skill_version_id=candidate_skill_id,
            dataset_id=dataset_id,
            comparison_metrics=deltas,
            decision=decision,
            reason=reason,
        )

    # ------------------------------------------------------------------
    def _compute_deltas(
        self,
        baseline: Dict[str, float],
        candidate: Dict[str, float],
    ) -> Dict[str, float]:
        keys = {
            "pass_rate",
            "avg_gpa",
            "avg_cost_usd",
            "avg_latency_s",
            "avg_tokens",
            "catastrophic_failure_rate",
        }
        deltas = {}
        for key in keys:
            deltas[f"delta_{key}"] = candidate.get(key, 0.0) - baseline.get(key, 0.0)
        return deltas

    def _evaluate_gates(
        self,
        deltas: Dict[str, float],
        baseline: Dict[str, float],
        candidate: Dict[str, float],
    ) -> tuple[str, str]:
        gates = self.gates
        reasons = []
        promote = True

        if deltas["delta_pass_rate"] < gates.min_pass_rate_delta:
            promote = False
            reasons.append(
                f"Pass rate delta {deltas['delta_pass_rate']:.3f} below gate {gates.min_pass_rate_delta:.3f}."
            )
        if deltas["delta_catastrophic_failure_rate"] > gates.max_catastrophic_delta:
            promote = False
            reasons.append("Catastrophic failure rate regressed.")
        if deltas["delta_avg_gpa"] < gates.min_gpa_delta:
            promote = False
            reasons.append("Average GPA did not improve.")
        token_ratio = candidate.get("avg_tokens", 1.0) / max(baseline.get("avg_tokens", 1.0), 1e-6)
        if token_ratio > gates.max_token_ratio:
            promote = False
            reasons.append(
                f"Token ratio {token_ratio:.2f} exceeds {gates.max_token_ratio:.2f}."
            )

        if promote:
            return "promote", "All promotion gates satisfied."
        if deltas["delta_pass_rate"] > 0:
            return "manual_review", "; ".join(reasons)
        return "reject", "; ".join(reasons)
