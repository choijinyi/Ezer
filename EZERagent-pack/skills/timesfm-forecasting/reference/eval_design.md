# hold-out 백테스트 eval 하니스 — 설계 근거 (Wave0.5 게이트)

> 대상 코드: `../scripts/holdout_eval.py` (채점자), `../scripts/test_eval_gate.py` (미설치 단위테스트).
> 본 문서는 하니스가 *왜 이렇게 생겼는가*를 출처 line 으로 고정한다. 환각0: 모든 지표 정의·정책은
> 아래 인용한 실측 line 또는 스킬 원칙에서만 끌어왔다.

---

## 1. 왜 필요한가 — 적대검증 §5 결론의 강제

적대검증(`../../../../_timesfm_parts/30_verification.md` §5, `20_proposals.md` 공통 안전장치 ⓑ)은
**모든 forecast 제안(P1~P14)의 채택 전제로 'hold-out 실측'을 강제**한다:

> "6~10점 초단 시계열에서 zero-shot 우위는 **본 레포 미확인** — 채택 전 hold-out 실측 강제,
> 자가보고 우위 신뢰 금지" (`20_proposals.md:13`)

`14_eval_bench.md` §3·§6 은 TimesFM 자체 테스트 스위트가 **수치 정확도가 아니라 API 계약만** 검증함을
못박는다("test가 API계약만", `14_eval §3`; `test_timesfm.py` 는 `np.random.randn` 난수 입력이라
예측값의 옳고 그름을 전혀 검사하지 않음, `14_eval_bench.md:90`). 따라서:

> "본 레포를 EZERagent/EZERagent 평가 게이트에 통합할 때, **'코드가 통과한다'≠'수치가 검증됐다'**를
> 명문화하고 producer≠evaluator 분리(LOCKED ref 채점) 원칙을 별도로 강제해야 한다."
> (`14_eval_bench.md:94`)

이 하니스가 그 "별도 강제"의 결정론 구현체다. P12(평가 무결성)·P1(병렬 백엔드 잔차게이트)·
P2/P3(R² 또는 backtest 오차 게이트) 가 모두 이 하니스의 exit code 를 채택 조건으로 삼는다.

---

## 2. producer ≠ evaluator — 무엇을 어떻게 분리했나

`eval-driven-self-improvement` 스킬(`../../../../EZERagent-rsi-skills/eval-driven-self-improvement/SKILL.md`)
Rule 1·3·4 를 본 하니스에 매핑:

| 스킬 원칙 (SKILL.md line) | 하니스 구현 |
|---|---|
| **Rule 1**: producer≠evaluator, 채점은 evaluator-owned launcher 가 *locked ref* 에서 추출해 실행(`SKILL.md:40`) | forecaster(producer)는 `{"point":[...]}` 예측만 반환. MASE/sMAPE/coverage 채점은 전적으로 `holdout_eval.py`(evaluator) 가 수행 — forecaster 의 자가보고 지표를 **읽지도 않는다**(`forecaster_timesfm` 는 point/quantile 만 파싱). |
| **Rule 3**: 채점 전 trust-gate, **producer 의 self-reported score 절대 신뢰 금지**, locked launcher 로 재실행(`SKILL.md:44`) | timesfm forecaster 는 subprocess 출력에서 예측값만 취하고 하니스가 동일 채점 코드로 재계산. baseline(seasonal-naive)도 **동일 분할·동일 분모**로 하니스가 직접 채점(`holdout_eval` 내 `forecaster_seasonal_naive` 재호출). |
| **Rule 4**: 측정 실패 = hard fail, silent-exclusion 금지(`SKILL.md:46`) | MASE 분모 0(`seasonal_naive_denominator → None`)·timesfm subprocess 실패 → 평균에서 빼는 게 아니라 `gate_pass=False`(measurement failure hard fail). CLI 는 RuntimeError 시 exit 2. |

**LOCKED-ref 채점 원칙(미구현분 명시):** 본 staging 하니스는 채점 로직의 결정론 토대다. 완전한
Rule 1(SHA256 manifest pin + evaluator-owned launcher 가 locked git ref 에서 추출)은 EZERagent
PACK 배포층(P9·P10·P12 의 preflight/verdict 결속)에서 핀을 건다 — `14_eval §6`·`P12 어떻게`
("`tests/`를 producer≠evaluator LOCKED fixture로"). 본 staging 단계는 **채점기 자체가 producer 와
분리·결정론**임을 보증하는 데까지가 범위이며, 암호학적 핀은 배포 단계 작업이다(외과적 경계).

---

## 3. 지표 정의 — Nixtla utilsforecast 참조 오라클

`14_eval_bench.md` §2 는 TimesFM 벤치가 point 지표를 **자체 구현이 아니라 Nixtla `utilsforecast`**
에서 그대로 import 함을 실측한다(`extended_benchmarks/utils.py:32-33`, `14_eval_bench.md:21`).
본 하니스는 그 정의를 stdlib 로 동형 재구현했다(numpy 의존 회피·결정론·이식성).

### 3.1 MASE (seasonal-naive 분모, 계절성 m)

- 정의: `MASE = mean(|actual−forecast|) / mean(|y_t − y_{t−m}|)`. 분모는 **in-sample(history)
  seasonal-naive 평균 절대오차**. TimesFM 벤치는 `mase_seas = partial(mase, seasonality=self.seasonality)`
  로 계절성을 주입한다(`utils.py:243`, `14_eval_bench.md:23`).
- **m 명시 설정(P12)**: TimesFM 은 일간 `D` 데이터에서 gluonts `get_seasonality()` 가 1 을 반환하는
  것을 **7 로 강제 override** 한다(`utils.py:88-94`):
  ```python
  if self.freq == "D":
      self.seasonality = 7
  ```
  이 override 는 "통계 baseline 에 유리하게 작용"하는 공정성 장치다(`14_eval_bench.md:32`). 본 하니스는
  이 값을 **숨기지 않고** `--seasonality` 인자로 노출하고 도움말에 "일간 D=7, 주간 52, 월간 12 등 명시
  설정"을 적었다(P12: "seasonality override D→7는 명시 설정값 노출", `20_proposals.md:204`). 기본값 1.
- **분모 0 보호**: 완전 상수 시계열 또는 `len(history) ≤ m` 이면 분모 0/측정불가 → `None` 반환. 이를
  평균에서 조용히 빼지 않고 **게이트 hard fail** 로 처리(Rule 4). 단위테스트 ⓓ가 이를 고정.

### 3.2 sMAPE

- 정의: `sMAPE(%) = mean( 200·|a−f| / (|a|+|f|) )`. `utils.py` 경로의 Nixtla sMAPE 와 동형.
  (long-horizon 경로는 `EPS=1e-7` 가드의 자체 구현이라 정의가 미세히 다름 — `14_eval_bench.md:45`;
  본 하니스는 **혼동 방지를 위해 utilsforecast 정의 한 종류만** 채택.)
- 분모 0(a=f=0) 항은 0 기여로 보호.

### 3.3 분위수 coverage (80% PI 실측 포함율)

- 정의: actual 이 `[q10, q90]` 구간에 든 비율. 명목 80% PI 대비 **실측 포함율**을 본다.
- TimesFM 벤치의 확률 지표는 9분위(0.1~0.9) pinball loss 합을 정규화한 scaled_CRPS 다(`utils.py:41-56`,
  `14_eval_bench.md:34`). 본 staging 하니스는 1차로 **coverage(보정 진단에 가장 직접적)** 만 산출한다 —
  v1 분위 헤드가 **미보정**임을 레포가 자백했기 때문이다("they have not been calibrated after
  pretraining ... use them with caution", `extended_benchmarks/README.md:23`, `14_eval_bench.md:43`).
  coverage 가 명목 0.8 에서 크게 벗어나면 그 자체가 미보정 신호다. CRPS 확장은 quantile 산출이 검증된
  뒤의 후속(헤드룸 남김 — eval-evolution, `SKILL.md:52`).
- forecaster 가 분위 밴드를 주지 않으면(dummy·seasonal-naive) coverage=`None` (측정 대상 아님 — silent
  pass 가 아니라 명시적 None).

### 3.4 두 종류 불확실성 비합산

`20_proposals.md` 공통 안전장치 ⓒ·P6: **시계열 분위수 불확실성 ≠ 이벤트 발생확률** — 합산 금지·병기만.
본 하니스는 시계열 분위수(coverage)만 다루며 이벤트확률을 일절 섞지 않는다(스키마에 합산 필드 없음).

---

## 4. deny-by-default 게이트 — `--gate-vs seasonal-naive`

EZERagent 철학 ⑤(deny-by-default)·적대검증 "자가보고 우위 신뢰 금지" 의 결정론 구현:

- `--gate-vs seasonal-naive` 지정 시, forecaster MASE 가 baseline(seasonal-naive) MASE 보다
  **strictly less(엄격히 작음)** 일 때만 `gate_pass=True`. **동률은 우위 입증 실패 → deny**.
  자기 자신(seasonal-naive)을 게이트에 걸면 동률이라 deny 되는 것이 정상(단위테스트
  `test_seasonal_not_strictly_better_denied`).
- 측정 불가(분모 0·데이터 부족) → deny(Rule 4 hard fail).
- exit code 가 사실(EZERagent 철학 ②): `gate_pass=True`→exit 0, gate fail→exit 1, 입력/런타임
  오류→exit 2. LLM 자연어 재추론 없이 exit code 만으로 채택 판정.
- baseline 은 P1/P2/P3 게이트 설계와 정합: P1 "잔차게이트 미통과 시 TimesFM 산출 폐기"(`20_proposals.md:53`),
  P2 "R²가 낮으면 게이트가 자동 탈락 ... 별도 hold-out 비교 지표(backtest 오차) 병행 필요"(`:67`).
  본 하니스의 MASE-vs-baseline 이 그 "backtest 오차" 비교를 제공한다.

---

## 5. 결정론·이식성·미설치 동작

- **순수 stdlib·numpy 의존 없음**: 지표 산술을 list 수학으로 구현. EZERagent 철학 ③(stdlib 우선,
  비표준 의존 끌지 말 것)·"TimesFM 미설치로도 import 단계에서 죽지 말 것" 충족. `holdout_eval.py` 는
  timesfm 을 import 하지 않으며, timesfm forecaster 선택 시에만 `timesfm_forecast.py` 를 subprocess
  로 부른다(없으면 친절한 안내 후 hard fail).
- **결정론**: seed 고정(현 경로 비랜덤이라 기록용), 입력 순서 보존(시계열 순서가 의미 → 재정렬 금지),
  JSON 출력 정렬 고정. 동일 입력 → 동일 출력·동일 exit code (본문대조 게이트 P14 가 의존).
- **pluggable forecaster**: `--forecaster timesfm|dummy|seasonal-naive`. dummy(last-value)·
  seasonal-naive 는 외부 의존 0 으로 게이트 로직 전체를 검증 가능 → `test_eval_gate.py` 가 TimesFM
  없이 23 케이스 통과.

---

## 6. 출력 스키마

```json
{
  "metrics": {"MASE": float|null, "sMAPE": float, "coverage_80pi": float|null,
              "mase_denominator": float|null, "seasonality_m": int, "horizon_k": int},
  "baseline_compare": {"baseline": "seasonal-naive", "baseline_MASE": float|null,
                       "forecaster_MASE": float|null, "forecaster_better": bool|null},
  "gate_pass": bool,
  "gate_reason": "...",
  "forecaster": "dummy|seasonal-naive|timesfm",
  "label": "hold-out 실측·self-reported 아님"
}
```

`label` 은 적대검증 §5 의 '미검증' 라벨 정신을 출력마다 고정 각인한다 — 이 수치는 hold-out 실측이며
벤더 self-report(GIFT-Eval #1, "25% better" 등 `14_eval_bench.md:78`)가 아님을 소비자가 혼동하지
못하게 한다(P12 "self-reported vs 재현가능 분리표기").

---

## 7. 범위 밖(후속 작업 — 명시)

- LOCKED-ref 암호학적 핀(SHA256 manifest + evaluator-owned launcher): EZERagent PACK 배포층
  (P9·P10·P12 preflight/verdict 결속). 본 staging 은 채점기-producer 분리·결정론까지.
- scaled_CRPS 9분위 합산 지표: quantile 산출이 검증된 뒤 eval-evolution 으로 추가(헤드룸 확인 후).
- rolling-origin 다중 윈도우: 현재는 단일 leave-last-k. TimesFM 벤치도 단일 윈도우 한계를 자백
  (`extended_benchmarks/README.md:35`, `14_eval_bench.md:11`)하므로, 다중 윈도우는 후속 헤드룸.
- GIFT-Eval 외부 리더보드 재현: 본 코드 범위 무관(외부 벤치, `14_eval_bench.md:80`).
