---
name: transcription
description: 음성·영상을 단어 단위 타임스탬프가 붙은 텍스트로 전사(ASR)하는 대표 스킬 — provider는 하드코딩하지 않고 ezer_select로 결정론 선택(무료·로컬 whisperx 바닥부터, deny-by-default). 자막·번역·클립 추출·점프컷의 공통 전처리. "전사 / 받아쓰기 / 자막 텍스트 / 타임스탬프 / transcribe / ASR / whisper" 트리거, 또는 clip-factory·localization-dub·podcast-repurpose·screen-demo·talking-head·hybrid 아키타입의 script 단계로 발동.
ezer:
  capability: transcription
  stability: beta
  cost_class: wall-heavy
  best_for: 음성·영상 전사와 단어 단위 타임스탬프 — 자막·번역·클립 추출·점프컷의 공통 전처리
  requires:
    bins: [ffmpeg]
  install:
    - {kind: brew, formula: ffmpeg}
    - {kind: apt, package: ffmpeg}
---

# transcription (ASR)

소스 미디어(음성/영상)를 **단어 단위 타임스탬프가 붙은 텍스트**로 전사한다. 이 산출물이
자막(caption)·번역(localization)·세그먼트 추출(clip-factory)·침묵 점프컷(talking-head)의
공통 토대다 — 6개 영상 아키타입이 이 한 능력에 의존한다.

> ★ezer-native(AGPL 클린룸): OpenMontage의 `transcriber`(whisperx) 구조를 참고했을 뿐
> 코드·구성을 복사하지 않는다. provider는 아래 카탈로그에서 결정론 선택한다.

## provider 선택 (하드코딩 금지 — ezer_select 위임)

provider 목록을 손으로 고르지 마라. 카탈로그를 ezer_select로 랭킹해 **설명가능하게** 고른다:

```bash
ezer_select rank --catalog "${EZER_PACK_DIR:-$HOME/.ezer/pack}/round/video_provider_catalog.json" \
  --capability transcription --intent "<용도: 자막/번역/클립/점프컷>" --free-first
```

- **무료·로컬 바닥**: `transcriber_whisperx`(faster-whisper/WhisperX·로컬·무키·단어 타임스탬프).
  키가 없어도 항상 가용(deny-by-default 통과) — 그래서 전사는 키 없이도 동작한다.
- **URL 자막 우선(무컴퓨트)**: `ytdlp_subs`(yt-dlp 자막·무키 free·`probe: yt-dlp`). 유튜브가
  publisher/auto 자막을 이미 제공하면 GPU 전사 없이 회수한다. 단 자막은 **세그먼트 단위**라
  `words[]`(단어 타임스탬프)가 **없다**(`supports.word_timestamps: false`) — 단어가 필수인 용도
  (caption-align·점프컷)는 자동으로 `transcriber_whisperx`로 격상된다(아래 단일 채널 글루).
- 더 높은 품질/언어가 필요하면 카탈로그에 클라우드 provider를 추가하고 키 설정 시 setup_offer로
  안내된다(이 스킬은 카탈로그만 소비 — provider 추가는 영상 v2 카탈로그 갱신).
- `--free-first`로 무료 바닥 우선. 사용자가 특정 provider를 원하면 `--prefer <id>`.

## 단일 채널 글루 (URL→자막/전사 — OPP-09)

`bin/transcribe_channel.py`가 "URL 하나 → 자막 우선, 없으면 ASR 폴백"을 **하나의 흐름**으로
통합한다. provider 분기는 산문 if가 아니라 **ezer_select 랭킹**이 결정하고(새 선택엔진 0),
자막 추출은 insane-search `phase0._youtube(subs=True)`(host-naming 허용 유일 파일)가 한다 —
AR(Agent Reach) 계약(순서 있는 후보 리스트·성공성×종결성 분리·probe 자연폴백)만 흡수한 클린룸
재구현(AR 소스 복붙 0).

```bash
python3 "$(dirname "$0")/transcribe_channel.py" run \
  --source "<URL 또는 로컬 미디어 경로>" --intent "<용도>" [--want-words] \
  [--prefer <id>] [--langs ko,en] [--out transcript.json]
```

- `ytdlp_subs`가 자막을 뽑으면 종결(컴퓨트 0). 자막 없음/단어 타임스탬프 필요 시 **비종결
  EMPTY**로 폴백(R6 조기포기 차단) → `transcriber_whisperx`(URL이면 `yt-dlp -x`로 오디오를 받아
  `ffmpeg -ar 16000 -ac 1` 후 ASR)로 떨어진다.
- `--want-words`(caption-align 선행)면 자막의 단어 타임스탬프 부재를 글루가 선제 감지해 ASR로
  격상한다 — caption-align garbage-in 차단.
- 실 whisperx ASR 실행은 이 글루가 아니라 위 ASR 레시피(별 노드/사람)가 수행한다 —
  producer≠evaluator(자가채점 금지). 품질 검증은 `video-verify-audio-sync`.

## 온디바이스 ASR 레시피 (whisperx 바닥 — 종량제 0·로컬 결정론)

provider가 `transcriber_whisperx`(무키 로컬)일 때의 권장 실행 파라미터. OpenCut의 브라우저
Whisper 워커(`services/transcription/worker.ts`: `pipeline("automatic-speech-recognition", q4,
device:"auto")`)가 입증한 *서버·API 0* 온디바이스 ASR을 우리 로컬 스택에 옮긴 레시피다 — 유료
클라우드 전사 의존을 닫는다(Max전용·종량제 금지 정합).

- **오디오 정규화**: 16kHz 모노 PCM으로 리샘플(ASR 모델 입력 규격) — `ffmpeg -ar 16000 -ac 1`.
- **청크-스트라이드**: 30초 청크 + 5초 스트라이드(경계 단어 누락 방지·OpenCut 동일 발상). 긴 미디어를
  청크로 흘려 메모리 상한 유지.
- **양자화 사다리**: 정확도/속도/VRAM 트레이드오프를 양자화로 — `q4`(4비트, 최저 자원·빠름) →
  `int8`(균형) → `fp16`(고정확·GPU). 자원이 허락하는 가장 정확한 단을 고른다(무음 저하 금지).
- **device 캐스케이드**: `cuda`(가능 시) → `cpu` 폴백. (브라우저 셸이면 WebGPU→WASM과 동형.)
  device·양자화·모델 가용성은 `ezer_select`의 **로컬 런타임 준비성 게이트**(probe `module: whisperx`)가
  사전 확인한다 — 미설치면 자신 있게 고르지 않는다(W0-4·무음실패 차단).
- **모델 사다리**: `tiny`/`base`(빠른 초안·점프컷용) → `small`/`medium`(자막 품질) → `large-v3`
  (최고 정확·다국어). 용도(`--intent`)에 맞춰 카탈로그가 안내.

> 정직 경계: 양자화·작은 모델은 정확도를 낮춘다 — 자막·번역 품질이 중요한 아키타입은 더 큰 단을
> 쓰고, 결과는 `video-verify-audio-sync`(별 노드)가 독립 확인한다(자가채점 금지).

## 산출물 계약 (다운스트림 6 아키타입이 소비)

`transcript.json` (작업 폴더):

```json
{
  "source": "<원본 미디어 경로 또는 URL>",
  "source_kind": "url | file",
  "language": "<감지/지정 언어>",
  "provider": "ytdlp_subs | transcriber_whisperx | <ezer_select가 고른 id>",
  "channel_trace": [
    {"provider": "ytdlp_subs", "verdict": "empty", "note": "no subtitles"},
    {"provider": "transcriber_whisperx", "verdict": "strong_ok", "note": "local asr"}
  ],
  "segments": [
    {"start": 0.0, "end": 3.2, "text": "...", "words": [{"w": "...", "start": 0.0, "end": 0.4}]}
  ],
  "duration_s": 0.0
}
```

- **`source_kind`/`channel_trace`**(OPP-09)는 단일 채널 글루가 채운다 — `channel_trace`는 "어느
  채널이 산출했고 앞선 채널은 왜 비었나"를 박제해 무음실패를 막는다(PHIL-09 negative knowledge).
  자막(`ytdlp_subs`)은 세그먼트 단위라 `words[]`가 없을 수 있다 — 단어가 필수면 글루가 ASR로
  격상한다(위 단일 채널 글루).
- **단어 단위 `words[]`**(start/end)가 핵심 — caption-align·점프컷·클립 경계가 이걸 쓴다.
- **speaker 라벨**(diarization)이 필요한 아키타입(podcast-repurpose)은 `segments[].speaker`를
  채운다(provider가 지원할 때만 — 미지원이면 정직하게 단일 화자로 표기).

## 환각0·producer≠evaluator (불가침)

- **타임스탬프는 소스 경계 안**이어야 한다: 모든 `end ≤ duration_s`, `start ≤ end`. 벗어나면
  전사 무효 — 다듬지 말고 재전사하라(garbage-in 차단).
- **추측 채우기 금지**: 들리지 않는 구간을 지어내지 마라. 불확실 구간은 빈 text + 표기.
- 검증은 산출 노드가 자가채점하지 않는다 — `video-verify-audio-sync`(별 노드)가 전사↔오디오
  정합을 독립 확인한다(D1 verdict 계약).

## 거버넌스 배선

- 위임 티켓에 전제로 넣을 때: `--requires-skills transcription`(D6 자동주입).
- 아키타입 매니페스트(D4) script 단계의 success_criteria 예: `{"kind":"json_valid"}`(transcript.json
  파싱) + 다운스트림이 `words[]` 존재를 확인.
- cost_class=wall-heavy: 긴 미디어는 작업 직후 임시파일 정리(자원 거버넌스).
