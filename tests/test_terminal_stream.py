"""Tests for core/terminal.py terminal stream capture and ring buffer."""

import io
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sloppykeys.core.terminal import TerminalBuffer, TeeStream
from sloppykeys.core.win32.bindings import get_clipboard_text, set_clipboard_text


def test_terminal_buffer_append_and_get():
    buf = TerminalBuffer(maxlen=10)
    e1 = buf.append("Initial info line", stream="stdout")
    assert e1["id"] == 1
    assert e1["text"] == "Initial info line"
    assert e1["stream"] == "stdout"
    assert not e1["is_err"]

    e2 = buf.append("Traceback (most recent call last):", stream="stderr")
    assert e2["id"] == 2
    assert e2["is_err"]

    e3 = buf.append("Failed: could not load model", stream="stdout")
    assert e3["id"] == 3
    assert e3["is_err"]  # Keyword detection

    # RapidOCR [INFO] logging to stderr should NOT be marked as error and ANSI codes stripped
    e4 = buf.append("\x1b[32m[INFO] Using engine_name: onnxruntime\x1b[0m", stream="stderr")
    assert e4["id"] == 4
    assert e4["text"] == "[INFO] Using engine_name: onnxruntime"
    assert e4["stream"] == "info"
    assert not e4["is_err"]

    # Test get_lines
    res = buf.get_lines(after_id=0)
    assert res["ok"]
    assert len(res["lines"]) == 4
    assert res["latest_id"] == 4
    assert res["total"] == 4

    # Test delta get_lines
    delta = buf.get_lines(after_id=3)
    assert len(delta["lines"]) == 1
    assert delta["lines"][0]["id"] == 4


def test_terminal_buffer_bounding():
    buf = TerminalBuffer(maxlen=5)
    for i in range(10):
        buf.append(f"Line {i}")

    res = buf.get_lines(after_id=0)
    assert len(res["lines"]) == 5
    assert res["total"] == 5
    assert res["latest_id"] == 10
    assert res["lines"][0]["text"] == "Line 5"
    assert res["lines"][-1]["text"] == "Line 9"


def test_terminal_buffer_text_and_clear():
    buf = TerminalBuffer(maxlen=10)
    buf.append("Normal line", stream="stdout")
    buf.append("Error line", stream="stderr")

    all_text = buf.get_text(errors_only=False)
    assert "Normal line" in all_text
    assert "Error line" in all_text

    err_text = buf.get_text(errors_only=True)
    assert "Normal line" not in err_text
    assert "Error line" in err_text

    buf.clear()
    assert buf.get_lines(after_id=0)["total"] == 0


def test_tee_stream_line_buffering():
    mock_orig = io.StringIO()
    buf = TerminalBuffer(maxlen=10)
    tee = TeeStream(mock_orig, buf, "stdout")

    # Partial writes
    tee.write("Hello ")
    assert buf.get_lines()["total"] == 0

    tee.write("world!\n")
    lines = buf.get_lines()["lines"]
    assert len(lines) == 1
    assert lines[0]["text"] == "Hello world!"

    # Multiple lines in single write
    tee.write("Line A\nLine B\nLine C")
    lines = buf.get_lines()["lines"]
    assert len(lines) == 3
    assert lines[1]["text"] == "Line A"
    assert lines[2]["text"] == "Line B"

    # Trailing line on flush
    tee.flush()
    lines = buf.get_lines()["lines"]
    assert len(lines) == 4
    assert lines[3]["text"] == "Line C"

    # Passthrough to original stream
    assert mock_orig.getvalue() == "Hello world!\nLine A\nLine B\nLine C"


def test_win32_clipboard_copy():
    test_str = "SloppyKeys test clipboard string \u2713"
    assert set_clipboard_text(test_str)
    read_back = get_clipboard_text()
    assert read_back == test_str


if __name__ == "__main__":
    test_terminal_buffer_append_and_get()
    print("test_terminal_buffer_append_and_get ok")
    test_terminal_buffer_bounding()
    print("test_terminal_buffer_bounding ok")
    test_terminal_buffer_text_and_clear()
    print("test_terminal_buffer_text_and_clear ok")
    test_tee_stream_line_buffering()
    print("test_tee_stream_line_buffering ok")
    test_win32_clipboard_copy()
    print("test_win32_clipboard_copy ok")
    print("All terminal stream tests passed!")
