from __future__ import annotations

from statistics import mean
from typing import Dict, List, Tuple

from models import GPAScore, NormalizedTrace


class TruLensGPAEvaluator:
    """Synthetic TruLens GPA evaluator for the MVP."""

    def score_trace(
        self,
        normalized_trace: NormalizedTrace,
        task_spec: Dict,
    ) -> GPAScore:
        plan_steps = max(1, len(normalized_trace.plan))
        action_count = max(1, len(normalized_trace.actions))
        passed = bool(normalized_trace.final_result.get("passed"))

        goal_fulfillment = 0.9 if passed else 0.35
        plan_quality = min(1.0, 0.4 + plan_steps * 0.08)
        plan_ratio = action_count / plan_steps
        plan_adherence = max(0.1, 1.1 - abs(1 - plan_ratio) * 0.4)
        execution_efficiency = max(0.1, 0.8 - max(0, plan_ratio - 1.2) * 0.3)
        logical_consistency = min(1.0, 0.5 + passed * 0.3 + (plan_quality - 0.5) * 0.4)

        aggregate = mean(
            [
                goal_fulfillment,
                plan_quality,
                plan_adherence,
                execution_efficiency,
                logical_consistency,
            ]
        )

        failure_tags: List[str] = []
        if not passed:
            failure_tags.append("goal-miss")
        if plan_quality < 0.55:
            failure_tags.append("weak-plan")
        if plan_adherence < 0.6:
            failure_tags.append("deviated-from-plan")
        if execution_efficiency < 0.5:
            failure_tags.append("redundant-actions")
        if logical_consistency < 0.5:
            failure_tags.append("hallucinated-state")

        rationale = self._build_rationale(
            passed,
            goal_fulfillment,
            failure_tags,
            task_spec.get("goal", "task"),
        )

        return GPAScore(
            task_run_id="",  # filled by orchestrator later
            goal_fulfillment=round(goal_fulfillment, 3),
            plan_quality=round(plan_quality, 3),
            plan_adherence=round(plan_adherence, 3),
            execution_efficiency=round(execution_efficiency, 3),
            logical_consistency=round(logical_consistency, 3),
            aggregate_gpa=round(aggregate, 3),
            rationale=rationale,
            failure_tags=failure_tags,
        )

    def _build_rationale(
        self,
        passed: bool,
        goal_fulfillment: float,
        failure_tags: List[str],
        goal: str,
    ) -> str:
        status = "met" if passed else "missed"
        tags = ", ".join(failure_tags) if failure_tags else "no major issues"
        return (
            f"Goal '{goal}' was {status} with fulfillment score {goal_fulfillment:.2f}; "
            f"diagnostics: {tags}."
        )
