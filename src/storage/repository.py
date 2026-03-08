from __future__ import annotations

from collections import defaultdict
from typing import Dict, Iterable, List, Optional

from models import BenchmarkRun, CandidateComparison, GPAScore, SkillVersion, TaskRun


class InMemoryRepository:
    """Lightweight repository for MVP orchestration."""

    def __init__(self) -> None:
        self._skills: Dict[str, SkillVersion] = {}
        self._runs: Dict[str, BenchmarkRun] = {}
        self._task_runs: Dict[str, List[TaskRun]] = defaultdict(list)
        self._gpa_scores: Dict[str, List[GPAScore]] = defaultdict(list)
        self._comparisons: List[CandidateComparison] = []

    # Skill versions -----------------------------------------------------
    def register_skill_version(self, skill: SkillVersion) -> None:
        self._skills[skill.id] = skill

    def get_skill_version(self, skill_id: str) -> Optional[SkillVersion]:
        return self._skills.get(skill_id)

    def list_skill_versions(self) -> List[SkillVersion]:
        return list(self._skills.values())

    # Benchmark runs -----------------------------------------------------
    def record_benchmark_run(
        self,
        run: BenchmarkRun,
        task_runs: Iterable[TaskRun],
        gpa_scores: Iterable[GPAScore],
    ) -> None:
        self._runs[run.id] = run
        task_runs_list = list(task_runs)
        gpa_scores_list = list(gpa_scores)
        self._task_runs[run.id] = task_runs_list
        self._gpa_scores[run.id] = gpa_scores_list

    def get_benchmark_run(self, run_id: str) -> Optional[BenchmarkRun]:
        return self._runs.get(run_id)

    def get_task_runs(self, run_id: str) -> List[TaskRun]:
        return self._task_runs.get(run_id, [])

    def get_gpa_scores(self, run_id: str) -> List[GPAScore]:
        return self._gpa_scores.get(run_id, [])

    # Comparisons --------------------------------------------------------
    def record_comparison(self, comparison: CandidateComparison) -> None:
        self._comparisons.append(comparison)

    def list_comparisons(self) -> List[CandidateComparison]:
        return list(self._comparisons)
