#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""EZERagent_registry — 자기기술 능력 레지스트리 (파생 카탈로그·손유지 금지).

스킬/도구 능력 목록을 사람이 손으로 유지하는 방식(EZERagent_preflight의 VIDEO_SKILLS·
APPBUILD_SKILLS 등 하드코딩 목록 + MEMORY.md 손편집)은 인덱스 부패의 원천이다.
이 도구는 pack/skills 트리를 walk 해 각 SKILL.md의 frontmatter(추가형 `EZERagent:` 블록 포함)를
파싱하고, **결정론으로 재생성되는** capability_catalog.json 을 만든다(손편집 금지). 또
요청한 능력(스킬·메모리)이 실재하는지 orphan-lint 한다.

핵심 불변식:
- 카탈로그는 **항상 재생성**된다(손유지 안 함). on-disk 카탈로그가 재유도본과 다르면 드리프트(verify=1).
- **점수(score/grade/rating 0-100·0-1) 금지** — frontmatter에 그런 키/값이 있으면 거부(REVIEWER_VERDICT_CONTRACT §1).
- 추가형 `EZERagent:` 블록은 전부 선택 — 없는 스킬도 정상(기존 92개 name+description만이라도 비파괴).

사용:
    python3 EZERagent_registry.py build  [--root DIR] [--json]   # skills walk → capability_catalog.json 원자적 재생성
    python3 EZERagent_registry.py verify [--root DIR] [--json]   # 재유도본 vs on-disk 카탈로그 diff + orphan-lint
    python3 EZERagent_registry.py resolve --id <skill:NAME|mem:SLUG> [--root DIR] [--json]
    python3 EZERagent_registry.py --self-test                    # 결정론 자기검증 (preflight C34 후보)

공통 옵션: --root <pack 디렉터리> (기본: $EZERAGENT_PACK_DIR 또는 ~/.EZERagent/pack)
종료 코드: 0 정합/found · 1 드리프트/orphan/self-test 실패 · 2 인자/입력 오류 · 3 잠금 실패
의존성: 파이썬 표준 라이브러리만 (네트워크·LLM 호출 없음·PyYAML 미사용·점수 미생성).
"""

import argparse
import contextlib
import io
import json
import os
import re
import sys
import tempfile
import time

CATALOG_REL = os.path.join("round", "capability_catalog.json")
INDEX_FILE = "MEMORY.md"

# ── 추가-전용 마이그레이션 원장 (W2-2 · catalog/frontmatter 스키마 진화) ──
# OpenCut migrations(services/storage/migrations/AGENTS.md:3-10) 클린룸: 영속 데이터를 삭제·개명·
# 교체하지 말고 새 필드를 옆에 추가하라. MIGRATIONS[i] = v_i → v_(i+1) 변환기(추가-전용·멱등).
CATALOG_SCHEMA_VERSION = 1


def _mig_0_to_1(cat):
    """v0→v1: schema_version 필드 도입(추가-전용 — 기존 필드 불변)."""
    cat["schema_version"] = 1
    return cat


MIGRATIONS = [_mig_0_to_1]  # index i = v_i → v_(i+1); len == CATALOG_SCHEMA_VERSION


def migrate_catalog(cat):
    """ordered 추가-전용 변환기 적용 → (migrated, from_v, to_v). 멱등(이미 current면 no-op).
    schema_version 미존재=v0. tool 지원 초과 버전은 fail-loud(다운그레이드 손실 차단)."""
    if not isinstance(cat, dict):
        raise ValueError("catalog 최상위가 객체(dict)가 아님")
    v = cat.get("schema_version", 0)
    if not (isinstance(v, int) and not isinstance(v, bool)) or v < 0:
        raise ValueError("schema_version 0 이상 정수 아님: %r" % v)
    if v > CATALOG_SCHEMA_VERSION:
        raise ValueError("schema_version(%d) > 도구 지원(%d) — 도구 업그레이드 필요(다운그레이드 금지)"
                         % (v, CATALOG_SCHEMA_VERSION))
    start = v
    while v < CATALOG_SCHEMA_VERSION:
        cat = MIGRATIONS[v](cat)
        v += 1
    return cat, start, v

SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")
INDEX_LINK_RE = re.compile(r"\]\(([^)\s]+\.md)\)")
HTML_COMMENT_RE = re.compile(r"<!--.*?-->", re.S)
FENCED_CODE_RE = re.compile(r"```.*?```", re.S)

# 추가형 EZERagent: 블록 — 전부 선택. 모르는 키는 통과(미래 내성)하되 점수류 키는 금지(아래 SCORE_KEY_RE).
EZERAGENT_LIST_KEYS = ("requires_skills", "fallback_skills", "related_memory", "known_blocks")
EZERAGENT_SCALAR_KEYS = ("capability", "stability", "best_for", "cost_class", "channel_tier")
VALID_STABILITY = ("stable", "beta", "experimental", "deprecated")
VALID_COST_CLASS = ("light", "wall-heavy", "context-heavy")  # 달러 없음(Max전용)
# channel_tier = 인증부담(auth-burden) enum — cost_tier(달러)와 별 축. 정수(0/1/2) 금지:
# L177-179 점수-우회 스캔이 한자리 정수를 걸러내므로 enum 문자열로 자연 회피한다(reward-hack 이중차단 불간섭).
#   open = 무인증(공개 API·yt-dlp·정적 HTML) / tls = 자격증명 1회(쿠키·토큰·키) / auth = 상시 브라우저 세션
VALID_CHANNEL_TIER = ("open", "tls", "auth")
# known_blocks = 정직한 차단 실측 — platform:YYYY-MM-DD:symptom (날짜=실측일만·환각0). 리스트라 점수 스캔 자연 회피.
KNOWN_BLOCK_RE = re.compile(r"^[a-z0-9][a-z0-9._-]*:\d{4}-\d{2}-\d{2}:[a-z0-9][a-z0-9 ._-]*$")
SCORE_KEY_RE = re.compile(r"score|grade|rating", re.I)


def default_pack_dir():
    """pack 위치 결정 — src/pack.rs pack_dir()의 폴백을 그대로 미러링한다."""
    for key in ("EZERAGENT_PACK_DIR", "AITERM_JARVIS_DIR"):
        v = os.environ.get(key, "")
        if v:
            return v
    return os.path.join(os.path.expanduser("~"), ".EZERagent/pack")


class FileLock:
    """O_CREAT|O_EXCL 잠금파일 — 다중 노드 동시 카탈로그 재생성 시 경합 차단."""

    def __init__(self, target, timeout=5.0, stale=30.0):
        self.path = target + ".lock"
        self.timeout = timeout
        self.stale = stale
        self.fd = None

    def __enter__(self):
        deadline = time.time() + self.timeout
        while True:
            try:
                self.fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                os.write(self.fd, str(os.getpid()).encode())
                return self
            except FileExistsError:
                try:
                    if time.time() - os.path.getmtime(self.path) > self.stale:
                        os.unlink(self.path)
                        continue
                except OSError:
                    pass
                if time.time() > deadline:
                    raise TimeoutError("잠금 획득 실패(%.0fs): %s" % (self.timeout, self.path))
                time.sleep(0.05)

    def __exit__(self, *exc):
        if self.fd is not None:
            os.close(self.fd)
        try:
            os.unlink(self.path)
        except OSError:
            pass
        return False


def _parse_value(v):
    """frontmatter 값 — '[a, b]' 인라인 리스트 또는 스칼라 문자열."""
    v = v.strip()
    if v.startswith("[") and v.endswith("]"):
        inner = v[1:-1].strip()
        if not inner:
            return []
        return [x.strip().strip("'\"") for x in inner.split(",") if x.strip()]
    return v.strip("'\"")


def parse_frontmatter(text):
    """name/description + 추가형 EZERagent 블록 파싱(하드 파서·PyYAML 미사용).

    반환 {name, description, EZERagent:{...}, _score_violation:bool}. 형식 불량이면 None 필드.
    EZERagent 블록은 2칸 들여쓰기 key: value(또는 [list]). 점수류 키 발견 시 _score_violation=True.
    """
    out = {"name": None, "description": None, "EZERagent": {}, "_score_violation": False}
    if not text.startswith("---"):
        return out
    end = text.find("\n---", 3)
    if end < 0:
        return out
    head = text[3:end]
    in_EZERagent = False
    for line in head.splitlines():
        if not line.strip():
            continue
        indented = line.startswith("  ") or line.startswith("\t")
        s = line.strip()
        if not indented:
            in_EZERagent = False
            if s.startswith("name:"):
                out["name"] = s[5:].strip()
            elif s.startswith("description:"):
                out["description"] = s[12:].strip()
            elif s.startswith("EZERagent:"):
                in_EZERagent = True
        elif in_EZERagent and ":" in s:
            k, _, v = s.partition(":")
            k = k.strip()
            if SCORE_KEY_RE.search(k):   # 점수류 키 금지(§1 reward-hack 채널 차단)
                out["_score_violation"] = True
                continue
            out["EZERagent"][k] = _parse_value(v)
    # 스칼라 값이 0-100 / 0-1 숫자처럼 보이면 점수 밀반입으로 간주(키명 우회 방지)
    for val in out["EZERagent"].values():
        if isinstance(val, str) and re.fullmatch(r"(100|\d{1,2}|0?\.\d+)", val):
            out["_score_violation"] = True
    return out


def index_links(index_text):
    """MEMORY.md 색인 링크 대상 — 주석·코드펜스 예시 제외(EZERagent_memory와 동일 규칙)."""
    visible = FENCED_CODE_RE.sub("", HTML_COMMENT_RE.sub("", index_text))
    return [m.group(1) for m in INDEX_LINK_RE.finditer(visible)
            if "/" not in m.group(1) and m.group(1) != INDEX_FILE]


def memory_slugs(pack_dir):
    """MEMORY.md 색인의 파일명을 정규화 슬러그 집합으로(타입 접두·.md 제거)."""
    idx = os.path.join(pack_dir, "memory", INDEX_FILE)
    if not os.path.isfile(idx):
        return set()
    text = open(idx, encoding="utf-8", errors="replace").read()
    out = set()
    for fn in index_links(text):
        out.add(normalize_slug(fn))
    return out


def normalize_slug(ref):
    """ref → 표준 슬러그: lower·.md 제거·타입접두(feedback_/user_/project_/reference_) 제거."""
    s = (ref or "").strip().lower()
    if s.endswith(".md"):
        s = s[:-3]
    for t in ("feedback_", "user_", "project_", "reference_"):
        if s.startswith(t):
            s = s[len(t):]
            break
    return s


def skill_dirs(skills_root):
    """skills_root 하위에서 SKILL.md를 가진 디렉터리명 목록(정렬)."""
    try:
        names = sorted(os.listdir(skills_root))
    except OSError:
        return []
    out = []
    for n in names:
        if n.startswith("."):
            continue
        if os.path.isfile(os.path.join(skills_root, n, "SKILL.md")):
            out.append(n)
    return out


def build_catalog(pack_dir):
    """skills 트리 → 카탈로그 dict(결정론·정렬). 점수 위반 frontmatter는 problems로 보고."""
    skills_root = os.path.join(pack_dir, "skills")
    names = skill_dirs(skills_root)
    name_set = set(names)
    mem_slugs = memory_slugs(pack_dir)

    capabilities = []
    orphans = {"skill": [], "memory": []}
    problems = []

    for name in names:
        path = os.path.join("skills", name, "SKILL.md")
        text = open(os.path.join(pack_dir, path), encoding="utf-8", errors="replace").read()
        fm = parse_frontmatter(text)
        if fm["_score_violation"]:
            problems.append("%s: EZERagent 블록에 점수류(score/grade/rating·0-100·0-1) 금지 위반" % name)
        if fm["name"] is None or fm["description"] is None:
            problems.append("%s: frontmatter(name/description) 불량" % name)
        EZERagent = dict(fm["EZERagent"])
        # enum 검증
        st = EZERagent.get("stability")
        if st is not None and st not in VALID_STABILITY:
            problems.append("%s: stability 무효(%r) — %s" % (name, st, "|".join(VALID_STABILITY)))
        cc = EZERagent.get("cost_class")
        if cc is not None and cc not in VALID_COST_CLASS:
            problems.append("%s: cost_class 무효(%r) — %s" % (name, cc, "|".join(VALID_COST_CLASS)))
        ct = EZERagent.get("channel_tier")
        if ct is not None and ct not in VALID_CHANNEL_TIER:
            problems.append("%s: channel_tier 무효(%r) — %s" % (name, ct, "|".join(VALID_CHANNEL_TIER)))
        for blk in _as_list(EZERagent.get("known_blocks")):
            if not KNOWN_BLOCK_RE.match(blk):
                problems.append("%s: known_blocks 형식 불량(%r) — platform:YYYY-MM-DD:symptom" % (name, blk))
        # orphan lint — requires/fallback skill 실재? related_memory 색인 존재?
        for key in ("requires_skills", "fallback_skills"):
            for ref in _as_list(EZERagent.get(key)):
                if ref not in name_set:
                    orphans["skill"].append({"from": name, "key": key, "ref": ref})
        for ref in _as_list(EZERagent.get("related_memory")):
            if normalize_slug(ref) not in mem_slugs:
                orphans["memory"].append({"from": name, "ref": ref})

        rec = {"id": "skill:%s" % name, "kind": "skill", "path": path,
               "name": fm["name"], "description": fm["description"]}
        for key in EZERAGENT_SCALAR_KEYS:
            if key in EZERagent:
                rec[key] = EZERagent[key]
        for key in EZERAGENT_LIST_KEYS:
            if key in EZERagent:
                rec[key] = _as_list(EZERagent[key])
        capabilities.append(rec)

    capabilities.sort(key=lambda r: r["id"])
    catalog = {
        "_generated": "EZERagent_registry.py build — 손편집 금지(재생성: python3 EZERagent_registry.py build)",
        "pack_dir": pack_dir,
        "counts": {"skills": len(capabilities),
                   "orphan_skill": len(orphans["skill"]),
                   "orphan_memory": len(orphans["memory"])},
        "capabilities": capabilities,
        "orphans": orphans,
    }
    return catalog, problems


def _as_list(v):
    if v is None:
        return []
    if isinstance(v, list):
        return v
    return [v]


def _serialize(catalog):
    """on-disk 비교용 결정론 직렬화 — _generated 배너는 비교에서 제외(재생성 시 동일 유지)."""
    return json.dumps(catalog, ensure_ascii=False, indent=2, sort_keys=True)


def cmd_build(pack_dir, as_json):
    catalog, problems = build_catalog(pack_dir)
    target = os.path.join(pack_dir, CATALOG_REL)
    os.makedirs(os.path.dirname(target), exist_ok=True)
    payload = _serialize(catalog) + "\n"
    try:
        with FileLock(target):
            fd, tmp = tempfile.mkstemp(dir=os.path.dirname(target), prefix=".catalog-")
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(payload)
            os.replace(tmp, target)  # 원자적 덮어쓰기
    except TimeoutError as e:
        return fail(3, str(e))
    summary = {"built": CATALOG_REL, "skills": catalog["counts"]["skills"],
               "orphans": catalog["counts"]["orphan_skill"] + catalog["counts"]["orphan_memory"],
               "problems": problems}
    if as_json:
        print(json.dumps(summary, ensure_ascii=False, indent=2))
    else:
        print("build: skills %d · orphan %d · problem %d → %s"
              % (summary["skills"], summary["orphans"], len(problems), target))
        for p in problems:
            print("  [PROBLEM] %s" % p)
    return 1 if problems else 0


def collect_problems(pack_dir):
    """verify 본체 — on-disk 카탈로그가 재유도본과 다른가(드리프트) + 점수/enum 위반 + orphan."""
    problems = []
    catalog, build_problems = build_catalog(pack_dir)
    problems.extend(build_problems)
    target = os.path.join(pack_dir, CATALOG_REL)
    if not os.path.isfile(target):
        problems.append("카탈로그 없음: %s — build 먼저 (손유지 금지·재생성)" % CATALOG_REL)
        return problems, catalog
    on_disk = open(target, encoding="utf-8", errors="replace").read()
    if on_disk.strip() != _serialize(catalog).strip():
        problems.append("드리프트: on-disk 카탈로그가 재유도본과 다름 — 손편집 의심, build로 재생성")
    for o in catalog["orphans"]["skill"]:
        problems.append("orphan skill: %s.%s → %s (스킬 없음)" % (o["from"], o["key"], o["ref"]))
    for o in catalog["orphans"]["memory"]:
        problems.append("orphan memory: %s → %s (색인에 없음)" % (o["from"], o["ref"]))
    return problems, catalog


def cmd_verify(pack_dir, as_json):
    problems, catalog = collect_problems(pack_dir)
    if as_json:
        print(json.dumps({"ok": not problems, "pack_dir": pack_dir,
                          "skills": catalog["counts"]["skills"], "problems": problems},
                         ensure_ascii=False, indent=2))
    else:
        for p in problems:
            print("[FAIL] %s" % p)
        print("verify: %s — 스킬 %d · 문제 %d (%s)"
              % ("OK" if not problems else "NOT OK", catalog["counts"]["skills"],
                 len(problems), pack_dir))
        if problems:
            print("이 출력 외의 추론으로 카탈로그 정합을 선언하지 마라.")
    return 0 if not problems else 1


def cmd_resolve(pack_dir, ident, as_json):
    catalog, _ = build_catalog(pack_dir)
    if ":" not in (ident or ""):
        return fail(2, "id는 'skill:NAME' 또는 'mem:SLUG' 형식")
    ns, _, key = ident.partition(":")
    found = None
    if ns == "skill":
        for rec in catalog["capabilities"]:
            if rec["id"] == "skill:%s" % key:
                found = rec
                break
    elif ns == "mem":
        found = {"id": "mem:%s" % key,
                 "resolved": normalize_slug(key) in memory_slugs(pack_dir)}
    else:
        return fail(2, "namespace는 skill|mem")
    if as_json:
        print(json.dumps({"id": ident, "found": found is not None and found.get("resolved", True),
                          "record": found}, ensure_ascii=False, indent=2))
    else:
        print(json.dumps(found, ensure_ascii=False, indent=2) if found else "not found: %s" % ident)
    if found is None or (ns == "mem" and not found.get("resolved")):
        return 1
    return 0


def fail(code, msg):
    print(json.dumps({"error": msg}, ensure_ascii=False), file=sys.stderr)
    return code


def cmd_migrate(path, as_json):
    """JSON 카탈로그를 현재 스키마 버전으로 추가-전용 마이그레이션(멱등·원자적·fail-loud)."""
    try:
        with open(path, encoding="utf-8") as f:
            cat = json.load(f)
    except FileNotFoundError:
        return fail(2, "파일 없음: %s" % path)
    except (OSError, json.JSONDecodeError) as e:
        return fail(2, "JSON 로드 실패: %s (%s)" % (path, e))
    try:
        migrated, from_v, to_v = migrate_catalog(cat)
    except ValueError as e:
        return fail(2, str(e))
    changed = from_v != to_v
    if changed:
        target = os.path.abspath(path)
        fd, tmp = tempfile.mkstemp(dir=os.path.dirname(target), prefix=".migrate-")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(migrated, f, ensure_ascii=False, indent=2)
            f.write("\n")
        os.replace(tmp, target)
    out = {"ok": True, "file": path, "from_version": from_v, "to_version": to_v, "changed": changed}
    if as_json:
        print(json.dumps(out, ensure_ascii=False, indent=2))
    else:
        print("migrate: %s — v%d→v%d %s" % (path, from_v, to_v,
              "(기록됨)" if changed else "(이미 current·no-op)"))
    return 0


def _write_skill(root, name, desc="d", EZERagent_lines=None):
    d = os.path.join(root, "skills", name)
    os.makedirs(d, exist_ok=True)
    fm = "---\nname: %s\ndescription: %s\n" % (name, desc)
    if EZERagent_lines:
        fm += "EZERagent:\n" + "".join("  %s\n" % ln for ln in EZERagent_lines)
    fm += "---\n\n본문\n"
    open(os.path.join(d, "SKILL.md"), "w", encoding="utf-8").write(fm)


def self_test():
    """tempdir 라운드트립 — build→verify OK → 고장 주입(드리프트·orphan·점수·enum)까지 검증."""
    failures = []
    with tempfile.TemporaryDirectory(prefix="EZERagent-registry-selftest-") as td:
        os.makedirs(os.path.join(td, "memory"))
        open(os.path.join(td, "memory", INDEX_FILE), "w", encoding="utf-8").write(
            "# MEMORY.md\n\n- [디시전](feedback_decision-consult-EZERagent-sot.md) — x\n")
        # 추가형 0키 비파괴: name+description만
        _write_skill(td, "plain-skill")
        # EZERagent 블록 있는 스킬(정상): requires_skills 실재·related_memory 색인 존재
        _write_skill(td, "rich-skill", EZERagent_lines=[
            "capability: video_generation", "stability: stable", "cost_class: wall-heavy",
            "requires_skills: [plain-skill]", "related_memory: [decision-consult-EZERagent-sot]"])

        ns = argparse.Namespace()
        sink = io.StringIO()
        with contextlib.redirect_stdout(sink), contextlib.redirect_stderr(sink):
            rc = cmd_build(td, False)
        if rc != 0:
            failures.append("정상 트리인데 build가 문제 보고: rc=%d" % rc)
        probs, cat = collect_problems(td)
        if probs:
            failures.append("정상 상태인데 verify가 문제 보고: %s" % probs)
        if cat["counts"]["skills"] != 2:
            failures.append("스킬 수 오집계: %d≠2" % cat["counts"]["skills"])
        # plain-skill 레코드엔 EZERagent 필드가 없어야 한다(추가형·비주입)
        plain = next((r for r in cat["capabilities"] if r["id"] == "skill:plain-skill"), {})
        if any(k in plain for k in EZERAGENT_SCALAR_KEYS + EZERAGENT_LIST_KEYS):
            failures.append("EZERagent 없는 스킬에 EZERagent 필드 주입됨")
        # 결정론: 연속 2회 직렬화 byte-identical
        if _serialize(build_catalog(td)[0]) != _serialize(build_catalog(td)[0]):
            failures.append("비결정 직렬화")
        # 고장1 드리프트: 카탈로그 손편집 → verify가 잡는가
        with open(os.path.join(td, CATALOG_REL), "a", encoding="utf-8") as f:
            f.write("\n  손편집\n")
        if not any("드리프트" in p for p in collect_problems(td)[0]):
            failures.append("카탈로그 드리프트 미검출")
        # 고장2 orphan skill: 없는 스킬 참조
        _write_skill(td, "orphan-ref", EZERagent_lines=["requires_skills: [does-not-exist]"])
        if not any("orphan skill" in p for p in collect_problems(td)[0]):
            failures.append("orphan skill 미검출")
        # 고장3 orphan memory: 색인에 없는 슬러그
        _write_skill(td, "orphan-mem", EZERagent_lines=["related_memory: [no-such-memory]"])
        if not any("orphan memory" in p for p in collect_problems(td)[0]):
            failures.append("orphan memory 미검출")
        # 고장4 점수 금지: EZERagent에 score 키 → 위반 검출(reward-hack 채널 차단)
        _write_skill(td, "score-bad", EZERagent_lines=["score: 90"])
        if not any("점수류" in p for p in build_catalog(td)[1]):
            failures.append("점수류 키(score:90) 미검출")
        # 점수 우회: 숫자 값 스칼라
        _write_skill(td, "score-sneak", EZERagent_lines=["capability: 87"])
        if not any("점수류" in p for p in build_catalog(td)[1]):
            failures.append("숫자 스칼라(점수 우회) 미검출")
        # 고장5 enum: 무효 stability
        _write_skill(td, "bad-enum", EZERagent_lines=["stability: awesome"])
        if not any("stability 무효" in p for p in build_catalog(td)[1]):
            failures.append("stability enum 위반 미검출")
        # OPP-08 정상: channel_tier(enum) + known_blocks(실측) → problems 0 · rec에 두 필드 방출
        with tempfile.TemporaryDirectory(prefix="EZERagent-reg-opp08-") as td2:
            os.makedirs(os.path.join(td2, "memory"))
            open(os.path.join(td2, "memory", INDEX_FILE), "w", encoding="utf-8").write("# MEMORY.md\n")
            _write_skill(td2, "ch-ok", EZERagent_lines=[
                "channel_tier: tls", "known_blocks: [reddit:2026-06-25:403-waf]"])
            cat2, probs2 = build_catalog(td2)
            if probs2:
                failures.append("정상 channel_tier/known_blocks인데 problems 보고: %s" % probs2)
            rec2 = next((r for r in cat2["capabilities"] if r["id"] == "skill:ch-ok"), {})
            if rec2.get("channel_tier") != "tls":
                failures.append("channel_tier 방출 누락/불일치: %r" % rec2.get("channel_tier"))
            if rec2.get("known_blocks") != ["reddit:2026-06-25:403-waf"]:
                failures.append("known_blocks 방출 누락/불일치: %r" % rec2.get("known_blocks"))
            # 거짓양성 회귀(중요): channel_tier enum 값이 점수-우회 스캔에 안 걸려야(정수tier 폐기 근거)
            fm_ok = parse_frontmatter(
                "---\nname: x\ndescription: d\nEZERagent:\n  channel_tier: open\n---\n본문\n")
            if fm_ok["_score_violation"]:
                failures.append("channel_tier enum이 점수-우회 스캔에 거짓양성(정수tier였다면 발생)")
        # OPP-08 고장A: 무효 channel_tier
        _write_skill(td, "ch-bad-tier", EZERagent_lines=["channel_tier: paid"])
        if not any("channel_tier 무효" in p for p in build_catalog(td)[1]):
            failures.append("channel_tier enum 위반 미검출")
        # OPP-08 고장B: known_blocks 형식 불량(날짜 없음)
        _write_skill(td, "ch-bad-block", EZERagent_lines=["known_blocks: [reddit-no-date]"])
        if not any("known_blocks 형식 불량" in p for p in build_catalog(td)[1]):
            failures.append("known_blocks 형식 위반 미검출")
        # 잠금 잔류 없어야
        if os.path.exists(os.path.join(td, CATALOG_REL) + ".lock"):
            failures.append("잠금파일 잔류")

    # 마이그레이션 원장(W2-2) — 추가-전용·멱등·fail-loud
    m1, f1, t1 = migrate_catalog({"capabilities": {}})           # v0(필드 없음) → v1
    if not (f1 == 0 and t1 == 1 and m1.get("schema_version") == 1 and "capabilities" in m1):
        failures.append("migrate v0→v1 실패(추가-전용): %s" % m1)
    m2, f2, t2 = migrate_catalog({"schema_version": 1, "x": 9})  # 이미 current → no-op(멱등)
    if not (f2 == 1 and t2 == 1 and m2.get("x") == 9):
        failures.append("migrate 멱등 실패")
    try:
        migrate_catalog({"schema_version": 99})                  # 도구 초과 → fail-loud
        failures.append("미래 버전이 fail-loud 아님")
    except ValueError:
        pass
    try:
        migrate_catalog({"schema_version": "1"})                 # 비정수 → fail-loud
        failures.append("비정수 schema_version이 fail-loud 아님")
    except ValueError:
        pass
    with tempfile.TemporaryDirectory(prefix="EZERagent-reg-mig-") as td:
        cp = os.path.join(td, "cat.json")
        json.dump({"capabilities": {"c": []}}, open(cp, "w", encoding="utf-8"))
        sink = io.StringIO()
        with contextlib.redirect_stdout(sink), contextlib.redirect_stderr(sink):
            if cmd_migrate(cp, True) != 0:
                failures.append("cmd_migrate(정상) exit 0 아님")
            if cmd_migrate(cp, True) != 0:
                failures.append("cmd_migrate 재실행(멱등) exit 0 아님")
            if cmd_migrate(os.path.join(td, "nope.json"), True) != 2:
                failures.append("cmd_migrate(없는 파일) exit 2 아님")
        if json.load(open(cp, encoding="utf-8")).get("schema_version") != 1:
            failures.append("cmd_migrate가 schema_version 기록 안 함")

    print(json.dumps({"self_test": "ok" if not failures else "fail",
                      "failures": failures}, ensure_ascii=False, indent=2))
    return 0 if not failures else 1


def main():
    ap = argparse.ArgumentParser(description="자기기술 능력 레지스트리 (파생 카탈로그·손유지 금지)")
    ap.add_argument("--root", default=None, help="pack 디렉터리 (기본: $EZERAGENT_PACK_DIR 또는 ~/.EZERagent/pack)")
    ap.add_argument("--self-test", action="store_true", help="결정론 자기검증")
    sub = ap.add_subparsers(dest="cmd")

    # --root은 전역(서브커맨드 앞)·서브커맨드 뒤 둘 다 받는다. 서브커맨드의 default=SUPPRESS는
    # 미지정 시 args.root를 덮어쓰지 않아 전역값을 보존한다(argparse 서브파서 그림자 버그 회피).
    def add_root(p):
        p.add_argument("--root", dest="root", default=argparse.SUPPRESS,
                       help="pack 디렉터리 (전역 --root와 동일)")

    b = sub.add_parser("build", help="skills walk → capability_catalog.json 원자적 재생성")
    add_root(b)
    b.add_argument("--json", action="store_true")
    v = sub.add_parser("verify", help="재유도본 vs on-disk 카탈로그 diff + orphan-lint (0=정합 1=문제)")
    add_root(v)
    v.add_argument("--json", action="store_true")
    r = sub.add_parser("resolve", help="단일 능력 조회 (skill:NAME | mem:SLUG)")
    add_root(r)
    r.add_argument("--id", required=True)
    r.add_argument("--json", action="store_true")
    mg = sub.add_parser("migrate", help="JSON 카탈로그 추가-전용 마이그레이션 (0=성공 2=입력/버전 오류)")
    mg.add_argument("file")
    mg.add_argument("--json", action="store_true")

    args = ap.parse_args()
    if args.self_test:
        return self_test()
    if args.cmd == "migrate":
        return cmd_migrate(args.file, args.json)
    pack_dir = args.root or default_pack_dir()
    if args.cmd == "build":
        return cmd_build(pack_dir, args.json)
    if args.cmd == "verify":
        return cmd_verify(pack_dir, args.json)
    if args.cmd == "resolve":
        return cmd_resolve(pack_dir, args.id, args.json)
    ap.print_help()
    return 2


if __name__ == "__main__":
    sys.exit(main())
