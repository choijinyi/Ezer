// ime.ts 리듀서 프로필별 기록 시퀀스 테스트 (bun test — 신규 의존성 0).
//
// 각 프로필은 실기기 WebKit이 발화한 DOM 이벤트 순서다. 리듀서를 그 순서로 돌려
// PTY로 나가는 바이트(sends)와 잔여 조합 상태(pending)를 검증한다.
import { describe, it, expect } from "bun:test";
import { imeStep, initialImeState, isHangulText, type ImeEvent, type ImeState } from "./ime";

/** 이벤트 시퀀스를 리듀서에 흘려 전송 바이트·debug·최종 state를 수집한다. */
function run(events: ImeEvent[], start: ImeState = initialImeState()) {
  let state = start;
  const sends: string[] = [];
  const debugs: string[] = [];
  for (const ev of events) {
    const r = imeStep(state, ev);
    state = r.state;
    for (const a of r.actions) {
      if ("send" in a) sends.push(a.send);
      else debugs.push(a.debug);
    }
  }
  return { state, sends, debugs, bytes: sends.join("") };
}

const input = (inputType: string, data: string | null): ImeEvent => ({ kind: "input", inputType, data });
const keydown = (keyCode: number, key: string): ImeEvent => ({ kind: "keydown", keyCode, key });
const onData = (data: string): ImeEvent => ({ kind: "onData", data });
// Profile D 유출용: xterm(Terminal._inputEvent)가 insertText 자모를 triggerDataEvent로 흘려보낸
// 중복 onData. main.ts 배선이 'insertText(한글) 디스패치 중 동기 발화'를 감지해 duplicate로 표시한다.
const onDataDup = (data: string): ImeEvent => ({ kind: "onData", data, duplicate: true });

describe("Profile C — 혼성(신규 버그): insertText 자모 커밋 후 표준 composition 진행", () => {
  it("insertText 'ㄴ' → compositionstart → onData '너' ⇒ 정확히 '너'만 전송(자모 유출 없음)", () => {
    const r = run([
      input("insertText", "ㄴ"), // 조합 첫 자모를 커밋 → pending "ㄴ"
      { kind: "compositionstart" }, // 이후 조합은 표준 composition으로 진행 → pending은 흡수됨
      onData("너"), // xterm이 완성 음절 1회 발화
    ]);
    expect(r.bytes).toBe("너"); // 수정 전에는 "ㄴ너" (자모 유출)
    expect(r.state.pending).toBe("");
    expect(r.debugs).toContain('DROP(composition-supersede) "ㄴ"');
  });

  it("어절 연쇄: 'ㄴ'+compositionstart+onData '너' 다음 음절 '는'은 유출 없음", () => {
    const r = run([
      input("insertText", "ㄴ"),
      { kind: "compositionstart" },
      onData("너"),
      { kind: "compositionstart" },
      onData("는"),
    ]);
    expect(r.bytes).toBe("너는");
  });

  it("composition inputType(insertCompositionText) 관측 시에도 pending drop", () => {
    const r = run([input("insertCompositionText", "너")], { pending: "ㄴ" });
    expect(r.state.pending).toBe("");
    expect(r.sends).toEqual([]); // 흡수된 자모는 폐기(전송 금지)
    expect(r.debugs).toContain('DROP(composition-supersede) "ㄴ"');
  });
});

describe("Profile B — 구형: 음절 단위 insertText → insertReplacementText 재조합 → keydown flush", () => {
  it("insertText '너' → insertReplacementText '넌' → keydown(Space) ⇒ '넌'", () => {
    const r = run([
      input("insertText", "너"), // pending "너"
      input("insertReplacementText", "넌"), // 조합 갱신 (pending → "넌")
      keydown(32, " "), // 비229 → flush
    ]);
    expect(r.bytes).toBe("넌");
    expect(r.state.pending).toBe("");
  });
});

describe("Profile A — 표준: composition 이벤트 + onData만", () => {
  it("compositionstart/update/end → onData '한' ⇒ onData 그대로 1회 전송, pending 무관여", () => {
    const r = run([
      { kind: "compositionstart" },
      { kind: "compositionupdate" },
      { kind: "compositionend" },
      onData("한"),
    ]);
    expect(r.sends).toEqual(["한"]);
    expect(r.bytes).toBe("한");
    expect(r.state.pending).toBe("");
  });
});

describe("병합 커밋 — 고속 입력 2음절 한 insertText", () => {
  it("insertText '안녕' ⇒ '안' 즉시 전송 + pending '녕', 이후 blur flush로 '녕'", () => {
    const r = run([
      input("insertText", "안녕"), // 앞 음절 "안" 즉시, 마지막 "녕" pending
      { kind: "blur" }, // 확정 flush
    ]);
    expect(r.sends).toEqual(["안", "녕"]);
    expect(r.bytes).toBe("안녕");
  });

  it("insertText '안녕' 직후 pending은 '녕'(flush 전)", () => {
    const r = run([input("insertText", "안녕")]);
    expect(r.state.pending).toBe("녕");
    expect(r.sends).toEqual(["안"]);
  });
});

describe("repl-sync — pending 없이 이미 전송된 음절 교정", () => {
  it("insertReplacementText '한' (pending 비어있음) ⇒ '\\x7f한' 전송", () => {
    const r = run([input("insertReplacementText", "한")]);
    expect(r.bytes).toBe("\x7f한");
    expect(r.sends).toEqual(["\x7f한"]);
  });
});

describe("deleteContentBackward — pending 감소", () => {
  it("멀티 pending '간다' → deleteContentBackward ⇒ '간'", () => {
    const r = run([input("deleteContentBackward", null)], { pending: "간다" });
    expect(r.state.pending).toBe("간");
  });
});

describe("keydown/blur flush · 229 무전송 · onData 순서 보존", () => {
  it("Enter(비229) keydown ⇒ pending flush", () => {
    const r = run([keydown(13, "Enter")], { pending: "안" });
    expect(r.bytes).toBe("안");
    expect(r.state.pending).toBe("");
  });

  it("keyCode 229 keydown ⇒ flush 안 함(조합 유지)", () => {
    const r = run([keydown(229, "Process")], { pending: "안" });
    expect(r.sends).toEqual([]);
    expect(r.state.pending).toBe("안");
  });

  it("blur ⇒ pending flush", () => {
    const r = run([{ kind: "blur" }], { pending: "안" });
    expect(r.bytes).toBe("안");
    expect(r.state.pending).toBe("");
  });

  it("onData 시 잔여 pending 먼저 전송 후 data (순서 보존)", () => {
    const r = run([onData("녕")], { pending: "안" });
    expect(r.sends).toEqual(["안", "녕"]); // pending 먼저, 그다음 data
    expect(r.bytes).toBe("안녕");
  });
});

describe("구멍① — keydown keyCode≠229 프로필(자모 유출 방어)", () => {
  it("insertText 'ㄴ' → keydown(74,'ㅓ')(비229 글자 키) → compositionstart → onData '너' ⇒ '너'(유출 없음)", () => {
    const r = run([
      input("insertText", "ㄴ"), // pending "ㄴ"
      keydown(74, "ㅓ"), // 비229 글자 키 — 허용목록 前엔 여기서 "ㄴ" flush(유출)
      { kind: "compositionstart" }, // 조합이 pending 자모 흡수 → drop
      onData("너"),
    ]);
    expect(r.bytes).toBe("너"); // 허용목록 前엔 "ㄴ너"
    expect(r.state.pending).toBe("");
  });

  it("229 인터리빙: insertText 'ㄴ' → keydown(229,'Process') → compositionstart → onData '너' ⇒ '너'", () => {
    const r = run([
      input("insertText", "ㄴ"),
      keydown(229, "Process"),
      { kind: "compositionstart" },
      onData("너"),
    ]);
    expect(r.bytes).toBe("너");
    expect(r.state.pending).toBe("");
  });

  it("허용목록 flush 유지: pending 'ㅋ' + keydown(32,' ') ⇒ 'ㅋ' flush(단독 자모+Space 무손상)", () => {
    const r = run([keydown(32, " ")], { pending: "ㅋ" });
    expect(r.bytes).toBe("ㅋ");
    expect(r.state.pending).toBe("");
  });

  it("keydown 계측: keydown(229,'Process')가 debug 라인을 남긴다", () => {
    const r = run([keydown(229, "Process")]);
    expect(r.debugs).toContain('keydown key="Process" code=229');
  });
});

describe("Profile D — ezer-neo(신규 실기기 버그): xterm _inputEvent insertText 자모 유출(이중 전송)", () => {
  // 근본 원인: macOS 26.5.1 WKWebView에서 음절은 insertText(첫 자모 커밋) → insertReplacementText
  // (조합 진행)로 pending에 버퍼되는데(표준 composition 이벤트 없음), xterm의 Terminal._inputEvent가
  // inputType==='insertText'인 그 첫 자모를 triggerDataEvent로 onData에 그대로 흘려보낸다.
  // → 완성 음절은 리듀서 input 경로가(pending flush) 보내고, 첫 자모는 onData가 또 보내 이중 전송.
  // 관측된 실기기 트레이스($TMPDIR/ezer-ime.log)의 각 FLUSH(onData)는 '다음 음절의 유출 onData'가
  // 직전 음절 pending을 flush한 것이다(유출 onData는 현재 음절 자모를 나르며 직전 pending을 확정).
  //
  // event.data 확정 근거:
  //  (a) xterm 소스 browser/Terminal.ts:1176 _inputEvent — inputType==='insertText' && data &&
  //      (!ev.composed || !_keyDownSeen)일 때 triggerDataEvent(ev.data). insertReplacementText는
  //      inputType이 달라 유출 안 됨 → '음절 첫 자모'만 유출(= 화면상 선행 자모).
  //  (b) 화면 실측 "ㅎ한ㄷ들ㅇ이 깨지진ㄷ다" — 음절마다 선행 자모(첫 insertText 커밋)가 덧붙음.
  //  ★깨 예외: 쌍자음 ㄲ은 Shift(keyCode 16)를 누른 채 입력 → insertText 직전 Shift keydown이
  //   _keyDownSeen=true로 만들어 xterm 가드 (!ev.composed || !_keyDownSeen)를 false로 뒤집어
  //   그 음절만 유출이 억제된다(트레이스에서 깨 앞에만 keydown Shift가 있고 유출 onData가 없음).
  const trace: ImeEvent[] = [
    // 한 (첫 음절 — flush할 직전 pending 없음)
    onDataDup("ㅎ"), input("insertText", "ㅎ"), keydown(229, "ㅎ"),
    input("insertReplacementText", "하"), keydown(229, "ㅏ"),
    input("insertReplacementText", "한"), keydown(229, "ㄴ"),
    input("insertReplacementText", "한"),
    // 들 (유출 onData "ㄷ"가 직전 "한"을 flush)
    onDataDup("ㄷ"), input("insertText", "ㄷ"), keydown(229, "ㄷ"),
    input("insertReplacementText", "드"), keydown(229, "ㅡ"),
    input("insertReplacementText", "들"), keydown(229, "ㄹ"),
    input("insertReplacementText", "들"),
    // 이 (유출 onData "ㅇ"가 "들"을 flush → 이는 Space keydown이 flush)
    onDataDup("ㅇ"), input("insertText", "ㅇ"), keydown(229, "ㅇ"),
    input("insertReplacementText", "이"), keydown(229, "ㅣ"),
    input("insertReplacementText", "이"),
    keydown(32, " "),          // 비229 Space → FLUSH(keydown) "이"
    onData(" "),               // Space 문자(비유출) → " " 전송
    input("insertText", " "),  // 한글 아님 → no-op
    // 깨 (Shift 유지 쌍자음 → 유출 onData 없음)
    keydown(16, "Shift"),
    input("insertText", "ㄲ"), keydown(229, "ㄲ"),
    input("insertReplacementText", "깨"), keydown(229, "ㅐ"),
    input("insertReplacementText", "꺳"), keydown(229, "ㅈ"),
    input("insertReplacementText", "깨"),
    // 진 (유출 onData "지"가 "깨"를 flush)
    onDataDup("지"), input("insertText", "지"), keydown(229, "ㅣ"),
    input("insertReplacementText", "진"), keydown(229, "ㄴ"),
    input("insertReplacementText", "진"),
    // 다 (유출 onData "ㄷ"가 "진"을 flush)
    onDataDup("ㄷ"), input("insertText", "ㄷ"), keydown(229, "ㄷ"),
    input("insertReplacementText", "다"), keydown(229, "ㅏ"),
    input("insertReplacementText", "다"),
    onData(" "),               // 끝 Space onData가 "다"를 flush(FLUSH(onData) "다") + " " 전송
    keydown(32, " "),          // pending 비어 flush no-op
    input("insertText", " "),  // no-op
  ];

  it("실기기 트레이스: 이중 전송 없이 정확히 '한들이 깨진다 '만 전송(선행 자모 유출 0)", () => {
    const r = run(trace);
    // 수정 전에는 "ㅎ한ㄷ들ㅇ이 깨지진ㄷ다 "(음절마다 선행 자모 유출, 깨만 정상).
    expect(r.bytes).toBe("한들이 깨진다 ");
    expect(r.state.pending).toBe("");
  });

  it("duplicate onData는 잔여 pending을 순서 보존 flush하고 유출 data는 폐기", () => {
    const r = run([onDataDup("ㄷ")], { pending: "한" });
    expect(r.sends).toEqual(["한"]);      // 직전 음절 "한"은 보존, 유출 "ㄷ"는 폐기
    expect(r.bytes).toBe("한");
    expect(r.state.pending).toBe("");
    expect(r.debugs).toContain('DROP(insertText-leak) "ㄷ"');
  });

  it("비-duplicate onData는 기존대로 pending flush 후 data 전송(회귀 방지 — Profile A/#순서보존)", () => {
    const r = run([onData("녕")], { pending: "안" });
    expect(r.sends).toEqual(["안", "녕"]);
  });
});

describe("isHangulText — 자모·완성형만 참", () => {
  it("자모/완성형 참, 그 외 거짓", () => {
    expect(isHangulText("ㄴ")).toBe(true);
    expect(isHangulText("너")).toBe(true);
    expect(isHangulText("안녕")).toBe(true);
    expect(isHangulText("a")).toBe(false);
    expect(isHangulText("1")).toBe(false);
    expect(isHangulText("")).toBe(false);
  });
});
