"""Deterministic final review checks + optional LLM polishing for generated Markdown."""

from __future__ import annotations

import json
import logging
import os
import re
from typing import Any
from urllib import request as urllib_request

logger = logging.getLogger(__name__)

DEFAULT_REVIEW_MODEL = "qwen2.5:14b"
DEFAULT_OLLAMA_BASE_URL = "http://localhost:11434"
DEFAULT_OLLAMA_TIMEOUT_SECONDS = 180
DEFAULT_ENABLE_LLM_POLISH = False


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
    checks.extend(_seo_checks(markdown, payload.get("target_keywords")))
    issue_count = sum(1 for check in checks if check["status"] != "pass")
    final_markdown = markdown + "\n" if markdown else "# Untitled\n\n검토 가능한 본문이 없습니다.\n"

    review_status = "ok" if issue_count == 0 else "needs_attention"
    review_polished = False

    # LLM 폴리싱: 빠른 기본 경로에서는 끄고, 고품질 모드에서만 켠다.
    if _llm_polish_enabled() and issue_count == 0 and final_markdown.strip():
        try:
            polished = _polish_with_ollama(final_markdown)
            final_markdown = polished
            review_status = "ok_polished"
            review_polished = True
        except Exception as exc:
            logger.warning("LLM polishing failed, using original: %s", exc)
            # fallback: review_status 는 "ok" 유지

    return {
        "review_status": review_status,
        "final_markdown": final_markdown,
        "checks": checks,
        "issue_count": issue_count,
        "review_polished": review_polished,
    }


def _llm_polish_enabled() -> bool:
    raw = os.getenv("REVIEW_ENABLE_LLM_POLISH")
    if raw is None:
        return DEFAULT_ENABLE_LLM_POLISH
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _polish_with_ollama(markdown: str) -> str:
    """Ollama LLM으로 오탈자 수정, 어색한 문장 다듬기, 흐름 개선을 수행한다."""
    model_name = os.getenv("REVIEW_MODEL", DEFAULT_REVIEW_MODEL)
    base_url = os.getenv("OLLAMA_BASE_URL", DEFAULT_OLLAMA_BASE_URL)
    timeout_seconds = int(os.getenv("OLLAMA_TIMEOUT_SECONDS", str(DEFAULT_OLLAMA_TIMEOUT_SECONDS)))

    prompt = _build_polish_prompt(markdown)
    body = {
        "model": model_name,
        "prompt": prompt,
        "stream": False,
    }
    http_request = urllib_request.Request(
        url=f"{base_url.rstrip('/')}/api/generate",
        data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib_request.urlopen(http_request, timeout=timeout_seconds) as response:
        response_payload = json.loads(response.read().decode("utf-8"))

    polished = str(response_payload.get("response") or "").strip()
    if not polished:
        raise ValueError("empty Ollama response")

    polished = _strip_markdown_fence(polished)
    _check_chinese_leakage(polished)

    # 줄 끝 정리
    if not polished.endswith("\n"):
        polished += "\n"
    return polished


def _build_polish_prompt(markdown: str) -> str:
    return f"""당신은 한국어 블로그 글의 최종 교정 편집자다.
아래 Markdown 글을 읽고 다음만 수행하라:
1. 오탈자, 맞춤법, 띄어쓰기 오류를 수정한다.
2. 어색하거나 부자연스러운 문장을 자연스럽게 다듬는다.
3. 문단 간 흐름이 매끄럽지 않으면 접속사나 연결어를 조정한다.

절대 금지 사항:
- 이미지 마크다운(![...](...))은 한 글자도 변경하지 않는다.
- 제목 구조(# , ## 등)는 변경하지 않는다.
- 사실 관계(장소명, 메뉴명, 가격, 날짜 등)는 변경하지 않는다.
- 새로운 내용을 추가하거나 기존 내용을 삭제하지 않는다.
- 반드시 한국어로만 출력한다. 중국어 절대 금지. 일본어, 영어 등 다른 언어 혼용도 금지.

출력은 교정된 Markdown 본문만 반환한다. 설명, 코드블록, JSON 금지.

원문 Markdown:
{markdown}""".strip()


def _strip_markdown_fence(text: str) -> str:
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = re.sub(r"^```(?:markdown|md)?\s*", "", stripped)
        stripped = re.sub(r"\s*```$", "", stripped)
    return stripped.strip()


def _check_chinese_leakage(text: str) -> None:
    """CJK Unified Ideographs(U+4E00-U+9FFF) 비율이 20% 초과 시 ValueError를 발생시킨다."""
    if not text:
        return
    cjk_count = sum(1 for ch in text if "\u4e00" <= ch <= "\u9fff")
    ratio = cjk_count / len(text)
    if ratio > 0.2:
        raise ValueError(
            f"LLM output is predominantly Chinese ({cjk_count}/{len(text)} CJK chars, {ratio:.1%}), falling back"
        )


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


def _parse_keywords(raw: Any) -> list[str]:
    text = str(raw or "").strip()
    if not text:
        return []
    parts = re.split(r"[,\n;/·]+", text)
    seen: list[str] = []
    for part in parts:
        token = part.strip()
        if token and token not in seen:
            seen.append(token)
    return seen


def _seo_checks(markdown: str, raw_keywords: Any) -> list[dict[str, str]]:
    """target_keywords가 있을 때만 제목 반영/본문 반영/키워드 스터핑을 점검한다."""
    keywords = _parse_keywords(raw_keywords)
    if not markdown or not keywords:
        return []
    lowered = markdown.lower()
    first_line = markdown.splitlines()[0].lower() if markdown.splitlines() else ""
    title_has_keyword = any(kw.lower() in first_line for kw in keywords)
    body_occurrences = sum(lowered.count(kw.lower()) for kw in keywords)
    body_has_keyword = body_occurrences > 0
    token_count = max(len(re.findall(r"\S+", markdown)), 1)
    # 스터핑은 "같은 검색어의 과도한 반복"이다. 짧은 글에서 검색어가 제목+본문에
    # 한 번씩 자연스럽게 나오는 것은 스터핑이 아니므로, 동일 검색어가 4회 이상
    # 등장하면서 그 검색어가 본문 토큰의 큰 비중(>15%)을 차지할 때만 과다로 본다.
    not_stuffed = True
    for kw in keywords:
        occurrences = lowered.count(kw.lower())
        kw_token_len = max(len(kw.split()), 1)
        share = (occurrences * kw_token_len) / token_count
        if occurrences >= 4 and share > 0.15:
            not_stuffed = False
            break
    return [
        _check(
            "seo_title_contains_keyword",
            title_has_keyword,
            "제목에 주력 검색어가 자연스럽게 포함되어 있습니다.",
        ),
        _check(
            "seo_keyword_in_body",
            body_has_keyword,
            "본문에 주력 검색어가 반영되어 있습니다.",
        ),
        _check(
            "seo_no_keyword_stuffing",
            not_stuffed,
            "검색어 반복이 과도하지 않습니다(키워드 스터핑 아님).",
        ),
    ]
