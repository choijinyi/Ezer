#!/bin/sh
# tauri build 전처리: UI 번들 최신화 + 데몬/CLI 릴리스 빌드 + externalBin 배치.
# tauri.conf.json beforeBuildCommand가 호출한다 (src-tauri 디렉토리 기준 실행).
# EZERAGENT_TARGET(예: x86_64-apple-darwin) 설정 시 그 타깃으로 크로스 빌드 — CI 매트릭스용.
# 미설정 시 호스트 타깃으로 빌드 — 로컬 빌드 동작 그대로 유지.
set -e
cd "$(dirname "$0")/.."

# Windows(.exe)·python3-부재 환경 대응: python 인터프리터를 OS 무관하게 해석
# (Windows CPython은 python3 없이 python만 제공하는 경우가 있어 폴백).
PY="$(command -v python3 || command -v python || true)"

sh ui/build.sh

if [ -n "$EZERAGENT_TARGET" ]; then
  triple="$EZERAGENT_TARGET"
  cargo build --release --target "$triple" --bin EZERagent --bin EZERagentd
  bindir="target/$triple/release"
else
  triple="$(rustc -vV | sed -n 's/^host: //p')"
  cargo build --release --bin EZERagent --bin EZERagentd
  bindir="target/release"
fi

# Windows 사이드카는 .exe 확장자 필수(tauri externalBin은 EZERagent-<triple>.exe 를 찾음).
case "$triple" in *windows*) exe=".exe" ;; *) exe="" ;; esac
mkdir -p src-tauri/binaries
cp "$bindir/EZERagent$exe" "src-tauri/binaries/EZERagent-$triple$exe"
cp "$bindir/EZERagentd$exe" "src-tauri/binaries/EZERagentd-$triple$exe"

# ── pack.tar.gz를 .app Contents/Resources/ 에 동봉 (옵션4 — 오프라인 자기완결·가시·핫스왑) ──
# 임베드 PACK_ALL(build.rs가 git-추적 EZERagent-pack/ 전 트리에서 생성한 권위 테이블)을 단일 SOT로
# `EZERagent pack-manifest`가 방출 → 정확히 그 파일집합만으로 결정론 tar(정렬·고정 mtime 2020-01-01·owner 0/0)
# 를 만들어 src-tauri/resources/ 에 둔다. release.yml pack-artifacts의 결정론 tar 로직과 동일하되,
# bundle-prep은 macOS(bsdtar — --sort/--mtime 미지원) beforeBuildCommand라 동일 로직을 python3로
# 표현한다(release.yml도 동일성·tar 단계를 python3 heredoc으로 수행). ★raw 트리 글롭이 아니라
# manifest.files(스캔·동일성 게이트 통과 집합)만 박제 — 개인정보·미추적 쓰레기 박제 회피.
# 미서명 로컬 빌드라 minisig는 생략(서명은 CI 무중단 채널 pack-artifacts가 별도 수행).
host_triple="$(rustc -vV | sed -n 's/^host: //p')"
case "$host_triple" in *windows*) host_exe=".exe" ;; *) host_exe="" ;; esac
if [ "$triple" = "$host_triple" ]; then
  manifest_EZERagent="$bindir/EZERagent$exe"      # 호스트 네이티브 사이드카 — 그대로 실행 가능
else
  # 크로스 빌드 레그(예: arm64 러너에서 x86_64): 사이드카는 타깃 ABI라 실행 불가 →
  # 호스트 EZERagent를 별도 빌드해 manifest emit에 쓴다(팩 콘텐츠는 타깃 무관 = 동일 manifest).
  cargo build --release --bin EZERagent
  manifest_EZERagent="target/release/EZERagent$host_exe"
fi

mkdir -p src-tauri/resources
"$manifest_EZERagent" pack-manifest > src-tauri/resources/pack-manifest.json
"$PY" - <<'PY'
import gzip, hashlib, io, json, os, sys, tarfile

# Windows 콘솔 기본 인코딩(cp1252)에서 한국어 print가 UnicodeEncodeError로 죽는 것 방지
# (macOS/Linux는 이미 utf-8이라 no-op). tar 내용(바이트)엔 무관 — 사람용 메시지 인코딩만 교정.
sys.stdout.reconfigure(encoding="utf-8")
sys.stderr.reconfigure(encoding="utf-8")

ROOT = "EZERagent-pack"
man = json.load(open("src-tauri/resources/pack-manifest.json"))
files = man["files"]
if not files:
    print("bundle-prep: manifest.files 비어있음 — 팩 임베드 실패", file=sys.stderr)
    sys.exit(1)

def sha256_file(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()

# 정확히 manifest.files 집합만 결정론 tar로(정렬 + 고정 mtime + owner 0/0 + gzip mtime 0).
# 각 파일은 디스크 sha256 == 임베드 권위 sha256 을 확인(드리프트 시 fail-closed).
with open("src-tauri/resources/pack.tar.gz", "wb") as raw:
    gz = gzip.GzipFile(filename="", mode="wb", fileobj=raw, mtime=0)
    tf = tarfile.open(fileobj=gz, mode="w")
    for rel in sorted(files):
        src = os.path.join(ROOT, rel)
        if not os.path.isfile(src):
            print(f"bundle-prep: manifest 등재 파일이 트리에 없음: {rel}", file=sys.stderr)
            sys.exit(1)
        got = sha256_file(src)
        if got != files[rel]:
            print(f"bundle-prep: 동일성 불일치 {rel}: embed {files[rel]} != tree {got}", file=sys.stderr)
            sys.exit(1)
        data = open(src, "rb").read()
        ti = tarfile.TarInfo(rel)
        ti.size = len(data)
        ti.mtime = 1577836800            # 2020-01-01T00:00:00Z (release.yml --mtime 과 동일 고정값)
        ti.uid = ti.gid = 0
        ti.uname = ti.gname = ""
        ti.mode = 0o644
        tf.addfile(ti, io.BytesIO(data))
    tf.close()
    gz.close()

# tar.gz digest를 manifest에 주입(WP-6 R-SIG-1 — 방출부 tar sha 기입 일관성). 임베드 팩은 미서명이나
# 포맷을 채널 manifest와 통일한다(digest 필드 상존). 검증기는 digest 비어있지 않으면 대조한다.
dh = hashlib.sha256()
with open("src-tauri/resources/pack.tar.gz", "rb") as df:
    for chunk in iter(lambda: df.read(1 << 16), b""):
        dh.update(chunk)
man["digest"] = dh.hexdigest()
with open("src-tauri/resources/pack-manifest.json", "w") as mf:
    json.dump(man, mf, ensure_ascii=False, indent=2)
    mf.write("\n")
print(f"bundle-prep: pack.tar.gz {len(files)}개 파일 결정론 동봉 + digest 주입 → src-tauri/resources/")
PY

echo "bundle-prep ready (ui/dist + binaries + resources/pack.tar.gz for $triple)"
