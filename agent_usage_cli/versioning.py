from __future__ import annotations


def normalize_release_version(value: str) -> str:
    parts = value.removeprefix("v").split(".")
    while len(parts) > 1 and parts[-1] == "0":
        parts.pop()
    return ".".join(parts)


def release_tag_matches_version(tag: str, version: str) -> bool:
    return normalize_release_version(tag) == normalize_release_version(version)
