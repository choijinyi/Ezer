#!/usr/bin/env python3
"""TimesFM 결정론 forecast CLI.

ezer 철학:
  - 수치 = 이 스크립트의 JSON 출력 (LLM 수치추론 금지). 해석·문장화는 LLM 몫.
  - timesfm는 lazy import — 미설치 시 import 단계에서 죽지 않고 check_timesfm.py 안내 후 exit 3.
  - 출력 불확실성은 '시계열 모델 분위수(quantile)'이며 이벤트 확률이 아니다(uncertainty_kind 명기).
    두 종류 불확실성(시계열 분위수 vs 이벤트확률)을 합산하지 말 것 — caveat에 박아둔다.

입력:
  --input   <csv|json>   CSV(--value-col 지정) 또는 JSON([[...],[...]] 또는 {"name":[...]})
  --value-col <name>     CSV에서 예측할 수치 컬럼 (반복 지정 가능: 다중 series)
  --horizon  <N>         예측 길이
  --output   <json>      결과 JSON 경로 (생략 시 stdout)

P11 ForecastConfig 플래그:
  --normalize-inputs / --no-normalize-inputs           (기본 on)
  --continuous-quantile / --no-continuous-quantile     (기본 on)
  --fix-quantile-crossing / --no-fix-quantile-crossing (기본 on)
  --infer-is-positive / --allow-negative               (기본 infer-is-positive on)
  --flip-invariance                                    (기본 off — True는 decode 2회 추론 2배비용)

출력 JSON 스키마:
  model_version, config, horizon,
  point_forecast            : (N, H)
  quantile_forecast         : (N, H, 10)   index0=mean, 1=q10, ..., 9=q90
  quantile_index_legend     : {0:"mean",1:"q10",...,9:"q90"}
  uncertainty_kind          : "timeseries_model_quantile(NOT event probability)"
  caveat
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import sys

# numpy는 timesfm 의존이지만 입력 파싱 단계에서도 쓰므로 lazy 처리.
# import 단계에서 죽지 않도록 timesfm/torch/numpy 모두 함수 안에서 import.


CHECK_HINT = (
    "먼저 preflight를 실행하세요:\n"
    "    python3 scripts/check_timesfm.py\n"
    "설치:  pip install timesfm[torch]  (또는 uv pip install timesfm[torch])"
)

QUANTILE_LEGEND = {
    0: "mean",
    1: "q10",
    2: "q20",
    3: "q30",
    4: "q40",
    5: "q50_median",
    6: "q60",
    7: "q70",
    8: "q80",
    9: "q90",
}


def detect_device() -> str:
    """정보용 device 감지 (cuda > mps > cpu).

    주의: TimesFM_2p5_200M_torch 는 내부에서 cuda/cpu만 자동 선택한다(MPS 미지원).
    이 값은 출력 config 기록·사용자 안내용일 뿐, 모델 로드 device를 강제하지 않는다.
    """
    try:
        import torch
    except Exception:
        return "unknown(torch 미설치)"
    try:
        if torch.cuda.is_available():
            return "cuda"
        if hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
            return "mps(정보용; torch 모델은 cpu로 로드됨)"
    except Exception:
        pass
    return "cpu"


def load_inputs(
    input_path: str, value_cols: list[str]
) -> tuple[list, list[str]]:
    """입력 파일을 series 리스트로 로드. numpy 없이 순수 stdlib 파싱.

    Returns (list_of_float_lists, series_names)
    """
    ext = os.path.splitext(input_path)[1].lower()

    if ext == ".json":
        with open(input_path) as f:
            data = json.load(f)
        if isinstance(data, dict):
            names = list(data.keys())
            series = [[float(v) for v in data[k]] for k in names]
        elif isinstance(data, list):
            # [[...],[...]] 또는 [number,...]
            if data and isinstance(data[0], (list, tuple)):
                series = [[float(v) for v in s] for s in data]
                names = [f"series_{i}" for i in range(len(series))]
            else:
                series = [[float(v) for v in data]]
                names = ["series_0"]
        else:
            raise ValueError("JSON 입력은 list 또는 dict 여야 합니다.")
        return series, names

    if ext == ".csv":
        with open(input_path, newline="") as f:
            reader = csv.DictReader(f)
            if reader.fieldnames is None:
                raise ValueError("CSV 헤더를 읽지 못했습니다.")
            cols = value_cols
            if not cols:
                # value-col 미지정 시: 전부 수치로 파싱되는 컬럼 자동 선택
                cols = []
                rows = list(reader)
                for name in reader.fieldnames:
                    vals = [r.get(name, "") for r in rows]
                    if vals and all(_is_number(v) for v in vals if v != ""):
                        cols.append(name)
                if not cols:
                    raise ValueError("수치 컬럼을 찾지 못했습니다. --value-col 로 지정하세요.")
                series = [
                    [float(r[name]) for r in rows if r.get(name, "") != ""]
                    for name in cols
                ]
                return series, cols
            missing = [c for c in cols if c not in reader.fieldnames]
            if missing:
                raise ValueError(
                    f"컬럼 없음: {missing}. 사용가능: {list(reader.fieldnames)}"
                )
            rows = list(reader)
            series = [
                [float(r[name]) for r in rows if r.get(name, "") != ""] for name in cols
            ]
            return series, cols

    raise ValueError(f"지원하지 않는 확장자: {ext} (.csv 또는 .json)")


def _is_number(s: str) -> bool:
    try:
        float(s)
        return True
    except (TypeError, ValueError):
        return False


def build_config(args, timesfm):
    """ForecastConfig 구성 (P11 플래그 반영)."""
    return timesfm.ForecastConfig(
        max_context=args.max_context,
        max_horizon=max(args.horizon, 1),
        normalize_inputs=args.normalize_inputs,
        per_core_batch_size=args.batch_size,
        use_continuous_quantile_head=args.continuous_quantile,
        force_flip_invariance=args.flip_invariance,
        infer_is_positive=args.infer_is_positive,
        fix_quantile_crossing=args.fix_quantile_crossing,
    )


def _stdin_json_main() -> int:
    """eval 하니스용 프로그래밍 인터페이스 (holdout_eval.py 가 subprocess 호출).

    stdin JSON {"history":[...], "horizon":N[, "freq_seasonality":m]} →
    stdout {"point":[...H], "quantiles":{"0.1":[...H], "0.9":[...H]}}.
    플래그는 SKILL 권장 기본값 고정(normalize/continuous/fix-crossing on, flip off;
    infer_is_positive 는 입력 부호로 결정). 수치=이 출력, 해석=LLM.
    """
    try:
        req = json.loads(sys.stdin.read())
        history = [float(v) for v in req["history"]]
        horizon = int(req["horizon"])
    except Exception as exc:
        print(f"[BLOCK] stdin-json 파싱 실패: {exc}", file=sys.stderr)
        return 3
    if horizon < 1 or len(history) < 1:
        print("[BLOCK] history/horizon 부족.", file=sys.stderr)
        return 3
    try:
        import numpy as np
        import torch
        import timesfm
    except Exception as exc:
        print(f"[BLOCK] timesfm/torch/numpy import 실패: {exc}", file=sys.stderr)
        print(CHECK_HINT, file=sys.stderr)
        return 3
    torch.set_float32_matmul_precision("high")
    hf_repo = "google/timesfm-2.5-200m-pytorch"
    model = timesfm.TimesFM_2p5_200M_torch.from_pretrained(hf_repo)
    model.compile(
        timesfm.ForecastConfig(
            max_context=max(32, len(history)),
            max_horizon=max(horizon, 1),
            normalize_inputs=True,
            per_core_batch_size=1,
            use_continuous_quantile_head=True,
            force_flip_invariance=False,
            infer_is_positive=all(v > 0 for v in history),
            fix_quantile_crossing=True,
        )
    )
    inputs = [np.asarray(history, dtype=np.float32)]
    point, quantiles = model.forecast(horizon=horizon, inputs=inputs)
    p = [float(x) for x in np.asarray(point)[0].tolist()][:horizon]
    q = np.asarray(quantiles)[0]  # (H, 10): idx 0=mean, 1=q10, ..., 9=q90
    q10 = [float(q[h][1]) for h in range(len(p))]
    q90 = [float(q[h][9]) for h in range(len(p))]
    print(json.dumps({
        "point": p,
        "quantiles": {"0.1": q10, "0.9": q90},
        "uncertainty_kind": "timeseries_model_quantile(NOT event probability)",
    }, ensure_ascii=False))
    return 0


def main() -> None:
    if "--stdin-json" in sys.argv:
        sys.exit(_stdin_json_main())
    parser = argparse.ArgumentParser(
        description="TimesFM 결정론 forecast CLI — 수치=이 출력, 해석=LLM.",
    )
    parser.add_argument("--input", required=True, help="입력 파일 (.csv 또는 .json)")
    parser.add_argument(
        "--value-col",
        action="append",
        default=[],
        dest="value_cols",
        help="CSV 예측 컬럼 (반복 지정으로 다중 series). 생략 시 수치 컬럼 자동 검출.",
    )
    parser.add_argument("--horizon", type=int, required=True, help="예측 길이")
    parser.add_argument("--output", help="결과 JSON 경로 (생략 시 stdout)")
    parser.add_argument(
        "--model",
        default="2.5",
        choices=["2.5"],
        help="모델 버전 (현재 torch 경로 2.5만)",
    )
    parser.add_argument(
        "--max-context",
        type=int,
        default=1024,
        help="max_context (기본 1024). 가장 긴 history에 맞춰 조정.",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=32,
        help="per_core_batch_size (기본 32). 메모리 빡빡하면 축소.",
    )

    # P11 플래그 — 기본값을 SKILL 권장과 일치시킨다
    parser.add_argument(
        "--normalize-inputs",
        dest="normalize_inputs",
        action="store_true",
        default=True,
        help="입력 정규화 (기본 on — scale 불안정 방지)",
    )
    parser.add_argument(
        "--no-normalize-inputs",
        dest="normalize_inputs",
        action="store_false",
    )
    parser.add_argument(
        "--continuous-quantile",
        dest="continuous_quantile",
        action="store_true",
        default=True,
        help="continuous quantile head (기본 on — 분위수 collapse 방지)",
    )
    parser.add_argument(
        "--no-continuous-quantile",
        dest="continuous_quantile",
        action="store_false",
    )
    parser.add_argument(
        "--fix-quantile-crossing",
        dest="fix_quantile_crossing",
        action="store_true",
        default=True,
        help="분위수 단조성 보정 q10<=...<=q90 (기본 on)",
    )
    parser.add_argument(
        "--no-fix-quantile-crossing",
        dest="fix_quantile_crossing",
        action="store_false",
    )
    parser.add_argument(
        "--infer-is-positive",
        dest="infer_is_positive",
        action="store_true",
        default=True,
        help="입력이 모두 >0 이면 출력을 >=0 으로 보장 (기본 on)",
    )
    parser.add_argument(
        "--allow-negative",
        dest="infer_is_positive",
        action="store_false",
        help="음수 가능 series(기온·수익률 등): infer_is_positive 끔",
    )
    parser.add_argument(
        "--flip-invariance",
        dest="flip_invariance",
        action="store_true",
        default=False,
        help="force_flip_invariance (기본 off). True=decode 2회 추론 2배비용 — 음수입력 대칭 필요 시만.",
    )
    args = parser.parse_args()

    # --- lazy import: 미설치 시 안내 후 exit 3 ---
    try:
        import numpy as np  # noqa: F401
        import torch
        import timesfm
    except Exception as exc:  # ImportError 및 전이 의존 실패 포함
        print(f"[BLOCK] timesfm/torch/numpy import 실패: {exc}", file=sys.stderr)
        print(CHECK_HINT, file=sys.stderr)
        sys.exit(3)

    # 입력 로드
    try:
        series, names = load_inputs(args.input, args.value_cols)
    except Exception as exc:
        print(f"[BLOCK] 입력 로드 실패: {exc}", file=sys.stderr)
        sys.exit(3)

    if not series or all(len(s) == 0 for s in series):
        print("[BLOCK] 비어있는 series.", file=sys.stderr)
        sys.exit(3)

    device = detect_device()

    torch.set_float32_matmul_precision("high")

    hf_repo = "google/timesfm-2.5-200m-pytorch"
    model = timesfm.TimesFM_2p5_200M_torch.from_pretrained(hf_repo)
    model.compile(build_config(args, timesfm))

    inputs = [np.asarray(s, dtype=np.float32) for s in series]
    point, quantiles = model.forecast(horizon=args.horizon, inputs=inputs)

    # numpy → list (결정론 직렬화)
    point_list = np.asarray(point).tolist()
    quant_list = np.asarray(quantiles).tolist()

    result = {
        "model_version": args.model,
        "hf_repo": hf_repo,
        "device_detected": device,
        "config": {
            "max_context": args.max_context,
            "max_horizon": max(args.horizon, 1),
            "per_core_batch_size": args.batch_size,
            "normalize_inputs": args.normalize_inputs,
            "use_continuous_quantile_head": args.continuous_quantile,
            "fix_quantile_crossing": args.fix_quantile_crossing,
            "infer_is_positive": args.infer_is_positive,
            "force_flip_invariance": args.flip_invariance,
        },
        "horizon": args.horizon,
        "series_names": names,
        "point_forecast": point_list,  # (N, H)
        "quantile_forecast": quant_list,  # (N, H, 10)
        "quantile_index_legend": {str(k): v for k, v in QUANTILE_LEGEND.items()},
        "uncertainty_kind": "timeseries_model_quantile(NOT event probability)",
        "caveat": (
            "quantile_forecast는 TimesFM의 시계열 분위수(model quantile)일 뿐, "
            "이벤트(사건) 발생확률이 아니다. 시계열 분위수와 이벤트확률은 "
            "서로 다른 종류의 불확실성이므로 합산하지 말고 병기만 하라. "
            "index 0=mean, 1=q10, ..., 9=q90 (index 0은 q0가 아님). "
            "정확도(MAE/coverage 등)는 hold-out 실측 전까지 '미검증'이다."
        ),
    }

    out = json.dumps(result, ensure_ascii=False, indent=2)
    if args.output:
        with open(args.output, "w", encoding="utf-8") as f:
            f.write(out)
        print(f"[OK] {len(names)} series, horizon={args.horizon} -> {args.output}")
    else:
        print(out)


if __name__ == "__main__":
    main()
