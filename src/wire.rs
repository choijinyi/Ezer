//! EZERagent↔EZERagentd 와이어 무결성 가드 (leaf — socket/pty/governance/pack 무의존).
//!
//! producer 자기검증: EZERagentd가 응답 `Value`를 NDJSON 줄로 직렬화할 때,
//! 같은 바이트를 즉시 재파싱한 `Value`가 선언과 `==`가 아니면 fail-loud(`Drift`).
//! 디코더 대칭검증: 응답에 additive하게 부착된 `_flen`(payload 바이트 길이) 선언과
//! 실제 재직렬화 길이가 동일버전에서 어긋나면 트렁케이션(`LenMismatch`)으로 거부.
//! `_pv` 마이너 스큐는 무차별 kill이 아니라 graceful downgrade(`VersionSkew`).
//!
//! ★additive sibling-injection(§4.1): `_flen`·`_pv`를 **기존 top-level 응답 객체에
//! 형제 키로 추가**한다. `ok`/`result`/`id`/`error`는 제자리 그대로 → 구 디코더
//! (`serde_json::from_str` + `resp["ok"]`, deny_unknown_fields 없음)는 추가 키를
//! 무시 → 호환 깨짐 0. `{"frame":…}` 래핑은 top-level을 가려 호환을 깨므로 금지.
//!
//! penpot 클린룸 근거(개념만·코드복사 0): mem.cljs `assert-written`의
//! `(= expected actual)` 불변식 + mem.rs write_vec의 "first 4 bytes = size" 길이선언
//! + changes.cljc `verify?=true` 기본-ON 정신. penpot 식별자·코드는 옮기지 않으며
//! NDJSON·serde_json 환경의 독립 구현이다.

use serde_json::Value;

/// 와이어 마이너 버전 단일진실.
pub const PROTO_PV: u16 = 1;

/// 응답 객체에 additive하게 부착되는 메타 키.
const KEY_FLEN: &str = "_flen";
const KEY_PV: &str = "_pv";

/// EZERagent↔EZERagentd 와이어 무결성 위반 분류. T1-3 `Severity`로 사상된다.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum AbiError {
    /// 인코드 round-trip 불일치: 직렬화→재파싱이 선언 `Value`와 다름 → Critical.
    Drift,
    /// 디코드 길이 불일치(동일버전): declared `_flen` != 실제 길이 → Critical(트렁케이션).
    LenMismatch,
    /// 디코드 불일치(버전 마이너 스큐): negotiated graceful downgrade(kill 아님).
    VersionSkew { peer_pv: u16, local_pv: u16 },
}

/// 인코드 자기검증 기본 ON. `EZERAGENT_ABI_VERIFY=0`로만 좁게 opt-out(debug-only 아님).
fn verify_on() -> bool {
    std::env::var("EZERAGENT_ABI_VERIFY").as_deref() != Ok("0")
}

/// 응답 payload(result 또는 error)의 canonical 직렬화 바이트 길이.
/// declared-len(`_flen`)의 선언값 — 둘 중 존재하는 쪽을 잰다(둘 다 없으면 0).
fn payload_len(resp: &Value) -> usize {
    let payload = resp.get("result").or_else(|| resp.get("error"));
    match payload {
        Some(v) => serde_json::to_string(v).map(|s| s.len()).unwrap_or(0),
        None => 0,
    }
}

/// producer 자기검증 프레이밍: 응답 `Value`를 declared-len 메타가 형제로 붙은 NDJSON 줄로.
///
/// (a) round-trip 동일성: 직렬화한 바이트를 즉시 재파싱해 선언 `Value`와 `==`가 아니면
///     `Err(Drift)`. `assert_eq!`/`debug_assert!`가 아니라 **명시 분기** — release에서도 발화.
/// (b) additive: 같은 top-level 객체에 `_flen`·`_pv`만 형제로 추가(중첩·래핑 없음).
pub fn frame_response(resp: &Value) -> Result<String, AbiError> {
    // (a) round-trip 자기검증 — 선언 == 실제 직렬화 결과.
    if verify_on() {
        let body = serde_json::to_string(resp).map_err(|_| AbiError::Drift)?;
        let reparsed: Value = serde_json::from_str(&body).map_err(|_| AbiError::Drift)?;
        if reparsed != *resp {
            return Err(AbiError::Drift); // → Severity::Critical
        }
    }
    // (b) additive sibling-injection — top-level은 보존, 메타만 형제로.
    let flen = payload_len(resp);
    let mut out = resp.clone();
    match out.as_object_mut() {
        Some(map) => {
            map.insert(KEY_FLEN.to_string(), Value::from(flen as u64));
            map.insert(KEY_PV.to_string(), Value::from(PROTO_PV as u64));
        }
        // 비-객체 응답은 메타를 달 자리가 없다 — 와이어 계약상 발생하지 않지만 fail-loud.
        None => return Err(AbiError::Drift),
    }
    let line = serde_json::to_string(&out).map_err(|_| AbiError::Drift)?;
    Ok(format!("{line}\n"))
}

/// T4-5A(==T5-6 strand-3 == ONE guard): 단일 RPC 응답 페이로드 바이트 상한.
/// **프로세스 수명·load = 기존 watchdog(governance.rs)** / **단일 RPC 응답 바이트 = 이 신규
/// 직교 가드** — ADR 경계: 두 책임은 별개이며 이 가드는 watchdog와 중복이 아니다(한 곳에만 둔다).
/// cap 수치는 로컬 실측 기본값이며 `EZERAGENT_MAX_RESPONSE_BYTES`로 조정(penpot 호스티드 MCP 15MB는
/// 검증 상수 아님 — 상속 금지). screen-buffer FIFO `truncated`(handlers.rs:860)와 무관한 별 표면.
pub const MAX_RESPONSE_BYTES: usize = 8 * 1024 * 1024;

/// 실측 가능한 cap 노브 — 기본 `MAX_RESPONSE_BYTES`, env로만 좁게 조정.
fn max_response_bytes() -> usize {
    std::env::var("EZERAGENT_MAX_RESPONSE_BYTES")
        .ok()
        .and_then(|v| v.parse().ok())
        .unwrap_or(MAX_RESPONSE_BYTES)
}

/// cap 초과 응답을 **fail-loud + 트렁케이트**한 sentinel 응답으로 치환한다.
/// 거대한 단일 응답이 클라이언트 컨텍스트·메모리를 폭주시키는 경로를 차단한다(스트림 폴백은
/// 호출자 결정 — 여기선 결정론 트렁케이트 sentinel을 돌려 항상 한 줄은 내보낸다).
///
/// 반환: cap 이내면 `None`(원본 그대로 진행), 초과면 `Some(sentinel)` — 원본 `id`는 보존하고
/// `result`를 `{response_truncated, original_bytes, cap_bytes}` fail-loud 페이로드로 교체.
pub fn cap_response(resp: &Value) -> Option<Value> {
    let cap = max_response_bytes();
    let bytes = serde_json::to_string(resp).map(|s| s.len()).unwrap_or(0);
    if bytes <= cap {
        return None;
    }
    let id = resp.get("id").cloned().unwrap_or(Value::Null);
    Some(serde_json::json!({
        "id": id,
        "ok": false,
        "error": {
            "code": "response_truncated",
            "message": format!(
                "RPC response {bytes} bytes exceeds cap {cap} — truncated (set EZERAGENT_MAX_RESPONSE_BYTES or use streaming)"
            ),
            "original_bytes": bytes,
            "cap_bytes": cap,
        }
    }))
}

/// 디코더 대칭검증: declared `_flen` == 실제 payload 직렬화 길이.
///
/// 반환은 **top-level 응답 객체 그대로**(additive 계약 — 구 디코더처럼 `resp["ok"]`/
/// `resp["result"]`를 그대로 읽을 수 있다). 메타가 없으면 legacy peer로 보고 무검증 수용.
/// 동일 `_pv` + 길이 불일치 = `LenMismatch`(Critical); 마이너 스큐 = `VersionSkew`(graceful).
pub fn parse_frame(raw: &str) -> Result<Value, AbiError> {
    let resp: Value = serde_json::from_str(raw.trim_end()).map_err(|_| AbiError::LenMismatch)?;

    // 메타 부재 = legacy peer(또는 검증 off로 보낸 프레임) → graceful 수용.
    let declared = resp.get(KEY_FLEN).and_then(|v| v.as_u64());
    let Some(declared) = declared else {
        return Ok(resp);
    };
    let peer_pv = resp.get(KEY_PV).and_then(|v| v.as_u64()).unwrap_or(0) as u16;

    let actual = payload_len(&resp) as u64;
    if declared != actual {
        // 동일버전이면 트렁케이션(Critical); 마이너 스큐면 graceful downgrade.
        return Err(if peer_pv == PROTO_PV {
            AbiError::LenMismatch
        } else {
            AbiError::VersionSkew {
                peer_pv,
                local_pv: PROTO_PV,
            }
        });
    }
    Ok(resp)
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    fn sample_reply() -> Value {
        json!({"id": 1, "ok": true, "result": {"surface": "surface:7", "rows": [1, 2, 3]}})
    }

    /// frame_response 출력이 여전히 top-level ok/result/id를 같은 자리에 둔다 —
    /// 구 형태 디코드가 성공하고, _flen/_pv는 형제(래퍼 아님)임을 박제.
    #[test]
    fn wire_roundtrip_is_additive() {
        let reply = sample_reply();
        let line = frame_response(&reply).expect("frame_response ok");
        assert!(line.ends_with('\n'));

        // 구 디코더 시점: 그냥 from_str 후 top-level 키를 읽는다.
        let decoded: Value = serde_json::from_str(line.trim_end()).unwrap();
        assert_eq!(decoded["ok"].as_bool(), Some(true));
        assert_eq!(decoded["id"], json!(1));
        assert_eq!(decoded["result"]["surface"], json!("surface:7"));

        // _flen/_pv는 top-level 형제 키 — "frame" 래퍼는 존재하지 않는다.
        assert!(decoded.get("_flen").is_some(), "_flen must be a sibling");
        assert!(decoded.get("_pv").is_some(), "_pv must be a sibling");
        assert!(decoded.get("frame").is_none(), "must NOT wrap under 'frame'");
        assert_eq!(decoded["_pv"].as_u64(), Some(PROTO_PV as u64));

        // parse_frame 왕복: top-level 객체 그대로 + 검증 통과(추가 키 제외 원본 필드 보존).
        let reparsed = parse_frame(&line).expect("parse_frame ok");
        assert_eq!(reparsed["ok"].as_bool(), Some(true));
        assert_eq!(reparsed["result"], reply["result"]);
    }

    /// round-trip 불가능(비-객체) 응답 주입 시 Drift.
    #[test]
    fn wire_drift_detected() {
        // 와이어 계약 위반: 응답이 객체가 아니면 메타를 달 자리가 없어 fail-loud.
        let not_an_object = json!([1, 2, 3]);
        assert_eq!(frame_response(&not_an_object), Err(AbiError::Drift));

        // round-trip 자기검증 분기 자체의 박제: 정상 객체는 통과(대조군).
        assert!(frame_response(&sample_reply()).is_ok());
    }

    /// _flen을 조작(트렁케이션 모사)하면 동일버전에서 LenMismatch.
    #[test]
    fn wire_len_mismatch() {
        let line = frame_response(&sample_reply()).unwrap();
        let mut tampered: Value = serde_json::from_str(line.trim_end()).unwrap();
        // declared len을 거짓으로 늘림 = 실제 payload보다 길게 선언(트렁케이션 신호).
        tampered["_flen"] = json!(99999);
        let raw = serde_json::to_string(&tampered).unwrap();
        assert_eq!(parse_frame(&raw), Err(AbiError::LenMismatch));
    }

    /// peer _pv가 local과 다르고 len도 불일치면 Critical이 아니라 VersionSkew(graceful).
    #[test]
    fn wire_version_skew_graceful() {
        let line = frame_response(&sample_reply()).unwrap();
        let mut skewed: Value = serde_json::from_str(line.trim_end()).unwrap();
        skewed["_pv"] = json!(PROTO_PV as u64 + 1); // 마이너 스큐
        skewed["_flen"] = json!(99999); // len도 불일치
        let raw = serde_json::to_string(&skewed).unwrap();
        match parse_frame(&raw) {
            Err(AbiError::VersionSkew { peer_pv, local_pv }) => {
                assert_eq!(peer_pv, PROTO_PV + 1);
                assert_eq!(local_pv, PROTO_PV);
            }
            other => panic!("expected VersionSkew (graceful), got {other:?}"),
        }
    }

    /// 메타가 전혀 없는 legacy peer 프레임은 무검증 graceful 수용.
    #[test]
    fn wire_legacy_peer_accepted() {
        let legacy = r#"{"id":1,"ok":true,"result":{"x":1}}"#;
        let v = parse_frame(legacy).expect("legacy frame accepted");
        assert_eq!(v["ok"].as_bool(), Some(true));
    }

    /// T4-5A: cap 이내 응답은 통과(None), cap 초과 응답은 fail-loud sentinel로 트렁케이트.
    /// env 노브로 cap을 작게 핀해 실측 sleep 없이 결정론 검증.
    #[test]
    fn wire_byte_cap_truncates_oversize() {
        // cap을 512바이트로 좁혀 핀(테스트 전용 — sentinel(고정 메시지)은 이 안에 들어가되
        // 거대 배열은 초과하도록). 직렬화는 lazy라 set 후 즉시 호출.
        std::env::set_var("EZERAGENT_MAX_RESPONSE_BYTES", "512");

        // cap 이내: 통과(None — 원본 그대로 진행).
        let small = json!({"id": 1, "ok": true, "result": {"x": 1}});
        assert!(
            cap_response(&small).is_none(),
            "cap 이내 응답은 트렁케이트하지 않는다"
        );

        // cap 초과: 거대 배열 → fail-loud sentinel(id 보존, error.code=response_truncated).
        let big_rows: Vec<u64> = (0..1000).collect();
        let big = json!({"id": 7, "ok": true, "result": {"rows": big_rows}});
        let sentinel = cap_response(&big).expect("oversize → sentinel");
        assert_eq!(sentinel["id"], json!(7), "원본 id 보존");
        assert_eq!(sentinel["ok"].as_bool(), Some(false), "fail-loud");
        assert_eq!(
            sentinel["error"]["code"].as_str(),
            Some("response_truncated")
        );
        // sentinel 자체는 cap 이내라 무한 재트렁케이트 루프가 없다(고정 크기 sentinel).
        assert!(
            cap_response(&sentinel).is_none(),
            "sentinel은 cap 이내 — 재트렁케이트 안 함"
        );

        std::env::remove_var("EZERAGENT_MAX_RESPONSE_BYTES");
    }
}
