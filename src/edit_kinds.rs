//! T1-2 · 다중 출력 경로 '누락0' 컴파일타임 3중 가드 — 단일진실 enum + no-wildcard 전수 match.
//!
//! ezer의 다중 소비 경로(미래 인-프로세스 Rust 편집기 ↔ 현존 Python 검증기 `check_timeline.py`
//! ↔ 워크플로우 게이트 `ezer_manifest.py`)가 공유하는 "종류 집합"(track kind·mode·transition)을
//! **단일 Rust enum**으로 단일진실화한다. penpot `rendering_architecture.md:90-119`의 3-가드 *패턴*만
//! 산문에서 클린룸 재유도한다(코드복사 0 · MPL-2.0 — penpot 트레이트 메서드명·match arm 미전사).
//!
//! 스코프(정직): penpot이 두 Rust 렌더 경로(`render_shape`↔`render_leaf_content`) 사이를 봉인하는 것과
//! 달리 ezer엔 *통합할 두 번째 Rust 렌더 경로 자체가 아직 없다*. 따라서 v1 가드는 **누락0만** 보장한다
//! (프레임/의미 패리티는 별도 raster-diff 하네스 소관 — 본 모듈은 보장하지 않음).
//!
//! 가드 ①(Type guard): 아래 enum은 `#[non_exhaustive]` 금지 + `dispatch_kind`가 `_ =>` 없는 전수
//! match → 새 변형 추가 시 모든 처리부 구현 전까지 **빌드 차단**(누락0).
//! 가드 ②(Capability guard): `SurfaceRenderer` 트레이트가 렌더 능력의 단일 선언(시그니처만 동결).
//! 가드 ③(Order guard): 단일 순서 함수는 인-프로세스 렌더러가 계획될 때 착륙(과조기 도입 금지).
//!
//! 리터럴은 `ezer-pack/schemas/edit_decisions.schema.json`·`bin/check_timeline.py:83/86/87`과
//! **글자 단위 일치**해야 하며, build.rs가 `OUT_DIR/ezer_kinds.json`을 생성해 그 일치를 박제한다.
//! 3자 파리티(enum codegen ↔ schema ↔ check_timeline)는 preflight C44.kind-enum-parity가 검증한다.

use serde::{Deserialize, Serialize};

/// 트랙 종류 단일진실 (schema:/properties/tracks/items/properties/kind · check_timeline TRACK_KINDS).
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "kebab-case")]
pub enum EditKind {
    Avatar,
    Broll,
    Graphic,
    Caption,
    Audio,
    Music,
}

/// 요소 배치 모드 (schema:/$defs/element/properties/mode · check_timeline EL_MODES).
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "kebab-case")]
pub enum Mode {
    Fullscreen,
    LeftCard,
    RoundedCropPip,
}

/// 전환 (schema:/$defs/element/properties/transition · check_timeline EL_TRANSITIONS).
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "kebab-case")]
pub enum Transition {
    Cut,
    Dissolve,
    Slide,
}

impl EditKind {
    /// 전수 변형 — round-trip 테스트·codegen 파리티의 기준. 변형 추가 시 여기도 갱신해야 하며,
    /// `dispatch_kind`의 no-wildcard match가 누락을 컴파일타임에 차단한다.
    pub const ALL: [EditKind; 6] = [
        EditKind::Avatar,
        EditKind::Broll,
        EditKind::Graphic,
        EditKind::Caption,
        EditKind::Audio,
        EditKind::Music,
    ];
}

/// 가드 ①(Type guard) — 각 `EditKind`를 *반드시* 처리한다. `dispatch_kind`의 match는 `_ =>`가
/// 없어 새 변형 추가 시 이 트레이트를 구현하는 모든 처리부가 빌드 차단된다(누락0). penpot Type-guard
/// 패턴의 클린룸 등가 — 식별자는 ezer 도메인 어휘로 독립 명명(penpot match arm 미전사).
pub trait KindHandler {
    type Out;
    fn on_avatar(&self) -> Self::Out;
    fn on_broll(&self) -> Self::Out;
    fn on_graphic(&self) -> Self::Out;
    fn on_caption(&self) -> Self::Out;
    fn on_audio(&self) -> Self::Out;
    fn on_music(&self) -> Self::Out;
}

/// 단일 디스패치 — `_ =>` 금지(penpot vector.rs no-wildcard 전수 match 패턴). 새 `EditKind` 변형은
/// 이 match에 arm을 추가하기 전까지 컴파일되지 않는다 = 누락0의 컴파일타임 강제.
pub fn dispatch_kind<H: KindHandler>(k: EditKind, h: &H) -> H::Out {
    match k {
        EditKind::Avatar => h.on_avatar(),
        EditKind::Broll => h.on_broll(),
        EditKind::Graphic => h.on_graphic(),
        EditKind::Caption => h.on_caption(),
        EditKind::Audio => h.on_audio(),
        EditKind::Music => h.on_music(),
    }
}

/// 가드 ②(Capability guard) — 렌더 능력의 단일 선언(시그니처만 동결·구현 보류). 인-프로세스 렌더러가
/// *계획될 때* 구현(editor-primitives §1). 새 렌더 능력은 여기 메서드로만 추가 → 모든 백엔드 구현
/// 전까지 빌드 차단(penpot Capability-guard 패턴). v1: 라이브 핫패스 통합·실제 렌더러 구현 금지
/// (인-프로세스 Rust 렌더러 미존재 — raster-diff 하네스 없이 핫패스 통합 강행 금지).
pub trait SurfaceRenderer {
    type Error;
    fn draw_track(&mut self, kind: EditKind) -> Result<(), Self::Error>;
    // (효과 추가 시 메서드 추가 — inline 금지. 가드 ③ 단일순서함수는 이 트레이트가 빌드될 때 착륙.)
}

#[cfg(test)]
mod tests {
    use super::*;

    // serde 리터럴이 스키마 enum 리터럴과 글자 단위 일치(kebab-case)함을 박제.
    #[test]
    fn t1_2_serde_literals_match_schema() {
        assert_eq!(serde_json::to_string(&EditKind::Avatar).unwrap(), "\"avatar\"");
        assert_eq!(serde_json::to_string(&EditKind::Broll).unwrap(), "\"broll\"");
        assert_eq!(serde_json::to_string(&Mode::LeftCard).unwrap(), "\"left-card\"");
        assert_eq!(
            serde_json::to_string(&Mode::RoundedCropPip).unwrap(),
            "\"rounded-crop-pip\""
        );
        assert_eq!(serde_json::to_string(&Transition::Cut).unwrap(), "\"cut\"");
        assert_eq!(serde_json::to_string(&Transition::Dissolve).unwrap(), "\"dissolve\"");
    }

    // build.rs 산출 ezer_kinds.json의 집합 == enum 전수 변형 집합(diff0). build.rs 리터럴 목록과
    // edit_kinds.rs enum이 어긋나면 이 테스트가 fail(이중 잠금 — 드리프트 컴파일/테스트 차단).
    #[test]
    fn t1_2_kind_enum_roundtrip() {
        let gen: serde_json::Value =
            serde_json::from_str(include_str!(concat!(env!("OUT_DIR"), "/ezer_kinds.json"))).unwrap();
        let all_kinds: Vec<String> = EditKind::ALL
            .iter()
            .map(|k| serde_json::to_value(k).unwrap().as_str().unwrap().to_owned())
            .collect();
        let gen_kinds: Vec<String> = gen["edit_kind"]
            .as_array()
            .unwrap()
            .iter()
            .map(|v| v.as_str().unwrap().to_owned())
            .collect();
        assert_eq!(gen_kinds, all_kinds, "ezer_kinds.json edit_kind == enum 전수 변형");
    }

    // no-wildcard dispatch_kind가 전수 변형을 처리함을 런타임에서도 확인(컴파일러가 누락0을 강제하나
    // 디스패치 동작 자체도 박제). 새 변형 추가 시 KindHandler 구현이 빌드 차단되는 게 핵심 가드.
    #[test]
    fn t1_2_dispatch_kind_exhaustive() {
        struct NameHandler;
        impl KindHandler for NameHandler {
            type Out = &'static str;
            fn on_avatar(&self) -> &'static str {
                "avatar"
            }
            fn on_broll(&self) -> &'static str {
                "broll"
            }
            fn on_graphic(&self) -> &'static str {
                "graphic"
            }
            fn on_caption(&self) -> &'static str {
                "caption"
            }
            fn on_audio(&self) -> &'static str {
                "audio"
            }
            fn on_music(&self) -> &'static str {
                "music"
            }
        }
        for k in EditKind::ALL {
            let name = dispatch_kind(k, &NameHandler);
            assert_eq!(serde_json::to_value(k).unwrap().as_str().unwrap(), name);
        }
    }
}
