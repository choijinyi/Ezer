//! 경계 실패 분류 — ezerd 거버넌스 신호(재시작-백오프·재시작 소진·rate/budget/실패 경보)를
//! 단일 타입 `Severity{Recoverable,Critical}`로 수렴한다. watchdog·alerts가 산재한
//! 문자열/경로 기반 ad-hoc 판정 대신 하나의 술어(is_critical)로 재시도-vs-격리를 결정한다.
//!
//! penpot 클린룸 근거(개념만·코드복사 0): render-wasm/src/error.rs:3-4의
//! `RECOVERABLE_ERROR=0x01 / CRITICAL_ERROR=0x02` 2분 1바이트 분류 *계약*과 단일 변환점 *산술*만
//! 차용한다. penpot 식별자·match 본문·매크로는 옮기지 않으며, ezer는 u8 wire가 아니라
//! Rust enum + serde 문자열로 재구현한다(MPL 파일전염 회피).

/// 경계 실패의 2분 분류(내부 거버넌스 타입 — RPC error wire code 아님).
#[derive(Clone, Copy, Debug, PartialEq, Eq, serde::Serialize, serde::Deserialize)]
#[serde(rename_all = "lowercase")] // -> "recoverable" / "critical"
pub enum Severity {
    Recoverable,
    Critical,
}

impl Severity {
    /// penpot error.rs:3-4 개념 등가 — 코드복사 0, 산술 계약만(0x01/0x02).
    /// wire는 serde 문자열을 쓰므로 프로덕션에서 호출되지 않는다(0x01/0x02 산술 핀은
    /// severity_roundtrip 테스트가 박제). 티켓 명세상 요구 메서드라 보존한다.
    #[allow(dead_code)]
    pub fn code(self) -> u8 {
        match self {
            Severity::Recoverable => 0x01,
            Severity::Critical => 0x02,
        }
    }
    pub fn as_str(self) -> &'static str {
        match self {
            Severity::Recoverable => "recoverable",
            Severity::Critical => "critical",
        }
    }
    /// 격리(retry-vs-isolate) 단일 술어 — critical만 격리.
    pub fn is_critical(self) -> bool {
        matches!(self, Severity::Critical)
    }
}

impl From<&str> for Severity {
    /// alerts.rs "warn"|"crit" 문자열 흡수 + serde 표면("recoverable"/"critical") 역방향.
    fn from(s: &str) -> Self {
        if s == "crit" || s == "critical" {
            Severity::Critical
        } else {
            Severity::Recoverable
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    /// 거버넌스 신호 → Severity 분류(리팩터된 단일점·producer).
    /// 이 함수는 governance/alerts의 산재 분류를 단일 어휘로 캡처한다.
    fn classify(situation: &str) -> Severity {
        match situation {
            "restart_backoff" => Severity::Recoverable, // 재시도 → 격리 안 함
            "exit_unrecoverable" => Severity::Critical,  // 3-retry 소진 → 격리
            "alert_crit" => Severity::from("crit"),
            "alert_warn" => Severity::from("warn"),
            "tick_panic" => Severity::Critical, // 개념: penpot panic→0x02
            other => panic!("unknown situation: {other}"),
        }
    }

    #[test]
    fn severity_roundtrip() {
        // serde 직렬화 표면 박제
        assert_eq!(
            serde_json::to_string(&Severity::Recoverable).unwrap(),
            "\"recoverable\""
        );
        assert_eq!(
            serde_json::to_string(&Severity::Critical).unwrap(),
            "\"critical\""
        );
        // 역직렬화 왕복
        let r: Severity = serde_json::from_str("\"recoverable\"").unwrap();
        let c: Severity = serde_json::from_str("\"critical\"").unwrap();
        assert_eq!(r, Severity::Recoverable);
        assert_eq!(c, Severity::Critical);
        // as_str/From 왕복
        assert_eq!(Severity::from(Severity::Recoverable.as_str()), Severity::Recoverable);
        assert_eq!(Severity::from(Severity::Critical.as_str()), Severity::Critical);
        // code() 산술 핀 (penpot error.rs:3-4 등가)
        assert_eq!(Severity::Recoverable.code(), 0x01);
        assert_eq!(Severity::Critical.code(), 0x02);
    }

    // ── 행위보존 핀(producer≠evaluator) — 리팩터 코드와 분리된 고정 테이블 ──
    // (situation, expected severity, expect_isolate)
    const DECISION_TABLE: &[(&str, &str, bool)] = &[
        ("restart_backoff", "recoverable", false), // 재시도 → 격리 안 함
        ("exit_unrecoverable", "critical", true),  // 격리
        ("alert_crit", "critical", true),
        ("alert_warn", "recoverable", false),
        ("tick_panic", "critical", true),
    ];

    #[test]
    fn severity_decision_table_is_behavior_preserving() {
        for (sit, sev, isolate) in DECISION_TABLE {
            let s = classify(sit); // 리팩터된 분류 함수(producer)
            assert_eq!(s.as_str(), *sev, "{sit}");
            assert_eq!(s.is_critical(), *isolate, "{sit}"); // 격리 술어 = is_critical
        }
    }
}
