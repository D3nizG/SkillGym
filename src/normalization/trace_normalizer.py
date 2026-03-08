from __future__ import annotations

from pathlib import Path
from typing import Dict, Tuple

from models import NormalizedTrace
from utils.io import load_json, write_json


class TraceNormalizer:
    """Converts raw Harbor traces into the normalized schema used downstream."""

    def normalize(self, raw_trace_path: str) -> Tuple[NormalizedTrace, str]:
        raw_path = Path(raw_trace_path)
        raw_payload = load_json(raw_path)
        normalized = NormalizedTrace(
            task_id=raw_payload["task_id"],
            goal=raw_payload.get("goal", ""),
            initial_context=raw_payload.get("initial_context", ""),
            plan=raw_payload.get("plan", []),
            actions=raw_payload.get("actions", []),
            final_result=raw_payload.get("final_result", {}),
            metadata=raw_payload.get("metadata", {}),
        )
        normalized_path = raw_path.with_name(raw_path.name.replace("raw", "normalized"))
        write_json(normalized_path, normalized.__dict__)
        return normalized, str(normalized_path)
