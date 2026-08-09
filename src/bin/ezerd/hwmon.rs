// Control Center 하드웨어 모니터링(control.hw) — CPU 코어별·GPU·NPU·메모리 스냅샷.
// CPU·MEM은 sysinfo(전 플랫폼). GPU·NPU는 macOS Apple Silicon 전용 —
// GPU는 IOAccelerator PerformanceStatistics(ioreg), NPU 코어수는 칩명 판정.
// 미지원 플랫폼·측정 불가 항목은 null 반환(UI가 "—" 표기).

use serde_json::{json, Value};
use std::sync::{Mutex, OnceLock};

// 지속 System — cpu_usage는 직전 refresh와의 델타로 측정된다. 콜마다 System::new+200ms
// 블로킹 sleep을 쓰던 구 패턴은 tokio 워커를 상시 점유했다(전수조사 A-5/B-14 교정).
// 폴링(2~5초) 간격 자체가 측정 창이 되므로 sleep이 불필요하다(부트 후 첫 콜만 0%).
static SYS: OnceLock<Mutex<sysinfo::System>> = OnceLock::new();

fn sys() -> &'static Mutex<sysinfo::System> {
    SYS.get_or_init(|| Mutex::new(sysinfo::System::new()))
}

/// 전체 CPU%·메모리 (control.dashboard 시스템 표시용 — snapshot과 같은 지속 System 공유)
pub fn cpu_mem() -> (f32, u64, u64) {
    let mut s = sys().lock().unwrap();
    s.refresh_memory();
    s.refresh_cpu_usage();
    (s.global_cpu_usage(), s.used_memory(), s.total_memory())
}

pub fn snapshot() -> Value {
    let (per_core, brand, total_pct, mem_used, mem_total) = {
        let mut s = sys().lock().unwrap();
        s.refresh_memory();
        s.refresh_cpu_usage();
        (
            s.cpus().iter().map(|c| c.cpu_usage()).collect::<Vec<f32>>(),
            s.cpus().first().map(|c| c.brand().trim().to_string()).unwrap_or_default(),
            s.global_cpu_usage(),
            s.used_memory(),
            s.total_memory(),
        )
    };
    let (perf, eff) = perf_eff_cores();
    json!({
        "cpu": {
            "cores": per_core.len(),
            "perf_cores": perf,
            "eff_cores": eff,
            "brand": brand,
            "total_pct": total_pct,
            "per_core_pct": per_core,
        },
        "mem": { "total": mem_total, "used": mem_used },
        "gpu": { "cores": gpu_cores(), "pct": gpu_pct() },
        // NPU 활용률(%)은 macOS 공개 API 부재(powermetrics=sudo 전용) — 무권한 실측 가능한
        // 유일 신호인 ANE 전력(W)을 제공하고 pct는 null 고정(환각 지표 생성 금지).
        "npu": { "cores": npu_cores(&brand), "pct": null, "watts": npu_watts() },
    })
}

// ─── macOS (Apple Silicon) ───

#[cfg(target_os = "macos")]
fn sysctl_u32(name: &str) -> Option<u32> {
    let out = std::process::Command::new("sysctl").args(["-n", name]).output().ok()?;
    if !out.status.success() {
        return None;
    }
    String::from_utf8_lossy(&out.stdout).trim().parse().ok()
}

// P/E 코어 분해 — Apple Silicon 전용 sysctl(Intel 맥은 미존재 → None)
#[cfg(target_os = "macos")]
fn perf_eff_cores() -> (Option<u32>, Option<u32>) {
    (sysctl_u32("hw.perflevel0.logicalcpu"), sysctl_u32("hw.perflevel1.logicalcpu"))
}

// GPU 코어 수 — AGXAccelerator(Apple GPU)의 gpu-core-count. 불변이라 1회 조회 후 캐시.
#[cfg(target_os = "macos")]
fn gpu_cores() -> Option<u32> {
    static CACHE: std::sync::OnceLock<Option<u32>> = std::sync::OnceLock::new();
    *CACHE.get_or_init(gpu_cores_probe)
}

#[cfg(target_os = "macos")]
fn gpu_cores_probe() -> Option<u32> {
    let out = std::process::Command::new("ioreg")
        .args(["-rc", "AGXAccelerator", "-d", "1"])
        .output()
        .ok()?;
    let s = String::from_utf8_lossy(&out.stdout);
    let line = s.lines().find(|l| l.contains("\"gpu-core-count\""))?;
    line.rsplit('=').next()?.trim().parse().ok()
}

// GPU 활용률 — IOAccelerator PerformanceStatistics의 "Device Utilization %"(무권한 실측)
#[cfg(target_os = "macos")]
fn gpu_pct() -> Option<f64> {
    let out = std::process::Command::new("ioreg")
        .args(["-r", "-d", "1", "-w0", "-c", "IOAccelerator"])
        .output()
        .ok()?;
    let s = String::from_utf8_lossy(&out.stdout);
    let key = "\"Device Utilization %\"=";
    let i = s.find(key)? + key.len();
    let digits: String = s[i..].chars().take_while(|c| c.is_ascii_digit()).collect();
    digits.parse().ok()
}

// Neural Engine 코어 수 — OS 미노출이라 칩명 판정(M시리즈 전 세대 16, Ultra만 2다이=32)
#[cfg(target_os = "macos")]
fn npu_cores(brand: &str) -> Option<u32> {
    if !brand.starts_with("Apple M") {
        return None;
    }
    Some(if brand.contains("Ultra") { 32 } else { 16 })
}

// NPU(ANE) 전력 — 연속 호출 간 IOReport 에너지 델타(J)/경과시간(s)=W. 첫 호출은 None.
#[cfg(target_os = "macos")]
fn npu_watts() -> Option<f64> {
    ane::power_watts()
}

// ─── ANE 전력 실측 — IOReport private dylib (macmon(MIT) 검증 기법의 클린룸 최소 포트) ───
// "Energy Model" 그룹의 ANE* 채널(Basic="ANE"·Max="ANE0"·Ultra="ANE0_{n}") 누적 에너지를
// 구독해 두 스냅샷 델타로 전력을 산출한다. 채널이 없거나(인텔 맥·일부 VM) 호출이 실패하면
// None(UI "—") — 관측 전용 fail-open이며 데몬 동작에 영향을 주지 않는다.
#[cfg(target_os = "macos")]
mod ane {
    use std::os::raw::{c_char, c_void};
    use std::ptr::null;
    use std::sync::{Mutex, OnceLock};
    use std::time::Instant;

    type CFTypeRef = *const c_void;
    type CFDictionaryRef = CFTypeRef;
    type CFMutableDictionaryRef = CFTypeRef;
    type CFStringRef = CFTypeRef;
    type CFArrayRef = CFTypeRef;
    type CFIndex = isize;
    const K_UTF8: u32 = 0x0800_0100; // kCFStringEncodingUTF8

    #[link(name = "CoreFoundation", kind = "framework")]
    extern "C" {
        fn CFRelease(cf: CFTypeRef);
        fn CFDictionaryGetValue(d: CFDictionaryRef, key: CFTypeRef) -> CFTypeRef;
        fn CFDictionaryCreateMutableCopy(alloc: CFTypeRef, cap: CFIndex, d: CFDictionaryRef) -> CFMutableDictionaryRef;
        fn CFArrayGetCount(a: CFArrayRef) -> CFIndex;
        fn CFArrayGetValueAtIndex(a: CFArrayRef, i: CFIndex) -> CFTypeRef;
        fn CFStringCreateWithCString(alloc: CFTypeRef, s: *const c_char, enc: u32) -> CFStringRef;
        fn CFStringGetCString(s: CFStringRef, buf: *mut c_char, size: CFIndex, enc: u32) -> bool;
    }

    #[link(name = "IOReport", kind = "dylib")]
    extern "C" {
        fn IOReportCopyAllChannels(a: u64, b: u64) -> CFDictionaryRef;
        fn IOReportCreateSubscription(a: *const c_void, b: CFMutableDictionaryRef, c: *mut CFMutableDictionaryRef, d: u64, e: CFTypeRef) -> CFTypeRef;
        fn IOReportCreateSamples(a: CFTypeRef, b: CFMutableDictionaryRef, c: CFTypeRef) -> CFDictionaryRef;
        fn IOReportCreateSamplesDelta(a: CFDictionaryRef, b: CFDictionaryRef, c: CFTypeRef) -> CFDictionaryRef;
        fn IOReportChannelGetGroup(a: CFDictionaryRef) -> CFStringRef;
        fn IOReportChannelGetChannelName(a: CFDictionaryRef) -> CFStringRef;
        fn IOReportChannelGetUnitLabel(a: CFDictionaryRef) -> CFStringRef;
        fn IOReportSimpleGetIntegerValue(a: CFDictionaryRef, b: i32) -> i64;
    }

    struct Sampler {
        subs: CFTypeRef,
        chans: CFMutableDictionaryRef,
        prev: Option<(CFDictionaryRef, Instant)>,
    }
    // raw 포인터는 CF 불변 규약(구독·채널 dict는 생성 후 읽기 전용) + Mutex 직렬화로 안전
    unsafe impl Send for Sampler {}

    static SAMPLER: OnceLock<Option<Mutex<Sampler>>> = OnceLock::new();

    pub fn power_watts() -> Option<f64> {
        let m = SAMPLER.get_or_init(|| unsafe { init() }).as_ref()?;
        let mut s = m.lock().ok()?;
        unsafe {
            let cur = IOReportCreateSamples(s.subs, s.chans, null());
            if cur.is_null() {
                return None;
            }
            let out = match s.prev.take() {
                Some((prev, t0)) => {
                    let dt = t0.elapsed().as_secs_f64();
                    let delta = IOReportCreateSamplesDelta(prev, cur, null());
                    CFRelease(prev);
                    let w = if delta.is_null() { None } else { ane_watts(delta, dt) };
                    if !delta.is_null() {
                        CFRelease(delta);
                    }
                    w
                }
                None => None, // 첫 호출 — 기준 스냅샷만 확보
            };
            s.prev = Some((cur, Instant::now()));
            out
        }
    }

    unsafe fn init() -> Option<Mutex<Sampler>> {
        let all = IOReportCopyAllChannels(0, 0);
        if all.is_null() {
            return None;
        }
        // ANE 에너지 채널이 있는 기기만 활성화(인텔 맥·일부 VM 제외)
        let has_ane = channels(all).any(|it| is_ane_energy(it));
        if !has_ane {
            CFRelease(all);
            return None;
        }
        let chans = CFDictionaryCreateMutableCopy(null(), 0, all);
        CFRelease(all);
        if chans.is_null() {
            return None;
        }
        let mut sub_out: CFMutableDictionaryRef = null();
        let subs = IOReportCreateSubscription(null(), chans, &mut sub_out, 0, null());
        if subs.is_null() {
            CFRelease(chans);
            return None;
        }
        Some(Mutex::new(Sampler { subs, chans, prev: None }))
    }

    // 델타 dict의 ANE 채널 에너지(J) 합산 → /dt = W
    unsafe fn ane_watts(delta: CFDictionaryRef, dt: f64) -> Option<f64> {
        if dt <= 0.0 {
            return None;
        }
        let mut joules = 0.0;
        let mut seen = false;
        for it in channels(delta) {
            if !is_ane_energy(it) {
                continue;
            }
            let scale = match cf_str(IOReportChannelGetUnitLabel(it)).trim() {
                "mJ" => 1e3,
                "uJ" => 1e6,
                "nJ" => 1e9,
                _ => continue,
            };
            joules += IOReportSimpleGetIntegerValue(it, 0) as f64 / scale;
            seen = true;
        }
        if seen {
            Some(joules / dt)
        } else {
            None
        }
    }

    unsafe fn is_ane_energy(item: CFDictionaryRef) -> bool {
        cf_str(IOReportChannelGetGroup(item)) == "Energy Model"
            && cf_str(IOReportChannelGetChannelName(item)).starts_with("ANE")
    }

    unsafe fn channels(dict: CFDictionaryRef) -> impl Iterator<Item = CFDictionaryRef> {
        let ck = std::ffi::CString::new("IOReportChannels").unwrap();
        let key = CFStringCreateWithCString(null(), ck.as_ptr(), K_UTF8);
        let arr: CFArrayRef = if key.is_null() { null() } else { CFDictionaryGetValue(dict, key) };
        if !key.is_null() {
            CFRelease(key);
        }
        let n = if arr.is_null() { 0 } else { CFArrayGetCount(arr) };
        (0..n).map(move |i| CFArrayGetValueAtIndex(arr, i)).filter(|it| !it.is_null())
    }

    unsafe fn cf_str(s: CFStringRef) -> String {
        if s.is_null() {
            return String::new();
        }
        let mut buf = [0 as c_char; 128];
        if CFStringGetCString(s, buf.as_mut_ptr(), buf.len() as CFIndex, K_UTF8) {
            std::ffi::CStr::from_ptr(buf.as_ptr()).to_string_lossy().into_owned()
        } else {
            String::new()
        }
    }
}

// ─── 타 플랫폼 스텁 (Windows GPU/NPU 카운터는 후속 트랙) ───

#[cfg(not(target_os = "macos"))]
fn perf_eff_cores() -> (Option<u32>, Option<u32>) {
    (None, None)
}

#[cfg(not(target_os = "macos"))]
fn gpu_cores() -> Option<u32> {
    None
}

#[cfg(not(target_os = "macos"))]
fn gpu_pct() -> Option<f64> {
    None
}

#[cfg(not(target_os = "macos"))]
fn npu_cores(_brand: &str) -> Option<u32> {
    None
}

#[cfg(not(target_os = "macos"))]
fn npu_watts() -> Option<f64> {
    None
}

#[cfg(test)]
mod tests {
    #[test]
    fn snapshot_has_all_sections() {
        let v = super::snapshot();
        assert!(v["cpu"]["cores"].as_u64().unwrap() > 0);
        assert_eq!(v["cpu"]["per_core_pct"].as_array().unwrap().len(), v["cpu"]["cores"].as_u64().unwrap() as usize);
        assert!(v["mem"]["total"].as_u64().unwrap() > 0);
        // Apple Silicon 실기에서는 GPU 코어수·활용률이 실측된다
        #[cfg(target_os = "macos")]
        {
            assert!(v["gpu"]["cores"].as_u64().unwrap_or(0) > 0);
            assert!(v["gpu"]["pct"].as_f64().is_some());
            assert!(v["npu"]["cores"].as_u64().unwrap_or(0) > 0);
        }
    }

    // ANE 전력은 연속 호출 델타라 2번째 스냅샷부터 값이 나온다.
    // CI VM은 IOReport ANE 채널이 없을 수 있어 강제 검증은 EZER_HW_STRICT=1(로컬 실기)로만.
    #[cfg(target_os = "macos")]
    #[test]
    fn ane_power_second_sample() {
        let _ = super::snapshot();
        std::thread::sleep(std::time::Duration::from_millis(400));
        let v = super::snapshot();
        if std::env::var("EZER_HW_STRICT").is_ok() {
            let w = v["npu"]["watts"].as_f64();
            assert!(w.is_some(), "Apple Silicon 실기에서 ANE watts 기대: {v}");
            assert!(w.unwrap() >= 0.0);
        }
    }
}
