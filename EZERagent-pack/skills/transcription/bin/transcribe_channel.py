#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""transcribe_channel — URL/path → 단어 단위 타임스탬프 전사 단일 채널 (OPP-09).

"URL 하나 → 자막 우선, 없으면 ASR 폴백 → transcript.json"을 **하나의 멘탈모델**로
통합한다. AR(Agent Reach)의 BaseChannel 계약(순서 있는 후보 리스트 · 성공성×종결성
분리 · probe 자연폴백)만 흡수해 EZERagent 인프라로 재구현한다(AR 소스 복붙 0):

  - provider 랭킹 = 기존 **EZERagent_select**(새 선택엔진 0). transcription capability의
    `ytdlp_subs`(무키 free 자막)가 `transcriber_whisperx`(무키 로컬 ASR) 위에 있되,
    자막 부재/단어 타임스탬프 필요 시 **자연 폴백**(if문 분기 0, EZERagent_select가 결정).
  - 자막 추출 = 기존 **phase0._youtube(subs=True)**(insane-search 벤더링·host-naming
    허용 유일 파일). vtt → segments 파싱은 거기서 stdlib re로 수행.
  - URL→ASR = `_ytdlp_audio()`로 오디오를 받아(yt-dlp -x) whisperx에 넘긴다. 실제
    ASR 실행은 transcription 스킬 레시피(별 노드/사람) — 이 글루는 그 호출 자리만
    명문화한다(producer≠evaluator: 품질 채점은 video-verify-audio-sync).

산출물 `transcript.json`(transcription/SKILL.md 계약 확장 — 파괴적 변경 0):
  기존 키(source/language/provider/segments/duration_s) 유지 +
  `source_kind`("url"|"file") + `channel_trace`[](어느 채널이 산출했고 앞선 채널은
  왜 비었나 — PHIL-06/PHIL-09 negative knowledge 박제).

stdlib only · 네트워크는 subprocess(yt-dlp)로만. 종량제 0(Groq/OpenAI 폴백 거부).

사용:
    transcribe_channel.py run --source <URL|path> [--intent ...] [--want-words]
        [--prefer <id>] [--langs ko,en] [--catalog <C.json>] [--out transcript.json]
        [--audio-out <wav>] [--dry-run]
    transcribe_channel.py --self-test

종료 코드: 0 성공(종결) · 1 채널 소진(가용 provider 0) · 2 인자/입력 오류.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
from urllib.parse import urlsplit


# ── 의존 모듈 결정론 로드 (pack 트리 내 경로 — SOT/LIVE 양쪽 동형) ──────────────
def _pack_dir() -> str:
    env = os.environ.get("EZERAGENT_PACK_DIR")
    if env:
        return os.path.expanduser(env)
    # 이 파일: <pack>/skills/transcription/bin/transcribe_channel.py → 3단 상위가 pack
    return os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))


def _load(modname: str, path: str):
    spec = importlib.util.spec_from_file_location(modname, path)
    if spec is None or spec.loader is None:
        raise ImportError("cannot load %s from %s" % (modname, path))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _import_deps():
    pack = _pack_dir()
    EZERagent_select = _load("EZERagent_select", os.path.join(pack, "bin", "EZERagent_select.py"))
    # phase0 imports `from .proc import utf8_env` → engine/ 디렉터리를 패키지로 로드해야 한다.
    engine_dir = os.path.join(pack, "skills", "insane-search", "engine")
    if engine_dir not in sys.path:
        sys.path.insert(0, os.path.dirname(engine_dir))  # insane-search/ 를 sys.path에
    phase0 = _load("engine.phase0", os.path.join(engine_dir, "phase0.py"))
    return EZERagent_select, phase0


def _default_catalog() -> str:
    return os.path.join(_pack_dir(), "round", "video_provider_catalog.json")


# ── 소스 종류 판정 ──────────────────────────────────────────────────────────
def _is_url(s: str) -> bool:
    return urlsplit(s).scheme in ("http", "https")


# ── URL → 로컬 오디오 글루 (whisperx 폴백 전처리) ─────────────────────────────
def _ytdlp_audio(url: str, out_wav: str, *, env, timeout: int = 600) -> str:
    """yt-dlp -x 로 오디오를 받아 16kHz 모노 wav로(transcription/SKILL.md:47 레시피).

    실제 다운로드는 네트워크 의존이라 호출 자리만 명문화한다. 반환=로컬 wav 경로."""
    subprocess.run(
        ["yt-dlp", "-x", "--audio-format", "wav",
         "--postprocessor-args", "ffmpeg:-ar 16000 -ac 1",
         "-o", out_wav, url],
        capture_output=True, text=True, encoding="utf-8", errors="strict",
        env=env, timeout=timeout, check=True,
    )
    return out_wav


class ChannelExhausted(Exception):
    """가용 transcription provider가 0 — 무음실패 아님(channel_trace 동반)."""

    def __init__(self, trace):
        super().__init__("transcription channel exhausted")
        self.trace = trace


# ── 단일 채널 본체 ──────────────────────────────────────────────────────────
def transcribe(source, *, intent="", want_words=False, prefer=None,
               langs=("ko", "en"), catalog_path=None, deps=None,
               whisperx=None, audio_out=None, audio_fetcher=None) -> dict:
    """URL/path → transcript.json dict. provider 분기는 EZERagent_select가 결정한다.

    deps=(EZERagent_select, phase0) 주입 가능(테스트 모킹). whisperx=콜러블 주입 가능
    (실 ASR은 별 노드/사람 레시피 — 미주입이면 호출 자리에서 NotImplementedError).
    audio_fetcher=URL→로컬 오디오 콜러블 주입 가능(기본 _ytdlp_audio — 테스트 모킹용).
    """
    fetch_audio = audio_fetcher or _ytdlp_audio
    EZERagent_select, phase0 = deps if deps else _import_deps()
    catalog = EZERagent_select.load_catalog(catalog_path or _default_catalog())
    src_kind = "url" if _is_url(source) else "file"
    ctx = {"intent": intent, "prefer": prefer}
    # free_first=True: 무키 free 바닥(자막·로컬 ASR) 우선. 반환 (ranked, unavailable, forced).
    ranked, unavailable, _forced = EZERagent_select.rank(
        catalog, "transcription", ctx, True)
    trace: list[dict] = []

    for prov in ranked:                      # PHIL-02 ordered candidate list (dict, prov["id"])
        pid = prov["id"]
        if pid == "ytdlp_subs":
            if src_kind != "url":
                trace.append({"provider": pid, "verdict": "n/a", "note": "not a url"})
                continue
            r = phase0._youtube(source, 15, subs=True, langs=tuple(langs))
            if r["ok"] and not (want_words and not r.get("has_words")):
                # 자막 추출 성공 + (단어 불필요 또는 단어 보유) → 종결
                trace.append({"provider": pid, "verdict": "strong_ok"
                              if r["route"] == "yt-dlp-subs" else "weak_ok",
                              "note": r["route"]})
                return _emit(source, src_kind, pid, r["segments"], langs, trace)
            # 자막 없음 또는 단어 타임스탬프 필요한데 미보유 → 비종결 폴백(R6)
            why = ("no subtitles" if not r["ok"]
                   else "segment-level only; word timestamps required")
            trace.append({"provider": pid, "verdict": "empty", "note": why})
            continue
        if pid == "transcriber_whisperx":
            env = _utf8_env(EZERagent_select, phase0)
            if src_kind == "file":
                media = source
                tmp = None
            else:
                tmp = audio_out or os.path.join(
                    tempfile.gettempdir(), "transcribe_channel_audio.wav")
                media = fetch_audio(source, tmp, env=env)
            if whisperx is None:
                trace.append({"provider": pid, "verdict": "deferred",
                              "note": "whisperx ASR recipe runs in transcription skill node"})
                raise NotImplementedError(
                    "whisperx ASR not wired here — run transcription skill on %s "
                    "(channel_trace: %s)" % (media, json.dumps(trace, ensure_ascii=False)))
            segments = whisperx(media, intent=intent)
            trace.append({"provider": pid, "verdict": "strong_ok", "note": "local asr"})
            return _emit(source, src_kind, pid, segments, langs, trace)
        # 미지 provider는 무시(fail-safe — EZERagent_select가 카탈로그를 늘려도 글루 불변)
        trace.append({"provider": pid, "verdict": "skip", "note": "unhandled provider"})

    raise ChannelExhausted(trace)


def _utf8_env(EZERagent_select, phase0):
    try:
        return phase0.utf8_env()
    except Exception:
        return os.environ.copy()


def _emit(source, src_kind, provider, segments, langs, trace) -> dict:
    duration = max((s.get("end", 0.0) for s in segments), default=0.0)
    return {
        "source": source,
        "source_kind": src_kind,
        "language": (list(langs)[0] if langs else None),
        "provider": provider,
        "channel_trace": trace,
        "segments": segments,
        "duration_s": round(duration, 3),
    }


# ── CLI ─────────────────────────────────────────────────────────────────────
def cmd_run(args) -> int:
    langs = tuple(s for s in (args.langs or "ko,en").split(",") if s.strip())
    try:
        out = transcribe(args.source, intent=args.intent or "",
                         want_words=args.want_words, prefer=args.prefer,
                         langs=langs, catalog_path=args.catalog,
                         audio_out=args.audio_out)
    except ChannelExhausted as e:
        print(json.dumps({"error": "channel exhausted (no available provider)",
                          "channel_trace": e.trace}, ensure_ascii=False, indent=2),
              file=sys.stderr)
        return 1
    except NotImplementedError as e:
        # whisperx 미배선 — 자막 폴백 지점까지의 trace를 정직하게 보고(무음실패 아님)
        print(str(e), file=sys.stderr)
        return 1
    text = json.dumps(out, ensure_ascii=False, indent=2)
    if args.dry_run or not args.out:
        print(text)
    else:
        with open(args.out, "w", encoding="utf-8") as f:
            f.write(text + "\n")
        print("wrote %s (provider=%s, %d segments)"
              % (args.out, out["provider"], len(out["segments"])))
    return 0


def self_test() -> int:
    failures = []

    # 1) _parse_vtt (phase0): publisher vtt → segments, word timestamps 없음
    _, phase0 = _import_deps()
    vtt = ("WEBVTT\n\n00:00:00.000 --> 00:00:02.500\nHello world\n\n"
           "00:00:02.500 --> 00:00:05.000\n<00:00:03.000><c>second</c> cue\n")
    segs = phase0._parse_vtt(vtt)
    if len(segs) != 2:
        failures.append("vtt parse: expected 2 segments, got %d" % len(segs))
    elif segs[0]["text"] != "Hello world" or "second cue" not in segs[1]["text"]:
        failures.append("vtt parse text wrong: %s" % segs)
    elif not (segs[0]["start"] == 0.0 and segs[0]["end"] == 2.5):
        failures.append("vtt parse timing wrong: %s" % segs[0])
    if phase0._parse_vtt("") != [] or phase0._parse_vtt("garbage\nno cues") != []:
        failures.append("empty/garbage vtt should yield []")

    # 2) _is_url
    if not _is_url("https://x/y") or _is_url("/local/path.mp4"):
        failures.append("_is_url misclassified")

    # 3) ordered candidate fallback: 자막 없음(EMPTY) → whisperx 폴백·trace 2엔트리
    class _P0:
        def _youtube(self, url, timeout, *, subs=False, langs=()):
            return {"ok": False, "route": None, "segments": [], "has_words": False,
                    "attempts": []}
    class _JS:
        def load_catalog(self, p):
            return {}
        def rank(self, cat, cap, ctx, ff):
            return ([{"id": "ytdlp_subs"}, {"id": "transcriber_whisperx"}], [], None)
    def _wx(media, intent=""):
        return [{"start": 0.0, "end": 1.0, "text": "asr", "words": [
            {"w": "asr", "start": 0.0, "end": 1.0}]}]
    def _fake_audio(url, out, *, env, timeout=600):
        return out  # no network — pretend audio fetched
    out = transcribe("https://v/1", deps=(_JS(), _P0()), whisperx=_wx,
                     audio_fetcher=_fake_audio)
    if out["provider"] != "transcriber_whisperx":
        failures.append("fallback: provider should be whisperx, got %s" % out["provider"])
    if len(out["channel_trace"]) != 2:
        failures.append("fallback: channel_trace should have 2 entries, got %s"
                        % out["channel_trace"])
    elif out["channel_trace"][0]["provider"] != "ytdlp_subs" or \
            out["channel_trace"][0]["verdict"] != "empty":
        failures.append("fallback: first trace not ytdlp_subs/empty: %s"
                        % out["channel_trace"][0])
    if out["source_kind"] != "url":
        failures.append("source_kind should be url")

    # 4) 자막 있음 → ytdlp_subs 종결, whisperx 미호출
    class _P0ok:
        def _youtube(self, url, timeout, *, subs=False, langs=()):
            return {"ok": True, "route": "yt-dlp-subs", "has_words": False,
                    "segments": [{"start": 0.0, "end": 2.0, "text": "hi"}], "attempts": []}
    called = {"wx": False}
    def _wx2(media, intent=""):
        called["wx"] = True
        return []
    out2 = transcribe("https://v/2", deps=(_JS(), _P0ok()), whisperx=_wx2)
    if out2["provider"] != "ytdlp_subs":
        failures.append("subs present: provider should be ytdlp_subs")
    if called["wx"]:
        failures.append("subs present: whisperx must NOT be called (compute waste)")
    if out2["channel_trace"][-1]["verdict"] != "strong_ok":
        failures.append("subs present: verdict should be strong_ok")
    if out2["duration_s"] != 2.0:
        failures.append("duration_s should be 2.0, got %s" % out2["duration_s"])

    # 5) want_words=True + 세그먼트자막(단어 없음) → whisperx 격상
    out3 = transcribe("https://v/3", deps=(_JS(), _P0ok()), whisperx=_wx,
                      want_words=True, audio_fetcher=_fake_audio)
    if out3["provider"] != "transcriber_whisperx":
        failures.append("want_words: should escalate to whisperx, got %s" % out3["provider"])
    if out3["channel_trace"][0]["verdict"] != "empty":
        failures.append("want_words: ytdlp_subs should be empty (word ts required)")

    # 6) file source → ytdlp_subs n/a, whisperx 직행
    out4 = transcribe("/local/a.mp4", deps=(_JS(), _P0ok()), whisperx=_wx)
    if out4["provider"] != "transcriber_whisperx" or out4["source_kind"] != "file":
        failures.append("file source routing wrong: %s" % out4["provider"])
    if out4["channel_trace"][0]["verdict"] != "n/a":
        failures.append("file source: ytdlp_subs should be n/a")

    # 7) 채널 소진(가용 0) → ChannelExhausted
    class _JSempty:
        def load_catalog(self, p):
            return {}
        def rank(self, cat, cap, ctx, ff):
            return ([], [], None)
    try:
        transcribe("https://v/4", deps=(_JSempty(), _P0ok()), whisperx=_wx)
        failures.append("empty ranking should raise ChannelExhausted")
    except ChannelExhausted:
        pass

    print(json.dumps({"self_test": "ok" if not failures else "fail",
                      "failures": failures}, ensure_ascii=False, indent=2))
    return 0 if not failures else 1


def main() -> int:
    ap = argparse.ArgumentParser(description="URL/path → transcript.json 단일 채널 (OPP-09)")
    ap.add_argument("--self-test", action="store_true")
    sub = ap.add_subparsers(dest="cmd")
    r = sub.add_parser("run", help="전사 채널 실행")
    r.add_argument("--source", required=True, help="URL 또는 로컬 미디어 경로")
    r.add_argument("--intent", default="")
    r.add_argument("--want-words", action="store_true", help="단어 타임스탬프 필수(자막→ASR 격상)")
    r.add_argument("--prefer", default=None)
    r.add_argument("--langs", default="ko,en")
    r.add_argument("--catalog", default=None)
    r.add_argument("--out", default=None, help="transcript.json 경로(미지정=stdout)")
    r.add_argument("--audio-out", default=None, help="URL→ASR 시 오디오 wav 경로")
    r.add_argument("--dry-run", action="store_true", help="파일 미기록·stdout 출력")
    args = ap.parse_args()
    if args.self_test:
        return self_test()
    if args.cmd == "run":
        return cmd_run(args)
    ap.print_help()
    return 2


if __name__ == "__main__":
    sys.exit(main())
