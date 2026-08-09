#!/usr/bin/env python3
"""holdout_eval.py — leave-last-k hold-out 백테스트 채점 하니스 (ezer P12/P1 게이트).

producer ≠ evaluator:
  - producer(예측자) = 교체 가능한 forecaster 인터페이스 (--forecaster timesfm|dummy|seasonal-naive)
  - evaluator(채점자) = 이 스크립트. forecaster의 자가보고 지표를 절대 신뢰하지 않고,
    forecaster는 오직 "과거 → 미래 예측값"만 반환하며 채점은 전적으로 이 하니스가 한다.

핵심 정책 (적대검증 §5 상속):
  - 모든 정확도 주장은 hold-out 실측 전까지 '미검증'. 출력 label 에 "hold-out 실측·self-reported 아님" 고정.
  - deny-by-default: --gate-vs seasonal-naive 이면 forecaster 가 seasonal-naive baseline 의 MASE 보다
    나쁘면(또는 동률 이상으로 우위 입증 실패) exit 1. 자가보고 우위 신뢰 금지.
  - 시계열 불확실성(분위수 coverage)과 이벤트 발생확률은 합산하지 않는다(병기만) — 이 하니스는
    시계열 분위수만 다룬다.

지표 (출처: Nixtla utilsforecast / 14_eval_bench.md §2):
  - MASE: seasonal-naive(계절성 m) 분모. m 은 --seasonality 로 명시 설정(P12 "D=7 등 명시설정").
  - sMAPE: 200·|y-ŷ| / (|y|+|ŷ|) 평균 (분모 0 보호).
  - 분위수 coverage: 80% PI(하한 q10·상한 q90) 가 실제값을 포함한 비율 — 명목 0.8 대비 실측 포함율.

결정론: seed 고정·정렬 고정·순수 stdlib 산술(numpy 의존 없음). TimesFM 미설치로도 dummy/seasonal-naive
로 게이트 로직이 완전히 돈다(timesfm forecaster 만 subprocess 로 timesfm_forecast.py 호출).
"""

import argparse
import json
import os
import subprocess
import sys

LABEL = "hold-out 실측·self-reported 아님"

# ---------------------------------------------------------------------------
# 지표 (순수 stdlib — 결정론)
# ---------------------------------------------------------------------------


def seasonal_naive_denominator(history, m):
    """MASE 분모: in-sample seasonal-naive 평균 절대오차 mean(|y_t - y_{t-m}|).

    Nixtla utilsforecast MASE 정의와 동형(14_eval §2: mase_seas = partial(mase, seasonality=m)).
    분모 0(완전 상수·m 만큼의 데이터 부족) 보호: 0 또는 None 이면 None 반환 → 호출부가 게이트 처리.
    """
    if m < 1:
        raise ValueError(f"seasonality m must be >= 1, got {m}")
    if len(history) <= m:
        return None  # seasonal diff 를 만들 데이터 부족
    diffs = [abs(history[t] - history[t - m]) for t in range(m, len(history))]
    if not diffs:
        return None
    denom = sum(diffs) / len(diffs)
    return denom if denom > 0.0 else None


def mase(actual, forecast, denom):
    """MASE = mean(|actual - forecast|) / denom. denom 은 seasonal_naive_denominator 산출값."""
    if denom is None:
        return None  # 분모 0 보호 — 측정 불가는 silent-exclude 가 아니라 None 으로 명시
    if len(actual) != len(forecast) or not actual:
        raise ValueError("actual/forecast length mismatch or empty")
    mae = sum(abs(a - f) for a, f in zip(actual, forecast)) / len(actual)
    return mae / denom


def smape(actual, forecast):
    """sMAPE(%) = mean( 200*|a-f| / (|a|+|f|) ). 분모 0(a=f=0)은 0 기여로 보호."""
    if len(actual) != len(forecast) or not actual:
        raise ValueError("actual/forecast length mismatch or empty")
    total = 0.0
    for a, f in zip(actual, forecast):
        denom = abs(a) + abs(f)
        total += 0.0 if denom == 0.0 else (200.0 * abs(a - f) / denom)
    return total / len(actual)


def coverage(actual, lower, upper):
    """분위수 coverage: actual 이 [lower, upper] 구간에 든 비율(실측 포함율).

    명목 80% PI(q10..q90) 대비 실측 포함율을 본다. lower/upper 없으면 None.
    """
    if lower is None or upper is None:
        return None
    if not (len(actual) == len(lower) == len(upper)) or not actual:
        raise ValueError("actual/lower/upper length mismatch or empty")
    inside = sum(1 for a, lo, hi in zip(actual, lower, upper) if lo <= a <= hi)
    return inside / len(actual)


# ---------------------------------------------------------------------------
# forecaster 플러그 (producer — 교체 가능)
# 각 forecaster: (history:list[float], horizon:int, m:int) -> dict
#   {"point":[...h], "lower":[...h]|None, "upper":[...h]|None}
# ---------------------------------------------------------------------------


def forecaster_dummy(history, horizon, m):
    """dummy = last-value(naive) 예측. 분위 밴드 없음(coverage=None)."""
    last = history[-1]
    return {"point": [last] * horizon, "lower": None, "upper": None}


def forecaster_seasonal_naive(history, horizon, m):
    """seasonal-naive baseline: ŷ_{T+h} = y_{T+h-m}. 기본 baseline(게이트 분모 모델과 동형 가정).

    데이터가 m 보다 짧으면 last-value 로 폴백(결정론).
    """
    point = []
    n = len(history)
    for h in range(1, horizon + 1):
        idx = n - m + ((h - 1) % m) if n >= m else n - 1
        point.append(history[idx])
    return {"point": point, "lower": None, "upper": None}


TIA_SKILL_DIR = os.environ.get(
    "EZER_TIA_DIR",
    os.path.expanduser("~/.claude/skills/foresight-trend-impact-analysis"),
)


def forecaster_classical(history, horizon, m):
    """classical = 우리 기존 TIA 7-curve OLS 엔진(tia_utils.fit_all_curves + extrapolate)을
    그대로 호출하는 incumbent forecaster — 재구현이 아니라 실제 스킬 코드 호출(공정 비교, P2).

    best-R² 곡선 외삽이 NaN/inf(특이점)면 Linear 외삽 → last-value 순으로 폴백(결정론·항상 유한).
    """
    import math as _m

    if TIA_SKILL_DIR not in sys.path:
        sys.path.insert(0, TIA_SKILL_DIR)
    try:
        import tia_utils
    except ImportError as e:
        raise RuntimeError(
            f"classical forecaster 요청됐으나 tia_utils import 실패({e}). "
            f"EZER_TIA_DIR 로 foresight-trend-impact-analysis 경로를 지정하라."
        )
    horizon_years = list(range(len(history), len(history) + horizon))
    fit = tia_utils.fit_all_curves(list(range(len(history))), history)

    def _extrap(curve_result):
        ext = tia_utils.extrapolate(curve_result, horizon_years, historical_v=history)
        table = ext.get("extrapolation", {})
        seq = [table.get(yr, float("nan")) for yr in horizon_years]
        ok = all(not (_m.isnan(x) or _m.isinf(x)) for x in seq)
        return seq if ok else None

    point = _extrap(fit["best_curve"]) if "best_curve" in fit else None
    if point is None:  # 특이점 폴백: Linear 곡선
        for r in fit.get("all_results", []):
            if r.get("curve") == "Linear" and "error" not in r:
                point = _extrap(r)
                break
    if point is None:  # 최종 폴백: last-value(naive)
        point = [history[-1]] * horizon
    return {"point": point, "lower": None, "upper": None}


def forecaster_timesfm(history, horizon, m, script_path):
    """timesfm = timesfm_forecast.py subprocess 호출(producer 외부 분리).

    이 하니스는 예측만 받고 채점은 직접 한다(자가보고 지표 무시). timesfm_forecast.py 가 없거나
    실패하면 RuntimeError 로 hard-fail(measurement failure = silent-exclude 금지, eval Rule 4).
    기대 stdout JSON: {"point":[...h], "quantiles":{"0.1":[...h], "0.9":[...h]}} (있으면 coverage 산출).
    """
    if not os.path.isfile(script_path):
        raise RuntimeError(
            f"timesfm forecaster 요청됐으나 {script_path} 없음. TimesFM 미설치 환경이면 "
            f"--forecaster dummy|seasonal-naive 로 게이트 로직을 검증하라."
        )
    payload = json.dumps({"history": history, "horizon": horizon, "freq_seasonality": m})
    proc = subprocess.run(
        [sys.executable, script_path, "--stdin-json"],
        input=payload,
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        raise RuntimeError(
            f"timesfm_forecast.py exit {proc.returncode}: {proc.stderr.strip()[:500]}"
        )
    try:
        out = json.loads(proc.stdout)
    except json.JSONDecodeError as e:
        raise RuntimeError(f"timesfm_forecast.py 출력 JSON 파싱 실패: {e}")
    point = out["point"]
    q = out.get("quantiles") or {}
    lower = q.get("0.1")
    upper = q.get("0.9")
    return {"point": point, "lower": lower, "upper": upper}


FORECASTERS = {
    "dummy": forecaster_dummy,
    "seasonal-naive": forecaster_seasonal_naive,
    "classical": forecaster_classical,
    "timesfm": forecaster_timesfm,
}


def run_forecaster(name, history, horizon, m, timesfm_script):
    if name == "timesfm":
        return forecaster_timesfm(history, horizon, m, timesfm_script)
    return FORECASTERS[name](history, horizon, m)


# ---------------------------------------------------------------------------
# 입력 로딩 (결정론·정렬 고정)
# ---------------------------------------------------------------------------


def load_series(path):
    """시계열 로드. JSON([float...] 또는 {"y":[...]}) 또는 한 줄당 한 값 텍스트.

    path == '-' 이면 stdin. 결정론을 위해 입력 순서를 그대로 보존(재정렬 안 함 — 시계열 순서가 의미).
    """
    raw = sys.stdin.read() if path == "-" else open(path, "r", encoding="utf-8").read()
    raw = raw.strip()
    if not raw:
        raise ValueError("입력 시계열이 비었다")
    try:
        obj = json.loads(raw)
        series = obj["y"] if isinstance(obj, dict) else obj
    except json.JSONDecodeError:
        series = [line.strip() for line in raw.splitlines() if line.strip()]
    return [float(v) for v in series]


# ---------------------------------------------------------------------------
# 백테스트 본체
# ---------------------------------------------------------------------------


def holdout_eval(series, k, m, forecaster, gate_vs, timesfm_script):
    """leave-last-k 백테스트.

    history = series[:-k], actual = series[-k:], horizon = k.
    forecaster(history) 예측 → MASE/sMAPE/coverage 산출. baseline = seasonal-naive 동일 분할.
    """
    if k < 1:
        raise ValueError(f"k must be >= 1, got {k}")
    if len(series) <= k + m:
        raise ValueError(
            f"시계열 길이 {len(series)} 가 hold-out k={k} + seasonality m={m} 에 부족하다"
        )
    history = series[:-k]
    actual = series[-k:]
    horizon = k

    denom = seasonal_naive_denominator(history, m)  # MASE 분모(in-sample, history 만 사용)

    fc = run_forecaster(forecaster, history, horizon, m, timesfm_script)
    fc_point = fc["point"]
    if len(fc_point) != horizon:
        raise ValueError(
            f"forecaster '{forecaster}' 가 horizon {horizon} 와 다른 길이 {len(fc_point)} 반환"
        )

    metrics = {
        "MASE": mase(actual, fc_point, denom),
        "sMAPE": smape(actual, fc_point),
        "coverage_80pi": coverage(actual, fc.get("lower"), fc.get("upper")),
        "mase_denominator": denom,
        "seasonality_m": m,
        "horizon_k": horizon,
    }

    # baseline 채점 — 동일 분할·동일 분모 → 공정 비교. gate_vs 지정 시 그 모델이 baseline(없으면 seasonal-naive).
    baseline_name = gate_vs if gate_vs else "seasonal-naive"
    base = run_forecaster(baseline_name, history, horizon, m, timesfm_script)
    base_mase = mase(actual, base["point"], denom)

    baseline_compare = {
        "baseline": baseline_name,
        "baseline_MASE": base_mase,
        "forecaster_MASE": metrics["MASE"],
        "forecaster_better": None,
    }

    gate_pass = True
    gate_reason = "no gate (gate_vs 미지정)"
    if gate_vs:
        fm, bm = metrics["MASE"], base_mase
        if fm is None or bm is None:
            # 측정 실패 = hard fail (silent-exclude 금지, eval Rule 4)
            gate_pass = False
            gate_reason = "MASE 측정 불가(분모 0 또는 데이터 부족) — deny-by-default hard fail"
            baseline_compare["forecaster_better"] = None
        else:
            better = fm < bm  # strictly better 만 우위 인정 (동률은 우위 입증 실패 → deny)
            baseline_compare["forecaster_better"] = better
            gate_pass = better
            gate_reason = (
                f"forecaster MASE {fm:.6f} < baseline {bm:.6f}"
                if better
                else f"forecaster MASE {fm:.6f} >= baseline {bm:.6f} (우위 입증 실패 — deny-by-default)"
            )
    else:
        baseline_compare["forecaster_better"] = (
            None
            if (metrics["MASE"] is None or base_mase is None)
            else metrics["MASE"] < base_mase
        )

    return {
        "metrics": metrics,
        "baseline_compare": baseline_compare,
        "gate_pass": gate_pass,
        "gate_reason": gate_reason,
        "forecaster": forecaster,
        "label": LABEL,
    }


def main(argv=None):
    p = argparse.ArgumentParser(
        description=(
            "leave-last-k hold-out 백테스트 채점 하니스 (producer≠evaluator). "
            "정확도 주장은 hold-out 실측 전까지 미검증 — 자가보고 우위 신뢰 금지."
        )
    )
    p.add_argument("--series", required=True, help="시계열 파일(JSON list/{y:[]} 또는 줄당 한 값), '-'=stdin")
    p.add_argument("--k", type=int, required=True, help="hold-out 시점 수 = horizon")
    p.add_argument(
        "--seasonality",
        type=int,
        default=1,
        help="MASE seasonal-naive 분모 계절성 m. 명시 설정(P12): 일간 D=7, 주간 52, 월간 12 등.",
    )
    p.add_argument(
        "--forecaster",
        choices=sorted(FORECASTERS.keys()),
        default="seasonal-naive",
        help="예측자 플러그. timesfm=timesfm_forecast.py subprocess, dummy=last-value, seasonal-naive=baseline.",
    )
    p.add_argument(
        "--gate-vs",
        choices=["seasonal-naive", "classical"],
        default=None,
        help="지정 시 forecaster MASE 가 해당 baseline(seasonal-naive=하한·classical=우리 7-curve 엔진) 보다 나쁘면 exit 1 (deny-by-default).",
    )
    p.add_argument(
        "--timesfm-script",
        default=os.path.join(os.path.dirname(os.path.abspath(__file__)), "timesfm_forecast.py"),
        help="timesfm forecaster 가 호출할 timesfm_forecast.py 경로.",
    )
    p.add_argument("--seed", type=int, default=0, help="결정론 seed(현 경로는 비랜덤이라 기록용).")
    args = p.parse_args(argv)

    import random

    random.seed(args.seed)  # 결정론 고정(향후 랜덤 분할 확장 대비)

    try:
        series = load_series(args.series)
        result = holdout_eval(
            series, args.k, args.seasonality, args.forecaster, args.gate_vs, args.timesfm_script
        )
    except (ValueError, RuntimeError) as e:
        print(json.dumps({"error": str(e), "gate_pass": False, "label": LABEL}, ensure_ascii=False))
        return 2

    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["gate_pass"] else 1


if __name__ == "__main__":
    sys.exit(main())
