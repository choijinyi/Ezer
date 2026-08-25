# 5회차 · AI 기반 영상 제작과 기사 생성 자동화

| 회차 | 시간 | 구성 | 선수 지식 |
|---|---|---|---|
| 5 / 7 | 12H | 핵심 개념 · 자동화 파이프라인 · 실습 3종 | 1~4회차(LLM·프롬프트·구조화 출력 / STT / 영상·멀티모달 / 임베딩·검색) |

## 학습 목표

이 회차를 마치면 다음을 할 수 있다.

- 디퓨전(diffusion)의 원리를 자기 말로 설명하고, 이미지·영상 생성 모델이 뉴스 제작의 어디(썸네일·B롤)에 쓰이는지 구분할 수 있다.
- 생성형 이미지·영상의 한계(사실 왜곡·일관성·딥페이크)와 그에 따른 금지선을 설명할 수 있다.
- 기사·영상에서 출발해 대본→TTS 나레이션→자막→합성으로 이어지는 숏폼 자동화 파이프라인의 단계 구조를 그릴 수 있다.
- 그 파이프라인의 각 단계에 1~4회차 기술(STT·영상 분석·검색·LLM)이 어디 들어가는지 짚을 수 있다.
- LLM 구조화 출력으로 씬별 대본(JSON)을 만들고, TTS API로 음성을 합성한 뒤 세그먼트 길이에 맞춰 SRT 자막을 동기화할 수 있다.
- 기사 1건을 입력하면 대본·음성·자막·썸네일 프롬프트까지 한 스크립트로 묶는 미니 파이프라인을 직접 돌릴 수 있다.

---

## 1. AI 이미지·영상 생성 심화

1권에서 "디퓨전 모델은 노이즈를 단계적으로 걷어내며 이미지를 만든다"고 배웠다. 이번에는 그 한 문장을 제작 실무로 끌어내려, *어디에 쓰고 어디에 쓰면 안 되는지*를 가른다.

### 1.1 디퓨전 원리 — 노이즈에서 그림으로

**[개념]** 디퓨전 모델은 학습 때 "깨끗한 이미지에 노이즈를 조금씩 더해 완전한 잡음으로 만드는 과정"을 거꾸로 푸는 법을 배운다. 생성할 때는 무작위 노이즈에서 출발해, 매 단계 "노이즈를 조금 덜어낸 더 그럴듯한 그림"을 추정하며 수십 단계를 반복한다. 텍스트 프롬프트는 이 걷어내기 방향을 잡아 주는 *나침반*이다 — "방송 스튜디오, 차분한 조명"이라는 말이 매 단계의 추정을 그쪽으로 끌어당긴다.

이 원리에서 실무 함의 두 가지가 나온다.

- **프롬프트가 분위기·구도를 좌우한다.** 단어 선택이 곧 결과의 방향이다(1.3).
- **같은 프롬프트라도 시작 노이즈가 다르면 결과가 달라진다.** 그래서 "똑같은 그림 두 장"을 보장하기 어렵다 — 이것이 일관성 문제(1.3)의 뿌리다.

### 1.2 이미지·영상 생성 모델과 용도

**[개념]** 뉴스 제작에서 생성형 비주얼은 *처음부터 끝까지 다 만드는 도구*가 아니라 **빈칸을 메우는 도구**다. 실사 취재 화면을 대체하는 것이 아니라, 실사로 채우기 어려운 자리에 보조 소재를 공급한다.

| 용도 | 무엇을 만드나 | 적합한 모델 유형 | 뉴스 제작에서의 위치 |
|---|---|---|---|
| 썸네일·카드 | 정지 이미지 1장 | 이미지 생성(Imagen·DALL·E 등) | 유튜브 썸네일, SNS 카드 |
| B롤·인서트 | 짧은 보조 영상 클립 | 영상 생성(Veo·Runway 등) | 개념 설명용 배경 영상, 자료 부족 구간 |
| 일러스트·도식 | 비실사 그림·아이콘 | 이미지 생성 | 통계·개념 시각화 |

**[주의]** 생성 영상·이미지는 **실제로 일어난 사건의 화면이 아니다.** 자료 화면(실사)과 생성 소재는 화면상·고지상 명확히 구분해야 한다. 생성 B롤을 사건 현장처럼 쓰면 시청자를 오인시키는 것이다.

### 1.3 일관성과 프롬프트 기법

**[개념]** 숏폼 한 편에는 여러 씬이 들어가는데, 씬마다 그림체·인물·색감이 튀면 완성도가 떨어진다. 이를 줄이는 실무 기법은 다음과 같다.

- **스타일 고정 문구** — "플랫 일러스트, 파스텔 톤, CBS 블루 포인트"처럼 *스타일 서술을 모든 씬 프롬프트에 공통으로* 붙인다.
- **시드(seed) 고정** — 모델이 지원하면 같은 시드를 줘서 시작 노이즈를 맞춘다. 변형을 줄이는 가장 직접적인 손잡이다.
- **참조 이미지** — 앞 씬 결과를 참조로 넣어 톤을 잇는다(모델이 지원할 때).
- **부정 프롬프트(negative prompt)** — "글자 왜곡, 손가락 6개, 워터마크" 등 피할 것을 명시한다.

**[팁]** 일관성을 코드로 다루기 쉽게 하려면, 스타일 문구를 상수로 빼고 씬별 묘사만 갈아 끼운다. 실습 3에서 썸네일 프롬프트를 만들 때 이 패턴을 쓴다.

### 1.4 한계와 금지선 — 사실 왜곡·딥페이크

**[주의]** 생성형 비주얼의 한계는 *기술 결함*이 아니라 *뉴스 윤리의 경계*다.

- **사실 왜곡** — 모델은 "그럴듯한" 그림을 만들 뿐, 사실을 보장하지 않는다. 존재하지 않는 장면·표정·배경을 자연스럽게 지어낸다.
- **딥페이크·실존 인물** — 실존 인물의 얼굴·음성을 본인 동의 없이 생성·합성하는 것은 **절대 금지선**이다. 정치인·취재원·일반인 모두 해당한다.
- **글자·로고** — 생성 이미지 속 한글·기관 로고는 깨지거나 가짜로 만들어지기 쉽다. 자막·로고는 생성물에 맡기지 말고 편집 단계에서 정식 소스로 올린다.

발행 전 **사람 검수 게이트**(머리말의 4원칙)는 생성 비주얼에도 그대로 적용된다.

---

## 2. 숏폼 자동화 파이프라인 설계

### 2.1 단계 구조: 원천에서 완성 영상까지

**[개념]** 숏폼 자동화는 한 번에 "영상을 만들어 줘"가 아니라, **작게 쪼갠 단계를 줄로 잇는 것**이다(1회차 2.4 프롬프트 체이닝의 확장). 각 단계 출력이 다음 단계 입력이 되며, 단계가 분리돼 있어야 검수·교체·디버깅이 쉽다.

```
[원천]            [대본]           [나레이션]        [자막]            [합성]
기사 / 영상   →  씬별 대본    →   TTS 음성      →  SRT 자막      →  영상 합성·발행
(텍스트·녹취)    (JSON 구조화)     (음성 파일)       (타임코드)        (B롤·썸네일 결합)
     │               │                │                │                  │
   1·2·3회차        1회차            본 회차          본 회차           본 회차
   (STT·영상)      (LLM·구조화)      (TTS)         (길이→타임코드)    (이미지 생성)
```

### 2.2 각 단계에 앞 회차 기술이 어디 들어가나

**[개념]** 5회차의 핵심은 *새 기술을 배우는 것*이 아니라, 1~4회차 모듈을 **생성·자동화로 연결**하는 것이다. 아래 표가 이 회차의 지도다.

| 단계 | 하는 일 | 쓰는 앞 회차 기술 | 본 회차에서 새로 더하는 것 |
|---|---|---|---|
| 원천 수집 | 기사 본문 / 영상 녹취를 텍스트로 확보 | 2회차 STT(음성→텍스트), 3회차 영상 분석 | — |
| 소재 선별 | 여러 원천에서 쓸 만한 소재 고르기 | 4회차 임베딩·검색·중복 탐지 | — |
| 대본 생성 | 씬별 나레이션·자막·키워드 작성 | 1회차 LLM·구조화 출력(JSON) | 영상용 씬 분할 설계 |
| 나레이션 | 대본을 음성으로 합성 | — | **TTS API**(3.1) |
| 자막 | 음성 길이에 맞춰 타임코드 부여 | — | **SRT 동기화**(3.2) |
| 합성·발행 | B롤·썸네일·자막 결합, 사람 검수 후 발행 | 1회차 이미지 생성 개념 | 썸네일 프롬프트 자동화 |

**[팁]** 처음부터 완벽한 끝단(영상 합성)을 노리지 말고, *대본→음성→자막*까지를 먼저 안정화한다. 영상 합성·발행은 도구 의존도가 높아 마지막에 붙이는 편이 안전하다. 6회차 PBL에서 이 줄을 실제 과제에 맞게 늘리고 줄인다.

### 2.3 사람 검수 게이트는 어디에 두나

**[주의]** 자동화 줄의 *발행 직전*에 반드시 사람 검수 게이트를 둔다. 특히 ① 대본의 사실관계(LLM 환각), ② 생성 비주얼의 오인 소지, ③ TTS 발음 오류(고유명사·숫자)를 확인한다. 자동화는 초안을 빠르게 만들 뿐, **발행 책임은 사람에게 있다.**

---

## 3. TTS와 자막 동기화

### 3.1 TTS API의 개념

**[개념]** TTS(Text-to-Speech)는 텍스트를 음성 파일로 바꾸는 기술이다. API 사용 흐름은 LLM과 닮았다 — *클라이언트 생성 → 모델·목소리 지정 → 텍스트 전달 → 오디오(바이트) 수신*. 핵심 선택지는 다음과 같다.

- **목소리(voice)** — 성별·톤·언어. 채널 정체성에 맞춰 고정하면 일관성이 산다.
- **속도(speed)** — 숏폼은 약간 빠른 편이 흡인력 있다. 단, 고유명사·숫자가 뭉개지지 않는 선에서.
- **출력 형식** — mp3·wav 등. 후속 편집 도구가 받는 형식으로 맞춘다.

**[주의]** 실존 인물의 목소리를 복제(voice cloning)해 그 사람이 말한 것처럼 쓰는 것은 금지선이다. TTS는 *채널의 내레이션 목소리*로만 쓰고, 취재원·인터뷰 음성은 실제 녹취를 사용한다.

### 3.2 음성 길이에 맞춘 자막 타임코드 정렬

**[개념]** 자막은 "언제부터 언제까지 어떤 글자를 띄울지"의 묶음이다. 대본을 씬(세그먼트)으로 나눠 각 세그먼트를 TTS로 합성하면, **각 음성 파일의 실제 재생 길이**를 잴 수 있다. 이 길이를 차례로 누적하면 세그먼트별 시작·끝 시각이 나온다.

```
세그먼트1 음성 2.4초  → 00:00:00,000 → 00:00:02,400
세그먼트2 음성 3.1초  → 00:00:02,400 → 00:00:05,500
세그먼트3 음성 2.0초  → 00:00:05,500 → 00:00:07,500
                          (앞 길이를 누적해 다음 시작점으로)
```

핵심은 **"음성을 먼저 만들고, 그 실제 길이로 자막 시각을 역산"**한다는 점이다. 글자 수로 길이를 추정하지 않는다 — TTS 속도·문장 부호에 따라 실제 길이가 다르기 때문이다.

### 3.3 SRT 생성 원리

**[개념]** SRT는 자막의 사실상 표준 텍스트 포맷이다. 구조가 단순해 코드로 생성하기 쉽다.

```
1
00:00:00,000 --> 00:00:02,400
첫 번째 자막 줄

2
00:00:02,400 --> 00:00:05,500
두 번째 자막 줄
```

각 블록은 *번호 → 시작,끝 시각(쉼표로 밀리초 구분) → 자막 텍스트 → 빈 줄* 순서다. 직접 문자열을 조립할 수도 있지만, 시각 포맷·이스케이프 실수를 줄이려면 `srt` 라이브러리로 객체를 만들어 직렬화하는 편이 안전하다(실습 2).

---

## 4. 실습

> 공통 준비: 파이썬 3.10+, `pip install google-genai srt`. 환경 변수 `GEMINI_API_KEY` 설정. (사내 정책상 외부 API가 제한되면 강사가 안내하는 사내 게이트웨이/대체 키를 사용한다.) 실습 코드는 1~4회차와 마찬가지로 *복붙용 정답이 아니라 내 데이터에 맞게 고쳐 쓰는 출발점*이다.

### [실습 1] 기사→숏폼 대본 자동 생성 (60분)

기사 본문을 넣어, **프로그램이 바로 쓸 수 있는 씬별 JSON 대본**을 받는다. 각 씬은 나레이션(음성용)·자막(화면용)·키워드(B롤/썸네일용)로 나뉜다. 1회차의 구조화 출력을 영상 제작에 맞춰 확장한 것이다.

```python
import os, json
from google import genai            # pip install google-genai
from google.genai import types

client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])  # 키는 환경 변수로

# 씬 배열을 강제하는 스키마 — narration(음성)과 caption(자막)을 분리한다.
scene_schema = {
    "type": "object",
    "properties": {
        "title": {"type": "string", "description": "숏폼 제목(40자 이내)"},
        "scenes": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "narration": {"type": "string", "description": "TTS로 읽을 1~2문장"},
                    "caption":   {"type": "string", "description": "화면 자막(짧게)"},
                    "keyword":   {"type": "string", "description": "B롤/썸네일용 핵심어"},
                },
                "required": ["narration", "caption", "keyword"],
            },
        },
    },
    "required": ["title", "scenes"],
}

article = "여기에 기사 본문을 붙여넣는다 ..."
prompt = (
    "다음 기사를 30초 내외 숏폼 대본으로 바꿔라. 4~6개 씬으로 나누고, "
    "각 씬의 narration은 방송 말투로 사실만, 과장 없이. caption은 narration의 핵심을 25자 이내로 요약. "
    "keyword는 그 씬에 어울리는 B롤/썸네일 검색어.\n\n" + article
)

resp = client.models.generate_content(
    model="gemini-2.5-flash",
    contents=prompt,
    config=types.GenerateContentConfig(
        temperature=0.3,                       # 사실 기반: 낮게
        response_mime_type="application/json",
        response_schema=scene_schema,
    ),
)

script = json.loads(resp.text)                 # 후속 단계가 바로 쓰는 딕셔너리
print(script["title"])
for i, sc in enumerate(script["scenes"], 1):
    print(f"[씬 {i}] {sc['narration']}  | 자막: {sc['caption']}  | 키워드: {sc['keyword']}")
```

**[주의]** 대본은 *초안*이다. narration의 사실관계·고유명사·숫자는 발행 전 사람이 검수한다(2.3).

### [실습 2] 대본→TTS 음성 + SRT 자막 생성·동기화 (90분)

실습 1의 씬 배열을 받아, 각 씬을 TTS로 합성하고 **음성의 실제 길이로 SRT 타임코드를 역산**한다(3.2). `srt` 라이브러리로 자막을 직렬화한다.

```python
# pip install google-genai srt
import os, wave, datetime, srt
from google import genai
from google.genai import types

client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])

def synth_tts(text: str, path: str) -> float:
    """텍스트를 음성(wav)으로 합성하고 재생 길이(초)를 반환한다."""
    resp = client.models.generate_content(
        model="gemini-2.5-flash-preview-tts",
        contents=text,
        config=types.GenerateContentConfig(
            response_modalities=["AUDIO"],
            speech_config=types.SpeechConfig(
                voice_config=types.VoiceConfig(
                    prebuilt_voice_config=types.PrebuiltVoiceConfig(
                        voice_name="Kore"      # 채널 내레이션 목소리로 고정
                    )
                )
            ),
        ),
    )
    pcm = resp.candidates[0].content.parts[0].inline_data.data  # 24kHz, 16bit, mono PCM
    with wave.open(path, "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(24000)
        w.writeframes(pcm)
    with wave.open(path, "rb") as w:
        return w.getnframes() / float(w.getframerate())          # 실제 길이(초)

# 실습 1의 결과(예시). 실제로는 script["scenes"]를 그대로 넘긴다.
scenes = [
    {"narration": "지역 소상공인 지원 정책이 다음 달부터 시행됩니다.", "caption": "소상공인 지원 시행"},
    {"narration": "지원 대상은 연 매출 3억 원 이하 사업장입니다.",     "caption": "대상: 연매출 3억 이하"},
    {"narration": "신청은 시청 누리집에서 받습니다.",                  "caption": "신청: 시청 누리집"},
]

subs, cursor = [], datetime.timedelta(0)        # cursor = 누적 시작 시각
for i, sc in enumerate(scenes, 1):
    dur = synth_tts(sc["narration"], f"scene_{i}.wav")           # 음성 합성 + 길이 측정
    start, end = cursor, cursor + datetime.timedelta(seconds=dur)
    subs.append(srt.Subtitle(index=i, start=start, end=end, content=sc["caption"]))
    cursor = end                                                  # 다음 씬 시작점으로 누적

with open("shorts.srt", "w", encoding="utf-8") as f:
    f.write(srt.compose(subs))                  # SRT 표준 포맷으로 직렬화
print("scene_*.wav 와 shorts.srt 생성 완료")
```

**[팁]** 화면 자막(caption)은 음성 대본(narration)보다 짧게 둔다. 귀로 듣는 문장과 눈으로 읽는 자막은 적정 길이가 다르다 — 그래서 실습 1에서 둘을 분리했다.

**[주의]** TTS 모델명·목소리·오디오 포맷은 제공사·버전에 따라 다르다. PCM 샘플레이트(여기선 24kHz)가 다르면 `wave` 설정을 맞춰야 길이가 정확히 계산된다. 다른 제공사(OpenAI 등)를 쓰면 합성 함수만 갈아 끼우고 나머지 동기화 로직은 그대로 재사용한다.

### [실습 3] 미니 파이프라인 통합 (90분)

실습 1·2를 함수로 분리해 **기사 1건 → 대본 → TTS → 자막(SRT) → 썸네일 프롬프트**까지 한 스크립트로 엮는다. 2.1의 단계 구조를 코드로 옮기는 작업이다.

```python
# pip install google-genai srt
import os, json, wave, datetime, srt
from google import genai
from google.genai import types

client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])

STYLE = "플랫 일러스트, 파스텔 톤, CBS 블루 포인트, 글자 없음"   # 썸네일 스타일 고정(1.3)

def make_script(article: str) -> dict:
    """① 기사 → 씬별 JSON 대본 (실습 1 요약본)."""
    schema = {
        "type": "object",
        "properties": {
            "title": {"type": "string"},
            "scenes": {"type": "array", "items": {
                "type": "object",
                "properties": {
                    "narration": {"type": "string"},
                    "caption":   {"type": "string"},
                    "keyword":   {"type": "string"},
                },
                "required": ["narration", "caption", "keyword"],
            }},
        },
        "required": ["title", "scenes"],
    }
    resp = client.models.generate_content(
        model="gemini-2.5-flash",
        contents="다음 기사를 4~6개 씬 숏폼 대본으로. 사실만, 과장 없이.\n\n" + article,
        config=types.GenerateContentConfig(
            temperature=0.3,
            response_mime_type="application/json",
            response_schema=schema,
        ),
    )
    return json.loads(resp.text)

def synth_tts(text: str, path: str) -> float:
    """② 텍스트 → 음성(wav), 길이(초) 반환 (실습 2와 동일)."""
    resp = client.models.generate_content(
        model="gemini-2.5-flash-preview-tts",
        contents=text,
        config=types.GenerateContentConfig(
            response_modalities=["AUDIO"],
            speech_config=types.SpeechConfig(
                voice_config=types.VoiceConfig(
                    prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name="Kore")
                )
            ),
        ),
    )
    pcm = resp.candidates[0].content.parts[0].inline_data.data
    with wave.open(path, "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(24000)
        w.writeframes(pcm)
    with wave.open(path, "rb") as w:
        return w.getnframes() / float(w.getframerate())

def build_srt(scenes: list, out_path: str = "shorts.srt") -> None:
    """③ 씬 음성 길이로 SRT 동기화 (실습 2 요약본)."""
    subs, cursor = [], datetime.timedelta(0)
    for i, sc in enumerate(scenes, 1):
        dur = synth_tts(sc["narration"], f"scene_{i}.wav")
        start, end = cursor, cursor + datetime.timedelta(seconds=dur)
        subs.append(srt.Subtitle(index=i, start=start, end=end, content=sc["caption"]))
        cursor = end
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(srt.compose(subs))

def thumbnail_prompt(script: dict) -> str:
    """④ 제목·첫 씬 키워드로 썸네일 생성 프롬프트 조립(스타일 고정)."""
    kw = script["scenes"][0]["keyword"] if script["scenes"] else ""
    return f"{script['title']} / 핵심: {kw}. {STYLE}"
    # 실제 이미지 생성 호출(의사코드):
    #   img = client.models.generate_images(model="imagen-...", prompt=thumbnail_prompt(script))
    #   img.save("thumb.png")  ← 모델·SDK에 따라 호출 형태가 다르므로 개념만 제시

def run_pipeline(article: str) -> dict:
    script = make_script(article)                 # ①
    build_srt(script["scenes"], "shorts.srt")     # ②③
    thumb = thumbnail_prompt(script)              # ④
    print("제목:", script["title"])
    print("자막 파일: shorts.srt / 음성: scene_*.wav")
    print("썸네일 프롬프트:", thumb)
    return {"script": script, "srt": "shorts.srt", "thumbnail_prompt": thumb}

if __name__ == "__main__":
    article = "여기에 기사 본문을 붙여넣는다 ..."
    run_pipeline(article)
    # [발행 전 사람 검수 게이트] 대본 사실관계·자막·TTS 발음·썸네일 오인 소지 확인 후 합성·발행
```

**[팁]** 함수를 단계별로 분리해 두면(`make_script`·`synth_tts`·`build_srt`·`thumbnail_prompt`), 6회차 PBL에서 한 단계만 바꿔 끼우기 쉽다. 예: 원천을 기사 대신 2회차 STT 녹취로, 소재 선별에 4회차 검색을 추가하는 식이다. 작성한 파이프라인 코드는 **버리지 말 것** — 6·7회차에서 재사용한다.

**[주의]** 이미지 생성 호출부는 모델·SDK 버전 차가 커서 의사코드로 남겼다. 실제 연결 시 ① 생성 썸네일의 글자·로고는 신뢰하지 말고 편집 단계에서 정식 소스로 덮으며(1.4), ② 생성물 저작권·상업적 사용 가능 여부를 확인하고, ③ AI 활용 사실을 사내 기준에 따라 고지한다.

---

## 5. 체크리스트

- [ ] 디퓨전이 "노이즈를 단계적으로 걷어내며 그림을 만든다"는 원리를 설명할 수 있다.
- [ ] 생성 이미지·영상의 용도(썸네일·B롤)와 금지선(사실 왜곡·딥페이크·실존 인물)을 구분할 수 있다.
- [ ] 숏폼 자동화의 단계 구조(원천→대본→TTS→자막→합성)와 각 단계의 앞 회차 기술을 짚을 수 있다.
- [ ] LLM 구조화 출력으로 씬별 JSON 대본을 만들었다(실습 1).
- [ ] TTS로 음성을 합성하고, 음성 실제 길이로 SRT 타임코드를 역산해 동기화했다(실습 2).
- [ ] 기사 1건을 대본·음성·자막·썸네일 프롬프트까지 한 스크립트로 엮었다(실습 3).
- [ ] 파이프라인 발행 직전에 사람 검수 게이트를 두어야 함을 이해했다.

## 6. 핵심 요약

- 디퓨전은 무작위 노이즈를 매 단계 걷어내며 그림을 만들고, 프롬프트가 그 방향을 잡는다. 생성 비주얼은 실사를 대체하는 게 아니라 **썸네일·B롤의 빈칸을 메우는** 보조 도구다.
- 숏폼 자동화는 "한 번에 영상"이 아니라 **원천→대본→TTS→자막→합성**으로 쪼갠 단계를 줄로 잇는 것이다. 각 단계에 1~4회차 기술(STT·영상·검색·LLM)이 들어간다.
- 자막은 **음성을 먼저 만들고 그 실제 길이로 시각을 역산**해 동기화한다. 글자 수로 추정하지 않는다.
- 구조화 출력으로 씬별 대본을, TTS로 음성을, `srt`로 자막을 만들면 한 스크립트로 미니 파이프라인이 완성된다.
- 사실 왜곡·딥페이크·실존 인물 음성/얼굴은 금지선이고, **발행 전 사람 검수**와 AI 활용 고지·저작권 확인은 자동화에서도 그대로 지킨다.

## 7. 다음 회차 예고

**6회차 · PBL 프로젝트 — CBS 업무 과제 해결(10H)** — 1~5회차에서 따로 익힌 모듈을 하나의 줄로 합친다. 1회차 LLM·구조화 출력, 2회차 STT, 3회차 영상·멀티모달 분석, 4회차 임베딩·검색이 5회차의 생성·자동화 파이프라인 위에서 만난다. 즉, *녹취·영상에서 소재를 뽑고(2·3) → 중복을 거르고 후보를 고른 뒤(4) → 대본을 쓰고(1) → 음성·자막·썸네일로 엮는(5)* 한 흐름을, CBS의 실제 과제(노컷TV 숏폼·기사 자동화)에 맞춰 팀으로 설계·구현하고 PoC 피드백 루프에 연결한다. 5회차까지의 파이프라인 코드와 프롬프트가 그대로 PBL의 출발 자산이 된다.

---

## 핵심 용어

| 용어 | 뜻 |
|---|---|
| 디퓨전(diffusion) | 무작위 노이즈를 단계적으로 걷어내며 이미지·영상을 생성하는 모델 |
| 시드(seed) | 생성의 시작 노이즈를 고정하는 값. 같은 시드 = 비슷한 결과 |
| 부정 프롬프트 | 생성 결과에서 피하고 싶은 요소를 명시하는 지시 |
| B롤 | 주 화면을 보조하는 인서트 영상. 자료 부족 구간을 메움 |
| 딥페이크 | 실존 인물의 얼굴·음성을 합성해 진짜처럼 만든 결과물(금지선) |
| TTS | 텍스트를 음성으로 바꾸는 기술(Text-to-Speech) |
| 보이스 클로닝 | 특정인의 목소리를 복제하는 TTS 기법. 동의 없는 사용은 금지선 |
| SRT | 번호·시각·텍스트 블록으로 된 표준 자막 텍스트 포맷 |
| 타임코드 | 자막·구간의 시작·끝 시각(시:분:초,밀리초) |
| 세그먼트 | 대본·자막을 나눈 한 조각(여기선 씬 단위) |
| 파이프라인 | 한 단계의 출력을 다음 단계 입력으로 잇는 자동화 흐름 |
| 사람 검수 게이트 | 자동 생성물을 발행 전 사람이 확인하는 필수 점검 지점 |
