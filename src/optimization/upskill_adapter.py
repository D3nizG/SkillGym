from __future__ import annotations

import json
from dataclasses import dataclass
from textwrap import dedent
from typing import Dict, List

from openai import OpenAI

from models import OptimizationContext, SkillVersion


@dataclass
class SkillCandidate:
    name: str
    content: str
    rationale: str


class UpskillOptimizer:
    """Trace-aware skill generator with OpenAI-backed candidate synthesis."""

    def __init__(
        self,
        max_candidates: int = 1,
        api_key: str | None = None,
        model: str = "gpt-4o-mini",
        strict_mode: bool = False,
    ) -> None:
        self.max_candidates = max_candidates
        self.model = model
        self.strict_mode = strict_mode
        self._client = OpenAI(api_key=api_key) if api_key else None

    def propose_candidates(
        self,
        skill_text: str,
        context: OptimizationContext,
    ) -> List[SkillCandidate]:
        if self._client is not None:
            candidate = self._propose_with_openai(skill_text, context)
            if candidate is not None:
                return [candidate]
            if self.strict_mode:
                raise RuntimeError(
                    "Strict mode enabled and OpenAI-based Upskill generation failed."
                )
        elif self.strict_mode:
            raise RuntimeError(
                "Strict mode requires OPENAI_API_KEY for Upskill generation."
            )

        recommendations = self._build_recommendations(context)
        candidate_body = dedent(
            f"""
            ## Continuous Improvement Overrides
            
            ### Diagnosed Weaknesses
            {recommendations['failures']}
            
            ### Trace-Guided Adjustments
            {recommendations['adjustments']}
            
            ### Harbor + TruLens Execution Recipe
            1. Always run Harbor benchmarks with deterministic seeds before editing the skill.
            2. Capture raw traces and normalize them immediately for TruLens GPA analysis.
            3. Elevate GPA dimensions (goal fulfillment, plan quality, adherence, efficiency, consistency) as hard checks.
            4. Summarize recurrent failure tags and update troubleshooting guidance below.
            
            ### Failure Tag Playbook
            {recommendations['playbook']}
            
            ### Token & Latency Budgets
            - Keep total tokens under 1.1x the current baseline average.
            - Abort and rewrite plans that exceed 12 steps unless justified by task scope.
            
            ### Promotion Gate Reminders
            - Pass rate must improve by >=3 percentage points.
            - Catastrophic failures may never increase.
            - GPA aggregate must hold or improve.
            - Latency and token use must trend downward.
            """
        ).strip()

        merged_skill = (
            skill_text.rstrip()
            + "\n\n"
            + "<!-- Upskill-generated guidance -->\n"
            + candidate_body
        )

        rationale = (
            "Derived from Upskill heuristic: reinforced missing-plan coverage and "
            "tightened Harbor/TruLens hand-offs using observed failure tags."
        )

        return [
            SkillCandidate(
                name=f"{context.skill_version.skill_name}-upskill",
                content=merged_skill,
                rationale=rationale,
            )
        ]

    def _propose_with_openai(
        self,
        skill_text: str,
        context: OptimizationContext,
    ) -> SkillCandidate | None:
        assert self._client is not None
        context_payload = self._build_llm_context(context)
        prompt = dedent(
            f"""
            You are optimizing an agent SKILL.md.
            Return ONLY valid JSON with:
            {{
              "candidate_skill": "<full SKILL.md text>",
              "rationale": "<short explanation>"
            }}

            Requirements:
            - Preserve the original intent of the skill.
            - Improve failure modes from trace diagnostics.
            - Keep guidance concise and operational.
            - Include explicit checks for planning, tool-use, and output-format compliance.
            - Do not include markdown code fences around JSON.

            Baseline SKILL.md:
            {skill_text}

            Optimization context (JSON):
            {context_payload}
            """
        ).strip()
        try:
            response = self._client.chat.completions.create(
                model=self.model,
                temperature=0.2,
                max_tokens=3000,
                messages=[
                    {
                        "role": "user",
                        "content": prompt,
                    }
                ],
            )
            content = self._extract_text(response)
            parsed = json.loads(content)
            candidate_skill = parsed["candidate_skill"].strip()
            rationale = parsed.get("rationale", "OpenAI-based Upskill generation.")
            if not candidate_skill:
                return None
            return SkillCandidate(
                name=f"{context.skill_version.skill_name}-upskill",
                content=candidate_skill,
                rationale=rationale,
            )
        except Exception:
            return None

    def _build_llm_context(self, context: OptimizationContext) -> str:
        gpa = [
            {
                "aggregate_gpa": score.aggregate_gpa,
                "goal_fulfillment": score.goal_fulfillment,
                "plan_quality": score.plan_quality,
                "plan_adherence": score.plan_adherence,
                "execution_efficiency": score.execution_efficiency,
                "logical_consistency": score.logical_consistency,
                "failure_tags": score.failure_tags,
            }
            for score in context.gpa_breakdown[:10]
        ]
        traces = []
        for trace in context.failing_traces[:5]:
            traces.append(
                {
                    "task_id": trace.task_id,
                    "goal": trace.goal,
                    "final_result": trace.final_result,
                }
            )
        payload = {
            "benchmark_summary": context.benchmark_summary,
            "failure_taxonomy": context.failure_taxonomy,
            "gpa_breakdown": gpa,
            "sample_failing_traces": traces,
        }
        return json.dumps(payload, indent=2)

    def _extract_text(self, response: object) -> str:
        choices = getattr(response, "choices", []) or []
        if choices:
            message = getattr(choices[0], "message", None)
            content = getattr(message, "content", None)
            if isinstance(content, str):
                return content.strip()
        return ""

    # ------------------------------------------------------------------
    def _build_recommendations(self, context: OptimizationContext) -> Dict[str, str]:
        failure_counts = context.failure_taxonomy or {}
        if not failure_counts:
            failure_summary = "No major failures observed; focus on efficiency tuning."
        else:
            ordered = sorted(failure_counts.items(), key=lambda item: item[1], reverse=True)
            failure_summary = "\n".join(
                f"- {tag}: {count} occurrences" for tag, count in ordered
            )
        adjustments = "\n".join(
            [
                "- Expand planning rubric with explicit goal/plan/adherence checklists.",
                "- Emphasize Harbor runtime config reuse to ensure reproducibility.",
                "- Inject TruLens GPA rationales into troubleshooting tips.",
            ]
        )
        playbook = "\n".join(
            [
                "- wrong-tool-selection: Enumerate preferred tool order before acting.",
                "- missing-plan: Fail fast if no plan exists; generate a 4+ step plan.",
                "- formatting-noncompliance: Restate output contract before final answer.",
                "- redundant-actions: Collapse adjacent tool calls unless new info appears.",
            ]
        )
        return {
            "failures": failure_summary,
            "adjustments": adjustments,
            "playbook": playbook,
        }
