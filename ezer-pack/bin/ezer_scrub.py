#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ezer_scrub.py — 원장·와이어 기록용 비밀 마스킹 공용 유틸 (G2 · cokacdir 성찰 2026-07-04)

voice_gate.py(mask_secrets)의 고신뢰 패턴 계층을 팩 공용으로 이식. 원장 특성상 과탐 계층
(엔트로피 24+·hex 32+)은 제외한다 — 경로·커밋해시·task key가 원장의 정상 구성요소라
오탐 0 이 요구되기 때문(음성 게이트는 '낭독 불가' 근거로 과탐 계층 유지 — 별개 정책).

계약:
- scrub(text) -> (text', n): 비밀 미검출(n=0)이면 원문 바이트 그대로, 검출 시
  정규화(NFKC·zero-width 제거)+마스킹본. 마스킹 문자열은 앞뒤 패딩(토큰 글루 방지).
- scrub_obj(obj) -> obj': dict/list 재귀로 str 값만 마스킹 — 직렬화 '후' 마스킹은
  JSON 구조를 깰 수 있어 값 단위로 적용한다. 비문자열·키·구조는 보존.
"""
import re
import unicodedata

MASK = " 마스킹된 비밀값 "  # 앞뒤 패딩 — 토큰 글루 방지 (voice_gate 원칙 7 승계)

# 고신뢰 비밀 패턴 (voice_gate.py _SECRET_PATTERNS의 구체 접두사·구조 계층)
_SECRET_PATTERNS = [
    re.compile(r"-----BEGIN[A-Z ]*PRIVATE KEY-----[\s\S]*?(-----END[A-Z ]*PRIVATE KEY-----|$)"),
    re.compile(r"(?i)\b(api[_-]?key|secret|token|passwd|password|비밀번호|암호)\s*[:=]\s*\S+"),
    re.compile(r"\bsk-[A-Za-z0-9_-]{8,}"),
    re.compile(r"\bgh[pousr]_[A-Za-z0-9]{16,}"),
    re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}"),
    re.compile(r"\bAKIA[0-9A-Z]{12,}"),
    re.compile(r"\bAIza[0-9A-Za-z_-]{10,}"),
    re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/=-]{15,}"),
]

_CTRL_ZW = re.compile("[\u0000-\u001f\u007f\u200b-\u200f\u202a-\u202e\u2060-\u2064\ufeff]")


def _normalize(text):
    """NFKC + 제어/zero-width 제거 (매칭 우회 차단 — voice_gate 원칙 7 승계)."""
    return _CTRL_ZW.sub("", unicodedata.normalize("NFKC", text))


def scrub(text):
    """비밀 의심 토큰 마스킹. 반환 (텍스트, 마스킹 건수) — n=0이면 원문 바이트 보존."""
    t = _normalize(text)
    n = 0
    for pat in _SECRET_PATTERNS:
        t, k = pat.subn(MASK, t)
        n += k
    return (t if n else text), n


# 민감 키 이름 — 값이 고신뢰 패턴에 안 걸려도(불투명 토큰) 키가 민감하면 값 전체를 마스킹한다.
# 키워드 집합은 위 _SECRET_PATTERNS의 key=value 계층과 동일 — 'task_key'·'idempotency_key' 등
# 정상 원장 키는 'api...key' 접두가 없어 미매칭(원장 오탐 0 원칙 유지).
_SECRET_KEY_RE = re.compile(r"(?i)(api[_-]?key|secret|token|passwd|password|비밀번호|암호)")


def scrub_obj(obj):
    """dict/list/str 재귀 마스킹 — str 값만 교체, 키·구조·비문자열 보존.
    ★WP-8(P-UTIL-1): 키 이름이 민감(_SECRET_KEY_RE)하면 값이 패턴에 안 걸려도 전체 마스킹."""
    if isinstance(obj, str):
        return scrub(obj)[0]
    if isinstance(obj, dict):
        out = {}
        for k, v in obj.items():
            if isinstance(v, str) and _SECRET_KEY_RE.search(str(k)):
                out[k] = MASK.strip()  # 민감키의 문자열 값은 내용 무관 마스킹(불투명 토큰 차단)
            else:
                out[k] = scrub_obj(v)
        return out
    if isinstance(obj, list):
        return [scrub_obj(v) for v in obj]
    return obj
