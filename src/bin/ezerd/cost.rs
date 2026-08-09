//! T7 비용 엔진 — 모델별 단가표로 토큰→USD 환산.
//!
//! 단가 출처(환각0):
//! - claude input/output: claude-api 스킬 Current Models 표(2026-06-04 캐시·권위).
//!   Opus 4.8 $5/$25 · Sonnet 4.6 $3/$15 · Haiku 4.5 $1/$5 · Fable 5 $10/$50 (per 1M).
//! - claude 캐시 단가: 표준 경제(prompt-caching 문서) — write(5m)=1.25×input, read=0.1×input.
//!   (opus/sonnet/haiku 행은 공개 단가표와 교차검증됨.)
//! - codex(gpt) 단가: 공개 모델 단가표 기준.
//! 미상 모델은 default(Sonnet). 구독 요금제는 실제 청구와 다를 수 있어 "추정"으로만 노출한다.

#[derive(Clone, Copy, Debug, PartialEq, serde::Serialize)]
pub struct Pricing {
    pub input_per_m: f64,
    pub output_per_m: f64,
    pub cache_write_per_m: f64,
    pub cache_read_per_m: f64,
}

const OPUS: Pricing = Pricing { input_per_m: 5.0, output_per_m: 25.0, cache_write_per_m: 6.25, cache_read_per_m: 0.50 };
const OPUS_LEGACY: Pricing = Pricing { input_per_m: 15.0, output_per_m: 75.0, cache_write_per_m: 18.75, cache_read_per_m: 1.50 };
const FABLE: Pricing = Pricing { input_per_m: 10.0, output_per_m: 50.0, cache_write_per_m: 12.5, cache_read_per_m: 1.0 };
const SONNET: Pricing = Pricing { input_per_m: 3.0, output_per_m: 15.0, cache_write_per_m: 3.75, cache_read_per_m: 0.30 };
const HAIKU: Pricing = Pricing { input_per_m: 1.0, output_per_m: 5.0, cache_write_per_m: 1.25, cache_read_per_m: 0.10 };
const HAIKU35: Pricing = Pricing { input_per_m: 0.8, output_per_m: 4.0, cache_write_per_m: 1.0, cache_read_per_m: 0.08 };
const GPT55: Pricing = Pricing { input_per_m: 5.0, output_per_m: 30.0, cache_write_per_m: 0.0, cache_read_per_m: 0.50 };
const GPT54: Pricing = Pricing { input_per_m: 2.5, output_per_m: 15.0, cache_write_per_m: 0.0, cache_read_per_m: 0.25 };
const GPT54MINI: Pricing = Pricing { input_per_m: 0.75, output_per_m: 4.5, cache_write_per_m: 0.0, cache_read_per_m: 0.075 };

/// 미상 모델 폴백 — Sonnet 단가.
pub const DEFAULT_PRICING: Pricing = SONNET;

/// 정규화 모델명 prefix → 단가. **most-specific 우선**(first-match wins): 4-8 행이 4 행보다 앞.
const TABLE: &[(&str, Pricing)] = &[
    ("claude-fable-5", FABLE),
    ("claude-mythos-5", FABLE),
    ("claude-mythos-preview", FABLE),
    ("claude-opus-4-8", OPUS),
    ("claude-opus-4-7", OPUS),
    ("claude-opus-4-6", OPUS),
    ("claude-opus-4-5", OPUS),
    ("claude-opus-4-1", OPUS_LEGACY),
    ("claude-opus-4", OPUS_LEGACY),
    ("claude-sonnet-4-6", SONNET),
    ("claude-sonnet-4-5", SONNET),
    ("claude-sonnet-4", SONNET),
    ("claude-haiku-4-5", HAIKU),
    ("claude-haiku-3-5", HAIKU35),
    ("gpt-5-5", GPT55),
    ("gpt-5-4-mini", GPT54MINI),
    ("gpt-5-4", GPT54),
];

/// 모델명 정규화: 소문자 · `[1m]` 등 대괄호 접미 제거 · `.`·`_`→`-` · 끝 `-YYYYMMDD` 제거.
fn normalize(model: &str) -> String {
    let mut s = model.trim().to_lowercase();
    if let Some(i) = s.find('[') {
        s.truncate(i); // claude-opus-4-8[1m] → claude-opus-4-8
    }
    s = s.replace(['.', '_'], "-");
    s = s.trim_matches('-').to_string();
    // 끝의 8자리 날짜 접미(-YYYYMMDD) 제거
    let parts: Vec<&str> = s.split('-').collect();
    if parts.len() > 1 {
        if let Some(last) = parts.last() {
            if last.len() == 8 && last.chars().all(|c| c.is_ascii_digit()) {
                return parts[..parts.len() - 1].join("-");
            }
        }
    }
    s
}

/// 모델 단가 조회 — prefix 매칭(most-specific 우선), 미상은 default(Sonnet).
pub fn pricing_for(model: &str) -> Pricing {
    let n = normalize(model);
    for (prefix, p) in TABLE {
        if n.starts_with(prefix) {
            return *p;
        }
    }
    DEFAULT_PRICING
}

/// 단가표 적중 여부 — false면 DEFAULT(Sonnet) 폴백으로 계산된 추정치라는 뜻.
/// UI가 "단가 미상" 표시에 쓴다(전수조사 B-4 — 폴백 왜곡을 조용히 숨기지 않는다).
pub fn has_pricing(model: &str) -> bool {
    let n = normalize(model);
    TABLE.iter().any(|(prefix, _)| n.starts_with(prefix))
}

/// 4-팩터 비용 공식(USD). cache_read는 컨텍스트 재사용 할인 단가.
pub fn calculate_cost(
    input_tokens: u64,
    output_tokens: u64,
    cache_creation_tokens: u64,
    cache_read_tokens: u64,
    model: &str,
) -> f64 {
    let p = pricing_for(model);
    (input_tokens as f64 / 1_000_000.0) * p.input_per_m
        + (output_tokens as f64 / 1_000_000.0) * p.output_per_m
        + (cache_creation_tokens as f64 / 1_000_000.0) * p.cache_write_per_m
        + (cache_read_tokens as f64 / 1_000_000.0) * p.cache_read_per_m
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn pricing_known_models() {
        assert_eq!(pricing_for("claude-opus-4-8"), OPUS);
        assert_eq!(pricing_for("claude-fable-5"), FABLE);
        assert_eq!(pricing_for("claude-sonnet-4-6"), SONNET);
        assert_eq!(pricing_for("claude-haiku-4-5"), HAIKU);
        assert_eq!(pricing_for("claude-opus-4-1"), OPUS_LEGACY, "4.1 legacy 단가");
        assert_eq!(pricing_for("claude-opus-4-0"), OPUS_LEGACY, "4.0 → claude-opus-4 prefix");
        // gpt-5-4-mini가 gpt-5-4보다 먼저 매칭돼야(more-specific)
        assert_eq!(pricing_for("gpt-5-4-mini"), GPT54MINI);
        assert_eq!(pricing_for("gpt-5-4"), GPT54);
    }

    #[test]
    fn normalize_strips_1m_and_date() {
        assert_eq!(pricing_for("claude-opus-4-8[1m]"), OPUS, "[1m] 접미 제거");
        assert_eq!(pricing_for("claude-opus-4-8-20251101"), OPUS, "-YYYYMMDD 제거");
        assert_eq!(pricing_for("Claude-Opus-4-8"), OPUS, "대소문자 무관");
        assert_eq!(pricing_for("claude.sonnet.4.6"), SONNET, "./_→-");
    }

    #[test]
    fn unknown_model_falls_back_to_sonnet() {
        assert_eq!(pricing_for("some-unknown-model"), DEFAULT_PRICING);
        assert_eq!(pricing_for(""), DEFAULT_PRICING);
    }

    #[test]
    fn cost_formula() {
        // opus 1M input + 1M output = 5 + 25 = 30
        assert!((calculate_cost(1_000_000, 1_000_000, 0, 0, "claude-opus-4-8") - 30.0).abs() < 1e-9);
        // + 1M cache_write(6.25) + 1M cache_read(0.50) = 36.75
        assert!((calculate_cost(1_000_000, 1_000_000, 1_000_000, 1_000_000, "claude-opus-4-8") - 36.75).abs() < 1e-9);
        // haiku 1M output = 5
        assert!((calculate_cost(0, 1_000_000, 0, 0, "claude-haiku-4-5") - 5.0).abs() < 1e-9);
        // 0 토큰 = $0
        assert_eq!(calculate_cost(0, 0, 0, 0, "claude-opus-4-8"), 0.0);
    }
}
