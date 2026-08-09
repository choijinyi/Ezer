#!/usr/bin/env python3
"""entity_registry 검증기 (schema_version 1).

사용법:
    python3 check_entity_registry.py validate <파일>

동작:
    entity_registry.schema.md 의 제약을 전수 검사한다.
    위반을 `<필드경로>: <사유>` 한 줄씩 stdout 에 출력한다.

종료 코드:
    0  정상 (위반 없음)
    1  위반 1개 이상
    2  파싱 불가 / 파일 없음 / 잘못된 인자

의존성: 표준 라이브러리(json, re, sys)만 사용한다.
"""
import json
import re
import sys

# entity_registry.schema.md §5 와 동일한 금칙 토큰 목록 (성격·역할·관계 누출 검출).
FORBIDDEN_TOKENS = [
    "성격", "성실", "착하", "착한", "악당", "악한", "사악", "잔인", "냉정", "다정",
    "상냥", "소심", "대범", "용감", "비겁", "정의", "배신", "영웅", "리더", "리더십",
    "카리스마", "우두머리", "내성적", "외향적", "관계", "친구", "우정", "사랑",
    "연인", "가족", "형제", "자매", "부모", "라이벌", "동료", "원수",
]

CHAR_ID_RE = re.compile(r"^char_[A-Za-z0-9]+$")
SPACE_ID_RE = re.compile(r"^space_[A-Za-z0-9]+$")


def _is_nonempty_str(v):
    return isinstance(v, str) and v.strip() != ""


def _check_features(field_path, value, violations):
    """static/dynamic_features: 비어있지 않음 + 금칙 토큰 없음."""
    if not isinstance(value, str):
        violations.append("%s: must be a string" % field_path)
        return
    if value.strip() == "":
        violations.append("%s: empty" % field_path)
        return
    hits = [t for t in FORBIDDEN_TOKENS if t in value]
    if hits:
        violations.append(
            "%s: forbidden token %s (personality/role/relationship description not allowed)"
            % (field_path, ", ".join("'%s'" % h for h in hits))
        )


def _check_portrait_reference(field_path, portrait, violations):
    """side/back 초상의 reference 는 'front' 고정."""
    if not isinstance(portrait, dict):
        violations.append("%s: must be an object" % field_path)
        return
    ref = portrait.get("reference")
    if ref != "front":
        violations.append("%s.reference: expected 'front', got %r" % (field_path, ref))


def validate(data):
    """검증. 위반 문자열 리스트를 반환한다(빈 리스트=정상)."""
    violations = []

    if not isinstance(data, dict):
        return ["<root>: top-level value must be a JSON object"]

    # 1. schema_version == 1
    sv = data.get("schema_version")
    if sv != 1 or isinstance(sv, bool):
        violations.append("schema_version: expected 1, got %r" % (sv,))

    defined_char_ids = set()
    defined_space_ids = set()
    seen_ids = set()

    # 2~5. characters
    characters = data.get("characters")
    if not isinstance(characters, list):
        violations.append("characters: expected an array")
    else:
        for i, ch in enumerate(characters):
            base = "characters[%d]" % i
            if not isinstance(ch, dict):
                violations.append("%s: must be an object" % base)
                continue

            cid = ch.get("id")
            if not isinstance(cid, str) or not CHAR_ID_RE.match(cid):
                violations.append("%s.id: invalid id %r (must match char_*)" % (base, cid))
            else:
                if cid in seen_ids:
                    violations.append("%s.id: duplicate id %r" % (base, cid))
                seen_ids.add(cid)
                defined_char_ids.add(cid)

            _check_features("%s.static_features" % base, ch.get("static_features"), violations)
            _check_features("%s.dynamic_features" % base, ch.get("dynamic_features"), violations)

            portraits = ch.get("portraits")
            if not isinstance(portraits, dict):
                violations.append("%s.portraits: expected an object" % base)
            else:
                for view in ("front", "side", "back"):
                    if view not in portraits:
                        violations.append("%s.portraits.%s: missing" % (base, view))
                # side/back reference == "front"
                for view in ("side", "back"):
                    if view in portraits:
                        _check_portrait_reference("%s.portraits.%s" % (base, view),
                                                   portraits[view], violations)

            overrides = ch.get("scene_overrides", [])
            if overrides is None:
                overrides = []
            if not isinstance(overrides, list):
                violations.append("%s.scene_overrides: expected an array" % base)
            else:
                for j, ov in enumerate(overrides):
                    op = "%s.scene_overrides[%d]" % (base, j)
                    if not isinstance(ov, dict):
                        violations.append("%s: must be an object" % op)
                        continue
                    scene = ov.get("scene")
                    if isinstance(scene, bool) or not isinstance(scene, int) or scene < 1:
                        violations.append("%s.scene: must be a positive integer, got %r"
                                          % (op, scene))

    # 3(공간). spaces
    spaces = data.get("spaces")
    if not isinstance(spaces, list):
        violations.append("spaces: expected an array")
    else:
        for i, sp in enumerate(spaces):
            base = "spaces[%d]" % i
            if not isinstance(sp, dict):
                violations.append("%s: must be an object" % base)
                continue
            sid = sp.get("id")
            if not isinstance(sid, str) or not SPACE_ID_RE.match(sid):
                violations.append("%s.id: invalid id %r (must match space_*)" % (base, sid))
            else:
                if sid in seen_ids:
                    violations.append("%s.id: duplicate id %r" % (base, sid))
                seen_ids.add(sid)
                defined_space_ids.add(sid)
            if not _is_nonempty_str(sp.get("slugline")):
                violations.append("%s.slugline: empty or missing" % base)
            if not _is_nonempty_str(sp.get("description")):
                violations.append("%s.description: empty or missing" % base)

    # 6. frame_index 참조 무결성
    frame_index = data.get("frame_index")
    if not isinstance(frame_index, list):
        violations.append("frame_index: expected an array")
    else:
        for i, fr in enumerate(frame_index):
            base = "frame_index[%d]" % i
            if not isinstance(fr, dict):
                violations.append("%s: must be an object" % base)
                continue
            chars = fr.get("characters", [])
            if not isinstance(chars, list):
                violations.append("%s.characters: expected an array" % base)
            else:
                for k, ref in enumerate(chars):
                    if ref not in defined_char_ids:
                        violations.append("%s.characters[%d]: undefined character id %r"
                                          % (base, k, ref))
            space_ref = fr.get("space")
            if space_ref not in defined_space_ids:
                violations.append("%s.space: undefined space id %r" % (base, space_ref))

    return violations


def main(argv):
    if len(argv) != 3 or argv[1] != "validate":
        sys.stderr.write("usage: python3 check_entity_registry.py validate <파일>\n")
        return 2

    path = argv[2]
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        sys.stderr.write("parse error: %s\n" % e)
        return 2

    violations = validate(data)
    for v in violations:
        print(v)
    return 1 if violations else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
