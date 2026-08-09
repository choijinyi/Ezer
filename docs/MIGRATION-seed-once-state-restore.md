# seed-once 상태 등급 마이그레이션 — 기존 설치본 복원 절차 (릴리스 노트 편입용)

> 대상 커밋: 9f3187f(seed-once 등급·C62)·4c580df·후속(Ownership 단일 SOT).
> 이 문서는 해당 수정이 포함된 **첫 릴리스의 릴리스 노트에 반드시 편입**한다.

## 무엇이 바뀌나

`memory/`(장기기억 색인·본문)·`round/SESSION_STATE.md`·`round/RECOVERY.md`는 이제
**seed-once 등급**이다: 부재 시에만 시드 설치되고, 존재하면 `init-pack --force`여도
불가침이다. 이전 버전(≤0.12.47)에서는 system 등급이라 init-pack 전량 스윕(부트 ⓪
`preflight --fix`가 결손 1건에도 호출)마다 vendor 골격으로 원복됐다 — 기억 색인·복원
상태가 주기 소실되던 실사고의 근본 원인.

## ⚠ 새 버전이 자동으로 복원해 주지 않는 것

seed-once는 "지금 존재하는 파일"을 보호한다. **구버전에서 이미 골격으로 원복된
설치본은, 새 버전 설치 후 그 골격이 그대로 보호된다.** 진짜 내용은 원복 당시
`<파일>.user`로 병치돼 있고 `.merge-pending.json` 원장에 `healed`로 기록돼 있다.

자동 복원을 하지 않는 이유: 원복 이후 사용자가 새로 쌓은 상태를 `.user` 구본으로
덮어쓰는 역파괴 위험이 있다. 복원은 아래 수동 절차(내용 검토 후 병합)가 안전측이다.

## 복원 절차 (설치 후 1회)

1. 새 버전 설치 후 부트 ⓪(`EZERagent_preflight.py`)의 **C62.pack-heal-ledger** WARN을
   확인한다 — 원복(healed) 파일 목록이 나온다.
2. 상태 파일별로 라이브 본과 `.user` 병치본을 비교한다:
   ```bash
   diff ~/.EZERagent/pack/memory/MEMORY.md      ~/.EZERagent/pack/memory/MEMORY.md.user
   diff ~/.EZERagent/pack/round/SESSION_STATE.md ~/.EZERagent/pack/round/SESSION_STATE.md.user
   diff ~/.EZERagent/pack/round/RECOVERY.md      ~/.EZERagent/pack/round/RECOVERY.md.user
   ```
3. 라이브 본이 아직 vendor 골격(사실상 빈 껍데기)이면 `.user`를 그대로 복원하고,
   원복 후 새로 쌓인 내용이 있으면 두 본을 **병합**한다(둘 다 보존이 원칙 —
   MEMORY.md는 색인이므로 양쪽 포인터의 합집합).
   ```bash
   cp ~/.EZERagent/pack/memory/MEMORY.md.user ~/.EZERagent/pack/memory/MEMORY.md   # 골격일 때만
   ```
4. `EZERagent pack-merge`로 원장 항목을 해소한다(해소 전까지 C62 WARN은 의도적으로 남는다).
5. 복원 후에는 seed-once 보호로 다시 원복되지 않는다 — 재발 확인:
   `python3 ~/.EZERagent/pack/bin/EZERagent_preflight.py --json | grep C62`.

## Windows 사용자 특이사항 (이 계열 최다 발생 플랫폼)

Windows에서 이 사고가 가장 잦았던 기전(실측): 팩 python 도구(EZERagent_memory.py·
EZERagent_memory_inject.py 등)가 상태 파일을 텍스트 모드(`open("w")`, newline 미지정)로
쓰므로 Windows에서 LF→CRLF 자동 변환된다. **내용이 논리적으로 같아도 바이트가
달라져**, 구버전에서는 노드가 색인을 재직렬화만 해도 매 스윕 '수정됨' 판정 →
치유(원복)됐다. 게다가 Windows는 hook 경로 계열 결손으로 부트 ⓪ `--fix`의 전량 스윕
트리거 빈도 자체가 높아 두 요인이 곱해졌다.

seed-once는 내용·해시 비교 **이전**에 보호하므로 CRLF 변형에도 불가침이다 —
Windows의 상태·기억 원복도 이 릴리스로 봉인된다(회귀 핀: pack.rs
`is_seed_once_classification_and_behavior` ①-w). 반면 `bin/*` 등 system 파일이 CRLF로
변형되면 여전히 치유되며 이는 올바른 방향이다 — bash/python 스크립트는 LF가 정답이라
치유가 곧 자가 교정이다.

## bin/ 코드 수정본(.user)에 대하여

`bin/*.py`는 여전히 system 등급이다(배포 무결성 anti-skew — 의도된 설계). 라이브에서
고친 코드가 `.user`로 병치돼 있다면 그 수정은 로컬에서 영속시킬 수 없다 —
**소스 레포(EZERagent-pack)로 승격 제보**하는 것이 유일한 영속 경로다. 이번 릴리스에는
그렇게 소실됐던 승인 수정분(EZERagent_resource_gate 동적 임계·codex 이중계수 제외,
inject-context 부서 분기, RSI 추천 제목)이 이미 흡수돼 있다.
