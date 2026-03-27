from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class UsageSummary:
    kind: str | None = None
    summary: str | None = None
    meaning: str | None = None
    source: str | None = None
    metrics: dict[str, Any] = field(default_factory=dict)
    windows: dict[str, Any] = field(default_factory=dict)
    session: dict[str, Any] = field(default_factory=dict)


@dataclass
class ProviderReport:
    id: str
    label: str
    auth: str
    mode: str | None = None
    desired_mode: str | None = None
    billing: str | None = None
    usage: UsageSummary = field(default_factory=UsageSummary)
    warnings: list[str] = field(default_factory=list)
    actions: list[str] = field(default_factory=list)
    evidence: dict[str, Any] = field(default_factory=dict)
    account: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return _prune(asdict(self))


def _prune(value: Any) -> Any:
    if isinstance(value, dict):
        cleaned: dict[str, Any] = {}
        for key, item in value.items():
            pruned = _prune(item)
            if pruned is None:
                continue
            if pruned == {}:
                continue
            cleaned[key] = pruned
        return cleaned
    if isinstance(value, list):
        return [_prune(item) for item in value]
    return value
