#!/usr/bin/env python3
"""manifest.jsonl 체크포인트·비용 원장 헬퍼 (B2 — MANIFEST_CHECKPOINT_CONTRACT v1).

계약: 유료 생성 호출 직전 `check`로 스킵 가능 여부를 결정론 판정한다.
skip 조건 = 산출물 파일 실존 AND 동일 inputs_hash의 status=ok 레코드 존재.
append-only: record는 추가만 한다(수정·삭제 금지 — 감사·retention).
stdlib만 사용. 네트워크 0.
"""
import argparse
import hashlib
import json
import os
import sys
from datetime import datetime, timezone


def inputs_hash(prompt: str, reference_paths=None, model: str = "", params: dict = None) -> str:
    parts = [prompt or ""]
    parts.extend(sorted(reference_paths or []))
    parts.append(model or "")
    for k in sorted((params or {}).keys()):
        parts.append(f"{k}={params[k]}")
    return hashlib.sha256("\n".join(parts).encode("utf-8")).hexdigest()


def _iter_records(manifest_path: str):
    if not os.path.exists(manifest_path):
        return
    with open(manifest_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                yield json.loads(line)
            except json.JSONDecodeError:
                continue  # 손상 줄 관대 파싱 — 계약 명시


def should_skip(manifest_path: str, output_path: str, hash_value: str, base_dir: str = ".") -> bool:
    resolved = output_path if os.path.isabs(output_path) else os.path.join(base_dir, output_path)
    if not os.path.exists(resolved):
        return False
    for rec in _iter_records(manifest_path):
        if (rec.get("output") == output_path and rec.get("inputs_hash") == hash_value
                and rec.get("status") == "ok"):
            return True
    return False


def record(manifest_path: str, skill: str, output: str, hash_value: str,
           model: str = "", params: dict = None, cost_usd: float = 0.0, status: str = "ok") -> None:
    os.makedirs(os.path.dirname(manifest_path) or ".", exist_ok=True)
    rec = {"ts": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
           "skill": skill, "output": output, "inputs_hash": hash_value,
           "model": model, "params": params or {}, "cost_usd": cost_usd, "status": status}
    with open(manifest_path, "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")


def total_cost(manifest_path: str) -> float:
    return round(sum(float(r.get("cost_usd", 0) or 0) for r in _iter_records(manifest_path)
                     if r.get("status") == "ok"), 6)


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest="cmd", required=True)

    c = sub.add_parser("check", help="skip 가능 여부: exit 0=skipped 가능, 1=생성 필요")
    c.add_argument("--manifest", required=True)
    c.add_argument("--output", required=True)
    c.add_argument("--hash", required=True)
    c.add_argument("--base-dir", default=".")

    r = sub.add_parser("record", help="레코드 append")
    r.add_argument("--manifest", required=True)
    r.add_argument("--skill", required=True)
    r.add_argument("--output", required=True)
    r.add_argument("--hash", required=True)
    r.add_argument("--model", default="")
    r.add_argument("--cost-usd", type=float, default=0.0)
    r.add_argument("--status", default="ok", choices=["ok", "failed", "rejected"])

    t = sub.add_parser("total-cost", help="ok 레코드 실비용 합산")
    t.add_argument("--manifest", required=True)

    h = sub.add_parser("hash", help="inputs_hash 산출")
    h.add_argument("--prompt", required=True)
    h.add_argument("--ref", action="append", default=[])
    h.add_argument("--model", default="")
    h.add_argument("--param", action="append", default=[], help="k=v 반복")

    a = p.parse_args(argv)
    if a.cmd == "check":
        if should_skip(a.manifest, a.output, a.hash, a.base_dir):
            print("RESULT=skipped 산출물 실존·동일 해시 ok 레코드 확인 — 유료 호출 생략")
            return 0
        print("RESULT=ok 생성 필요(산출물 부재 또는 입력 변경)")
        return 1
    if a.cmd == "record":
        record(a.manifest, a.skill, a.output, a.hash, a.model, None, a.cost_usd, a.status)
        print(f"RESULT=ok appended output={a.output} status={a.status}")
        return 0
    if a.cmd == "total-cost":
        print(total_cost(a.manifest))
        return 0
    if a.cmd == "hash":
        params = dict(kv.split("=", 1) for kv in a.param)
        print(inputs_hash(a.prompt, a.ref, a.model, params))
        return 0
    return 2


if __name__ == "__main__":
    sys.exit(main())
