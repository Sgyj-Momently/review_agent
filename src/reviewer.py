"""Deterministic final review checks for generated Markdown."""

from __future__ import annotations

import re
from typing import Any


def review_document(payload: dict[str, Any]) -> dict[str, Any]:
    markdown = str(payload.get("styled_markdown") or "").strip()
    excluded = payload.get("excluded_photos") or []
    checks = [
        _check("non_empty", bool(markdown), "본문이 비어 있지 않습니다."),
        _check("has_title", markdown.startswith("# "), "제목이 Markdown H1으로 존재합니다."),
        _check("has_body", len(re.findall(r"\S+", markdown)) >= 8, "본문이 최소 길이를 충족합니다."),
        _check(
            "excluded_photos_not_referenced",
            not _references_excluded_photo(markdown, excluded),
            "제외된 사진이 최종 본문에 직접 참조되지 않습니다.",
        ),
    ]
    issue_count = sum(1 for check in checks if check["status"] != "pass")
    final_markdown = markdown + "\n" if markdown else "# Untitled\n\n검토 가능한 본문이 없습니다.\n"
    return {
        "review_status": "ok" if issue_count == 0 else "needs_attention",
        "final_markdown": final_markdown,
        "checks": checks,
        "issue_count": issue_count,
    }


def _check(name: str, passed: bool, message: str) -> dict[str, str]:
    return {"name": name, "status": "pass" if passed else "fail", "message": message}


def _references_excluded_photo(markdown: str, excluded_photos: list[Any]) -> bool:
    for photo in excluded_photos:
        if not isinstance(photo, dict):
            continue
        file_name = str(photo.get("file_name") or "").strip()
        if file_name and file_name in markdown:
            return True
    return False

