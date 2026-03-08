from __future__ import annotations

from dataclasses import dataclass
from textwrap import dedent
from typing import Dict, List

from models import OptimizationContext, SkillVersion


@dataclass
class SkillCandidate:
    name: str
    content: str
    rationale: str


class UpskillOptimizer:
    """Trace-aware skill generator stub that mimics Upskill behavior."""

    def __init__(self, max_candidates: int = 1) -> None:
        self.max_candidates = max_candidates

    def propose_candidates(
        self,
        skill_text: str,
        context: OptimizationContext,
    ) -> List[SkillCandidate]:
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
