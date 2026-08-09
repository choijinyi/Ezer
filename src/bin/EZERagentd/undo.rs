//! T2-5 — 상한(cap) undo 스택 + 양방향 빈-변경 가드 + 독립 20s 트랜잭션 강제커밋.
//!
//! ADDITIVE leaf primitive: EZERagent는 editor-primitives §1에서 snapshot-and-replace를 *명시 채택*했고
//! (diff-and-patch 거부), 본 모듈은 그 위에 스택 거버넌스 절반(상한·커서·가드·타임아웃)만 얹는다.
//! 실제 change-record 직렬화 포맷은 편집기 도메인 소유 — 본 leaf는 `C` 제네릭으로 불투명(snapshot-
//! replace 모델 불변, diff-and-patch 재도입 아님).
//!
//! penpot undo.cljs(MPL-2.0)의 *개념·산술·불변식*만 클린룸 차용 — ClojureScript 코드복사 0:
//!   - :58-74  undo-entry 스키마(양방향 undo/redo·selected·timestamp·by 작성자)
//!   - :79-86  MAX-UNDO-SIZE + subvec front 축출(ring-buffer 아님 — growable vec)
//!   - :121-123 빈 변경 가드(undo·redo 둘 다 non-empty일 때만 push)
//!   - :124-127 분기 절단(점프 인덱스 뒤 take 후 conj)
//!   - :130-131 커서 clamp `(min (inc index) (dec MAX))` → front 축출 시 커서 re-base
//!   - :261-274 20s discard-transaction 강제커밋(watchdog과 무관한 독립 시계)
//!
//! 분리 가드: socket/pty/governance/pack/recall 무의존 leaf. 트랜잭션 강제커밋 타임아웃은
//! governance.rs watchdog 정책시간과 인과적으로 무관한 독립 시계다(category error 회피).

/// 정수 틱 격자 — check_timeline.py:49 `TICKS_PER_SECOND = 120_000`(OpenCut/OpenMontage 선행연구)
/// 재사용. raw timestamp 대신 이 격자로 시간표현 중복을 피한다. 코어 `time` 모듈 신설 시 이동.
#[allow(dead_code)]
const TICKS_PER_SECOND: i64 = 120_000;

/// undo 엔트리(양방향) — 모든 필드 `#[serde(default)]`로 additive-safe 박제.
/// `C` = 편집기 도메인이 채우는 불투명 change-record(본 leaf는 형식 미관여).
#[allow(dead_code)]
#[derive(serde::Serialize, serde::Deserialize, Clone, Default, Debug, PartialEq)]
pub struct UndoEntry<C> {
    #[serde(default)]
    pub undo: Vec<C>,
    #[serde(default)]
    pub redo: Vec<C>,
    #[serde(default)]
    pub group: String,
    #[serde(default)]
    pub selected_before: Vec<u64>,
    #[serde(default)]
    pub selected_after: Vec<u64>,
    #[serde(default)]
    pub tick: i64, // TICKS_PER_SECOND=120_000 격자
    #[serde(default)]
    pub by_surface: Option<u64>, // 작성자 태그 ONLY(멀티에이전트 undo coherence 주장 아님)
}

/// 상한 undo 스택 — growable Vec + 커서 index + cap. front 축출 시 커서 re-base.
#[allow(dead_code)]
pub struct UndoStack<C> {
    items: Vec<UndoEntry<C>>,
    index: i64, // 현재 위치(-1 = undo할 것 없음)
    cap: usize,
}

#[allow(dead_code)]
impl<C> UndoStack<C> {
    pub fn new(cap: usize) -> Self {
        UndoStack { items: Vec::new(), index: -1, cap: cap.max(1) }
    }

    pub fn len(&self) -> usize {
        self.items.len()
    }

    pub fn is_empty(&self) -> bool {
        self.items.is_empty()
    }

    pub fn can_undo(&self) -> bool {
        self.index >= 0
    }

    pub fn can_redo(&self) -> bool {
        (self.index + 1) < self.items.len() as i64
    }

    /// penpot undo.cljs:121-127·:79-86·:130-131 클린룸:
    ///   (1) 빈 변경 가드 → (2) 분기 절단 → (3) 적재 → (4) 상한 축출 + 커서 re-base.
    pub fn push(&mut self, e: UndoEntry<C>) {
        // (1) 빈 변경 가드 — 양쪽 non-empty일 때만(:121-123). 좀비 엔트리 누적 차단.
        if e.undo.is_empty() || e.redo.is_empty() {
            return;
        }
        // (2) 분기 절단 — 점프(materialize) 뒤 redo 가지 제거(:124-127 take (inc index)).
        let keep = (self.index + 1).max(0) as usize;
        let keep = keep.min(self.items.len());
        self.items.truncate(keep);
        // (3) 적재.
        self.items.push(e);
        self.index = self.items.len() as i64 - 1;
        // (4) 상한 축출 + 커서 RE-BASE — penpot subvec(:79-86) + clamp(:130-131) 의미론.
        if self.items.len() > self.cap {
            let drop = self.items.len() - self.cap;
            self.items.drain(0..drop);
            self.index -= drop as i64; // ★re-base: 축출분만큼 커서 당김
            if self.index < -1 {
                self.index = -1; // clamp >= -1
            }
        }
    }

    /// 현재 index 엔트리 반환 후 커서 한 칸 뒤로(:undo).
    pub fn undo(&mut self) -> Option<&UndoEntry<C>> {
        if self.index < 0 {
            return None;
        }
        let i = self.index as usize;
        self.index -= 1;
        Some(&self.items[i])
    }

    /// 커서 한 칸 앞으로 이동 후 그 엔트리 반환(:redo).
    pub fn redo(&mut self) -> Option<&UndoEntry<C>> {
        if !self.can_redo() {
            return None;
        }
        self.index += 1;
        Some(&self.items[self.index as usize])
    }

    /// index 점프(materialize) — 커서만 이동(스냅샷 적용은 호출부). penpot :89-97.
    pub fn materialize(&mut self, index: i64) {
        let clamped = index.clamp(-1, self.items.len() as i64 - 1);
        self.index = clamped;
    }
}

/// 열린 편집 트랜잭션 — 독립 20s 강제커밋 타임아웃(watchdog과 무관한 별도 시계).
/// 빠른 마이크로 편집을 한 undo 단위로 coalesce(OpenCut preview-commit 동형). penpot :261-274.
#[allow(dead_code)]
pub struct Transaction {
    opened_tick: i64,
    commit_timeout_ticks: i64, // 기본 20s * 120_000
}

#[allow(dead_code)]
impl Transaction {
    /// 기본 20s 타임아웃으로 트랜잭션 열기.
    pub fn open(now_tick: i64) -> Self {
        Transaction { opened_tick: now_tick, commit_timeout_ticks: 20 * TICKS_PER_SECOND }
    }

    /// 튜너블 타임아웃(초)로 열기 — watchdog 정책시간과 *독립*(바인딩 금지).
    pub fn open_with_secs(now_tick: i64, timeout_secs: i64) -> Self {
        Transaction {
            opened_tick: now_tick,
            commit_timeout_ticks: timeout_secs * TICKS_PER_SECOND,
        }
    }

    /// 주입된 clock(now_tick)으로 강제커밋 시점 판정 — 실제 sleep 0(결정론).
    pub fn force_commit_due(&self, now_tick: i64) -> bool {
        now_tick - self.opened_tick >= self.commit_timeout_ticks
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn entry(k: i32) -> UndoEntry<i32> {
        UndoEntry { undo: vec![k], redo: vec![k], ..Default::default() }
    }

    // ① cap 초과 시 front 축출 + 커서 re-base 후 undo가 올바른 엔트리를 가리킴(회귀 핵심).
    #[test]
    fn overflow_then_undo_points_to_correct_entry() {
        let mut s = UndoStack::<i32>::new(3);
        for k in 0..5 {
            s.push(entry(k));
        } // 0,1 축출 → items=[2,3,4], index=2
        assert_eq!(s.len(), 3, "cap이 성장 제한");
        assert_eq!(s.undo().map(|e| e.undo[0]), Some(4));
        assert_eq!(s.undo().map(|e| e.undo[0]), Some(3));
        assert_eq!(s.undo().map(|e| e.undo[0]), Some(2));
        assert!(s.undo().is_none(), "index == -1");
    }

    // ② 빈 변경 가드: undo·redo 중 한쪽이라도 비면 push no-op.
    #[test]
    fn empty_bidirectional_guard_is_noop() {
        let mut s = UndoStack::<i32>::new(8);
        s.push(UndoEntry { undo: vec![1], redo: vec![], ..Default::default() }); // redo 빔
        assert!(!s.can_undo());
        s.push(UndoEntry { undo: vec![], redo: vec![1], ..Default::default() }); // undo 빔
        assert!(!s.can_undo());
        assert_eq!(s.len(), 0, "둘 다 적재 거부");
    }

    // ③ undo→redo→undo 라운드트립 동일 엔트리.
    #[test]
    fn undo_redo_roundtrip_same_entry() {
        let mut s = UndoStack::<i32>::new(8);
        for k in 0..3 {
            s.push(entry(k));
        }
        assert_eq!(s.undo().map(|e| e.undo[0]), Some(2));
        assert_eq!(s.redo().map(|e| e.redo[0]), Some(2));
        assert_eq!(s.undo().map(|e| e.undo[0]), Some(2));
    }

    // ④ materialize 점프 후 push가 점프 지점 뒤를 절단(truncate-on-branch).
    #[test]
    fn jump_then_push_truncates_redo_branch() {
        let mut s = UndoStack::<i32>::new(8);
        for k in 0..4 {
            s.push(entry(k));
        } // index=3
        s.materialize(1); // index=1 (엔트리 0,1까지)
        s.push(entry(99)); // index 1 뒤(2,3) 절단 후 적재 → items=[0,1,99]
        assert_eq!(s.len(), 3);
        assert!(!s.can_redo(), "절단으로 redo 가지 제거");
        assert_eq!(s.undo().map(|e| e.undo[0]), Some(99));
    }

    // ⑤ 트랜잭션 강제커밋: 타임아웃 경과 시 true, 미경과 시 false(주입 clock — 실제 sleep 0).
    #[test]
    fn force_commit_due_uses_injected_clock() {
        let t = Transaction::open(0);
        assert!(!t.force_commit_due(19 * TICKS_PER_SECOND), "19s — 미경과");
        assert!(t.force_commit_due(20 * TICKS_PER_SECOND), "20s — 강제커밋");
        // 튜너블 타임아웃도 독립 동작.
        let t2 = Transaction::open_with_secs(100, 5);
        assert!(!t2.force_commit_due(100 + 4 * TICKS_PER_SECOND));
        assert!(t2.force_commit_due(100 + 5 * TICKS_PER_SECOND));
    }

    // serde 라운드트립 — additive-safe #[serde(default)] 박제.
    #[test]
    fn undo_entry_serde_roundtrip() {
        let e: UndoEntry<i32> = UndoEntry {
            undo: vec![1, 2],
            redo: vec![3],
            group: "g1".into(),
            selected_before: vec![7],
            selected_after: vec![8, 9],
            tick: 123,
            by_surface: Some(5),
        };
        let j = serde_json::to_string(&e).unwrap();
        let back: UndoEntry<i32> = serde_json::from_str(&j).unwrap();
        assert_eq!(e, back);
        // 누락 필드 default 채움(additive-safe).
        let partial: UndoEntry<i32> = serde_json::from_str("{\"undo\":[1],\"redo\":[2]}").unwrap();
        assert_eq!(partial.tick, 0);
        assert_eq!(partial.by_surface, None);
    }
}
