"""Behaviour tests for session monitoring and attention analysis."""

from claude_notify.session_monitor import ClaudeSessionMonitor
from claude_notify.transcript import SessionSummary


def analyze(
    last_response: str, awaiting_user: bool = True
) -> dict:
    summary = SessionSummary(
        last_response=last_response, awaiting_user=awaiting_user
    )
    return ClaudeSessionMonitor._analyze(summary)


def test_no_response_needs_no_attention():
    summary = SessionSummary(awaiting_user=True, last_response=None)
    assert ClaudeSessionMonitor._analyze(summary)["needs_attention"] is False


def test_mid_turn_needs_no_attention():
    # Claude acted but a tool result followed, so it is not the user's move yet.
    state = analyze("Which option do you prefer?", awaiting_user=False)
    assert state["needs_attention"] is False


def test_waiting_phrase_needs_attention():
    state = analyze("Sure. Would you like me to continue with that?")
    assert state["needs_attention"] is True


def test_trailing_question_needs_attention():
    state = analyze("Here is the plan. Which option do you prefer?")
    assert state["needs_attention"] is True
    assert state["pattern"] == "question"


def test_error_phrase_needs_attention():
    state = analyze("I was unable to compile the target.")
    assert state["needs_attention"] is True
    assert state["pattern"] == "error"


def test_benign_completion_needs_no_attention():
    state = analyze("All set. I have written the files and we are done.")
    assert state["needs_attention"] is False


# --- discovery / check_sessions integration -------------------------------

_AWAITING_QUESTION = [
    '{"type":"user","cwd":"/work/widget","timestamp":"2026-06-19T10:00:00.000Z",'
    '"message":{"role":"user","content":[{"type":"text","text":"hi"}]}}',
    '{"type":"assistant","cwd":"/work/widget","timestamp":"2026-06-19T10:00:30.000Z",'
    '"message":{"role":"assistant",'
    '"content":[{"type":"text","text":"Which database should I use?"}]}}',
]


def _seed_transcript(tmp_path, name: str, lines: list[str]):
    project_dir = tmp_path / "projects" / "-work-widget"
    project_dir.mkdir(parents=True, exist_ok=True)
    transcript = project_dir / name
    transcript.write_text("\n".join(lines), encoding="utf-8")
    return transcript


def test_check_sessions_surfaces_awaiting_question(tmp_path, monkeypatch):
    transcript = _seed_transcript(tmp_path, "0a1b-session.jsonl", _AWAITING_QUESTION)
    monkeypatch.setattr(
        ClaudeSessionMonitor,
        "_find_project_roots",
        lambda self: [tmp_path / "projects"],
    )

    monitor = ClaudeSessionMonitor()
    results = monitor.check_sessions()

    assert len(results) == 1
    session = results[0]
    assert session["project"] == "widget"  # from cwd, not the encoded dir name
    assert session["project_path"] == "/work/widget"
    assert session["pattern"] == "question"
    assert session["transcript_path"] == str(transcript)


def test_check_sessions_notifies_once_until_changed(tmp_path, monkeypatch):
    _seed_transcript(tmp_path, "0a1b-session.jsonl", _AWAITING_QUESTION)
    monkeypatch.setattr(
        ClaudeSessionMonitor,
        "_find_project_roots",
        lambda self: [tmp_path / "projects"],
    )

    monitor = ClaudeSessionMonitor()
    assert len(monitor.check_sessions()) == 1
    # Unchanged file on the next poll yields nothing new.
    assert monitor.check_sessions() == []


def test_check_sessions_ignores_sessions_still_working(tmp_path, monkeypatch):
    working = _AWAITING_QUESTION + [
        '{"type":"user","cwd":"/work/widget","timestamp":"2026-06-19T10:00:35.000Z",'
        '"toolUseResult":{"ok":true},'
        '"message":{"role":"user","content":[{"type":"tool_result"}]}}',
    ]
    _seed_transcript(tmp_path, "0a1b-session.jsonl", working)
    monkeypatch.setattr(
        ClaudeSessionMonitor,
        "_find_project_roots",
        lambda self: [tmp_path / "projects"],
    )

    monitor = ClaudeSessionMonitor()
    # Last entry is a tool result -> Claude is mid-turn -> no attention.
    assert monitor.check_sessions() == []
