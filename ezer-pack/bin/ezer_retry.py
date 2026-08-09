#!/usr/bin/env python3
"""ezer_retry — 재시도 예외 분류 공유 모듈 (clean-room reimplementation).

계약 (contract)
---------------
- 4xx (429 · 408 제외) = 영구 실패 → fast-fail (즉시 재raise, 재시도 금지)
- 5xx · 네트워크 오류 · 타임아웃 = 일시 실패 → 유한 재시도 (지수 백오프)

즉, 클라이언트 잘못(대부분의 4xx)은 재시도해도 같은 결과이므로 즉시 포기하고,
서버 과부하(5xx)·전송 계층 장애(네트워크·타임아웃)만 제한된 횟수 안에서 재시도한다.
재시도는 항상 유한하다 — 무한 루프는 계약 위반이다.

공개 API
--------
- classify(status_or_exc) -> "fatal" | "retryable"
- with_retry(fn=None, *, attempts=3, base=1.0, cap=10.0, sleep=time.sleep)
- CLI: python3 ezer_retry.py classify <int>   (exit 0=retryable / 1=fatal / 2=인자오류)

원본 ViMax retry.py의 코드를 복사하지 않고 규칙(철학)만 클린룸 재구현했다.
"""

import functools
import inspect
import sys
import time

__all__ = ["classify", "with_retry"]


def _classify_status(code):
    """int HTTP 상태 코드 → 'fatal' | 'retryable'."""
    if code in (429, 408):
        return "retryable"
    if 400 <= code <= 499:
        return "fatal"
    if 500 <= code <= 599:
        return "retryable"
    return "fatal"


def _int_status(value):
    """value가 (bool 아닌) int면 그 값을, 아니면 None을 반환."""
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    return None


def classify(status_or_exc):
    """HTTP 상태 코드(int) 또는 예외 객체를 'fatal' | 'retryable'로 분류한다.

    - int: _classify_status 규칙(429·408 retryable, 그 외 4xx fatal, 5xx retryable, 나머지 fatal)
    - 예외 객체:
        * .status_code 또는 .status (int) 속성이 있으면 그 코드로 판정
        * OSError 하위(TimeoutError·ConnectionError·소켓 등 네트워크류) → retryable
        * 그 외(ValueError 등 일반) → fatal
    """
    if isinstance(status_or_exc, BaseException):
        code = _int_status(getattr(status_or_exc, "status_code", None))
        if code is None:
            code = _int_status(getattr(status_or_exc, "status", None))
        if code is not None:
            return _classify_status(code)
        if isinstance(status_or_exc, OSError):
            # TimeoutError·ConnectionError는 OSError 하위 → 여기서 retryable로 잡힌다.
            return "retryable"
        return "fatal"

    code = _int_status(status_or_exc)
    if code is not None:
        return _classify_status(code)

    raise TypeError(
        "classify expects an int HTTP status or an exception instance, "
        f"got {type(status_or_exc).__name__}"
    )


def with_retry(fn=None, *, attempts=3, base=1.0, cap=10.0, sleep=time.sleep):
    """retryable 예외에 한해 지수 백오프로 재시도하는 데코레이터.

    @with_retry            (기본 파라미터) 와
    @with_retry(attempts=5) (커스텀) 두 형태 모두 지원한다.

    - retryable(classify 판정)일 때만 재시도. fatal은 즉시 재raise.
    - 백오프: 시도 n(0-based) 실패 후 min(cap, base * 2**n) 초 만큼 sleep.
    - attempts는 유한 상한(>0) 필수 — 무한 재시도 금지. 마지막 시도 실패 시 재raise.
    - sleep 주입 가능(테스트에서 실제 대기 없이 호출값만 수집).
    """
    if not isinstance(attempts, int) or isinstance(attempts, bool) or attempts < 1:
        raise ValueError("attempts must be a positive int (finite retry bound required)")

    def decorate(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            for n in range(attempts):
                try:
                    return func(*args, **kwargs)
                except Exception as exc:
                    if classify(exc) == "fatal":
                        raise
                    if n == attempts - 1:
                        raise
                    sleep(min(cap, base * (2 ** n)))
            # range(attempts>=1)는 항상 최소 1회 도므로 도달 불가.
            raise RuntimeError("with_retry: unreachable")

        wrapper.attempts = attempts
        wrapper.base = base
        wrapper.cap = cap
        return wrapper

    if fn is not None:
        return decorate(fn)
    return decorate


def _main(argv):
    """CLI: classify <int> → stdout 판정, exit 0=retryable / 1=fatal / 2=인자오류."""
    if len(argv) != 2 or argv[0] != "classify":
        print("usage: ezer_retry.py classify <int-status>", file=sys.stderr)
        return 2
    try:
        code = int(argv[1])
    except ValueError:
        print("error: status must be an integer", file=sys.stderr)
        return 2
    verdict = classify(code)
    print(verdict)
    return 0 if verdict == "retryable" else 1


if __name__ == "__main__":
    sys.exit(_main(sys.argv[1:]))
