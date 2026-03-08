from __future__ import annotations

import logging
import os
from statistics import mean
from typing import Dict, List, Tuple

from models import GPAScore, NormalizedTrace

try:
    from trulens.providers.openai.provider import OpenAI
except Exception:  # pragma: no cover - optional dependency
    OpenAI = None

LOGGER = logging.getLogger(__name__)


class TruLensGPAEvaluator:
    """Evaluate traces with TruLens OpenAI providers (fallbacks to heuristics)."""

    def __init__(
        self,
        judge_model: str = "gpt-4o-mini",
        api_key: str | None = None,
        instructions: str | None = None,
        strict_mode: bool = False,
    ) -> None:
        self.judge_model = judge_model
        self.strict_mode = strict_mode
        self.instructions = instructions or (
            "Score the agent on goal fulfillment, planning, adherence, efficiency, and consistency. "
            "Return clear rationales."
        )
        self._provider = None
        if api_key:
            os.environ.setdefault("OPENAI_API_KEY", api_key)
        if OpenAI is not None and os.getenv("OPENAI_API_KEY"):
            try:
                self._provider = OpenAI(model_engine=self.judge_model)
            except Exception as exc:  # pragma: no cover - network dependency
                if self.strict_mode:
                    raise RuntimeError(
                        f"Failed to initialize TruLens provider in strict mode: {exc}"
                    ) from exc
                LOGGER.warning("Failed to initialize TruLens OpenAI provider: %s", exc)
                self._provider = None
        elif self.strict_mode:
            raise RuntimeError(
                "Strict mode requires TruLens OpenAI provider. Set OPENAI_API_KEY and ensure "
                "trulens-providers-openai is installed."
            )

    def score_trace(
        self,
        normalized_trace: NormalizedTrace,
        task_spec: Dict,
    ) -> GPAScore:
        if self._provider is None:
            if self.strict_mode:
                raise RuntimeError(
                    "Strict mode enabled but TruLens provider is unavailable."
                )
            return self._fallback(normalized_trace, task_spec)
        try:
            return self._score_with_trulens(normalized_trace, task_spec)
        except Exception as exc:  # pragma: no cover - network dependency
            if self.strict_mode:
                raise RuntimeError(
                    f"Strict mode disallows TruLens fallback; scoring failed: {exc}"
                ) from exc
            LOGGER.warning("TruLens evaluation failed (%s); using fallback.", exc)
            return self._fallback(normalized_trace, task_spec)

    # ------------------------------------------------------------------
    def _score_with_trulens(
        self,
        normalized_trace: NormalizedTrace,
        task_spec: Dict,
    ) -> GPAScore:
        provider = self._provider
        assert provider is not None
        goal_prompt = normalized_trace.goal or task_spec.get("goal", "Task goal")
        final_answer = normalized_trace.final_result.get("output", "")
        goal_score, goal_meta = provider.relevance_with_cot_reasons(
            prompt=goal_prompt,
            response=final_answer,
            criteria="Does the final answer satisfy the goal and constraints?",
            additional_instructions=self.instructions,
        )

        trace_text = self._serialize_trace(normalized_trace)
        plan_text = self._serialize_plan(normalized_trace)
        plan_quality, plan_meta = provider.plan_quality_with_cot_reasons(
            trace=plan_text,
            criteria="Rate the decomposition quality and coverage.",
        )
        plan_adherence, adherence_meta = provider.plan_adherence_with_cot_reasons(
            trace=trace_text,
            criteria="Did the actions follow the stated plan without drift?",
        )
        execution_efficiency, eff_meta = provider.execution_efficiency_with_cot_reasons(
            trace=trace_text,
            criteria="Did the agent minimize redundant tool calls or looping?",
        )
        logical_consistency, logic_meta = provider.logical_consistency_with_cot_reasons(
            trace=trace_text,
            criteria="Were thoughts/actions consistent with prior context and state?",
        )

        goal_norm = self._normalize(goal_score)
        plan_quality_norm = self._normalize(plan_quality)
        plan_adherence_norm = self._normalize(plan_adherence)
        execution_efficiency_norm = self._normalize(execution_efficiency)
        logical_consistency_norm = self._normalize(logical_consistency)

        aggregate = mean(
            [
                goal_norm,
                plan_quality_norm,
                plan_adherence_norm,
                execution_efficiency_norm,
                logical_consistency_norm,
            ]
        )

        failure_tags = self._tags_from_scores(
            goal_norm,
            plan_quality_norm,
            plan_adherence_norm,
            execution_efficiency_norm,
            logical_consistency_norm,
        )
        rationale = " | ".join(
            filter(
                None,
                [
                    self._extract_reason(goal_meta, "goal"),
                    self._extract_reason(plan_meta, "plan"),
                    self._extract_reason(adherence_meta, "adherence"),
                    self._extract_reason(eff_meta, "efficiency"),
                    self._extract_reason(logic_meta, "consistency"),
                ],
            )
        )

        return GPAScore(
            task_run_id="",
            goal_fulfillment=round(goal_norm, 3),
            plan_quality=round(plan_quality_norm, 3),
            plan_adherence=round(plan_adherence_norm, 3),
            execution_efficiency=round(execution_efficiency_norm, 3),
            logical_consistency=round(logical_consistency_norm, 3),
            aggregate_gpa=round(aggregate, 3),
            rationale=rationale or "TruLens judge completed without rationale.",
            failure_tags=failure_tags,
        )

    def _fallback(self, normalized_trace: NormalizedTrace, task_spec: Dict) -> GPAScore:
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
        failure_tags = self._tags_from_scores(
            goal_fulfillment,
            plan_quality,
            plan_adherence,
            execution_efficiency,
            logical_consistency,
        )
        rationale = self._build_rationale(
            passed,
            goal_fulfillment,
            failure_tags,
            task_spec.get("goal", "task"),
        )
        return GPAScore(
            task_run_id="",
            goal_fulfillment=round(goal_fulfillment, 3),
            plan_quality=round(plan_quality, 3),
            plan_adherence=round(plan_adherence, 3),
            execution_efficiency=round(execution_efficiency, 3),
            logical_consistency=round(logical_consistency, 3),
            aggregate_gpa=round(aggregate, 3),
            rationale=rationale,
            failure_tags=failure_tags,
        )

    # ------------------------------------------------------------------
    def _normalize(self, score: float, min_val: float = 0.0, max_val: float = 3.0) -> float:
        span = max_val - min_val
        if span <= 0:
            return 0.0
        return max(0.0, min(1.0, (score - min_val) / span))

    def _serialize_plan(self, trace: NormalizedTrace) -> str:
        if not trace.plan:
            return "No plan was recorded."
        return "\n".join(f"{step.get('step_id')}: {step.get('description')}" for step in trace.plan)

    def _serialize_trace(self, trace: NormalizedTrace) -> str:
        lines = [f"Goal: {trace.goal}", f"Context: {trace.initial_context}"]
        for action in trace.actions:
            entry = (
                f"[{action.get('timestamp')}] "
                f"{action.get('type')}({action.get('tool_name')}): {action.get('content')} "
                f"=> {action.get('observation')}"
            )
            lines.append(entry)
        lines.append(f"Final answer: {trace.final_result.get('output')}")
        return "\n".join(lines)

    def _extract_reason(self, meta: Dict | None, label: str) -> str:
        if not isinstance(meta, dict):
            return ""
        for key in ("reason", "reasons", "analysis", "explanation"):
            if meta.get(key):
                return f"{label}: {meta[key]}"
        return ""

    def _tags_from_scores(
        self,
        goal_fulfillment: float,
        plan_quality: float,
        plan_adherence: float,
        execution_efficiency: float,
        logical_consistency: float,
    ) -> List[str]:
        tags: List[str] = []
        if goal_fulfillment < 0.6:
            tags.append("goal-miss")
        if plan_quality < 0.55:
            tags.append("weak-plan")
        if plan_adherence < 0.6:
            tags.append("deviated-from-plan")
        if execution_efficiency < 0.5:
            tags.append("redundant-actions")
        if logical_consistency < 0.5:
            tags.append("hallucinated-state")
        return tags

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
