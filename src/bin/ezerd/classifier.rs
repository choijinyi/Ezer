//! Agent hook event classifier — (source, event, tool) → (wire_name, is_actionable).
//! cmux CLI/FeedEventClassifier.swift의 Rust 포팅. raw 이벤트명 매칭이 아니라 타입화 의미
//! 레지스트리로 분류해 "tool-start를 approval로 오인"하는 버그(cmux #4985)를 구조적으로 막는다.
//! ★이 분류기는 에이전트를 막지 않는다 — actionable 신호만 부여한다(승인 블로킹은 pack 정책).

/// 사용자-주의 의미. 알림·블로킹은 이 의미로만 결정 — raw 이벤트명 문자열 매칭 금지.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
enum FeedEventSemantic {
    ApprovalRequest,        // 실제 승인 대기 (actionable)
    ToolStart,              // 전용 승인 이벤트 보유 에이전트의 pre-tool (telemetry)
    ToolStartMaybeApproval, // 전용 승인 이벤트 없는 pre-tool → side-effecting만 escalate
    ToolEnd,
    PromptSubmit,
    Response,
    SubagentResponse,
    SessionStart,
    SessionEnd,
    StatusNotification,
    Unknown, // 안전 기본 = telemetry, never actionable
}

/// 공개 진입점 — usage.event 핸들러가 호출.
/// 반환: (wire hook_event_name, is_actionable).
pub fn classify(source: &str, event: &str, tool_name: &str) -> (String, bool) {
    let semantic = feed_event_semantic(source, event);
    wire_mapping(semantic, source, tool_name)
}

/// (source, event) → 의미. 등록 source는 자기 테이블, 미등록은 generic 테이블.
fn feed_event_semantic(source: &str, event: &str) -> FeedEventSemantic {
    match registered_semantic(source, event) {
        Some(s) => s,
        None => generic_semantic(event),
    }
}

/// 등록 source(claude·codex)의 (event)→의미. 미등록 source면 None(→ generic).
/// ★cmux 동치: 등록 source의 미등록 event는 .unknown(generic 폴백 아님).
fn registered_semantic(source: &str, event: &str) -> Option<FeedEventSemantic> {
    use FeedEventSemantic::*;
    match source {
        "claude" => Some(match event {
            "PermissionRequest" => ApprovalRequest,
            "PreToolUse" => ToolStart,
            "PostToolUse" => ToolEnd,
            // ★E-a 필수: CLI가 hook_event_name을 PRE_TOOL/POST_TOOL/STOP/SUBAGENT_STOP로 변환해
            //   데몬에 보낸다(ezer.rs hook_to_event_params). E-a는 raw_hook_event 미동봉이라 데몬이
            //   받는 값은 변환명뿐 → 이 키를 병기하지 않으면 모든 이벤트가 Unknown으로 떨어진다.
            //   E-b(raw_hook_event 동봉) 후엔 PreToolUse/PostToolUse 키가 실효 — 둘 다 두면 양 단계 안전.
            "PRE_TOOL" => ToolStart,
            "POST_TOOL" => ToolEnd,
            "UserPromptSubmit" => PromptSubmit,
            "SessionStart" => SessionStart,
            "SessionEnd" => SessionEnd,
            "Stop" | "STOP" => Response,
            "SubagentStop" | "SUBAGENT_STOP" => SubagentResponse,
            "Notification" => StatusNotification,
            _ => Unknown, // 등록 source의 미등록 event = unknown
        }),
        "codex" => Some(match event {
            // ★의도적: Codex의 PermissionRequest는 telemetry — 블로킹하면 'Approve for me'
            //   auto-review를 막는다(cmux line 172-174).
            "PermissionRequest" => ToolStart,
            "PreToolUse" => ToolStart,
            "PRE_TOOL" => ToolStart, // ★E-a: CLI 변환명 병기(claude 동일 사유)
            "beforeShellExecution" => ToolStart,
            "PostToolUse" => ToolEnd,
            "POST_TOOL" => ToolEnd, // ★E-a: CLI 변환명 병기
            "UserPromptSubmit" => PromptSubmit,
            "SessionStart" => SessionStart,
            "SessionEnd" => SessionEnd,
            "Stop" | "STOP" => Response,
            "SubagentStop" | "SUBAGENT_STOP" => SubagentResponse,
            "Notification" => StatusNotification,
            _ => Unknown,
        }),
        _ => None, // 미등록 source(gemini/agy 등) → generic
    }
}

/// 미등록 source의 (event)→의미. pre-tool이 유일 신호라 toolStartMaybeApproval.
fn generic_semantic(event: &str) -> FeedEventSemantic {
    use FeedEventSemantic::*;
    match event {
        "PreToolUse" => ToolStartMaybeApproval,
        "beforeShellExecution" => ToolStartMaybeApproval,
        "PermissionRequest" => ApprovalRequest,
        "PostToolUse" => ToolEnd,
        "UserPromptSubmit" => PromptSubmit,
        "SessionStart" => SessionStart,
        "SessionEnd" => SessionEnd,
        "Stop" => Response,
        "SubagentStop" => SubagentResponse,
        "Notification" => StatusNotification,
        _ => Unknown,
    }
}

/// 의미 → (wire명, actionable). tool 의존 의미만 tool_name 사용.
fn wire_mapping(semantic: FeedEventSemantic, source: &str, tool_name: &str) -> (String, bool) {
    use FeedEventSemantic::*;
    match semantic {
        ApprovalRequest => {
            dedicated_approval_event(tool_name).unwrap_or_else(|| ("PermissionRequest".into(), true))
        }
        ToolStartMaybeApproval => {
            if let Some(d) = dedicated_approval_event(tool_name) {
                d
            } else if is_side_effecting_tool(tool_name, source) {
                ("PermissionRequest".into(), true)
            } else {
                ("PreToolUse".into(), false)
            }
        }
        ToolStart => ("PreToolUse".into(), false),
        ToolEnd => ("PostToolUse".into(), false),
        PromptSubmit => ("UserPromptSubmit".into(), false),
        Response => ("Stop".into(), false),
        SubagentResponse => ("SubagentStop".into(), false),
        SessionStart => ("SessionStart".into(), false),
        SessionEnd => ("SessionEnd".into(), false),
        StatusNotification => ("Notification".into(), false),
        Unknown => ("PreToolUse".into(), false), // 안전 기본
    }
}

/// 전용 승인 wire 이벤트를 가진 툴 → 그 매핑, 아니면 None.
fn dedicated_approval_event(tool_name: &str) -> Option<(String, bool)> {
    match tool_name {
        "ExitPlanMode" => Some(("ExitPlanMode".into(), true)),
        "AskUserQuestion" => Some(("AskUserQuestion".into(), true)),
        _ => None,
    }
}

/// 상태를 변경해 승인 프롬프트를 받아야 하는 툴 — cmux sideEffectingTools 19개 1:1 포팅.
/// read-only(Read/Grep/Glob/Task/WebFetch/WebSearch/LS/TodoWrite)는 의도적 제외.
fn is_side_effecting_tool(tool_name: &str, _source: &str) -> bool {
    if tool_name.is_empty() {
        return false;
    }
    matches!(
        tool_name,
        "Bash"
            | "Write"
            | "Edit"
            | "MultiEdit"
            | "NotebookEdit"
            | "apply_patch"
            | "shell"
            | "terminal"
            | "run_command"
            | "write_to_file"
            | "replace_file_content"
            | "multi_replace_file_content"
            | "manage_task"
            | "schedule"
            | "ask_permission"
            | "invoke_subagent"
            | "define_subagent"
            | "manage_subagents"
            | "generate_image"
    )
    // kiro 소문자 alias는 ezer 미사용 → 미포팅(미래 kiro 도입 시 source=="kiro" 분기 추가).
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn claude_pretool_is_non_actionable() {
        assert_eq!(
            classify("claude", "PreToolUse", "Bash"),
            ("PreToolUse".into(), false)
        );
    }

    /// ★E-a 경로: 데몬이 실제로 받는 값은 CLI 변환명(PRE_TOOL/POST_TOOL). 병기 키가 없으면
    /// Unknown으로 떨어져 분류가 무력화된다(reviewer §4 치명 교정 핀).
    #[test]
    fn claude_cli_converted_names_are_classified() {
        assert_eq!(
            classify("claude", "PRE_TOOL", "Bash"),
            ("PreToolUse".into(), false)
        );
        assert_eq!(
            classify("claude", "POST_TOOL", "Bash"),
            ("PostToolUse".into(), false)
        );
        assert_eq!(
            classify("claude", "STOP", ""),
            ("Stop".into(), false)
        );
        assert_eq!(
            classify("claude", "SUBAGENT_STOP", ""),
            ("SubagentStop".into(), false)
        );
    }

    #[test]
    fn codex_cli_converted_names_are_classified() {
        assert_eq!(
            classify("codex", "PRE_TOOL", "shell"),
            ("PreToolUse".into(), false)
        );
        assert_eq!(
            classify("codex", "POST_TOOL", "shell"),
            ("PostToolUse".into(), false)
        );
    }

    /// 미등록 source(gemini/agy)의 side-effecting pre-tool → approval escalate.
    #[test]
    fn generic_side_effecting_escalates() {
        assert_eq!(
            classify("gemini", "PreToolUse", "Bash"),
            ("PermissionRequest".into(), true)
        );
        assert_eq!(
            classify("gemini", "PreToolUse", "run_command"),
            ("PermissionRequest".into(), true)
        );
    }

    #[test]
    fn generic_read_only_stays_telemetry() {
        assert_eq!(
            classify("gemini", "PreToolUse", "Read"),
            ("PreToolUse".into(), false)
        );
    }

    /// ★#4985: codex PermissionRequest는 의도적 telemetry(블로킹하면 'Approve for me' 차단).
    #[test]
    fn codex_permission_is_non_actionable() {
        assert_eq!(
            classify("codex", "PermissionRequest", "Bash"),
            ("PreToolUse".into(), false)
        );
    }

    #[test]
    fn claude_permission_is_actionable() {
        assert_eq!(
            classify("claude", "PermissionRequest", "Bash"),
            ("PermissionRequest".into(), true)
        );
    }

    #[test]
    fn dedicated_exit_plan_mode_and_ask_user_question() {
        assert_eq!(
            classify("claude", "PermissionRequest", "ExitPlanMode"),
            ("ExitPlanMode".into(), true)
        );
        assert_eq!(
            classify("claude", "PermissionRequest", "AskUserQuestion"),
            ("AskUserQuestion".into(), true)
        );
    }

    #[test]
    fn unknown_event_is_safe_default() {
        assert_eq!(
            classify("claude", "FutureEvent", "X"),
            ("PreToolUse".into(), false)
        );
    }

    /// cmux sideEffectingTools 19개 exact match 박제 — read-only는 제외 확인.
    #[test]
    fn all_19_side_effecting_tools_match() {
        let side = [
            "Bash",
            "Write",
            "Edit",
            "MultiEdit",
            "NotebookEdit",
            "apply_patch",
            "shell",
            "terminal",
            "run_command",
            "write_to_file",
            "replace_file_content",
            "multi_replace_file_content",
            "manage_task",
            "schedule",
            "ask_permission",
            "invoke_subagent",
            "define_subagent",
            "manage_subagents",
            "generate_image",
        ];
        assert_eq!(side.len(), 19);
        for t in side {
            assert!(is_side_effecting_tool(t, "claude"), "{t} should be side-effecting");
        }
        for t in ["Read", "Grep", "Glob", "Task", "WebFetch", "WebSearch", "LS", "TodoWrite", ""] {
            assert!(!is_side_effecting_tool(t, "claude"), "{t} must not be side-effecting");
        }
    }
}
