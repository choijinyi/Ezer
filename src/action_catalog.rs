//! T4-3 · 에이전트 온보딩 3단 — (1) 정적 본문(pack include_str!, 기존) (2) 런타임 카탈로그
//! 플레이스홀더 치환 (3) on-demand 단건 조회.
//!
//! penpot `PenpotMcpServer.ts:136` `instructions.replace('$api_types', apiDocs.getTypeNames())`
//! (런타임 플레이스홀더 치환) + `:215` `PenpotApiInfoTool` (on-demand 단건 상세)의 **구조만**
//! 클린룸 차용한다(penpot 도메인 텍스트 미복사 · MPL-2.0). v1은 penpot처럼 단일 플레이스홀더
//! (`$action_catalog`)만 둔다($skill_index는 후속 — EZERagent-design, penpot-attested 아님).
//!
//! ★Max 토큰효율: 전체 산문을 정적 본문에 하드코딩하지 않고 런타임에 카탈로그를 *치환*해 주입,
//! 단건 상세는 `editor.action_info(name)`로 on-demand. 단 핵심 가치는 토큰절감(그건 RTK 차선)이
//! 아니라 **반-드리프트/반-환각** — 카탈로그를 실제 EZERagentd 레지스트리(`edit_kinds::EditKind`)에서
//! *기계적으로 파생*해 정적 본문과 실제 표면이 절대 어긋날 수 없게 한다(단일진실).
//!
//! penpot 정직성(propmap T4-3.revision): penpot은 $api_types를 *정적* 타입명 목록
//! (apiDocs.getTypeNames())에서 파생한다. 여기 카탈로그도 컴파일타임 동결 enum(EditKind)에서
//! 파생하므로 동급의 정적-파생이다(라이브 가변 레지스트리가 아님 → 추가 인프라·환각 위험 0).

use crate::edit_kinds::EditKind;

/// 정적 온보딩 본문에 박는 런타임 치환 플레이스홀더(penpot $api_types 등가, 단일).
pub const ACTION_CATALOG_PLACEHOLDER: &str = "$action_catalog";

/// 카탈로그 1행 — 액션 이름(kebab serde 리터럴)과 한 줄 요지.
fn action_summary(kind: EditKind) -> &'static str {
    // ★no-wildcard match(edit_kinds 가드① 정신) — 새 EditKind 추가 시 여기 미처리면 빌드 차단.
    // 요지는 EZERagent 도메인 어휘(penpot 텍스트 미복사). 카탈로그 *구조*만 차용.
    match kind {
        EditKind::Avatar => "아바타 발화 트랙 — 화자 영상 합성",
        EditKind::Broll => "b-roll 트랙 — 보조 영상 인서트",
        EditKind::Graphic => "그래픽 트랙 — 자막카드·도형·오버레이",
        EditKind::Caption => "캡션 트랙 — 타임코드 동기 자막",
        EditKind::Audio => "오디오 트랙 — 내레이션·효과음",
        EditKind::Music => "음악 트랙 — 배경음악",
    }
}

/// 액션 이름 리터럴(serde kebab) — EditKind 단일진실에서 파생(하드코딩 금지).
pub fn action_name(kind: EditKind) -> String {
    serde_json::to_value(kind)
        .ok()
        .and_then(|v| v.as_str().map(str::to_string))
        .unwrap_or_default()
}

/// ★런타임 카탈로그 본문 — 실제 EditKind 레지스트리에서 *파생*(하드코딩 0). 정적 본문의
/// `$action_catalog` 자리에 치환될 텍스트. 레지스트리에 변형이 추가되면 이 출력이 자동 반영
/// (드리프트 구조적 불가). penpot getTypeNames() 등가.
pub fn render_catalog() -> String {
    let mut s = String::new();
    for k in EditKind::ALL {
        s.push_str(&format!("- {}: {}\n", action_name(k), action_summary(k)));
    }
    s
}

/// (2) 런타임 플레이스홀더 치환 — 정적 본문의 `$action_catalog`를 파생 카탈로그로 교체.
/// penpot `instructions.replace('$api_types', …)` 등가. 플레이스홀더가 없으면 본문 무변(회귀 0).
pub fn substitute_catalog(body: &str) -> String {
    body.replace(ACTION_CATALOG_PLACEHOLDER, &render_catalog())
}

/// (3) on-demand 단건 조회 — 액션 이름 하나의 상세를 반환(전체 미주입). 미지의 이름은 None.
/// penpot `PenpotApiInfoTool(name)` 등가. EZERagentd `editor.action_info` RPC가 이걸 호출.
pub fn action_info(name: &str) -> Option<serde_json::Value> {
    EditKind::ALL.iter().copied().find(|k| action_name(*k) == name).map(|k| {
        serde_json::json!({
            "name": action_name(k),
            "summary": action_summary(k),
        })
    })
}

/// 전체 카탈로그를 구조화 JSON으로 — EZERagentd `editor.action_catalog` RPC용(레지스트리 파생).
pub fn catalog_json() -> serde_json::Value {
    let items: Vec<serde_json::Value> = EditKind::ALL
        .iter()
        .copied()
        .map(|k| serde_json::json!({"name": action_name(k), "summary": action_summary(k)}))
        .collect();
    serde_json::json!({ "actions": items })
}

#[cfg(test)]
mod tests {
    use super::*;

    // 카탈로그가 EditKind 레지스트리 전수와 정확히 일치(파생 — 하드코딩 아님).
    #[test]
    fn t4_3_catalog_derived_from_registry_not_hardcoded() {
        let cat = render_catalog();
        for k in EditKind::ALL {
            assert!(cat.contains(&action_name(k)), "카탈로그에 {} 누락", action_name(k));
        }
        // 행 수 == 레지스트리 변형 수(추가/누락 0).
        assert_eq!(cat.lines().count(), EditKind::ALL.len());
    }

    // ★(2) 런타임 치환 — 정적 본문의 플레이스홀더가 파생 카탈로그로 교체된다(하드코딩 아님 증명).
    #[test]
    fn t4_3_placeholder_substituted_at_runtime() {
        let static_body = "온보딩.\n## 액션\n$action_catalog\n끝.";
        let out = substitute_catalog(static_body);
        assert!(!out.contains(ACTION_CATALOG_PLACEHOLDER), "플레이스홀더가 남아있음(치환 실패)");
        assert!(out.contains("avatar:"), "치환된 카탈로그에 실제 레지스트리 항목 없음");
        // 정적 본문 자체엔 카탈로그가 하드코딩되어 있지 않다.
        assert!(!static_body.contains("avatar"), "정적 본문에 카탈로그가 하드코딩됨(토큰낭비)");
    }

    // 플레이스홀더 없는 본문은 무변(회귀 0).
    #[test]
    fn t4_3_no_placeholder_is_noop() {
        let body = "플레이스홀더 없음";
        assert_eq!(substitute_catalog(body), body);
    }

    // ★(3) on-demand 단건 — 이름 하나만 상세 반환(전체 아님), 미지의 이름은 None.
    #[test]
    fn t4_3_on_demand_returns_single_item() {
        let one = action_info("caption").unwrap();
        assert_eq!(one["name"], "caption");
        assert!(one.get("summary").is_some());
        // 단건이지 전체가 아님 — 다른 액션은 응답에 없다.
        assert!(!one.to_string().contains("avatar"));
        assert!(action_info("does-not-exist").is_none());
    }

    // catalog_json이 레지스트리 전수를 담는다(RPC 파생 일치).
    #[test]
    fn t4_3_catalog_json_covers_registry() {
        let j = catalog_json();
        let arr = j["actions"].as_array().unwrap();
        assert_eq!(arr.len(), EditKind::ALL.len());
    }
}
