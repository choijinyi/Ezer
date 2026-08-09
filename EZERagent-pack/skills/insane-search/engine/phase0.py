"""Phase 0 — official public-API router (the SANCTIONED exception to No-Site-Name).

Per SKILL.md R5, platforms that publish official no-auth public endpoints get a
deterministic route tried BEFORE the generic WAF grid. This is the *enforced,
in-engine* version of what used to be agent-driven curl snippets in SKILL.md —
so the agent can no longer silently skip it (which is exactly how Reddit/X were
wrongly declared "blocked": the grid 403'd on `.json` and nobody tried `.rss`).

This file is the ONLY engine/ module allowed to name platform hosts; it is
exempted in `bias_check.EXPLICIT_ALLOW_FILES`. Do NOT add per-site logic to any
other engine file — generic WAF handling stays site-agnostic.

Contract:
    route(url) -> Optional[dict]
      None              → url is not a recognised Phase-0 platform; caller runs
                          the generic grid as usual.
      {"platform","ok","route","content","final_url","attempts":[...]}
                        → recognised platform. `ok` says whether an official
                          route succeeded. Even on ok=False the caller should
                          fall through to the grid, but `attempts` is recorded
                          so failure is never silent.

Each attempt dict: {"route","platform","ok","status","bytes","note"} and an
optional "auth" flag. `auth=True` is a first-class negative-knowledge signal
(login/iframe wall etc.) that the caller maps to `Verdict.AUTH_REQUIRED` instead
of the generic BLOCKED — "auth required" is honest about *why* the route stops
(retrying TLS cannot help) rather than implying a transient WAF block.
"""
from __future__ import annotations

import re
import subprocess
from typing import Optional
from urllib.parse import parse_qs, urlsplit

from .proc import utf8_env


# --- low-level helpers -------------------------------------------------------
def _cffi_get(url: str, *, impersonate: str = "safari", timeout: int = 15,
              extra_referer: str = ""):
    from curl_cffi import requests as r  # lazy: engine works even if missing
    headers = {
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9,ko;q=0.8",
    }
    if extra_referer:
        headers["Referer"] = extra_referer
    return r.get(
        url,
        impersonate=impersonate,  # type: ignore[arg-type]
        timeout=timeout,
        headers=headers,
        allow_redirects=True,
    )


def _host(url: str) -> str:
    h = (urlsplit(url).hostname or "").lower()
    return h[4:] if h.startswith("www.") else h  # strip the literal "www." prefix only


def _attempt(platform: str, route: str, ok: bool, status: int, body: str, note: str = "",
             auth: bool = False) -> dict:
    # `auth=True` marks a terminal "login/auth wall" (not a transient block) so the
    # caller can surface Verdict.AUTH_REQUIRED. Existing callers omit it (default
    # False) → no behaviour change for reddit/x/youtube.
    a = {"platform": platform, "route": route, "ok": ok, "status": status,
         "bytes": len(body or ""), "note": note}
    if auth:
        a["auth"] = True
    return a


# --- platform detectors ------------------------------------------------------
def _detect(url: str) -> Optional[str]:
    h = _host(url)
    if not h:
        return None
    if "reddit.com" in h or h == "redd.it":
        return "reddit"
    if h in ("x.com", "twitter.com") or h.endswith(".x.com") or h.endswith(".twitter.com"):
        return "x"
    if "youtube.com" in h or h == "youtu.be":
        return "youtube"
    # Naver no-auth public endpoints (clean-room port of references/naver.md).
    # Scope is Korea/Naver only; Chinese platforms (bilibili/小红书) and Chzzk are
    # intentionally NOT routed — they have no measured no-auth contract in
    # references/ (would be a hallucinated/AR-imported path). See OPP-03 REVISE.
    if h == "naver.com" or h.endswith(".naver.com") or h.endswith(".naver.me"):
        return "naver"
    return None


# --- reddit ------------------------------------------------------------------
def _reddit(url: str, timeout: int) -> dict:
    attempts: list[dict] = []
    base = url.split("?", 1)[0].rstrip("/")
    # Build an .rss / .json target from the path (works for /r/<sub> and post URLs).
    rss_url = base + ("/.rss" if "/comments/" not in base else ".rss")
    json_url = base + ("/.json" if "/comments/" not in base else ".json")

    # Route 1: RSS (the route that actually survives — Reddit gates the JSON API).
    try:
        x = _cffi_get(rss_url, timeout=timeout)
        ok = x.status_code == 200 and ("<rss" in x.text or "<feed" in x.text)
        attempts.append(_attempt("reddit", "rss", ok, x.status_code, x.text,
                                 "feed" if ok else "no-feed-markers"))
        if ok:
            return {"platform": "reddit", "ok": True, "route": "rss",
                    "content": x.text, "final_url": rss_url, "attempts": attempts}
    except Exception as e:
        attempts.append(_attempt("reddit", "rss", False, 0, "", f"{type(e).__name__}"))

    # Route 2: JSON via curl_cffi (often 403 now, but try — cheap).
    try:
        x = _cffi_get(json_url, timeout=timeout)
        ok = x.status_code == 200 and x.text.lstrip().startswith(("{", "["))
        attempts.append(_attempt("reddit", "json", ok, x.status_code, x.text,
                                 "json" if ok else f"status={x.status_code}"))
        if ok:
            return {"platform": "reddit", "ok": True, "route": "json",
                    "content": x.text, "final_url": json_url, "attempts": attempts}
    except Exception as e:
        attempts.append(_attempt("reddit", "json", False, 0, "", f"{type(e).__name__}"))

    return {"platform": "reddit", "ok": False, "route": None, "content": "",
            "final_url": url, "attempts": attempts}


# --- x / twitter -------------------------------------------------------------
_TWEET_ID_RE = re.compile(r"/status(?:es)?/(\d+)")


def _x(url: str, timeout: int) -> dict:
    attempts: list[dict] = []
    m = _TWEET_ID_RE.search(url)

    if m:  # single tweet → tweet-result + oembed (both no-auth, reliable)
        tid = m.group(1)
        try:
            x = _cffi_get(f"https://cdn.syndication.twimg.com/tweet-result?id={tid}&token=a", timeout=timeout)
            d = x.json() if x.status_code == 200 else {}
            ok = bool(d.get("text"))
            attempts.append(_attempt("x", "tweet-result", ok, x.status_code, x.text,
                                     "has-text" if ok else f"status={x.status_code}"))
            if ok:
                return {"platform": "x", "ok": True, "route": "tweet-result",
                        "content": x.text, "final_url": url, "attempts": attempts}
        except Exception as e:
            attempts.append(_attempt("x", "tweet-result", False, 0, "", f"{type(e).__name__}"))
        try:
            ourl = f"https://publish.twitter.com/oembed?url=https://twitter.com/i/status/{tid}&omit_script=1"
            x = _cffi_get(ourl, timeout=timeout)
            d = x.json() if x.status_code == 200 else {}
            ok = bool(d.get("html"))
            attempts.append(_attempt("x", "oembed", ok, x.status_code, x.text,
                                     "has-html" if ok else f"status={x.status_code}"))
            if ok:
                return {"platform": "x", "ok": True, "route": "oembed",
                        "content": x.text, "final_url": ourl, "attempts": attempts}
        except Exception as e:
            attempts.append(_attempt("x", "oembed", False, 0, "", f"{type(e).__name__}"))
    else:  # profile timeline → syndication (rate-limit-prone; retry once)
        handle = urlsplit(url).path.strip("/").split("/")[0]
        _reserved = {"i", "search", "home", "explore", "messages", "notifications", "settings", "hashtag"}
        if handle and handle.lower() not in _reserved:
            surl = f"https://syndication.twitter.com/srv/timeline-profile/screen-name/{handle}"
            for attempt_no in range(2):
                try:
                    x = _cffi_get(surl, timeout=timeout)
                    ok = x.status_code == 200 and "__NEXT_DATA__" in x.text
                    attempts.append(_attempt("x", f"syndication-timeline#{attempt_no+1}", ok,
                                             x.status_code, x.text,
                                             "timeline" if ok else f"status={x.status_code}"))
                    if ok:
                        return {"platform": "x", "ok": True, "route": "syndication-timeline",
                                "content": x.text, "final_url": surl, "attempts": attempts}
                except Exception as e:
                    attempts.append(_attempt("x", f"syndication-timeline#{attempt_no+1}", False, 0, "", f"{type(e).__name__}"))

    return {"platform": "x", "ok": False, "route": None, "content": "",
            "final_url": url, "attempts": attempts}


# --- youtube subtitle parsing (OPP-09 — stdlib clean-room VTT → segments) ----
# WebVTT cue timing line: `HH:MM:SS.mmm --> HH:MM:SS.mmm [settings]`. yt-dlp also
# emits SRT-style `HH:MM:SS,mmm` with a comma; accept both. We intentionally do
# NOT depend on any upstream webvtt/srt library (clean-room: stdlib re only).
_VTT_CUE_RE = re.compile(
    r"(\d{1,2}):(\d{2}):(\d{2})[.,](\d{1,3})\s*-->\s*"
    r"(\d{1,2}):(\d{2}):(\d{2})[.,](\d{1,3})"
)
# Inline cue tags YouTube embeds in auto-caption text (e.g. <00:00:01.200><c> ... </c>).
_VTT_TAG_RE = re.compile(r"<[^>]+>")


def _vtt_ts(h: str, m: str, s: str, ms: str) -> float:
    return int(h) * 3600 + int(m) * 60 + int(s) + int(ms.ljust(3, "0")) / 1000.0


def _parse_vtt(text: str) -> list[dict]:
    """Parse a WebVTT/SRT subtitle body into transcript segments (stdlib only).

    Returns [{"start","end","text"}] — no words[] (publisher/auto VTT carry
    segment-level timing only; word-level timestamps require ASR → §4 escalation).
    Empty/unparsable input returns [] so the caller falls back (EMPTY, non-terminal).
    """
    segments: list[dict] = []
    lines = (text or "").replace("\r\n", "\n").replace("\r", "\n").split("\n")
    i, n = 0, len(lines)
    while i < n:
        m = _VTT_CUE_RE.search(lines[i])
        if not m:
            i += 1
            continue
        start = _vtt_ts(*m.group(1, 2, 3, 4))
        end = _vtt_ts(*m.group(5, 6, 7, 8))
        i += 1
        buf: list[str] = []
        while i < n and lines[i].strip() and not _VTT_CUE_RE.search(lines[i]):
            buf.append(_VTT_TAG_RE.sub("", lines[i]).strip())
            i += 1
        body = " ".join(t for t in buf if t).strip()
        if body and end >= start:
            segments.append({"start": round(start, 3), "end": round(end, 3), "text": body})
    return segments


def _ytdlp_subs(url: str, timeout: int, langs: tuple[str, ...], auto: bool) -> dict:
    """One yt-dlp subtitle route (publisher when auto=False, auto-caption when True).

    Prints the chosen VTT to stdout via `-o -` so no temp files are written
    (clean-room, side-effect-light). Returns {"ok","segments","stdout","note"}.
    """
    flag = "--write-auto-subs" if auto else "--write-subs"
    p = subprocess.run(
        ["yt-dlp", flag, "--skip-download", "--sub-format", "vtt",
         "--sub-langs", ",".join(langs), "-o", "-", url],
        capture_output=True, text=True,
        encoding="utf-8", errors="strict",  # OPP-16: high-integrity child text — fail-loud
        env=utf8_env(),
        timeout=max(timeout, 60),
    )
    segments = _parse_vtt(p.stdout) if p.returncode == 0 else []
    note = ("subtitles" if segments
            else ("no-segments" if p.returncode == 0 else (p.stderr or "").strip()[:80]))
    return {"ok": bool(segments), "segments": segments, "stdout": p.stdout, "note": note}


# --- youtube -----------------------------------------------------------------
def _youtube(url: str, timeout: int, *, subs: bool = False,
             langs: tuple[str, ...] = ("ko", "en")) -> dict:
    """YouTube Phase-0 router.

    Default (subs=False) = metadata-only dump-json (insane-search page reading;
    callers like fetch_chain are unaffected). subs=True (transcribe channel,
    OPP-09) prepends two subtitle routes BEFORE dump-json:
      route 1 --write-subs       → publisher captions   STRONG_OK
      route 2 --write-auto-subs  → auto captions        WEAK_OK
      route 3 --dump-json        → metadata only (no subtitles → EMPTY, fall back)
    On the subtitle routes the returned dict carries `segments`/`has_words`
    (transcript material); `has_words` is always False (VTT = segment-level only).
    """
    attempts: list[dict] = []
    if subs:
        try:
            r = _ytdlp_subs(url, timeout, langs, auto=False)
            attempts.append(_attempt("youtube", "yt-dlp-subs", r["ok"],
                                     200 if r["ok"] else 0, r["stdout"], r["note"]))
            if r["ok"]:
                return {"platform": "youtube", "ok": True, "route": "yt-dlp-subs",
                        "content": r["stdout"], "final_url": url, "attempts": attempts,
                        "segments": r["segments"], "has_words": False}
            ra = _ytdlp_subs(url, timeout, langs, auto=True)
            attempts.append(_attempt("youtube", "yt-dlp-auto-subs", ra["ok"],
                                     200 if ra["ok"] else 0, ra["stdout"], ra["note"]))
            if ra["ok"]:
                return {"platform": "youtube", "ok": True, "route": "yt-dlp-auto-subs",
                        "content": ra["stdout"], "final_url": url, "attempts": attempts,
                        "segments": ra["segments"], "has_words": False}
        except FileNotFoundError:
            attempts.append(_attempt("youtube", "yt-dlp-subs", False, 0, "", "yt-dlp not installed"))
            return {"platform": "youtube", "ok": False, "route": None, "content": "",
                    "final_url": url, "attempts": attempts}
        except Exception as e:
            attempts.append(_attempt("youtube", "yt-dlp-subs", False, 0, "", f"{type(e).__name__}"))
        # subtitles unavailable → fall through to metadata dump-json (non-terminal EMPTY)
    try:
        p = subprocess.run(
            ["yt-dlp", "--dump-json", "--skip-download", url],
            capture_output=True, text=True,
            encoding="utf-8", errors="strict",  # OPP-16: yt-dlp JSON high-integrity — fail-loud (caught below → route fails)
            env=utf8_env(),
            timeout=max(timeout, 60),
        )
        ok = p.returncode == 0 and p.stdout.strip().startswith("{")
        note = "json" if ok else (p.stderr or "").strip()[:80]
        attempts.append(_attempt("youtube", "yt-dlp", ok, 200 if ok else 0, p.stdout, note))
        if ok:
            return {"platform": "youtube", "ok": True, "route": "yt-dlp",
                    "content": p.stdout, "final_url": url, "attempts": attempts}
    except FileNotFoundError:
        attempts.append(_attempt("youtube", "yt-dlp", False, 0, "", "yt-dlp not installed"))
    except Exception as e:
        attempts.append(_attempt("youtube", "yt-dlp", False, 0, "", f"{type(e).__name__}"))
    return {"platform": "youtube", "ok": False, "route": None, "content": "",
            "final_url": url, "attempts": attempts}


# --- naver --------------------------------------------------------------------
# Clean-room port of the measured no-auth contracts in references/naver.md.
# Live-measured 2026-06-25 (curl_cffi, this machine):
#   finance siseJson  → HTTP 200, body starts "[" (OHLCV JSON array)   tier-0
#   m.blog PostView    → HTTP 200, ~64KB se-main-container post body   tier-0
#   cafe               → login + iframe double wall (naver.md:96-99)   auth-required
# Endpoints are no-auth but unofficial → can go stale; ok=False just falls through
# to the generic grid (R6), so staleness degrades gracefully, never breaks.
_BLOG_PATH_RE = re.compile(r"^/([A-Za-z0-9_-]+)/(\d+)")


def _query_param(url: str, key: str) -> str:
    return (parse_qs(urlsplit(url).query).get(key) or [""])[0]


def _parse_blog_path(url: str) -> tuple[str, str]:
    """blog.naver.com/{ID}/{NO} → (ID, NO). Also accepts ?blogId=&logNo= form."""
    bid = _query_param(url, "blogId")
    lno = _query_param(url, "logNo")
    if bid and lno:
        return bid, lno
    m = _BLOG_PATH_RE.match(urlsplit(url).path)
    return (m.group(1), m.group(2)) if m else ("", "")


def _naver_success(route: str, content: str, final_url: str, attempts: list[dict]) -> dict:
    return {"platform": "naver", "ok": True, "route": route,
            "content": content, "final_url": final_url, "attempts": attempts}


def _naver(url: str, timeout: int) -> dict:
    attempts: list[dict] = []
    h = _host(url)

    # (a) finance siseJson — tier-0 no-auth OHLCV JSON (naver.md:43-55).
    if "finance.naver.com" in h:
        code = _query_param(url, "code") or _query_param(url, "symbol")
        if code:
            api = (f"https://api.finance.naver.com/siseJson.naver?symbol={code}"
                   f"&requestType=1&timeframe=day&count=200")
            try:
                x = _cffi_get(api, impersonate="chrome", timeout=timeout)
                ok = x.status_code == 200 and x.text.lstrip().startswith("[")
                attempts.append(_attempt("naver", "finance-siseJson", ok, x.status_code, x.text,
                                         "ohlcv-json" if ok else f"status={x.status_code}"))
                if ok:
                    return _naver_success("finance-siseJson", x.text, api, attempts)
            except Exception as e:
                attempts.append(_attempt("naver", "finance-siseJson", False, 0, "", f"{type(e).__name__}"))

    # (b) blog → m.blog mobile HTML (iPhone UA contract, naver.md:5-16) then RSS.
    if "blog.naver.com" in h:
        bid, lno = _parse_blog_path(url)
        if bid and lno:
            murl = f"https://m.blog.naver.com/PostView.naver?blogId={bid}&logNo={lno}"
            try:
                x = _cffi_get(murl, impersonate="safari_ios", timeout=timeout,
                              extra_referer="https://m.naver.com/")
                ok = x.status_code == 200 and len(x.text) > 2000
                attempts.append(_attempt("naver", "blog-mobile", ok, x.status_code, x.text,
                                         "post" if ok else f"status={x.status_code}"))
                if ok:
                    return _naver_success("blog-mobile", x.text, murl, attempts)
            except Exception as e:
                attempts.append(_attempt("naver", "blog-mobile", False, 0, "", f"{type(e).__name__}"))
            # RSS fallback (latest ~50 posts, ~300-char bodies; naver.md:18-21).
            rss = f"https://rss.blog.naver.com/{bid}.xml"
            try:
                x = _cffi_get(rss, timeout=timeout)
                ok = x.status_code == 200 and "<rss" in x.text
                attempts.append(_attempt("naver", "blog-rss", ok, x.status_code, x.text,
                                         "feed" if ok else "no-feed-markers"))
                if ok:
                    return _naver_success("blog-rss", x.text, rss, attempts)
            except Exception as e:
                attempts.append(_attempt("naver", "blog-rss", False, 0, "", f"{type(e).__name__}"))

    # (c) cafe → login + iframe double wall (naver.md:96-99). Declare auth-required
    # up front so the grid does not spin uselessly; caller maps to AUTH_REQUIRED.
    if "cafe.naver.com" in h:
        attempts.append(_attempt("naver", "cafe", False, 0, "", "auth-required:login+iframe", auth=True))

    return {"platform": "naver", "ok": False, "route": None, "content": "",
            "final_url": url, "attempts": attempts}


_ROUTERS = {"reddit": _reddit, "x": _x, "youtube": _youtube, "naver": _naver}


# --- public entrypoint -------------------------------------------------------
def route(url: str, *, timeout: int = 15, subs: bool = False,
          langs: tuple[str, ...] = ("ko", "en")) -> Optional[dict]:
    platform = _detect(url)
    if platform is None:
        return None
    if platform == "youtube":
        return _youtube(url, timeout, subs=subs, langs=langs)
    return _ROUTERS[platform](url, timeout)
