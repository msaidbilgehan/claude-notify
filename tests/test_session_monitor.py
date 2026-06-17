"""Behaviour tests for transcript attention analysis."""

from claude_notify.session_monitor import ClaudeSessionMonitor


def analyze(lines: list[str]) -> dict:
    return ClaudeSessionMonitor()._analyze_transcript_state(lines)


def test_empty_transcript_needs_no_attention():
    assert analyze([])["needs_attention"] is False


def test_waiting_phrase_needs_attention():
    state = analyze(["Sure, I can help.", "Would you like me to continue with that?"])
    assert state["needs_attention"] is True


def test_trailing_question_needs_attention():
    state = analyze(["Here is the plan.", "Which option do you prefer?"])
    assert state["needs_attention"] is True
    assert state["pattern"] == "question"


def test_error_phrase_needs_attention():
    state = analyze(["Running the build...", "error: the target failed to compile"])
    assert state["needs_attention"] is True


def test_benign_completion_needs_no_attention():
    state = analyze(["All set.", "I have written the files and we are done."])
    assert state["needs_attention"] is False
