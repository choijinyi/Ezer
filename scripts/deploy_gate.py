#!/usr/bin/env python3
"""deploy_gate.py — EZERagent/EZERagentd 게이트 배포 (정석복구 ④ · 영구 재발방지).

★실행 금지 — 오너 승인 후 master 감독 하에서만 `--execute`로 실행한다.
  scratch/deploy_*_swap.py(미서명 ad-hoc·빌드세대 스큐·Desktop SRC=iCloud 재발원)를 대체한다.

게이트 체인(순서 고정):
  1. 동시성 락(flock) 획득    — 다중 배포 스크립트 병렬 가동에 의한 파일 충돌 차단
  2. SRC=~/dev 강제          — Desktop(iCloud 동기화 경합·' 2' 충돌사본 재발원) 차단
  3. iCloud xattr 부재        — 빌드 dir·산출물에 com.apple.CloudDocs 있으면 중단
  4. 동세대 검증              — EZERagent·EZERagentd mtime 근접 + size 존재(빌드세대 스큐 차단)
  5. ★현재상태 백업(run-id)   — 매 실행 새 backup_dir에: 앱 번들 전체 ditto 복사(서명·xattr·nested 보존)
                                + 각 타깃 lstat/readlink/sha256 inventory + 개별 백업(symlink-aware)
  6. 원자 4경로 교체          — cp + existed 제거 → os.replace(rename·실행중 바이너리 안전)
  7. xattr 제거 → codesign    — ★xattr -c/-cr 를 서명 '前'에(신규 ad-hoc 봉인)
  8. EZERagent --version 스모크     — ★EZERagentd 직접 실행 금지(부팅 부작용)·EZERagentd는 codesign -v 만
  9. 최종 deep verify         — 실패 시 자동 롤백:
       ★staging rollback: 동일 FS(/Applications)의 .rollback-staging 공간에 ditto 복원 후 서명/해시를 사전 검증.
       성공 시에만 기존 타깃을 existed 제거 후 원자 교체.
  10. 데몬 재시작             — ★--execute 성공 시 자동 실행(2026-07-06 오너 지시 — 수동 kill·재가동 폐기):
       drain(저장 신호·best-effort) → system.identify 정확 PID로 종료 및 respawn 폴링. 실패 시 hard fail.
       구 데몬 종료 후 launchd KeepAlive가 새 번들의 EZERagentd를 respawn하고, 새 EZERagentd의 auto-restore
       (phoenix)가 노드를 복원한다. 단독 재시작은 기존대로 --restart.
"""
import hashlib
import json
import os
import shutil
import socket as _socket
import subprocess
import sys
import time
import fcntl

# ★SRC는 반드시 ~/dev(iCloud 밖). $HOME 기반(범용 배포 이식성).
# EZERAGENT_DEPLOY_SRC로 오버라이드 가능 — 동시 빌드가 target/를 휘젓는 환경에서 검증된 격리 스냅샷
# 디렉토리에서 배포하기 위함(여전히 gate_src_path의 ~/dev 검증을 거친다).
SRC = os.path.expanduser(os.environ.get("EZERAGENT_DEPLOY_SRC", "~/dev/EZERagent/target/release"))
APP_BUNDLE = "/Applications/EZERagent.app"
APP_MACOS = "/Applications/EZERagent.app/Contents/MacOS"
BREW = "/opt/homebrew/bin"
BACKUP_BASE = os.path.join(SRC, "deploy_backups")

TARGETS = [
    ("EZERagent", f"{APP_MACOS}/EZERagent"),
    ("EZERagentd", f"{APP_MACOS}/EZERagentd"),
    # EZERagent-app = Tauri GUI(웹뷰). ui/dist를 generate_context!로 컴파일타임 임베드하므로 UI 변경은
    # EZERagent-app 재빌드로만 반영된다(brew엔 없음 — GUI 전용). UI 변경 배포 시 cargo build -p EZERagent-app 선행 필수.
    ("EZERagent-app", f"{APP_MACOS}/EZERagent-app"),
    ("EZERagent", f"{BREW}/EZERagent"),
    ("EZERagentd", f"{BREW}/EZERagentd"),
]

# flock 핸들 전역 보유 (가비지 컬렉션 해제 방지)
LOCK_FILE = None

def die(msg, code=1):
    print(f"❌ {msg}")
    sys.exit(code)

def run(cmd):
    return subprocess.run(cmd, capture_output=True, text=True)

def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()

# ── 게이트 0: 동시성 락 (flock) ─────────────────────────────────────────
def gate_concurrency_lock():
    global LOCK_FILE
    lock_path = "/tmp/EZERagent_deploy_gate.lock"
    try:
        LOCK_FILE = open(lock_path, "w")
        fcntl.flock(LOCK_FILE, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        die("이미 다른 EZERagent 배포 게이트 프로세스가 실행 중입니다 (flock 락 획득 실패).")
    print("  ✓ 동시성 락 획득(flock)")

# ── 게이트 1: SRC=~/dev 강제 ──────────────────────────────────────────
def gate_src_path():
    real = os.path.realpath(SRC)
    if "/Desktop/" in real or "/dev/" not in real:
        die(f"SRC가 ~/dev 밖 — iCloud 재발 위험: {real}")
    print(f"  ✓ SRC ~/dev 내부: {real}")

# ── 게이트 2: iCloud xattr 부재 ───────────────────────────────────────
def gate_no_icloud():
    for p in [SRC] + [os.path.join(SRC, n) for n, _ in TARGETS]:
        if "com.apple.CloudDocs" in run(["xattr", p]).stdout:
            die(f"iCloud 동기화 xattr 감지(빌드 경합 위험): {p}")
    print("  ✓ iCloud xattr 없음(빌드 dir·산출물)")

# ── 게이트 3: 동세대(EZERagent·EZERagentd) ────────────────────────────────────────
def gate_same_generation():
    EZERagent, EZERagentd = os.path.join(SRC, "EZERagent"), os.path.join(SRC, "EZERagentd")
    for f in (EZERagent, EZERagentd):
        if not os.path.isfile(f):
            die(f"빌드 산출물 누락: {f} — 재빌드 필요")
    dt = abs(os.path.getmtime(EZERagent) - os.path.getmtime(EZERagentd))
    if dt > 300:
        die(f"EZERagent·EZERagentd 빌드세대 스큐 {dt:.0f}s > 300s — 동시 빌드 필요(cargo build --bin EZERagent --bin EZERagentd)")
    print(f"  ✓ 동세대 mtimeΔ={dt:.0f}s EZERagent={os.path.getsize(EZERagent):,}B EZERagentd={os.path.getsize(EZERagentd):,}B")

# ── 타깃 inventory(symlink-aware) ────────────────────────────────────
def inventory_target(dst):
    existed = os.path.exists(dst) or os.path.islink(dst)
    d = {
        "dst": dst,
        "in_bundle": dst.startswith(APP_MACOS),
        "is_symlink": os.path.islink(dst),
        "existed": existed
    }
    if d["is_symlink"]:
        d["link_target"] = os.readlink(dst)
        d["size"] = d["sha256"] = None
    elif existed:
        d["link_target"] = None
        d["size"] = os.path.getsize(dst)
        d["sha256"] = sha256(dst)
    else:
        d["link_target"] = d["size"] = d["sha256"] = None
    return d

# ── 게이트 4: 현재상태 백업(run-id) + 번들 ditto + 서명 inventory ──────
def backup_current_state():
    run_id = str(int(time.time()))
    backup_dir = os.path.join(BACKUP_BASE, run_id)
    os.makedirs(backup_dir, exist_ok=False)  # run-id 고유 → stale 롤백 차단
    inv = {"run_id": run_id, "backup_dir": backup_dir, "bundle_sig": {}, "targets": []}

    # ★앱 번들 전체 ditto 복사(원본 서명·xattr·nested 보존 — BLOCKER2 가역성).
    # zip 아님이 디렉토리 복사(ditto --rsrc --extattr --acl)
    bundle_bak = os.path.join(backup_dir, "EZERagent.app")
    r = run(["ditto", "--rsrc", "--extattr", "--acl", APP_BUNDLE, bundle_bak])
    if r.returncode != 0:
        die(f"앱 번들 ditto 백업 실패(가역성 미확보): {r.stderr.strip()}")
    inv["bundle_bak"] = bundle_bak
    inv["bundle_xattrs"] = run(["xattr", APP_BUNDLE]).stdout.splitlines()

    def sig(args):
        r = run(args)
        return r.stdout + r.stderr

    inv["bundle_sig"]["codesign_dvvv"] = sig(["codesign", "-dvvv", APP_BUNDLE])
    inv["bundle_sig"]["entitlements"] = sig(["codesign", "-d", "--entitlements", ":-", APP_BUNDLE])
    inv["bundle_sig"]["deep"] = sig(["codesign", "-dvvv", "--deep", APP_BUNDLE])

    for i, (_, dst) in enumerate(TARGETS):
        meta = inventory_target(dst)
        if not meta["is_symlink"] and meta["existed"]:
            bcopy = os.path.join(backup_dir, f"t{i}_{os.path.basename(dst)}.bak")
            shutil.copy2(dst, bcopy)
            meta["backup_copy"] = bcopy
        inv["targets"].append(meta)

    with open(os.path.join(backup_dir, "inventory.json"), "w") as f:
        json.dump(inv, f, indent=2, ensure_ascii=False)
    print(f"  ✓ 현재상태 백업(run-id={run_id}): 번들 ditto 복사 + symlink-aware inventory → {backup_dir}")
    return inv

# ── 원자 4경로 교체 (existed 제거 포함) ──────────────────────────────────
def atomic_replace():
    for srcname, dst in TARGETS:
        tmp = dst + ".new-deploygate"
        if os.path.lexists(tmp):
            os.remove(tmp)
        shutil.copy2(os.path.join(SRC, srcname), tmp)
        # os.replace는 dst가 regular file이든 symlink이든 원자적으로 대체(rename-over) —
        # symlink일 때 os.remove 先을 두면 부재 창이 생긴다(MEDIUM·codex) → 직접 replace.
        os.replace(tmp, dst)
        print(f"  ✓ 교체 {dst} ({os.path.getsize(dst):,}B)")

# ── 재서명: ★xattr 제거(서명 前) → codesign(신규 ad-hoc) ─────────────
def resign():
    for _, dst in TARGETS:
        run(["xattr", "-c", dst])
        r = run(["codesign", "--force", "--sign", "-", dst])
        if r.returncode != 0:
            raise RuntimeError(f"codesign {dst}: {r.stderr.strip()}")
    run(["xattr", "-cr", APP_BUNDLE])
    r = run(["codesign", "--force", "--deep", "--sign", "-", APP_BUNDLE])
    if r.returncode != 0:
        raise RuntimeError(f"codesign --deep 번들: {r.stderr.strip()}")
    print("  ✓ xattr 제거(서명 前) → codesign --force --deep")

# ── 스모크: EZERagent --version (★EZERagentd 직접실행 금지) ──────────────────────
def smoke():
    for _, dst in TARGETS:
        if os.path.basename(dst) == "EZERagent":
            r = run([dst, "--version"])
            if r.returncode != 0:
                raise RuntimeError(f"EZERagent --version 스모크 실패 {dst}: {r.stderr.strip()}")
            print(f"  ✓ EZERagent --version: {r.stdout.strip()} ({dst})")
        else:
            r = run(["codesign", "-v", dst])
            if r.returncode != 0:
                raise RuntimeError(f"EZERagentd codesign -v 실패 {dst}: {r.stderr.strip()}")
            print(f"  ✓ EZERagentd codesign -v PASS (직접 실행 안 함) {dst}")

# ── 롤백: ★staging rollback (임시 디렉토리에서 사전 검증 후 existed 제거 교체) ──
def rollback(inv):
    print("⏪ 롤백 — Staging Rollback 개시")
    # 백업을 APP_BUNDLE 동일FS(/Applications)의 .rollback-staging에 복원
    staged_app = "/Applications/EZERagent.app.rollback-staging"
    if os.path.exists(staged_app):
        shutil.rmtree(staged_app)

    bundle_bak = inv.get("bundle_bak")
    if bundle_bak and os.path.exists(bundle_bak):
        r = run(["ditto", "--rsrc", "--extattr", "--acl", bundle_bak, staged_app])
        if r.returncode != 0:
            die(f"  [Staging] ditto 복사 실패: {r.stderr.strip()}", 1)
    
    # 스왑 前 검증
    v = run(["codesign", "--verify", "--deep", "--strict", staged_app])
    if v.returncode != 0:
        die(f"  [Staging] 원본 서명 복원 검증 실패: {v.stderr.strip()}", 1)
    
    # 통과 시에만 스왑 — 현재 번들을 먼저 .old로 rename(원자·빠름)해 비우고 staging 입주.
    # rmtree 先(느림)은 크래시 시 번들 소실 창이 크다 → rename-old로 gap 최소화(같은 FS).
    old = "/Applications/EZERagent.app.rollback-old"
    if os.path.exists(old):
        shutil.rmtree(old)
    if os.path.exists(APP_BUNDLE):
        os.rename(APP_BUNDLE, old)
    os.rename(staged_app, APP_BUNDLE)
    if os.path.exists(old):
        shutil.rmtree(old)
    print(f"  ⏪ 앱 번들 ditto 복원 완료(원본 서명 보존·rename-old 스왑)")

    # xattr 대조 출력
    orig_xattrs = inv.get("bundle_xattrs", [])
    curr_xattrs = run(["xattr", APP_BUNDLE]).stdout.splitlines()
    print(f"  ✓ xattr 대조 출력: 원본={orig_xattrs} -> 복원={curr_xattrs}")

    # brew 및 기타 타깃 복원
    for meta in inv["targets"]:
        if meta["in_bundle"]:
            continue
        dst = meta["dst"]
        
        # existed가 false면 제거 상태 유지(원래 부재 복원)
        if not meta["existed"]:
            if os.path.lexists(dst):
                os.remove(dst)
                print(f"  ⏪ 원래 존재하지 않던 파일 제거 유지: {dst}")
            continue

        if os.path.lexists(dst):
            os.remove(dst)  # existed 제거

        if meta["is_symlink"]:
            os.symlink(meta["link_target"], dst)
            print(f"  ⏪ symlink 복원 {dst} → {meta['link_target']}")
        elif meta.get("backup_copy"):
            shutil.copy2(meta["backup_copy"], dst)
            print(f"  ⏪ {dst}")

    # ★최종 검증 — 불일치를 출력만 말고 누적 → die hard fail(복원 실패 기계 감지·HIGH codex).
    errors = []
    v_final = run(["codesign", "--verify", "--deep", "--strict", APP_BUNDLE])
    if v_final.returncode != 0:
        errors.append(f"번들 codesign --verify --deep --strict FAIL: {v_final.stderr.strip()}")
    else:
        print("  롤백 후 codesign --verify --deep --strict: PASS")
    # 번들 xattr 대조(정렬 비교 — 나열 순서 무관).
    curr_bundle_x = sorted(run(["xattr", APP_BUNDLE]).stdout.split())
    if curr_bundle_x != sorted(inv.get("bundle_xattrs", [])):
        errors.append(f"번들 xattr 불일치: now={curr_bundle_x} orig={sorted(inv.get('bundle_xattrs', []))}")
    for meta in inv["targets"]:
        dst = meta["dst"]
        if not os.path.lexists(dst):
            if meta["existed"]:
                errors.append(f"복원 누락(존재해야 함): {dst}")
            continue
        if meta["sha256"] and not os.path.islink(dst) and sha256(dst) != meta["sha256"]:
            errors.append(f"sha256 불일치: {dst}")
    if errors:
        die("★롤백 복원 검증 실패(hard fail):\n  - " + "\n  - ".join(errors))
    print("  ✓ 롤백 복원 검증 PASS(서명·sha256·번들 xattr 일치)")

# ── 데몬 self-pid: system.identify RPC ─────────────────────────────────
def _socket_path():
    return os.environ.get("EZERAGENT_SOCKET") or os.path.expanduser("~/.local/state/EZERagent/EZERagent.sock")

def daemon_identify(timeout=2.0):
    path = _socket_path()
    if not os.path.exists(path):
        return None
    try:
        s = _socket.socket(_socket.AF_UNIX, _socket.SOCK_STREAM)
        s.settimeout(timeout)
        s.connect(path)
        s.sendall(b'{"id":1,"method":"system.identify","params":{}}\n')
        buf = b""
        while b"\n" not in buf:
            chunk = s.recv(65536)
            if not chunk:
                break
            buf += chunk
        s.close()
        return json.loads(buf.decode().splitlines()[0]).get("result", {}).get("daemon_pid")
    except Exception:
        return None

# ── drain: 재시작 前 살아있는 노드에 저장 신호 (best-effort·자체 watchdog 12s) ──
def drain_nodes():
    EZERagent_cli = f"{BREW}/EZERagent"
    if not os.path.isfile(EZERagent_cli):
        EZERagent_cli = f"{APP_MACOS}/EZERagent"
    r = run([EZERagent_cli, "drain"])
    print(f"  ✓ drain(저장 신호·best-effort): rc={r.returncode} {r.stdout.strip()}")

# ── 데몬 재시작 (실패 시 restart hard fail) ─────────────────────────────
def restart_daemon(inv):
    res = {"ts": int(time.time())}
    before = daemon_identify()
    res["before_pid"] = before
    if before:
        run(["kill", "-TERM", str(before)])
    
    down = False
    for _ in range(50):
        if daemon_identify() is None:
            down = True
            break
        time.sleep(0.1)
    res["down_confirmed"] = down
    
    # 데몬 다운 실패 시 hard fail
    if before and not down:
        die(f"기존 데몬(PID {before})이 5초 내에 종료되지 않았습니다. (restart hard fail)", 1)

    ready = False
    after = None
    for _ in range(50):
        after = daemon_identify()
        if after is not None and after != before:
            ready = True
            break
        time.sleep(0.1)
    res["after_pid"] = after
    res["socket_ready"] = ready
    res["note"] = "launchd KeepAlive 적재면 자동 respawn; 아니면 다음 launch-agent/claim-role autostart"
    
    rp = os.path.join(inv["backup_dir"], "restart_result.json")
    with open(rp, "w") as f:
        json.dump(res, f, indent=2, ensure_ascii=False)
    
    # 데몬 기동 실패 시 hard fail
    if not ready:
        die(f"신규 데몬 기동 및 socket-ready 감지 실패 (restart hard fail). 결과={rp}", 1)
        
    print(f"  ✓ restart: down={down} ready={ready} before={before} after={after} → {rp}")

# ── crash recovery: 이전 실행이 staging swap 중간에 죽었으면 잔존물에서 복구 ──
def crash_recovery():
    """rollback 스왑은 rename(APP_BUNDLE→.old) → rename(staging→APP_BUNDLE) 2단계라
    그 사이 크래시 시 APP_BUNDLE이 비어 있을 수 있다(완전 원자 아님·HIGH codex).
    시작부에서 잔존 .rollback-old/.rollback-staging을 결정론으로 정리·복구한다
    (renamex_np ctypes RENAME_SWAP 복잡성 회피)."""
    old = "/Applications/EZERagent.app.rollback-old"
    staging = "/Applications/EZERagent.app.rollback-staging"
    if os.path.exists(old):
        if not os.path.exists(APP_BUNDLE):
            os.rename(old, APP_BUNDLE)  # step1 직후 크래시 → 번들 복귀
            print(f"  ⚠ crash recovery: {old} → {APP_BUNDLE} 복귀(중단된 스왑 회복)")
        else:
            shutil.rmtree(old)  # step2 후·step3 前 크래시 → old 잔존 정리
            print(f"  ⚠ crash recovery: 잔존 {old} 정리")
    if os.path.exists(staging):
        shutil.rmtree(staging)  # 미완 staging 잔존 정리
        print(f"  ⚠ crash recovery: 잔존 {staging} 정리")


def main():
    print("=== deploy_gate.py (정석복구 ④) ===")
    gate_concurrency_lock()
    crash_recovery()  # ★락 직후·게이트 前: 이전 미완 스왑 잔존물 복구

    # --restart 진입경로 처리
    if "--restart" in sys.argv:
        if not os.path.exists(BACKUP_BASE):
            die("백업 디렉토리가 존재하지 않습니다. 먼저 전체 배포를 실행하십시오.")
        dirs = sorted([d for d in os.listdir(BACKUP_BASE) if d.isdigit()])
        if not dirs:
            die("생성된 백업 정보가 없습니다.")
        latest_dir = os.path.join(BACKUP_BASE, dirs[-1])
        with open(os.path.join(latest_dir, "inventory.json")) as f:
            inv = json.load(f)
        restart_daemon(inv)
        print("✅ 데몬 재시작 및 socket-ready 검증 성공.")
        return

    gate_src_path()
    gate_no_icloud()
    gate_same_generation()
    inv = backup_current_state()
    try:
        atomic_replace()
        resign()
        smoke()
        v = run(["codesign", "--verify", "--deep", "--strict", APP_BUNDLE])
        if v.returncode != 0:
            raise RuntimeError(f"최종 deep verify 실패: {v.stderr.strip()}")
        print(f"✅ 게이트 배포 완료 — 백업={inv['backup_dir']}")
    except Exception as e:
        print(f"❌ 배포 실패: {e}")
        rollback(inv)
        sys.exit(1)
    # ★스텝 10(2026-07-06 오너 지시): 배포 성공 확정 후 구 데몬 자동 교체 — drain(저장 신호)
    # → 구 데몬 SIGTERM → 신 데몬 socket-ready 폴링. 파일 교체는 이미 완료·검증됐으므로
    # 재시작 실패는 롤백하지 않고 hard fail로 알린다(restart_daemon 내 die).
    # 구 데몬이 아예 없으면 교체할 대상이 없다 — 건너뛴다(다음 기동이 새 바이너리·기존 성공 배포 불변).
    if daemon_identify() is None:
        print("  ✓ 실행 중인 데몬 없음 — 재시작 생략(다음 기동이 새 EZERagentd)")
        return
    drain_nodes()
    restart_daemon(inv)
    print("✅ 데몬 교체 완료 — 구 데몬 종료·신 데몬 socket-ready 확인")

if __name__ == "__main__":
    # ★안전장치: --execute(배포) 또는 --restart(데몬 재시작) 없이는 실행 거부.
    if "--execute" in sys.argv or "--restart" in sys.argv:
        main()
    else:
        print(__doc__)
        print("배포(오너 승인 후): python3 scripts/deploy_gate.py --execute")
        print("데몬 재시작(오너 승인 후): python3 scripts/deploy_gate.py --restart")
        sys.exit(2)
