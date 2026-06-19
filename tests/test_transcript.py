"""Behaviour tests for transcript summarisation."""

from datetime import timedelta

from claude_notify.transcript import (
    MAX_RESPONSE_PREVIEW_CHARS,
    format_preview,
    summarize_transcript,
)


def _write(tmp_path, lines: list[str]) -> str:
    path = tmp_path / "session.jsonl"
    path.write_text("\n".join(lines), encoding="utf-8")
    return str(path)


# Genuine prompt at 10:00:05, a tool round-trip, final reply at 10:02:35.
_LINES = [
    '{"type":"user","isMeta":true,"cwd":"/work/proj",'
    '"timestamp":"2026-06-19T10:00:00.000Z",'
    '"message":{"role":"user","content":"<caveat/>"}}',
    '{"type":"user","cwd":"/work/proj","timestamp":"2026-06-19T10:00:05.000Z",'
    '"message":{"role":"user","content":[{"type":"text","text":"Do the thing"}]}}',
    '{"type":"user","cwd":"/work/proj","timestamp":"2026-06-19T10:00:12.000Z",'
    '"toolUseResult":{"ok":true},'
    '"message":{"role":"user","content":[{"type":"tool_result"}]}}',
    '{"type":"assistant","cwd":"/work/proj","timestamp":"2026-06-19T10:02:35.000Z",'
    '"message":{"role":"assistant",'
    '"content":[{"type":"thinking","thinking":"hm"},'
    '{"type":"text","text":"All done. The answer is 42."}]}}',
    '{"type":"ai-title","aiTitle":"Do the thing","sessionId":"x"}',
]


def test_extracts_cwd_last_response_and_title(tmp_path):
    summary = summarize_transcript(_write(tmp_path, _LINES))

    assert summary.cwd == "/work/proj"
    assert summary.last_response == "All done. The answer is 42."
    assert summary.title == "Do the thing"
    assert summary.awaiting_user is True  # assistant spoke last


def test_duration_spans_prompt_to_final_reply(tmp_path):
    summary = summarize_transcript(_write(tmp_path, _LINES))

    # 10:00:05 genuine prompt -> 10:02:35 reply; the tool result at 10:00:12 and
    # the isMeta entry are not turn boundaries and must be ignored.
    assert summary.duration == timedelta(minutes=2, seconds=30)


def test_last_title_wins_when_updated(tmp_path):
    lines = _LINES + ['{"type":"ai-title","aiTitle":"Renamed session"}']
    summary = summarize_transcript(_write(tmp_path, lines))
    assert summary.title == "Renamed session"


def test_missing_file_returns_empty_summary_without_raising():
    summary = summarize_transcript("/no/such/transcript.jsonl")

    assert summary.cwd is None
    assert summary.last_response is None
    assert summary.duration is None
    assert summary.title is None


def test_malformed_and_blank_lines_are_skipped(tmp_path):
    lines = [
        "",
        "not json at all{",
        '{"type":"assistant","timestamp":"2026-06-19T10:00:10.000Z",'
        '"message":{"role":"assistant","content":[{"type":"text","text":"hi"}]}}',
        "[1, 2, 3]",  # valid JSON, but not an object
    ]
    summary = summarize_transcript(_write(tmp_path, lines))
    assert summary.last_response == "hi"


def test_parser_returns_full_untruncated_response(tmp_path):
    long_text = ("word " * 200).strip()  # ~999 chars, well over the preview cap
    line = (
        '{"type":"assistant","timestamp":"2026-06-19T10:00:10.000Z",'
        '"message":{"role":"assistant","content":[{"type":"text","text":"'
        + long_text
        + '"}]}}'
    )
    summary = summarize_transcript(_write(tmp_path, [line]))

    # Truncation is a display concern; the parser keeps the full text so callers
    # can analyse it (e.g. detect a trailing question).
    assert summary.last_response == long_text


def test_format_preview_collapses_whitespace_and_truncates():
    preview = format_preview("line one\n\n  line   two " + "x" * 500)
    assert len(preview) <= MAX_RESPONSE_PREVIEW_CHARS
    assert preview.endswith("…")
    assert "\n" not in preview


def test_format_preview_collapses_short_text_without_ellipsis():
    assert format_preview("hello   world\nthere") == "hello world there"


def test_awaiting_user_false_when_tool_result_is_last(tmp_path):
    lines = [
        '{"type":"assistant","cwd":"/work/proj",'
        '"timestamp":"2026-06-19T10:00:10.000Z",'
        '"message":{"role":"assistant","content":[{"type":"tool_use","name":"Bash"}]}}',
        '{"type":"user","cwd":"/work/proj","timestamp":"2026-06-19T10:00:12.000Z",'
        '"toolUseResult":{"ok":true},'
        '"message":{"role":"user","content":[{"type":"tool_result"}]}}',
    ]
    summary = summarize_transcript(_write(tmp_path, lines))
    assert summary.awaiting_user is False  # Claude is mid-turn


def test_duration_none_when_no_user_prompt(tmp_path):
    line = (
        '{"type":"assistant","timestamp":"2026-06-19T10:00:10.000Z",'
        '"message":{"role":"assistant","content":[{"type":"text","text":"hi"}]}}'
    )
    summary = summarize_transcript(_write(tmp_path, [line]))
    assert summary.duration is None


def test_response_with_only_tool_use_has_no_text(tmp_path):
    line = (
        '{"type":"assistant","cwd":"/work/proj",'
        '"timestamp":"2026-06-19T10:00:10.000Z",'
        '"message":{"role":"assistant","content":[{"type":"tool_use","name":"Bash"}]}}'
    )
    summary = summarize_transcript(_write(tmp_path, [line]))
    assert summary.last_response is None
    assert summary.cwd == "/work/proj"
