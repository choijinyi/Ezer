#!/usr/bin/env python3
"""TimesFM preflight — 결정론 하드웨어/환경 게이트 (stdlib만).

EZERagent 철학:
  - 수치·판정은 이 스크립트의 출력과 exit code가 사실이다 (LLM 재추론 금지).
  - 비표준 의존(psutil 등) 끌지 않는다 — sysctl / /proc / os.statvfs / shutil 만 사용.
  - deny-by-default: ARM(Apple Silicon)에서는 PAX/lingvo(JAX 구경로) 차단, torch 경로만 허용.

이 스크립트는 모델을 로드하지 않는다. 실제 forecast 전에 먼저 돌려
  - exit 0: READY      — 안전하게 로드 가능
  - exit 2: WARN       — tight (작은 batch·CPU 한정 등으로 가능하나 빡빡)
  - exit 3: BLOCK      — 요구사항 미달. 로드 금지.

검사 항목:
  1. RAM       — 총 물리 메모리 (sysctl hw.memsize / /proc/meminfo / os fallback)
  2. Disk      — HF 캐시(또는 홈) 여유공간 (shutil.disk_usage), 모델 가중치 + 여유
  3. Python    — >= 3.10
  4. Arch      — platform.machine(): arm64 면 torch 경로만 허용(PAX/lingvo deny)
  5. Packages  — timesfm / torch 설치 여부 (없으면 설치 안내, BLOCK 아님)
  6. Dataset-fit (선택) — --num-series/--context-length/--horizon 주면 메모리 추정

사용:
    python3 check_timesfm.py
    python3 check_timesfm.py --model 2.5
    python3 check_timesfm.py --json
    python3 check_timesfm.py --num-series 1000 --context-length 1024 --horizon 24
    python3 check_timesfm.py --num-series 5000 --context-length 2048 --estimate-only
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import shutil
import sys

# ---------------------------------------------------------------------------
# 모델 카탈로그 (params / context / disk / RAM tier)
#   근거: README.md:452-456 (버전표), SKILL.md:132-136 (하드웨어표),
#         15_skill_packaging 패키징 파트.
# ---------------------------------------------------------------------------

MODEL_CATALOG = {
    "1.0": {
        "name": "TimesFM 1.0 (200M)",
        "params": "200M",
        "max_context": 2048,
        "min_ram_gb": 4.0,
        "recommended_ram_gb": 8.0,
        "disk_gb": 2.0,
        "hf_repo": "google/timesfm-1.0-200m-pytorch",
    },
    "2.0": {
        "name": "TimesFM 2.0 (500M)",
        "params": "500M",
        "max_context": 2048,
        "min_ram_gb": 8.0,
        "recommended_ram_gb": 16.0,
        "disk_gb": 4.0,
        "hf_repo": "google/timesfm-2.0-500m-pytorch",
    },
    "2.5": {
        "name": "TimesFM 2.5 (200M)",
        "params": "200M",
        "max_context": 16384,
        "min_ram_gb": 2.0,
        "recommended_ram_gb": 4.0,
        "disk_gb": 2.0,  # ~800MB 가중치 + 여유
        "hf_repo": "google/timesfm-2.5-200m-pytorch",
    },
}

# exit code 계약
READY = 0
WARN = 2
BLOCK = 3


# ---------------------------------------------------------------------------
# 결정론 시스템 측정 (stdlib only)
# ---------------------------------------------------------------------------


def get_total_ram_gb() -> float:
    """총 물리 RAM(GB). psutil 금지 — sysctl/proc/os fallback."""
    # macOS: sysctl hw.memsize
    if sys.platform == "darwin":
        try:
            import subprocess

            out = subprocess.run(
                ["sysctl", "-n", "hw.memsize"],
                capture_output=True,
                text=True,
                check=True,
            )
            return int(out.stdout.strip()) / (1024**3)
        except Exception:
            pass
    # Linux: /proc/meminfo
    if sys.platform.startswith("linux"):
        try:
            with open("/proc/meminfo") as f:
                for line in f:
                    if line.startswith("MemTotal"):
                        return int(line.split()[1]) / (1024 * 1024)
        except Exception:
            pass
    # POSIX fallback: os.sysconf
    try:
        pages = os.sysconf("SC_PHYS_PAGES")
        page_size = os.sysconf("SC_PAGE_SIZE")
        return (pages * page_size) / (1024**3)
    except (ValueError, OSError, AttributeError):
        return 0.0


def get_free_disk_gb() -> tuple[float, str]:
    """HF 캐시(또는 홈) 디렉터리 여유공간(GB)과 검사 경로."""
    hf_home = os.environ.get("HF_HOME", os.path.expanduser("~/.cache/huggingface"))
    check_dir = hf_home if os.path.isdir(hf_home) else os.path.expanduser("~")
    try:
        usage = shutil.disk_usage(check_dir)
        return usage.free / (1024**3), check_dir
    except Exception:
        return 0.0, check_dir


# ---------------------------------------------------------------------------
# Dataset-fit 메모리 추정 (공식: SKILL.md:113-114)
#   RAM ≈ 0.8 GB(model) + 0.5 GB(overhead) + (0.2 MB × num_series × ctx / 1000)
#   (입력데이터 항을 공식 그대로 사용. +20% 버퍼.)
# ---------------------------------------------------------------------------


def estimate_dataset_ram_gb(
    num_series: int, context_length: int, horizon: int = 0
) -> dict:
    model_gb = 0.8
    overhead_gb = 0.5
    # 0.2 MB × num_series × ctx / 1000  →  GB 로 환산 (MB/1024)
    input_mb = 0.2 * num_series * context_length / 1000.0
    input_gb = input_mb / 1024.0
    # 출력: num_series × horizon × 10 quantile × 4 bytes
    output_gb = (num_series * horizon * 10 * 4) / (1024**3) if horizon > 0 else 0.0
    total = model_gb + overhead_gb + input_gb + output_gb
    return {
        "model_weights_gb": model_gb,
        "overhead_gb": overhead_gb,
        "input_data_gb": input_gb,
        "output_data_gb": output_gb,
        "total_gb": total,
        "total_with_buffer_gb": total * 1.2,
    }


# ---------------------------------------------------------------------------
# 패키지 설치 확인 (import 시도 — 미설치는 WARN, BLOCK 아님)
# ---------------------------------------------------------------------------


def package_installed(import_name: str) -> tuple[bool, str]:
    try:
        mod = __import__(import_name)
        return True, getattr(mod, "__version__", "unknown")
    except Exception:
        return False, ""


# ---------------------------------------------------------------------------
# 메인 검사
# ---------------------------------------------------------------------------


def run_checks(model_version: str) -> dict:
    profile = MODEL_CATALOG[model_version]
    checks = []
    verdict = READY  # 가장 관대에서 시작, 하향만

    def worsen(level: int) -> None:
        nonlocal verdict
        if level > verdict:
            verdict = level

    # 1. RAM
    total_ram = get_total_ram_gb()
    if total_ram <= 0:
        checks.append(
            {
                "name": "RAM",
                "status": "warn",
                "value": "측정 실패",
                "detail": "총 RAM을 결정론적으로 측정하지 못했습니다(미지원 플랫폼).",
            }
        )
        worsen(WARN)
    elif total_ram < profile["min_ram_gb"]:
        checks.append(
            {
                "name": "RAM",
                "status": "fail",
                "value": f"{total_ram:.1f} GB",
                "detail": (
                    f"{profile['name']} 최소 {profile['min_ram_gb']:.0f} GB 필요. "
                    f"현재 {total_ram:.1f} GB — 로드 시 스왑·행 위험. BLOCK."
                ),
            }
        )
        worsen(BLOCK)
    elif total_ram < profile["recommended_ram_gb"]:
        checks.append(
            {
                "name": "RAM",
                "status": "warn",
                "value": f"{total_ram:.1f} GB",
                "detail": (
                    f"권장 {profile['recommended_ram_gb']:.0f} GB 미만. "
                    f"작은 batch(per_core_batch_size<=4)로만 가능. tight."
                ),
            }
        )
        worsen(WARN)
    else:
        checks.append(
            {
                "name": "RAM",
                "status": "pass",
                "value": f"{total_ram:.1f} GB",
                "detail": f"권장 {profile['recommended_ram_gb']:.0f} GB 충족.",
            }
        )

    # 2. Disk
    free_disk, disk_dir = get_free_disk_gb()
    if free_disk <= 0:
        checks.append(
            {
                "name": "Disk",
                "status": "warn",
                "value": "측정 실패",
                "detail": f"{disk_dir} 여유공간 측정 실패.",
            }
        )
        worsen(WARN)
    elif free_disk < profile["disk_gb"]:
        checks.append(
            {
                "name": "Disk",
                "status": "fail",
                "value": f"{free_disk:.1f} GB free ({disk_dir})",
                "detail": (
                    f"가중치(~800MB) + 여유 위해 {profile['disk_gb']:.0f} GB 필요. "
                    f"HF_HOME을 더 큰 볼륨으로 옮기거나 공간 확보. BLOCK."
                ),
            }
        )
        worsen(BLOCK)
    else:
        checks.append(
            {
                "name": "Disk",
                "status": "pass",
                "value": f"{free_disk:.1f} GB free ({disk_dir})",
                "detail": f"{profile['disk_gb']:.0f} GB 요구 충족.",
            }
        )

    # 3. Python
    pyver = ".".join(str(v) for v in sys.version_info[:3])
    if sys.version_info[:2] < (3, 10):
        checks.append(
            {
                "name": "Python",
                "status": "fail",
                "value": pyver,
                "detail": "TimesFM은 Python >= 3.10 필요. BLOCK.",
            }
        )
        worsen(BLOCK)
    else:
        checks.append(
            {
                "name": "Python",
                "status": "pass",
                "value": pyver,
                "detail": ">= 3.10 충족.",
            }
        )

    # 4. Arch — ARM(Apple Silicon)이면 PAX/lingvo(JAX 구경로) deny, torch만 허용
    machine = platform.machine()
    if machine == "arm64":
        checks.append(
            {
                "name": "Arch",
                "status": "pass",
                "value": machine,
                "detail": (
                    "Apple Silicon(arm64) 감지 — PAX/lingvo(JAX 구경로)는 deny, "
                    "torch 경로(timesfm[torch])만 허용. MPS latency/메모리 미실측이므로 "
                    "wall-clock은 보수적으로 추정(force_flip_invariance=True 시 decode 2회=2배)."
                ),
            }
        )
    else:
        checks.append(
            {
                "name": "Arch",
                "status": "pass",
                "value": machine or "unknown",
                "detail": "torch 경로 사용. (x86_64/기타)",
            }
        )

    # 5. Packages (미설치 = WARN)
    tf_ok, tf_ver = package_installed("timesfm")
    if tf_ok:
        checks.append(
            {
                "name": "timesfm",
                "status": "pass",
                "value": f"{tf_ver}",
                "detail": "timesfm 설치됨.",
            }
        )
    else:
        checks.append(
            {
                "name": "timesfm",
                "status": "warn",
                "value": "미설치",
                "detail": "설치: pip install timesfm[torch] (또는 uv pip install timesfm[torch]).",
            }
        )
        worsen(WARN)

    torch_ok, torch_ver = package_installed("torch")
    if torch_ok:
        checks.append(
            {
                "name": "torch",
                "status": "pass",
                "value": f"{torch_ver}",
                "detail": "torch 설치됨.",
            }
        )
    else:
        checks.append(
            {
                "name": "torch",
                "status": "warn",
                "value": "미설치",
                "detail": "설치: pip install 'torch>=2.0.0' (하드웨어별 index-url 참고).",
            }
        )
        worsen(WARN)

    verdict_label = {READY: "READY", WARN: "WARN", BLOCK: "BLOCK"}[verdict]
    return {
        "model": profile["name"],
        "hf_repo": profile["hf_repo"],
        "max_context": profile["max_context"],
        "verdict": verdict_label,
        "exit_code": verdict,
        "total_ram_gb": round(total_ram, 2),
        "free_disk_gb": round(free_disk, 2),
        "machine": machine,
        "checks": checks,
    }


# ---------------------------------------------------------------------------
# 출력
# ---------------------------------------------------------------------------


def print_catalog() -> None:
    print("=" * 64)
    print("  모델 카탈로그")
    print("=" * 64)
    print(f"  {'ver':<5} {'params':<7} {'max_context':<12} {'min_ram':<9} {'disk'}")
    print(f"  {'-'*5} {'-'*7} {'-'*12} {'-'*9} {'-'*6}")
    for ver, p in MODEL_CATALOG.items():
        print(
            f"  {ver:<5} {p['params']:<7} {p['max_context']:<12} "
            f"{p['min_ram_gb']:.0f} GB{'':<3} ~{p['disk_gb']:.0f} GB"
        )
    print("=" * 64)


def print_report(report: dict) -> None:
    icons = {"pass": "[OK]", "warn": "[WARN]", "fail": "[BLOCK]"}
    print("=" * 64)
    print(f"  TimesFM Preflight — {report['model']}")
    print("=" * 64)
    for c in report["checks"]:
        print(f"  {icons.get(c['status'], '[?]'):<8} {c['name']:<10} {c['value']}")
        print(f"           {c['detail']}")
    print("-" * 64)
    print(f"  VERDICT: {report['verdict']}  (exit {report['exit_code']})")
    print("=" * 64)


def print_dataset_estimate(
    num_series: int, context_length: int, horizon: int, total_ram_gb: float
) -> int:
    """데이터셋 메모리 추정 출력. fit 못 하면 BLOCK 권고 반환."""
    mem = estimate_dataset_ram_gb(num_series, context_length, horizon)
    required = mem["total_with_buffer_gb"]
    print("=" * 64)
    print("  Dataset-fit 메모리 추정")
    print("=" * 64)
    print(f"  {num_series:,} series x {context_length} ctx, horizon={horizon}")
    print(f"  공식: 0.8(model) + 0.5(overhead) + 0.2MB*N*ctx/1000 + output")
    print("-" * 64)
    print(f"  model_weights:   {mem['model_weights_gb']:.2f} GB")
    print(f"  overhead:        {mem['overhead_gb']:.2f} GB")
    print(f"  input_data:      {mem['input_data_gb']:.2f} GB")
    print(f"  output_data:     {mem['output_data_gb']:.2f} GB")
    print(f"  total:           {mem['total_gb']:.2f} GB")
    print(f"  total(+20%):     {required:.2f} GB")
    print("-" * 64)
    print(f"  system RAM:      {total_ram_gb:.1f} GB")
    rec = READY
    if total_ram_gb <= 0:
        print("  [WARN] RAM 미측정 — fit 판정 보류.")
        rec = WARN
    elif required > total_ram_gb:
        print(
            f"  [BLOCK] {required:.1f} GB 필요 > {total_ram_gb:.1f} GB. "
            f"context_length 축소 또는 series 청크 분할 필요."
        )
        rec = BLOCK
    elif required > total_ram_gb * 0.8:
        print(f"  [WARN] {required:.1f} GB 필요 — 메모리 빡빡. batch 축소 권고.")
        rec = WARN
    else:
        print(f"  [OK] fit: {required:.1f} GB 필요, {total_ram_gb:.1f} GB 보유.")
    print("=" * 64)
    return rec


def main() -> None:
    parser = argparse.ArgumentParser(
        description="TimesFM 결정론 preflight (stdlib only). exit: 0 READY / 2 WARN / 3 BLOCK."
    )
    parser.add_argument(
        "--model",
        choices=list(MODEL_CATALOG.keys()),
        default="2.5",
        help="모델 버전 (기본 2.5)",
    )
    parser.add_argument("--json", action="store_true", help="JSON 출력")
    parser.add_argument(
        "--num-series", type=int, metavar="N", help="데이터셋 series 수 (메모리 추정)"
    )
    parser.add_argument(
        "--context-length", type=int, metavar="LEN", help="각 series 길이 (max_context)"
    )
    parser.add_argument(
        "--horizon", type=int, metavar="H", default=24, help="예측 horizon (기본 24)"
    )
    parser.add_argument(
        "--estimate-only",
        action="store_true",
        help="시스템 검사 생략, 데이터셋 메모리 추정만",
    )
    args = parser.parse_args()

    # estimate-only: 시스템 검사 생략
    if args.estimate_only:
        if not (args.num_series and args.context_length):
            print("--estimate-only 에는 --num-series 와 --context-length 가 필요합니다.")
            sys.exit(BLOCK)
        total_ram = get_total_ram_gb()
        rec = print_dataset_estimate(
            args.num_series, args.context_length, args.horizon, total_ram
        )
        sys.exit(rec)

    report = run_checks(args.model)

    # 데이터셋 추정 동반 (있으면 verdict 결합)
    dataset_rec = READY
    if args.num_series and args.context_length:
        dataset_rec = print_dataset_estimate(
            args.num_series, args.context_length, args.horizon, report["total_ram_gb"]
        )

    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print_report(report)
        print_catalog()

    final = max(report["exit_code"], dataset_rec)
    sys.exit(final)


if __name__ == "__main__":
    main()
