// WKWebView 한글 IME 조합 판단 로직 — 순수 리듀서.
//
// main.ts의 DOM 이벤트 핸들러(input·keydown·blur·composition·onData)는 이 리듀서에
// 배선만 하고, PTY로 보낼 바이트(send)와 계측(debug)은 전부 actions로만 나온다.
// 순수 함수라 프로필별 이벤트 시퀀스를 결정론으로 재현·회귀 테스트할 수 있다.
//
// 배경(main.ts 원 주석 요약): WKWebView는 표준 composition 이벤트 없이 ①음절 첫 자모를
// insertText로 커밋(xterm이 즉시 전송 = 자모 유출) ②조합 진행을 insertReplacementText로
// value 치환(xterm 미인지 = 완성 글자 유실)한다. 이 리듀서가 자모 유출을 pending에
// 붙들었다가 음절 확정 시 완성 글자만 보낸다.

export interface ImeState {
  /** 조합 중이라 아직 확정 전송하지 않은 한글 음절(들). 보통 1글자, 병합/치환 시 다중. */
  pending: string;
}

export type ImeEvent =
  | { kind: "input"; inputType: string; data: string | null }
  | { kind: "keydown"; keyCode: number; key: string }
  | { kind: "compositionstart" }
  | { kind: "compositionupdate" }
  | { kind: "compositionend" }
  | { kind: "onData"; data: string; duplicate?: boolean }
  | { kind: "blur" };

/** send=PTY로 보낼 바이트, debug=EZERagentImeDebug 채널 로그(평시 미출력). */
export type ImeAction = { send: string } | { debug: string };

export interface ImeResult {
  state: ImeState;
  actions: ImeAction[];
}

export const initialImeState = (): ImeState => ({ pending: "" });

// 자모(31xx·11xx) + 완성형 음절(AC00-D7A3) — 멀티문자 허용: 고속 입력에서 IME가 여러 음절을
// 한 insertText로 병합 커밋하므로 단일 문자만 인정하면 그 묶음이 통째로 유실된다.
const HANGUL_TEXT = /^[ㄱ-ㆎᄀ-ᇿ가-힣]+$/;
export const isHangulText = (t: string) => HANGUL_TEXT.test(t);

// keydown flush 허용목록: 조합 확정이 필요한 제어·공백 키만. 글자 키는 flush 금지 —
// 일부 WebKit 프로필이 조합 참여 글쇠를 keyCode≠229로 발화해 자모 pending이 유출되던 구멍 봉인.
// 글자 키의 pending은 후속 input/composition/onData 이벤트가 해소한다(바이트·순서 불변).
const KEYDOWN_FLUSH_KEYS = new Set([
  "Enter", " ", "Tab", "Backspace", "Delete", "Escape",
  "ArrowLeft", "ArrowRight", "ArrowUp", "ArrowDown",
  "Home", "End", "PageUp", "PageDown",
]);

export function imeStep(state: ImeState, event: ImeEvent): ImeResult {
  const actions: ImeAction[] = [];
  let pending = state.pending;

  const flush = (why: string) => {
    if (pending) {
      actions.push({ debug: `FLUSH(${why}) "${pending}"` });
      actions.push({ send: pending });
      pending = "";
    }
  };
  // 프로필 불변 규칙: 조합 이벤트가 관측되는 순간, pending 자모는 정의상 그 조합에 흡수된
  // 것이므로 폐기(drop)한다 — flush 금지. 어떤 WebKit 프로필에서도 조합 이벤트 후 pending
  // 자모 전송이 옳은 경우는 없다(혼성 프로필 C의 자모 유출 근본 차단).
  const dropSuperseded = () => {
    if (pending) {
      actions.push({ debug: `DROP(composition-supersede) "${pending}"` });
      pending = "";
    }
  };

  switch (event.kind) {
    case "input": {
      const { inputType, data } = event;
      actions.push({ debug: `input ${inputType} data="${data ?? "∅"}" pending="${pending}"` });
      if (inputType === "insertCompositionText" || inputType === "insertFromComposition") {
        // 표준 composition inputType 관측 → 조합이 pending 자모를 흡수했다 → drop.
        dropSuperseded();
      } else if (inputType === "insertText" && data && isHangulText(data)) {
        // 직전 조합 확정 후 새 커밋을 '수정 가능 창'(pending)에 둔다. 병합 커밋(2음절+)은
        // 마지막 음절만 수정 창에 — 앞 음절들은 확정분이므로 즉시 전송.
        flush("insertText");
        if (data.length > 1) {
          actions.push({ debug: `SEND(multi-head) "${data.slice(0, -1)}"` });
          actions.push({ send: data.slice(0, -1) });
        }
        pending = data.slice(-1);
      } else if (inputType === "insertReplacementText" && data) {
        if (pending) {
          pending = data; // 조합 갱신 (하→한)
        } else {
          // 이미 전송된 직전 음절의 교정 — PTY 동기화: 백스페이스+재전송
          actions.push({ debug: `SEND(repl-sync) DEL+"${data}"` });
          actions.push({ send: "\x7f" + data });
        }
      } else if (inputType === "deleteContentBackward" && pending) {
        // 멀티 pending(병합 커밋 잔여)이면 마지막 글자만 — IME 부분 재조합 대응
        pending = pending.slice(0, -1);
        actions.push({ debug: `del-backward pending="${pending}"` });
      }
      break;
    }
    case "keydown": {
      // 계측은 전 keydown(229 포함) — 제5 프로필 이벤트 시퀀스 진단 채널.
      actions.push({ debug: `keydown key="${event.key}" code=${event.keyCode}` });
      // 제어·공백 키(IME 처리중 229 제외) 직전에만 조합 확정 — 글자 키 flush는 자모 유출 구멍.
      if (event.keyCode !== 229 && KEYDOWN_FLUSH_KEYS.has(event.key)) {
        flush("keydown");
      }
      break;
    }
    case "compositionstart":
    case "compositionupdate": {
      // 조합 시작/진행 관측 → pending 자모는 이 조합에 흡수됨 → drop.
      actions.push({ debug: event.kind });
      dropSuperseded();
      break;
    }
    case "compositionend": {
      // 확정 완성 음절은 xterm의 onData로 별도 도착하므로 여기서 drop하지 않는다.
      actions.push({ debug: event.kind });
      break;
    }
    case "onData": {
      actions.push({ debug: `onData data="${event.data}"${event.duplicate ? " DUP" : ""} pending="${pending}"` });
      // 프로필 D(EZERagent-neo, macOS 26.5.1 WKWebView): xterm(Terminal._inputEvent)가 음절 첫 자모의
      // insertText 커밋을 triggerDataEvent로 onData에 유출한다. 같은 자모를 아래 input 경로가 이미
      // pending에 버퍼·확정하므로 이 onData의 data는 중복(선행 자모 유출)이다. main.ts 배선이
      // 'insertText(한글) 디스패치 중 동기 발화'를 감지해 duplicate로 표시한다 → 잔여 pending(직전
      // 음절 확정분)은 순서 보존해 flush하되 유출된 data는 폐기(전송 금지)한다.
      flush("onData");
      if (event.duplicate) {
        actions.push({ debug: `DROP(insertText-leak) "${event.data}"` });
        break;
      }
      // 비-중복(프로필 A 표준 composition·비-WKWebView Windows·순서보존 안전장치): 완성 음절을 그대로 PTY로.
      actions.push({ send: event.data });
      break;
    }
    case "blur": {
      flush("blur");
      break;
    }
  }

  return { state: { pending }, actions };
}
