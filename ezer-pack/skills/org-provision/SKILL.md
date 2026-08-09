---
name: org-provision
description: grill-me 부서 합의 문서(산문 md)를 실제 부서 생성·첫 프로젝트 착수까지 가동. 사용자가 "이 문서대로 부서 만들어/편성해", "합의대로 부서 가동", "부서 자동 생성", "org 매니페스트 적용", "부서 전체 삭제/재편성"을 명령할 때 발동. 종료상태=부서 가동+착수확인+오너 보고(문서에서 멈추지 않음).
---

# org-provision — 합의 문서 → 실제 부서 가동

## 종료 상태 (반드시 여기까지)
"부서 가동 + 첫 프로젝트 착수 확인 + 오너 보고". 매니페스트·문서 작성에서 멈추면 실패다.

## 절차
1. **컴파일** (master·LLM): 합의 md *파일만* 읽어 org-manifest.json 생성. 내 기억이 아니라 md verbatim 추출(요약·창작 금지). source_quote는 합의 md에서 기계적 copy-paste + 그 부서 display/key 변별토큰 포함 문장으로.
2. **검증**: `python3 ~/.ezer/pack/bin/ezer_org.py validate <manifest>`. FAIL이면 오류 항목 보고 후 재컴파일(최대 2회→오너 escalation). 절대 우회 금지.
3. **승인 제시**: 오너께 매니페스트 요약(부서·계정·첫 프로젝트) 1회 제시 → 승인 대기. ★오너 보유결정.
4. **적용(CSO 위임)**: master는 직접 apply 금지(exit3). CSO에 위임: `ezer send --to cso "[org] EZER_ROLE=cso python3 ~/.ezer/pack/bin/ezer_org.py apply <manifest>"` + send-key Return. CSO가 집행.
5. **착수 확인**: `python3 ~/.ezer/pack/bin/ezer_org.py status <manifest>`. incomplete면 hang/redeploy 분기 교정(§design 7.2) — hang은 CSO 개입 요청, redeploy는 apply 재실행 1회.
6. **오너 보고**: "N개 부서 생성·M개 첫 프로젝트 착수 확인" + status 스냅샷. 미착수분 명시.

## 삭제 (재편성)
- 개별: CSO에 `ezer_org.py destroy --dept <key>` / 전체: `--all`.
- 인프라(pack)까지: `--purge`. 작업물까지: `--purge-workdir`(의무 tar 스냅샷 자동 선행·오너 이중승인).
- 삭제 → grill-me 재협의 → 재 apply 로 자유 재편성.

## 불변식
- 부서 mutation은 CSO만(`ezer-dept` exit7 + ezer_org assert). 오너 게이트=③승인·비가역삭제.
- 환각0: validate 통과 못한 매니페스트는 apply 불가.
