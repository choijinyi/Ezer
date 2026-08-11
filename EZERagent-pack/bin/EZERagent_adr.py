#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""EZERagent_adr — ADR(Architectural Decision Records) 결정기록 레이어의 결정론 도구.

출처: 외부 수집 지식(YouTube 4JtB_QvKT8w "하네스 엔지니어링"·바이브마피아 최수민) —
오너 SOT 아님. 영상 발췌: "ADR은 아키텍추럴 디시전 레커즈 … 설계에 대해서 어떤 결정을
했을 때 이거를 문서로 남겨 둬야 나중에 온보딩하는 개발자(에이전트)들이 이 조직은 이런
기준으로 의사결정을 내리는구나를 알 수 있다 … ADR 문서는 공용 SSOT로서 계속 관리하는
문서 … 컨벤션 문서랑 ADR 문서가 계속 커져요 … 모든 ADR 내용이 이 작업을 평가하는 데
참조될 필요는 없다 … 이 작업과 관련된 것만 골라내는 서브에이전트 … 과거의 의사결정
기록 중에서 이번에 참고해야 될 것만 정리".

영상에 나온 세 동작만 결정론으로 환원한다(날조 0):
  add      — 설계 결정 1건을 채번(0001+)하여 NNNN-<slug>.md로 영속 기록(공용 SSOT 누적).
  list     — 누적된 결정 기록을 한 줄 요약으로 일람.
  relevant — "이 작업과 관련된 것만 골라내는" 결정론 보조(복잡한 RAG 불필요): query
             키워드가 제목/context/decision에 매칭되는 ADR만 추려 콤팩트 참조본을 만든다.

채번·파일생성은 다중 노드 동시 쓰기에 안전하도록 잠금(FileLock) 하에 수행한다(EZERagent_memory
패턴 미러링). 같은 add 재실행도 기존 파일을 덮어쓰지 않고 새 번호를 받는다(멱등 안전).

사용:
    python3 EZERagent_adr.py add --title "X 도입" --decision "X 채택" \
        [--context "왜"] [--consequences "결과"] \
        [--status accepted|proposed|superseded] [--supersedes NNNN]
    python3 EZERagent_adr.py list [--json]
    python3 EZERagent_adr.py relevant --query "키워드1 키워드2" [--json]
    python3 EZERagent_adr.py --self-test

공통 옵션: --dir <ADR 디렉터리> (기본: $EZERAGENT_PACK_DIR/round/ADR 또는 ~/.EZERagent/pack/round/ADR)

종료 코드: 0 성공 · 1 매칭 0건/없음 · 2 인자·입력 오류 · 3 잠금 실패
의존성: 파이썬 표준 라이브러리만 (네트워크·LLM 호출 없음).
"""

import argparse
import json
import os
import re
import sys
import tempfile
import time

VALID_STATUS = ("accepted", "proposed", "superseded")
ADR_FILE_RE = re.compile(r"^(\d{4})-(.+)\.md$")
NUM_RE = re.compile(r"^\d{4}$")
VALID_CONFIDENCE = ("low", "medium", "high")  # 정성 enum — 수치 score 금지(reward-hack 채널 차단)
DECISION_LOG = "DECISION_LOG.jsonl"           # ADR store에 동거하는 결정 근거 ledger(append-only)
# rubber-stamp 이유 차단 — reason 전체가 보일러플레이트일 때만(단어 포함은 허용·오탐 방지).
# 영상: "'best option'은 이유가 아니다" — 실 trade-off rationale를 강제한다.
BANNED_REASON = ("best option", "the best option", "best choice", "obvious choice",
                 "최선", "최선의 선택", "가장 좋은 선택", "당연", "그냥")


def pack_dir():
    """pack 위치 결정 — src/pack.rs pack_dir()·EZERagent_orchestra의 폴백을 그대로 미러링한다."""
    for key in ("EZERAGENT_PACK_DIR",):
        v = os.environ.get(key, "")
        if v:
            return v
    return os.path.join(os.path.expanduser("~"), ".EZERagent/pack")


def default_adr_dir():
    return os.path.join(pack_dir(), "round", "ADR")


class FileLock:
    """O_CREAT|O_EXCL 잠금파일 — EZERagent_memory.FileLock과 동일 구현(채번 경합 차단).
    다중 노드가 동시에 add 할 때 같은 번호가 두 번 발급되는 것을 막는다."""

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
                try:  # 죽은 프로세스가 남긴 만료 잠금은 회수한다
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


def slugify(title):
    """제목 → 파일명 슬러그. 한글은 보존(영상 ADR은 자연어 제목), 공백·구분자는 하이픈,
    경로 분리자·기타 위생 위험 문자는 제거(파일명 주입·경로 탈출 차단)."""
    s = (title or "").strip().lower()
    s = re.sub(r"[\s_]+", "-", s)              # 공백·언더스코어 → 하이픈
    s = re.sub(r"[^0-9a-z가-힣-]", "", s)       # 영숫자·한글·하이픈만 남김(분리자 제거)
    s = re.sub(r"-{2,}", "-", s).strip("-")    # 중복·양끝 하이픈 정리
    return s


def adr_files(adir):
    """디렉터리의 ADR 파일을 번호 오름차순으로 — NNNN-<slug>.md 패턴만 인정."""
    try:
        names = os.listdir(adir)
    except OSError:
        return []
    out = []
    for n in names:
        m = ADR_FILE_RE.match(n)
        if m:
            out.append((int(m.group(1)), n))
    out.sort(key=lambda x: x[0])
    return out


def next_number(adir):
    """다음 채번 — 기존 최대 번호 + 1 (0001부터). 비어 있으면 1."""
    files = adr_files(adir)
    return (files[-1][0] + 1) if files else 1


def parse_adr(text):
    """ADR 본문에서 title·status·context·decision·consequences 추출.
    형식 불량 섹션은 빈 문자열. relevant 매칭·list 요약의 단일 파서."""
    out = {"title": "", "status": "", "context": "", "decision": "", "consequences": "",
           "options": "", "reason": ""}
    # 제목: 첫 '# NNNN. <title>' 헤더
    m = re.search(r"(?m)^#\s+\d{4}\.\s*(.+?)\s*$", text)
    if m:
        out["title"] = m.group(1).strip()
    # 섹션 본문: '## <라벨>' 다음 '## ' 또는 끝까지
    for key, label in (("status", "Status"), ("context", "Context"),
                       ("decision", "Decision"), ("consequences", "Consequences"),
                       ("options", "Options Considered"), ("reason", "Reason")):
        sm = re.search(r"(?m)^##\s+%s\s*\n(.*?)(?:\n##\s|\Z)" % label, text, re.S)
        if sm:
            out[key] = sm.group(1).strip()
    return out


def parse_options(raw_list):
    """--options 값들을 [{option, rejected_because, selected}]로. 형식 'TEXT :: 거부이유'
    또는 선택안 'TEXT :: SELECTED'(또는 '선택'). '::' 없으면 거부이유 빈 값."""
    opts = []
    for raw in (raw_list or []):
        if "::" in raw:
            text, _, why = raw.partition("::")
            text, why = text.strip(), why.strip()
        else:
            text, why = raw.strip(), ""
        selected = why.upper() == "SELECTED" or why == "선택"
        opts.append({"option": text, "rejected_because": "" if selected else why,
                     "selected": selected})
    return opts


def is_boilerplate_reason(reason):
    """reason 전체가 rubber-stamp 보일러플레이트인가(보수적·whole-reason 매칭으로 오탐 방지)."""
    r = (reason or "").strip().lower().rstrip(" .。!?·")
    return r in BANNED_REASON


def cmd_add(adir, args):
    title = (args.title or "").strip()
    if not title:
        return fail(2, "--title(결정 제목)은 비울 수 없다")
    decision = (args.decision or "").strip()
    if not decision:
        return fail(2, "--decision(내린 결정)은 비울 수 없다")
    status = (args.status or "accepted").strip().lower()
    if status not in VALID_STATUS:
        return fail(2, "status는 %s 중 하나" % "|".join(VALID_STATUS))
    if args.supersedes is not None and not NUM_RE.match(args.supersedes):
        return fail(2, "--supersedes는 4자리 번호(NNNN)여야 한다: %r" % args.supersedes)
    slug = slugify(title)
    if not slug:
        return fail(2, "제목에서 유효한 슬러그를 만들 수 없다(영숫자·한글 없음): %r" % title)

    # ── D3 의사결정 근거(Options Considered + rejected_because + 비보일러플레이트 reason) ──
    # getattr 기본값으로 기존 호출(신 필드 없는 Namespace)과 완전 호환(회귀 0).
    options = parse_options(getattr(args, "options", None))
    reason = (getattr(args, "reason", None) or "").strip()
    material = bool(getattr(args, "material", False)) or bool(options)
    confidence = (getattr(args, "confidence", None) or "medium").strip().lower()
    if confidence not in VALID_CONFIDENCE:
        return fail(2, "confidence는 %s 중 하나" % "|".join(VALID_CONFIDENCE))
    if material:
        # 커버리지 게이트: 단일옵션 rubber-stamp 차단. 모두 잠금/생성 전 거부 → 잔재 0.
        if len(options) < 2:
            return fail(2, "material 결정은 옵션 >=2개 필요(--options 'A :: 거부이유' 반복). 현재 %d" % len(options))
        if sum(1 for o in options if o["selected"]) != 1:
            return fail(2, "옵션 중 정확히 1개를 'TEXT :: SELECTED'로 선택 표시해야 한다")
        for o in options:
            if not o["selected"] and not o["rejected_because"]:
                return fail(2, "거부 옵션 %r에 rejected_because(:: 이유)가 필요하다" % o["option"])
        if not reason:
            return fail(2, "material 결정은 --reason(비보일러플레이트 근거)이 필요하다")
        if is_boilerplate_reason(reason):
            return fail(2, "reason이 보일러플레이트(%r)다 — 실 trade-off를 적어라('best option/최선'은 이유 아님)" % reason)

    os.makedirs(adir, exist_ok=True)
    lock_target = os.path.join(adir, ".adr")  # 채번 직렬화용 잠금 기준점
    try:
        with FileLock(lock_target):
            num = next_number(adir)
            fname = "%04d-%s.md" % (num, slug)
            fpath = os.path.join(adir, fname)
            content = render_adr(num, title, status, args.context,
                                 decision, args.consequences, args.supersedes,
                                 options, reason)
            # 원자적 생성(O_EXCL) — 잠금 하에서도 동일 슬러그 충돌 시 명확히 거부(덮어쓰기 0).
            try:
                fd = os.open(fpath, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            except FileExistsError:
                return fail(2, "이미 존재: %s (다른 제목을 쓰거나 파일을 직접 수정하라)" % fname)
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(content)
            # D3: 동거 결정 ledger(append-only·같은 store) — rsi ledger.jsonl 패턴. score 키 없음.
            if material:
                subject = (getattr(args, "subject", None) or title).strip()
                entry = {"event": "decision", "number": "%04d" % num, "ts": int(time.time()),
                         "stage": getattr(args, "stage", None),
                         "category": getattr(args, "category", None),
                         "subject": subject,
                         "options_considered": [{"option": o["option"],
                                                 "rejected_because": o["rejected_because"]}
                                                for o in options],
                         "selected": next((o["option"] for o in options if o["selected"]), ""),
                         "reason": reason, "confidence": confidence, "adr_file": fname}
                with open(os.path.join(adir, DECISION_LOG), "a", encoding="utf-8") as lf:
                    lf.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except TimeoutError as e:
        return fail(3, str(e))

    print(json.dumps({"added": fname, "number": "%04d" % num,
                      "title": title, "status": status}, ensure_ascii=False))
    return 0


def render_adr(num, title, status, context, decision, consequences, supersedes,
               options=None, reason=None):
    """ADR 본문 렌더 — SSOT 결정기록 형식. D3: 고려한 대안·거부이유·근거(rationale) 추가."""
    lines = []
    lines.append("# %04d. %s" % (num, title))
    lines.append("")
    lines.append("## Status")
    lines.append(status)
    if supersedes:
        # 대체 링크: 영상의 "결정들을 어떤 근거로 하였는지" 추적성 — 폐기된 결정으로 역링크.
        lines.append("")
        lines.append("supersedes [%s](%s-*.md)" % (supersedes, supersedes))
    lines.append("")
    lines.append("## Context")
    lines.append((context or "").strip() or "(미기재)")
    lines.append("")
    lines.append("## Decision")
    lines.append(decision.strip())
    lines.append("")
    # D3: 온보딩 에이전트가 rubber-stamp와 실 trade-off를 구분하도록 대안·거부이유·근거 명시.
    if options:
        lines.append("## Options Considered")
        for o in options:
            if o.get("selected"):
                lines.append("- %s — SELECTED" % o["option"])
            else:
                lines.append("- %s — rejected because: %s"
                             % (o["option"], o.get("rejected_because") or "(미기재)"))
        lines.append("")
        lines.append("## Reason")
        lines.append((reason or "").strip() or "(미기재)")
        lines.append("")
    lines.append("## Consequences")
    lines.append((consequences or "").strip() or "(미기재)")
    lines.append("")
    return "\n".join(lines)


def cmd_list(adir, as_json):
    files = adr_files(adir)
    items = []
    for num, fn in files:
        adr = parse_adr(open(os.path.join(adir, fn), encoding="utf-8",
                             errors="replace").read())
        items.append({"number": "%04d" % num, "file": fn,
                      "title": adr["title"], "status": adr["status"]})
    if as_json:
        print(json.dumps({"dir": adir, "count": len(items), "items": items},
                         ensure_ascii=False, indent=2))
    else:
        for it in items:
            print("%s  [%s]  %s" % (it["number"], it["status"] or "?", it["title"]))
        print("ADR: %d건 (%s)" % (len(items), adir))
    return 0


def query_norm(s):
    """query 정규화 — 소문자·영숫자/한글 토큰 집합(공백분리). relevant 매칭의 단일 규칙."""
    return [t for t in re.split(r"\s+", (s or "").strip().lower()) if t]


def matches(adr, terms):
    """ADR이 query 키워드에 매칭되는가 — 제목/context/decision을 합친 텍스트에 부분일치.
    영상: "이 작업과 관련된 것만 골라내는" 결정론 보조. 매칭된 키워드 목록을 함께 반환."""
    hay = ("%s %s %s %s" % (adr["title"], adr["context"], adr["decision"],
                            adr.get("reason", ""))).lower()
    hit = [t for t in terms if t in hay]
    return hit


def cmd_relevant(adir, query, as_json):
    terms = query_norm(query)
    if not terms:
        return fail(2, "--query(공백분리 키워드)는 비울 수 없다")
    files = adr_files(adir)
    items = []
    for num, fn in files:
        adr = parse_adr(open(os.path.join(adir, fn), encoding="utf-8",
                             errors="replace").read())
        hit = matches(adr, terms)
        if hit:
            items.append({"number": "%04d" % num, "file": fn,
                          "title": adr["title"], "status": adr["status"],
                          "decision": adr["decision"], "matched": hit})
    # 매칭 키워드 많은 순 — 더 관련 깊은 결정을 위로(콤팩트 참조본).
    items.sort(key=lambda x: (-len(x["matched"]), x["number"]))
    if as_json:
        print(json.dumps({"dir": adir, "query": terms, "count": len(items),
                          "items": items}, ensure_ascii=False, indent=2))
    else:
        for it in items:
            print("%s  [%s]  %s" % (it["number"], it["status"] or "?", it["title"]))
            print("    결정: %s" % it["decision"].replace("\n", " "))
            print("    매칭: %s" % ", ".join(it["matched"]))
        print("relevant: %d건 매칭 (query=%s, %s)" % (len(items), " ".join(terms), adir))
    # 영상 취지(관련 결정만 골라내기)에서 0건은 "참조할 과거 결정 없음" — 자율 게이트가
    # 빈 결과를 "통과"로 오독하지 않게 exit 1로 구분(list와 달리 relevant는 질의 도구).
    return 0 if items else 1


def fail(code, msg):
    print(json.dumps({"error": msg}, ensure_ascii=False), file=sys.stderr)
    return code


def self_test():
    """tempdir 라운드트립 — add 채번·섹션 형식·중복 add 새 번호·relevant 매칭/비매칭·
    slug 위생·경로 탈출 방지를 밀폐 검증(preflight 자기검증부)."""
    import contextlib
    import io
    failures = []
    sink = io.StringIO()
    with tempfile.TemporaryDirectory(prefix="EZERagent-adr-selftest-") as td:
        adir = os.path.join(td, "ADR")

        # slug 위생: 경로 탈출·분리자가 슬러그에 새지 않는다
        assert "/" not in slugify("../../etc/passwd"), "slug 경로 탈출"
        assert os.sep not in slugify("a/b\\c"), "slug 분리자 잔존"
        assert slugify("테스트 결정") == "테스트-결정", \
            "한글 제목 슬러그 오류: %r" % slugify("테스트 결정")
        if not slugify("####"):
            pass  # 유효 문자 없으면 빈 슬러그(add가 exit 2로 거부) — 정상

        # add 1: 채번 0001 + 섹션 형식
        ns1 = argparse.Namespace(title="테스트 결정", decision="X 채택", context="왜 X",
                                 consequences="결과 Y", status="accepted", supersedes=None)
        with contextlib.redirect_stdout(sink), contextlib.redirect_stderr(sink):
            rc1 = cmd_add(adir, ns1)
        if rc1 != 0:
            failures.append("첫 add 실패")
        files = adr_files(adir)
        if not files or files[0][0] != 1:
            failures.append("첫 ADR이 0001로 채번되지 않음: %s" % files)
        else:
            body = open(os.path.join(adir, files[0][1]), encoding="utf-8").read()
            for sec in ("# 0001. 테스트 결정", "## Status", "## Context",
                        "## Decision", "X 채택", "## Consequences"):
                if sec not in body:
                    failures.append("첫 ADR 본문에 '%s' 누락" % sec)
            if not files[0][1].startswith("0001-"):
                failures.append("파일명이 0001- 접두가 아님: %s" % files[0][1])

        # add 2: 0002 채번(충돌 없음)
        ns2 = argparse.Namespace(title="두 번째 결정", decision="Y 채택", context=None,
                                 consequences=None, status="proposed", supersedes="0001")
        with contextlib.redirect_stdout(sink), contextlib.redirect_stderr(sink):
            rc2 = cmd_add(adir, ns2)
        files = adr_files(adir)
        if rc2 != 0 or len(files) != 2 or files[1][0] != 2:
            failures.append("두 번째 add 채번 오류(0002 기대): %s" % files)
        body2 = open(os.path.join(adir, files[1][1]), encoding="utf-8").read()
        if "supersedes [0001]" not in body2:
            failures.append("supersedes 링크 누락")
        if "(미기재)" not in body2:
            failures.append("빈 context/consequences가 (미기재)로 채워지지 않음")

        # 같은 add 재실행: 기존 파일을 덮어쓰지 않고 새 번호를 받는다(IMPL_SPEC §N2-5:
        # "같은 add 재실행해도 기존 파일 덮어쓰지 않음(새 번호) — 멱등성은 list가 깨지지
        # 않음으로 판정"). 슬러그가 같아도 번호 접두가 달라 파일명이 다르므로 충돌 없음.
        with contextlib.redirect_stdout(sink), contextlib.redirect_stderr(sink):
            rc3 = cmd_add(adir, ns1)  # ns1과 동일 제목 → 같은 슬러그, 새 번호 0003
        files = adr_files(adir)
        if rc3 != 0 or len(files) != 3 or files[2][0] != 3:
            failures.append("동일 제목 재 add가 새 번호(0003)를 받지 못함: %s" % files)
        # 기존 0001은 무손상(원본 내용 보존 — 덮어쓰기 0)
        orig = open(os.path.join(adir, files[0][1]), encoding="utf-8").read()
        if "X 채택" not in orig or files[0][0] != 1:
            failures.append("재 add가 기존 0001을 덮어쓰거나 손상시킴")

        # list: 2건 출력(파서 라운드트립)
        with contextlib.redirect_stdout(sink), contextlib.redirect_stderr(sink):
            cmd_list(adir, False)

        # relevant: '테스트' → 0001만, '없는키워드' → 0건(exit 1)
        with contextlib.redirect_stdout(sink), contextlib.redirect_stderr(sink):
            rel_rc = cmd_relevant(adir, "테스트", False)
        if rel_rc != 0:
            failures.append("relevant '테스트' 매칭 실패")
        # 결정론 매칭 직접 검증
        a1 = parse_adr(open(os.path.join(adir, files[0][1]), encoding="utf-8").read())
        a2 = parse_adr(open(os.path.join(adir, files[1][1]), encoding="utf-8").read())
        if not matches(a1, query_norm("테스트")):
            failures.append("0001이 '테스트'에 매칭되지 않음")
        if matches(a2, query_norm("테스트")):
            failures.append("0002가 '테스트'에 잘못 매칭(2번은 '두 번째 결정')")
        # decision 본문 매칭도 확인(제목 외 영역 — 영상: 제목/context/decision 참조)
        if not matches(a1, query_norm("채택")):
            failures.append("decision 본문('X 채택') 키워드 매칭 실패")
        with contextlib.redirect_stdout(sink), contextlib.redirect_stderr(sink):
            none_rc = cmd_relevant(adir, "절대로없는키워드zzz", False)
        if none_rc != 1:
            failures.append("매칭 0건인데 exit 1 아님")

        # 잘못된 인자: 빈 제목·잘못된 status·잘못된 supersedes
        with contextlib.redirect_stdout(sink), contextlib.redirect_stderr(sink):
            if cmd_add(adir, argparse.Namespace(
                    title="", decision="d", context=None, consequences=None,
                    status="accepted", supersedes=None)) != 2:
                failures.append("빈 제목 add가 exit 2로 거부되지 않음")
            if cmd_add(adir, argparse.Namespace(
                    title="t", decision="d", context=None, consequences=None,
                    status="wrong", supersedes=None)) != 2:
                failures.append("잘못된 status가 거부되지 않음")
            if cmd_add(adir, argparse.Namespace(
                    title="t", decision="d", context=None, consequences=None,
                    status="accepted", supersedes="bad")) != 2:
                failures.append("잘못된 supersedes가 거부되지 않음")
        # 위 거부 add들이 디렉터리를 오염시키지 않았다(재 add 포함 3건 유지)
        if len(adr_files(adir)) != 3:
            failures.append("거부된 add가 파일을 남김")

        # ── D3: 의사결정 근거(Options Considered + 동거 ledger + 커버리지 게이트) ──
        before = len(adr_files(adir))
        mns = argparse.Namespace(title="아키텍처 선택", decision="A 채택", context=None,
                                 consequences=None, status="accepted", supersedes=None,
                                 options=["A :: SELECTED", "B :: 비용 과다", "C :: 락인"],
                                 reason="A는 무료 로컬이고 락인이 없어 EZERagent 제약에 부합",
                                 material=True, stage="design", category="provider",
                                 subject=None, confidence="high")
        with contextlib.redirect_stdout(sink), contextlib.redirect_stderr(sink):
            if cmd_add(adir, mns) != 0:
                failures.append("material add(옵션2+reason) 실패")
        mfiles = adr_files(adir)
        if len(mfiles) == before + 1:
            mbody = open(os.path.join(adir, mfiles[-1][1]), encoding="utf-8").read()
            for sec in ("## Options Considered", "— SELECTED",
                        "rejected because: 비용 과다", "## Reason"):
                if sec not in mbody:
                    failures.append("material ADR 본문에 %r 누락" % sec)
        else:
            failures.append("material add가 새 ADR을 만들지 않음")
        # 동거 ledger: 1줄·score 키 부재·confidence/selected/options 정합
        logp = os.path.join(adir, DECISION_LOG)
        if not os.path.isfile(logp):
            failures.append("DECISION_LOG.jsonl 미생성")
        else:
            llines = [l for l in open(logp, encoding="utf-8").read().splitlines() if l.strip()]
            ent = json.loads(llines[0]) if llines else {}
            if len(llines) != 1:
                failures.append("ledger 줄 수 오류: %d" % len(llines))
            if "score" in json.dumps(ent, ensure_ascii=False):
                failures.append("ledger에 금지된 score 키 존재")
            if ent.get("confidence") != "high" or ent.get("selected") != "A" \
                    or len(ent.get("options_considered", [])) != 3:
                failures.append("ledger 메타 정합 오류: %s" % ent)
        # 게이트: 단일옵션 material → exit 2
        def _g(**kw):
            base = dict(title="t", decision="d", context=None, consequences=None,
                        status="accepted", supersedes=None, options=None, reason=None,
                        material=False, stage=None, category=None, subject=None,
                        confidence="medium")
            base.update(kw)
            with contextlib.redirect_stdout(sink), contextlib.redirect_stderr(sink):
                return cmd_add(adir, argparse.Namespace(**base))
        if _g(title="단일", options=["only :: SELECTED"], reason="r", material=True) != 2:
            failures.append("단일옵션 material이 exit 2로 거부되지 않음")
        if _g(title="보일러", options=["A :: SELECTED", "B :: x"], reason="최선", material=True) != 2:
            failures.append("보일러플레이트 reason('최선')이 거부되지 않음")
        if _g(title="노리즌", options=["A :: SELECTED", "B :: x"], reason=None, material=True) != 2:
            failures.append("reason 없는 material이 거부되지 않음")
        # 비-material 일반 add(회귀)·'최선' 포함 reason도 비material이면 통과(오탐 방지)
        if _g(title="비머티리얼", reason="최선의 분석을 거쳐 채택") != 0:
            failures.append("비-material 일반 add 실패(회귀)")
        # 거부 게이트는 파일 무생성: material 정상 + 비material 통과 = before+2
        if len(adr_files(adir)) != before + 2:
            failures.append("게이트 거부 add가 파일을 남김: %d" % len(adr_files(adir)))

        # 잠금 잔류 없음
        if os.path.exists(os.path.join(adir, ".adr.lock")):
            failures.append("잠금파일 잔류")

    print(json.dumps({"self_test": "ok" if not failures else "fail",
                      "failures": failures}, ensure_ascii=False, indent=2))
    return 0 if not failures else 1


def main():
    # preflight 호환: `--self-test`는 subcommand 없이도 동작해야 한다(가로채기).
    if "--self-test" in sys.argv:
        return self_test()
    ap = argparse.ArgumentParser(description="ADR 결정기록 결정론 도구(하네스 N2)")
    ap.add_argument("--dir", default=None, help="ADR 디렉터리 (기본: pack/round/ADR)")
    sub = ap.add_subparsers(dest="cmd")

    a = sub.add_parser("add", help="설계 결정 1건 채번 기록 (0001+ · NNNN-slug.md)")
    a.add_argument("--title", required=True, help="결정 제목 (슬러그·헤더에 사용)")
    a.add_argument("--decision", required=True, help="내린 결정")
    a.add_argument("--context", default=None, help="배경·문제 (왜 결정했나)")
    a.add_argument("--consequences", default=None, help="결과·trade-off")
    a.add_argument("--status", default="accepted", choices=VALID_STATUS)
    a.add_argument("--supersedes", default=None, help="대체하는 기존 ADR 번호(NNNN)")
    # D3 의사결정 근거(rationale) — 신 인자. 미지정 시 기존 동작과 동일(비-material).
    a.add_argument("--options", action="append", default=None,
                   help="고려한 대안 'TEXT :: 거부이유'(선택안은 'TEXT :: SELECTED'). 반복. >=2면 material")
    a.add_argument("--reason", default=None, help="선택 근거(비보일러플레이트 — 'best option/최선' 거부)")
    a.add_argument("--material", action="store_true", help="중대 결정 — 옵션>=2 커버리지 게이트 강제")
    a.add_argument("--stage", default=None, help="결정이 난 단계(ledger 메타)")
    a.add_argument("--category", default=None, help="결정 분류(ledger 메타)")
    a.add_argument("--subject", default=None, help="결정 주제(기본: 제목)")
    a.add_argument("--confidence", default="medium", choices=VALID_CONFIDENCE,
                   help="정성 신뢰도(수치 score 금지)")

    li = sub.add_parser("list", help="누적 ADR 한 줄 일람")
    li.add_argument("--json", action="store_true")

    re = sub.add_parser("relevant", help="이 작업 관련 ADR만 추림 (키워드 매칭)")
    re.add_argument("--query", required=True, help="공백분리 키워드")
    re.add_argument("--json", action="store_true")

    args = ap.parse_args()
    adir = args.dir or default_adr_dir()
    if args.cmd == "add":
        return cmd_add(adir, args)
    if args.cmd == "list":
        return cmd_list(adir, args.json)
    if args.cmd == "relevant":
        return cmd_relevant(adir, args.query, args.json)
    ap.print_help()
    return 2


if __name__ == "__main__":
    sys.exit(main())
