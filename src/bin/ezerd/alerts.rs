//! T7 E6 경보 엔진 — 임계값·반복실패 경보의 순수 평가기 + 설정 로딩.
//! governance.rs watchdog가 에지 디바운스로 발화(능동 경보)하고, control.alerts RPC가 같은
//! 평가기로 현재 상태(UI 배지)를 노출한다 — 단일 진실원으로 둘이 갈라지지 않게.
//! ★자동응답 금지(governance 교리): 감지·격상(이벤트)만, cycle/clear/budget 판단은 master의 몫.
//! 데이터 소스: 노드 rate(observed_usage) + 7d usage_records(비용·토큰) + 7d events(반복실패).

use crate::state::Daemon;
use serde_json::{json, Value};
use std::sync::atomic::Ordering;
use std::sync::Arc;

/// 경보 임계 설정 — alerts-config.json(pack)에서 로드, 누락/파손은 기본값(graceful degrade).
#[derive(Clone, Debug, PartialEq)]
pub struct AlertConfig {
    pub rate_limit_pct: f64,  // 노드 rate ≥ 이 %(5h/7d 쿼터) → 경보. 기본 90.
    pub weekly_cost_usd: f64, // 7d 비용 ≥ → 경보. 0=비활성(한도 미설정 시 오경보 방지). 기본 0.
    pub weekly_tokens: u64,   // 7d 토큰 ≥ → 경보. 0=비활성. 기본 0.
    pub fail_count: u64,      // 툴 실패수 ≥ → 경보. 기본 5.
    pub fail_rate: f64,       // 동시에 실패율 ≥. 기본 0.3.
    pub fail_min_calls: u64,  // 최소 호출수(소표본 노이즈 차단). 기본 5.
}

impl Default for AlertConfig {
    fn default() -> Self {
        AlertConfig {
            rate_limit_pct: 90.0,
            weekly_cost_usd: 0.0,
            weekly_tokens: 0,
            fail_count: 5,
            fail_rate: 0.3,
            fail_min_calls: 5,
        }
    }
}

impl AlertConfig {
    /// pack의 alerts-config.json 로드. 없거나 파싱 실패면 기본값.
    pub fn load() -> Self {
        let path = ezer::pack::pack_dir().join("alerts-config.json");
        std::fs::read_to_string(&path)
            .ok()
            .and_then(|s| serde_json::from_str::<Value>(&s).ok())
            .map(|v| Self::from_value(&v))
            .unwrap_or_default()
    }

    /// 부분 설정도 허용 — 빠진 키는 기본값(순수·테스트 핀).
    pub fn from_value(v: &Value) -> Self {
        let d = Self::default();
        let f = |k: &str, def: f64| v.get(k).and_then(|x| x.as_f64()).unwrap_or(def);
        let u = |k: &str, def: u64| v.get(k).and_then(|x| x.as_u64()).unwrap_or(def);
        AlertConfig {
            rate_limit_pct: f("rate_limit_pct", d.rate_limit_pct),
            weekly_cost_usd: f("weekly_cost_usd", d.weekly_cost_usd),
            weekly_tokens: u("weekly_tokens", d.weekly_tokens),
            fail_count: u("fail_count", d.fail_count),
            fail_rate: f("fail_rate", d.fail_rate),
            fail_min_calls: u("fail_min_calls", d.fail_min_calls),
        }
    }
}

/// 평가 입력 스냅샷 — 호출부(watchdog/RPC)가 락 잡고 수집(평가기는 락 무관·순수).
#[derive(Default)]
pub struct Snapshot {
    pub rates: Vec<(String, String, f64)>,        // (role, label, used_pct)
    pub weekly_cost_usd: f64,
    pub weekly_tokens: u64,
    pub tool_failures: Vec<(String, u64, u64, f64)>, // (tool, calls, fail, fail_rate)
}

/// 단일 경보.
#[derive(Clone, Debug, PartialEq)]
pub struct Alert {
    pub kind: String,     // "rate_limit" | "weekly_budget" | "repeated_failure"
    pub key: String,      // 에지 디바운스 키 (예: "rate_limit:worker:5h")
    pub severity: String, // "warn" | "crit"
    pub message: String,
    pub detail: Value,
}

impl Alert {
    pub fn to_value(&self) -> Value {
        json!({"kind": self.kind, "key": self.key, "severity": self.severity,
               "message": self.message, "detail": self.detail})
    }
    /// "warn"|"crit" String 표면을 단일 술어 Severity로 파생(기존 String 필드 불변·외과적).
    pub fn severity_enum(&self) -> crate::severity::Severity {
        crate::severity::Severity::from(self.severity.as_str())
    }
}

/// 순수 평가 — 스냅샷+설정 → 현재 발화 중인 경보(key 오름차순 결정론 정렬).
pub fn evaluate(snap: &Snapshot, cfg: &AlertConfig) -> Vec<Alert> {
    let mut out: Vec<Alert> = Vec::new();
    // 1. rate limit (노드 5h/7d 쿼터)
    for (role, label, pct) in &snap.rates {
        if *pct >= cfg.rate_limit_pct {
            out.push(Alert {
                kind: "rate_limit".into(),
                key: format!("rate_limit:{role}:{label}"),
                severity: if *pct >= 95.0 { "crit" } else { "warn" }.into(),
                message: format!("{role} {label} rate {:.0}%", pct),
                detail: json!({"role": role, "label": label, "used_pct": pct}),
            });
        }
    }
    // 2. 주간 예산 한도 (0=비활성)
    if cfg.weekly_cost_usd > 0.0 && snap.weekly_cost_usd >= cfg.weekly_cost_usd {
        out.push(Alert {
            kind: "weekly_budget".into(),
            key: "weekly_budget:cost".into(),
            severity: "warn".into(),
            message: format!("주간 비용 ${:.2} ≥ 한도 ${:.2}", snap.weekly_cost_usd, cfg.weekly_cost_usd),
            detail: json!({"cost_usd": snap.weekly_cost_usd, "limit": cfg.weekly_cost_usd}),
        });
    }
    if cfg.weekly_tokens > 0 && snap.weekly_tokens >= cfg.weekly_tokens {
        out.push(Alert {
            kind: "weekly_budget".into(),
            key: "weekly_budget:tokens".into(),
            severity: "warn".into(),
            message: format!("주간 토큰 {} ≥ 한도 {}", snap.weekly_tokens, cfg.weekly_tokens),
            detail: json!({"tokens": snap.weekly_tokens, "limit": cfg.weekly_tokens}),
        });
    }
    // 3. 반복 실패 (fail수·실패율·최소표본 동시 충족)
    for (tool, calls, fail, rate) in &snap.tool_failures {
        if *fail >= cfg.fail_count && *calls >= cfg.fail_min_calls && *rate >= cfg.fail_rate {
            out.push(Alert {
                kind: "repeated_failure".into(),
                key: format!("repeated_failure:{tool}"),
                severity: if *rate >= 0.5 { "crit" } else { "warn" }.into(),
                message: format!("{tool} 반복 실패 {}/{} ({:.0}%)", fail, calls, rate * 100.0),
                detail: json!({"tool": tool, "calls": calls, "fail": fail, "fail_rate": rate}),
            });
        }
    }
    out.sort_by(|a, b| a.key.cmp(&b.key));
    out
}

/// 데몬에서 평가 스냅샷 수집 — 노드 rate(in-memory) + 7d usage_records/events(analytics).
/// 락 순서: surfaces → (해제) → analytics. consumption 미사용(교착 회피).
pub fn snapshot(daemon: &Arc<Daemon>, now: f64) -> Snapshot {
    let mut rates = Vec::new();
    {
        let surfaces = daemon.surfaces.lock().unwrap();
        for s in surfaces.values() {
            if s.exited.load(Ordering::Relaxed) {
                continue;
            }
            let role = s.role.lock().unwrap().clone().unwrap_or_else(|| "?".into());
            if let Some(u) = s.observed_usage.lock().unwrap().as_ref() {
                for w in &u.rate {
                    rates.push((role.clone(), w.label.clone(), w.used_pct));
                }
            }
        }
    }
    let since = crate::analytics::window_since(now, "7d");
    let (weekly_cost_usd, weekly_tokens, tool_failures) = {
        let guard = daemon.analytics.lock().unwrap();
        match guard.as_ref() {
            Some(conn) => {
                let a = crate::analytics::analytics_summary(conn, since);
                let cost = a["totals"]["cost_usd"].as_f64().unwrap_or(0.0);
                let toks = a["totals"]["tokens"].as_u64().unwrap_or(0);
                let sk = crate::analytics::skills_summary(conn, since);
                let fails = sk["failures"]
                    .as_array()
                    .map(|arr| {
                        arr.iter()
                            .map(|f| {
                                (
                                    f["name"].as_str().unwrap_or("").to_string(),
                                    f["calls"].as_u64().unwrap_or(0),
                                    f["fail"].as_u64().unwrap_or(0),
                                    f["fail_rate"].as_f64().unwrap_or(0.0),
                                )
                            })
                            .collect()
                    })
                    .unwrap_or_default();
                (cost, toks, fails)
            }
            None => (0.0, 0, Vec::new()),
        }
    };
    Snapshot { rates, weekly_cost_usd, weekly_tokens, tool_failures }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn config_partial_and_defaults() {
        assert_eq!(AlertConfig::from_value(&json!({})), AlertConfig::default());
        let c = AlertConfig::from_value(&json!({"rate_limit_pct": 80, "weekly_cost_usd": 50}));
        assert_eq!(c.rate_limit_pct, 80.0);
        assert_eq!(c.weekly_cost_usd, 50.0);
        assert_eq!(c.fail_count, 5, "빠진 키는 기본값");
    }

    #[test]
    fn evaluate_fires_expected_alerts() {
        let cfg = AlertConfig { weekly_cost_usd: 10.0, ..AlertConfig::default() };
        let snap = Snapshot {
            rates: vec![
                ("worker".into(), "5h".into(), 92.0),  // ≥90 warn
                ("master".into(), "7d".into(), 97.0),  // ≥95 crit
                ("cso".into(), "5h".into(), 50.0),     // 미발화
            ],
            weekly_cost_usd: 12.0, // ≥10 → 발화
            weekly_tokens: 0,      // 한도 0 = 비활성
            tool_failures: vec![
                ("Bash".into(), 10, 6, 0.6),  // fail6≥5·calls10≥5·rate0.6≥0.3 → crit
                ("Edit".into(), 3, 3, 1.0),   // calls3<5(min) → 미발화
                ("Read".into(), 20, 2, 0.1),  // rate0.1<0.3 → 미발화
            ],
        };
        let alerts = evaluate(&snap, &cfg);
        let keys: Vec<&str> = alerts.iter().map(|a| a.key.as_str()).collect();
        assert!(keys.contains(&"rate_limit:worker:5h"));
        assert!(keys.contains(&"rate_limit:master:7d"));
        assert!(!keys.contains(&"rate_limit:cso:5h"));
        assert!(keys.contains(&"weekly_budget:cost"));
        assert!(keys.contains(&"repeated_failure:Bash"));
        assert!(!keys.iter().any(|k| k.contains("Edit") || k.contains("Read")));
        // 심각도
        let crit: Vec<&str> = alerts.iter().filter(|a| a.severity == "crit").map(|a| a.key.as_str()).collect();
        assert!(crit.contains(&"rate_limit:master:7d") && crit.contains(&"repeated_failure:Bash"));
        // 결정론 정렬(key asc)
        let mut sorted = keys.clone();
        sorted.sort();
        assert_eq!(keys, sorted);
    }

    #[test]
    fn severity_enum_maps_warn_crit() {
        use crate::severity::Severity;
        let warn = Alert {
            kind: "rate_limit".into(),
            key: "k".into(),
            severity: "warn".into(),
            message: String::new(),
            detail: json!({}),
        };
        let crit = Alert { severity: "crit".into(), ..warn.clone() };
        assert_eq!(warn.severity_enum(), Severity::Recoverable);
        assert_eq!(crit.severity_enum(), Severity::Critical);
        // 기존 String wire 필드 불변(외과적 — 파생자만 추가)
        assert_eq!(warn.severity, "warn");
        assert_eq!(crit.severity, "crit");
    }

    #[test]
    fn weekly_budget_disabled_when_zero() {
        let cfg = AlertConfig::default(); // weekly_cost_usd=0
        let snap = Snapshot { weekly_cost_usd: 9999.0, ..Snapshot::default() };
        assert!(evaluate(&snap, &cfg).is_empty(), "한도 0이면 비용 경보 비활성");
    }
}
