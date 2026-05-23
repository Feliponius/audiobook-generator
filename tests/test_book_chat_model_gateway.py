import subprocess

from book_chat.model_gateway import HermesGatewayResult, ask_via_hermes_codex


def test_ask_via_hermes_codex_builds_codex_command(monkeypatch):
    calls = []

    def fake_run(command, *, capture_output, text, timeout, cwd):
        calls.append(command)
        return subprocess.CompletedProcess(
            command,
            0,
            stdout="session_id: abc123\nPOC answer\n",
            stderr="",
        )

    monkeypatch.setattr(subprocess, "run", fake_run)

    result = ask_via_hermes_codex("Say hi", model="gpt-5.5", timeout_seconds=12)

    assert isinstance(result, HermesGatewayResult)
    assert result.ok is True
    assert result.provider == "hermes_openai_codex"
    assert result.model == "gpt-5.5"
    assert result.fallback_used is False
    assert result.text == "POC answer"
    assert calls == [
        [
            "hermes",
            "chat",
            "-q",
            "Say hi",
            "--provider",
            "openai-codex",
            "-m",
            "gpt-5.5",
            "-Q",
        ]
    ]


def test_ask_via_hermes_codex_reports_failure(monkeypatch):
    def fake_run(command, *, capture_output, text, timeout, cwd):
        return subprocess.CompletedProcess(command, 1, stdout="", stderr="rate limited")

    monkeypatch.setattr(subprocess, "run", fake_run)

    result = ask_via_hermes_codex("Say hi")

    assert result.ok is False
    assert result.text == ""
    assert "rate limited" in result.error


def test_ask_via_hermes_codex_handles_timeout(monkeypatch):
    def fake_run(command, *, capture_output, text, timeout, cwd):
        raise subprocess.TimeoutExpired(command, timeout)

    monkeypatch.setattr(subprocess, "run", fake_run)

    result = ask_via_hermes_codex("Say hi", timeout_seconds=1)

    assert result.ok is False
    assert "timed out" in result.error.lower()
