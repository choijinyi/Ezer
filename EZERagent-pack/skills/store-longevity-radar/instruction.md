# 장수 점포 레이더 (상가업소 시계열)

## What this skill does

공공데이터포털 **「소상공인시장진흥공단_상가(상권)정보」** 공개 파일(비회원 다운로드 가능)을 이용해 두 가지를 한다.

1. `current` — 최신 분기 스냅샷(전국 17개 시도 zip)에서 **업종코드/상호 키워드로 점포 전수**를 뽑는다. 스냅샷에 존재 = 해당 시점 영업 중으로 취급되는 데이터다.
2. `match` — 사용자가 가진 **과거 스냅샷 CSV**(예: 2019년 국가중점데이터 배포본)와 상호·좌표를 매칭해 **"과거에도 존재했고 지금도 존재하는" 장수 점포**를 추출한다.

기본 업종은 문구·완구(`G21302` 문구/회화용품 소매업, `G21306` 장난감 소매업)이며 옵션으로 어떤 업종이든 지정할 수 있다.

## Honest limitations (반드시 사용자에게 고지)

- 이 데이터에는 **사업자등록번호·개업일이 없다.** 산출되는 것은 "최초 관측 시점 하한"(그 시점에 이미 존재)이지 개업일이 아니다.
- 상호 변경·이전한 점포는 매칭에서 빠진다(과소집계). 동명 상호는 좌표 거리(기본 150m)로 구분하지만 단정하지 않는다.
- 폐업 확정은 사업자등록번호 확보 후 `nts-business-registration`(국세청 상태조회)으로 하고, 인허가 업종이면 `localdata-business-status`로 인허가일자(업력)를 본다.

## Design principles

- 점수·등급 같은 해석 라벨을 만들지 않는다. 스냅샷 존재 사실 + 매칭 방법만 담는다.
- 무인증 공개 파일 서버이므로 프록시를 거치지 않고 사용자 머신에서 직접 받는다.
- 최신 zip은 수백 MB이므로 1일 로컬 캐시(`~/.cache/k-skill/store-longevity-radar/`)한다. 반복 다운로드하지 않는다.

## When to use

- "지금도 영업 중인 오래된 문방구/철물점/레코드점 리스트 뽑아줘"
- "이 업종 전국 점포 전수 데이터 줘 (주소·좌표 포함)"
- "10년 전에도 있었고 아직 있는 가게 찾아줘" (과거 스냅샷 CSV 필요)

## Prerequisites

- 인터넷 연결, `python3` (stdlib만 사용)
- `scripts/store_longevity_radar.py` helper
- `match`를 쓰려면 과거 스냅샷 CSV 파일 (사용자가 보유하거나 별도 확보; 과거분은 공공데이터포털에서 최신 분기만 배포되므로 강의·연구용 미러 등에서 구한다)

## Credential requirements

- 없음. 무인증 공개 파일 다운로드다.

## Inputs

- `--code`: 상권업종소분류코드 (반복 지정, 기본 `G21302` `G21306`). 다른 업종을 `match`할 때 코드체계가 바뀌었다면 현재 코드와 과거 코드를 모두 반복 지정한다.
- `--keyword`: 상호 키워드 (반복 지정, 기본 문구/문방구/완구/장난감 — 업종코드 밖 점포 보완용)
- `--sido`: 시도명 필터 (예: `서울`, `부산`; 생략 시 전국)
- `--zip`: 이미 받아둔 최신 zip 경로 (생략 시 자동 다운로드+캐시)
- `--old-csv`: (`match` 전용) 과거 스냅샷 CSV, 반복 지정. `'|'`/`','` 구분자 자동 감지
- `--max-dist`: (`match` 전용) 동일 상호 허용 좌표 거리(m), 기본 150
- `--out`, `--format`: 출력 파일/형식 (csv 기본, json 가능)

## CLI examples

```bash
# 전국 문구·완구 현재 전수 → CSV
npx -y @nomadamas/k-skill@0 exec store-longevity-radar scripts/store_longevity_radar.py -- \
  current --out 전국_문구완구.csv

# 서울·부산만, 과거 2019 스냅샷과 매칭해 장수 점포 추출
npx -y @nomadamas/k-skill@0 exec store-longevity-radar scripts/store_longevity_radar.py -- \
  match --sido 서울 --sido 부산 --old-csv 상가업소정보_201912_01.csv --out 장수점포.csv

# 다른 업종 예: 철물점 상호 키워드로
npx -y @nomadamas/k-skill@0 exec store-longevity-radar scripts/store_longevity_radar.py -- \
  current --code NONE --keyword 철물 --out 전국_철물점.csv
```

## Workflow

1. `current`부터 실행해 대상 업종 전수를 확보한다. zip 자동 다운로드는 수 분 걸릴 수 있음을 사용자에게 알린다.
2. 과거 스냅샷 CSV가 있으면 `match`로 장수 점포를 추출한다. 기본 문구·완구 코드는 helper가 2022년 이전 `D08A01`/`D04A01`/`D04A02`를 자동 포함한다. 다른 업종은 현재 코드와 과거 코드를 `--code`로 함께 지정한다.
3. 결과 전달 시 위 Honest limitations를 함께 요약한다.
4. 후속 확인이 필요하면 `nts-business-registration`(폐업 확정), `localdata-business-status`(인허가 업력), `kakao-map`(전화번호·현재 등재)을 안내한다.

## Failure modes

- 데이터셋 페이지에서 파일 ID 발견 실패 → `unavailable` + 수동 확인 URL 출력 (분기 개편 시 페이지 구조 변경 가능).
- 공공데이터포털 접속/다운로드 timeout 또는 HTTP 실패 → `unavailable` + 원인 + 수동 확인 URL 출력.
- 다운로드 중단 → `.part` 파일만 남고 캐시로 승격되지 않음. 재실행하면 이어서 새로 받는다.
- `match`에 과거 CSV 미지정 → argparse 에러. 과거분 확보 방법을 사용자에게 안내한다.
- 0건 매칭: 업종코드가 스냅샷 코드체계와 다를 수 있다. `--keyword`만으로 재시도한다.

## Official surfaces

- 데이터셋: <https://www.data.go.kr/data/15083033/fileData.do>
- 다운로드: `https://www.data.go.kr/cmm/cmm/fileDownload.do?atchFileId=<FILE_ID>&fileDetailSn=1` (무인증)
- 관련 스킬: `nts-business-registration`, `localdata-business-status`, `kakao-map`

## Done when

- `current` 결과 건수와 출력 파일 경로가 보고되었다.
- `match` 사용 시 매칭 방법(상가업소번호/상호+좌표)별 건수가 보고되었다.
- 개업일이 아닌 "최초 관측 시점 하한"임이 사용자에게 고지되었다.
