//! T3-2 · directive 합성 캐스케이드 — 단일 결정론 reduce-merge.
//!
//! ezer directive 합성(글로벌 < 프로젝트 < 역할, 뒤 셋이 앞을 override)을 *하나의* 결정론
//! reduce 함수로 정규화한다. penpot `tokens_lib.cljc:1329-1338`의 `get-tokens-in-active-sets`
//! (활성 셋 순서대로 reduce + merge, 뒤 셋이 같은 키를 *조용히* override = CSS 캐스케이드 동형)의
//! **패턴만** 클린룸 재유도한다(코드복사 0 · MPL-2.0 · CSS Cascade 표준이 출처).
//!
//! ★합성 LOGIC(코드)이지 directive *내용*이 아니다 — soul/CLAUDE/directive 텍스트는 건드리지
//! 않는다(autopilot denylist). 이 모듈은 "어떤 레이어가 어떤 키를 이긴다"는 결합 규칙만 정의한다.
//!
//! 충돌 정책(propmap T3-2.revision 교정 반영 — penpot의 실제 2단 의미):
//!  ① **교차-레벨 같은 키 override = SILENT**(캐스케이드의 목적 — penpot은 여기서 에러 안 냄).
//!  ② **fail-loud = 같은 *레벨* 안에서 같은 키를 서로 다른 값으로 두 번 선언**(구조적 모호성 —
//!     penpot name-collision의 등가: 합쳐질 때 어느 값이 이길지 결정 불가). 이건 호출자가 한
//!     레벨에 같은 키를 중복 적재한 버그라 조용히 덮지 않고 드러낸다.

use std::collections::BTreeMap;

/// 합성 레이어 — 우선순위 오름차순(전역=0 < 프로젝트=1 < 역할=2 …). `entries`는 (키, 값) 목록.
/// 같은 레이어 안에서 키 중복은 fail-loud(②) — 캐스케이드 override(①)는 *레이어 사이*에서만.
#[derive(Debug, Clone)]
pub struct Layer {
    pub name: String,
    pub entries: Vec<(String, String)>,
}

impl Layer {
    pub fn new(name: impl Into<String>, entries: Vec<(String, String)>) -> Self {
        Layer { name: name.into(), entries }
    }
}

/// 합성 결과 — 결정론 정렬(BTreeMap)된 최종 키→값. `provenance`는 각 키의 최종 승자 레이어명.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Composed {
    pub merged: BTreeMap<String, String>,
    pub provenance: BTreeMap<String, String>,
}

/// 같은 레벨 내 같은 키를 서로 다른 값으로 선언 — penpot name-collision 등가의 구조적 모호성.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct CollisionError {
    pub layer: String,
    pub key: String,
    pub first: String,
    pub second: String,
}

/// ★단일 결정론 reduce-merge 캐스케이드 (penpot get-tokens-in-active-sets 패턴, 클린룸).
///
/// layers를 **주어진 순서대로** reduce하며 같은 키는 뒤(높은 우선순위) 레이어가 조용히 override(①).
/// 단, *한 레이어 내부*에 같은 키가 다른 값으로 둘 이상 있으면 BLOCK(②, fail-loud).
/// 같은 레이어 내 같은 키·같은 값 중복은 무해 → 허용(idempotent).
///
/// 결정론: 입력 layers·entries 순서가 같으면 출력(merged·provenance)이 글자 단위로 동일.
/// 멱등: compose(compose 결과를 단일 레이어로 되먹임) == 원본 merged (재합성 안정).
pub fn compose_layers(layers: &[Layer]) -> Result<Composed, CollisionError> {
    let mut merged: BTreeMap<String, String> = BTreeMap::new();
    let mut provenance: BTreeMap<String, String> = BTreeMap::new();
    for layer in layers {
        // 레이어 내부 중복(②) 선검사 — 같은 키 다른 값이면 BLOCK. 같은 값 중복은 통과.
        let mut within: BTreeMap<&str, &str> = BTreeMap::new();
        for (k, v) in &layer.entries {
            if let Some(prev) = within.insert(k.as_str(), v.as_str()) {
                if prev != v.as_str() {
                    return Err(CollisionError {
                        layer: layer.name.clone(),
                        key: k.clone(),
                        first: prev.to_string(),
                        second: v.clone(),
                    });
                }
            }
        }
        // 교차-레벨 override(①) — 뒤 레이어가 앞을 조용히 덮는다(캐스케이드 목적).
        for (k, v) in &layer.entries {
            merged.insert(k.clone(), v.clone());
            provenance.insert(k.clone(), layer.name.clone());
        }
    }
    Ok(Composed { merged, provenance })
}

#[cfg(test)]
mod tests {
    use super::*;

    fn e(pairs: &[(&str, &str)]) -> Vec<(String, String)> {
        pairs.iter().map(|(k, v)| (k.to_string(), v.to_string())).collect()
    }

    // ★결정론 — 글로벌<프로젝트<역할 우선순위(뒤 셋이 이긴다). penpot 캐스케이드 동형.
    #[test]
    fn t3_2_global_lt_project_lt_role_later_wins() {
        let layers = vec![
            Layer::new("global", e(&[("tone", "neutral"), ("verbosity", "low")])),
            Layer::new("project", e(&[("tone", "strict")])),
            Layer::new("role", e(&[("verbosity", "high")])),
        ];
        let c = compose_layers(&layers).unwrap();
        // 역할이 없는 키는 프로젝트가, 프로젝트도 없으면 글로벌이 살아남는다.
        assert_eq!(c.merged.get("tone").map(String::as_str), Some("strict"));
        assert_eq!(c.merged.get("verbosity").map(String::as_str), Some("high"));
        // provenance: 최종 승자 레이어.
        assert_eq!(c.provenance.get("tone").map(String::as_str), Some("project"));
        assert_eq!(c.provenance.get("verbosity").map(String::as_str), Some("role"));
    }

    // 역할이 글로벌·프로젝트를 모두 override (가장 높은 우선순위).
    #[test]
    fn t3_2_role_overrides_all_lower_levels() {
        let layers = vec![
            Layer::new("global", e(&[("k", "g")])),
            Layer::new("project", e(&[("k", "p")])),
            Layer::new("role", e(&[("k", "r")])),
        ];
        let c = compose_layers(&layers).unwrap();
        assert_eq!(c.merged.get("k").map(String::as_str), Some("r"));
        assert_eq!(c.provenance.get("k").map(String::as_str), Some("role"));
    }

    // ★멱등 — 합성 결과를 단일 레이어로 되먹여 재합성해도 merged 동일(재합성 안정).
    #[test]
    fn t3_2_idempotent_remerge() {
        let layers = vec![
            Layer::new("global", e(&[("a", "1"), ("b", "2")])),
            Layer::new("project", e(&[("b", "3"), ("c", "4")])),
            Layer::new("role", e(&[("c", "5")])),
        ];
        let first = compose_layers(&layers).unwrap();
        // 결과를 단일 레이어로 환원 → 재합성.
        let folded: Vec<(String, String)> =
            first.merged.iter().map(|(k, v)| (k.clone(), v.clone())).collect();
        let second = compose_layers(&[Layer::new("composed", folded)]).unwrap();
        assert_eq!(first.merged, second.merged, "재합성이 merged를 바꾸면 안 됨(멱등)");
    }

    // 교차-레벨 같은 키 override는 SILENT(에러 아님) — 캐스케이드의 목적(①).
    #[test]
    fn t3_2_cross_level_override_is_silent_not_error() {
        let layers = vec![
            Layer::new("global", e(&[("k", "g")])),
            Layer::new("role", e(&[("k", "r")])),
        ];
        // 에러 없이 통과해야 한다.
        assert!(compose_layers(&layers).is_ok());
    }

    // 같은 *레벨* 안에서 같은 키 다른 값 = fail-loud(②, 구조적 모호성).
    #[test]
    fn t3_2_same_level_divergent_key_is_fail_loud() {
        let layers = vec![Layer::new("project", e(&[("k", "x"), ("k", "y")]))];
        let err = compose_layers(&layers).unwrap_err();
        assert_eq!(err.layer, "project");
        assert_eq!(err.key, "k");
    }

    // 같은 레벨 같은 키·같은 값 중복은 무해 → 허용(idempotent 입력 견딤).
    #[test]
    fn t3_2_same_level_duplicate_same_value_ok() {
        let layers = vec![Layer::new("global", e(&[("k", "v"), ("k", "v")]))];
        assert!(compose_layers(&layers).is_ok());
    }

    // 빈 입력·빈 레이어는 빈 결과(경계).
    #[test]
    fn t3_2_empty_is_empty() {
        assert!(compose_layers(&[]).unwrap().merged.is_empty());
        assert!(compose_layers(&[Layer::new("g", vec![])]).unwrap().merged.is_empty());
    }
}
