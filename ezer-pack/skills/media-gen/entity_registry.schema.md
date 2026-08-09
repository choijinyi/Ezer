# entity_registry 스키마 정의 (schema_version 1)

서사형(narrative) 영상 워크플로우의 **캐릭터·공간 영속 레지스트리** 스키마다.
설계 근거: ViMax 계열의 static/dynamic 특징 분리 + 3뷰(front/side/back) 초상 앵커링을
클린룸(원본 코드 미참조) 재설계한 것. 목적은 여러 씬·샷에 걸쳐 **동일 인물·동일 공간의
정체성(identity)을 결정론적으로 고정**하는 것이다.

이 문서는 `check_entity_registry.py` 검증기와 **동일한 제약 집합**을 명문화한다. 문서와
검증기가 불일치하면 그 자체가 결함이다.

---

## 1. 최상위 구조

```json
{"schema_version":1, "mode":"narrative", "style":"<전역 스타일>",
 "characters":[ ... ],
 "spaces":[ ... ],
 "frame_index":[ ... ]}
```

| 필드 | 타입 | 필수 | 설명 · 제약 |
|------|------|------|------|
| `schema_version` | int | 필수 | **반드시 정수 1**. 다른 값·타입이면 위반. 스키마 진화 시 검증기와 함께 올린다. |
| `mode` | string | 필수 | 레지스트리 용도. 현재 서사형은 `"narrative"`. |
| `style` | string | 필수 | 전역 시각 스타일(예: "따뜻한 톤의 실사풍"). 모든 초상·프레임에 공통 적용되는 상위 지시. |
| `characters` | array | 필수 | 캐릭터 객체 배열(0개 이상). 항목 구조는 §2. |
| `spaces` | array | 필수 | 공간 객체 배열(0개 이상). 항목 구조는 §3. |
| `frame_index` | array | 필수 | 생성된 프레임 색인 배열(0개 이상). 항목 구조는 §4. |

---

## 2. characters[] — 캐릭터 객체

```json
{"id":"char_001","identifier":"지우",
 "static_features":"<불변: 얼굴·체형·나이대>",
 "dynamic_features":"<가변: 의상·소품>",
 "portraits":{
   "front":{"path":"media/portraits/char_001_front.png","status":"pending|generated"},
   "side":{"path":"...","status":"pending","reference":"front"},
   "back":{"path":"...","status":"pending","reference":"front"}},
 "scene_overrides":[{"scene":2,"dynamic_features":"..."}]}
```

| 필드 | 타입 | 필수 | 설명 · 제약 |
|------|------|------|------|
| `id` | string | 필수 | **`char_` 접두 + 영숫자**(정규식 `^char_[A-Za-z0-9]+$`, 예 `char_001`). 캐릭터·공간 통틀어 **유일**해야 한다. |
| `identifier` | string | 필수 | 사람이 읽는 호칭·이름(예: "지우"). 프롬프트 가독용이며 static/dynamic 판정에는 쓰지 않는다. |
| `static_features` | string | 필수 | **불변 물리 특징만**: 성별·나이대·이목구비·얼굴형·헤어·체형·키·흉터 등. **비어 있으면 안 됨**(공백만도 위반). **성격·역할·관계 서술 혼입 금지**(§5). |
| `dynamic_features` | string | 필수 | **가변 특징만**: 의상·소품·헤어스타일 변화 등 씬에 따라 바뀔 수 있는 요소. **비어 있으면 안 됨**. **성격·역할·관계 서술 혼입 금지**(§5). |
| `portraits` | object | 필수 | `front`/`side`/`back` 3뷰 초상. 구조는 §2.1. |
| `scene_overrides` | array | 선택 | 특정 씬에서 `dynamic_features`를 덮어쓰는 규칙. 각 항목 `{"scene":<양의 정수>,"dynamic_features":"..."}`. `scene`은 **양의 정수(≥1)** 여야 한다. static은 override 대상이 아니다(불변이므로). |

### 2.1 portraits 객체

3뷰 초상은 정체성 앵커다. `front`가 기준 뷰이고, `side`·`back`은 **front를 참조**해 생성한다.

| 필드 | 타입 | 필수 | 설명 · 제약 |
|------|------|------|------|
| `front` | object | 필수 | 기준 정면 초상. `{"path":..., "status":...}`. `reference` 없음(자기 자신이 기준). |
| `side` | object | 필수 | 측면 초상. `{"path":..., "status":..., "reference":"front"}`. **`reference`는 문자열 `"front"` 고정**. |
| `back` | object | 필수 | 후면 초상. `side`와 동일 규칙. **`reference`는 `"front"` 고정**. |
| `*.path` | string | 필수 | 미디어 경로(예: `media/portraits/char_001_front.png`). |
| `*.status` | string | 필수 | 생성 상태. `"pending"`(미생성) 또는 `"generated"`(생성됨). |

---

## 3. spaces[] — 공간 객체

```json
{"id":"space_001","slugline":"INT. 서재 - 밤","description":"<세팅만>","anchor_frames":[]}
```

| 필드 | 타입 | 필수 | 설명 · 제약 |
|------|------|------|------|
| `id` | string | 필수 | **`space_` 접두 + 영숫자**(정규식 `^space_[A-Za-z0-9]+$`, 예 `space_001`). 캐릭터·공간 통틀어 **유일**. |
| `slugline` | string | 필수 | 시나리오 슬러그라인(예: `INT. 서재 - 밤`). 실내외·장소·시간대. |
| `description` | string | 필수 | **세팅(공간 구조·가구·분위기)만** 서술. 등장인물 서술은 넣지 않는다. |
| `anchor_frames` | array | 필수 | 이 공간의 기준 프레임 경로 목록(초기엔 빈 배열 허용). |

---

## 4. frame_index[] — 프레임 색인 객체

```json
{"path":"media/images/03.png","characters":["char_001"],"space":"space_001","shot":3}
```

| 필드 | 타입 | 필수 | 설명 · 제약 |
|------|------|------|------|
| `path` | string | 필수 | 생성된 프레임 이미지 경로. |
| `characters` | array[string] | 필수 | 이 프레임에 등장하는 **캐릭터 id 목록**. **모두 §2에 정의된 id여야 함**(참조 무결성). 미정의 id 참조 시 위반. |
| `space` | string | 필수 | 이 프레임의 **공간 id**. **§3에 정의된 id여야 함**(참조 무결성). 미정의 id 참조 시 위반. |
| `shot` | int | 필수 | 샷 번호(양의 정수). |

---

## 5. static/dynamic 성격·역할·관계 혼입 금지 (핵심 불변식)

`static_features`·`dynamic_features`는 **시각적으로 렌더 가능한 물리 특징**만 담는다.
성격·역할·관계 같은 **비시각 서술**이 섞이면 이미지 생성 프롬프트가 오염되어 정체성
드리프트가 생긴다. 따라서 아래 **금칙 토큰**이 static/dynamic에 **부분 문자열로라도** 나타나면
위반으로 판정한다(휴리스틱 누출 검출기).

**금칙 토큰 목록(문서·검증기 공통):**

```
성격, 성실, 착하, 착한, 악당, 악한, 사악, 잔인, 냉정, 다정, 상냥, 소심, 대범,
용감, 비겁, 정의, 배신, 영웅, 리더, 리더십, 카리스마, 우두머리, 내성적, 외향적,
관계, 친구, 우정, 사랑, 연인, 가족, 형제, 자매, 부모, 라이벌, 동료, 원수
```

> 참고: 단일 글자 `적`(enemy)은 `적갈색`·`내성적` 등 물리·기존 토큰과의 부분 문자열 오탐이
> 커서 목록에서 제외한다(정체성 누출의 대표어 `내성적`·`외향적`·`라이벌`·`원수`로 대체 커버).

- 판정 방식: 대상 문자열에 위 토큰 중 하나라도 **substring**으로 포함되면 위반.
- 예) `static_features: "각진 턱, 착한 성격의 리더"` → `착한`·`성격`·`리더` 검출 → 위반.
- 물리 특징만 쓴 예) `"30대 초반 남성, 각진 턱, 175cm 마른 체형, 왼쪽 눈썹 흉터"` → 통과.
- 한계 명시: 이 검출기는 **누출 조기 경보**이지 의미 판정기가 아니다. 물리 묘사에 금칙
  토큰이 우연히 포함되면 오탐(false positive)이 날 수 있으므로, static/dynamic에는
  금칙 토큰과 겹치지 않는 물리 어휘를 쓰는 것을 규약으로 한다.

---

## 6. 제약 요약 (검증기가 전수 검사하는 항목)

1. `schema_version` == 정수 `1`.
2. 모든 `id`는 유일하고 패턴(`char_*` / `space_*`)을 따른다.
3. 각 캐릭터의 `static_features`·`dynamic_features`는 **비어 있지 않다**(공백-only 포함 위반).
4. `static_features`·`dynamic_features`에 **성격·역할·관계 금칙 토큰 혼입 없음**(§5).
5. 각 캐릭터 `portraits.side.reference` 와 `portraits.back.reference` == `"front"`.
6. `frame_index[*].characters` 의 모든 id와 `frame_index[*].space` 는 **정의된 id만 참조**.
7. `scene_overrides[*].scene` 은 **양의 정수(≥1)**.

위반은 `check_entity_registry.py`가 `<필드경로>: <사유>` 한 줄씩 출력한다.
종료 코드: `0`(정상) / `1`(위반 ≥1) / `2`(JSON 파싱 불가·파일 없음).
