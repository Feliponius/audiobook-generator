"""Model gateway helpers for Book Chat experiments.

This module intentionally keeps the first Hermes/Codex integration small and
app-callable. The production Book Chat service can later wrap this in a richer
provider abstraction with Gemini fallback, retries, and structured prompting.
"""

from __future__ import annotations

from dataclasses import dataclass
import subprocess
from typing import Optional


@dataclass(frozen=True)
class HermesGatewayResult:
    ok: bool
    provider: str
    model: str
    text: str
    fallback_used: bool = False
    error: str = ""
    returncode: Optional[int] = None


def _strip_hermes_session_header(stdout: str) -> str:
    """Remove Hermes CLI's `session_id: ...` line from quiet output."""
    lines = stdout.splitlines()
    if lines and lines[0].startswith("session_id:"):
        lines = lines[1:]
    return "\n".join(lines).strip()


def ask_via_hermes_codex(
    prompt: str,
    *,
    model: str = "gpt-5.5",
    timeout_seconds: int = 90,
    cwd: str | None = None,
) -> HermesGatewayResult:
    """Ask Hermes to answer a prompt through OpenAI Codex OAuth.

    This proves the audiobook app can treat Hermes as a local model gateway
    without directly handling Codex OAuth tokens.
    """
    command = [
        "hermes",
        "chat",
        "-q",
        prompt,
        "--provider",
        "openai-codex",
        "-m",
        model,
        "-Q",
    ]
    try:
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            cwd=cwd,
        )
    except subprocess.TimeoutExpired as exc:
        return HermesGatewayResult(
            ok=False,
            provider="hermes_openai_codex",
            model=model,
            text="",
            error=f"Hermes/Codex call timed out after {timeout_seconds}s",
            returncode=None,
        )
    except OSError as exc:
        return HermesGatewayResult(
            ok=False,
            provider="hermes_openai_codex",
            model=model,
            text="",
            error=str(exc),
            returncode=None,
        )

    text = _strip_hermes_session_header(completed.stdout)
    if completed.returncode != 0:
        return HermesGatewayResult(
            ok=False,
            provider="hermes_openai_codex",
            model=model,
            text=text,
            error=(completed.stderr or completed.stdout).strip(),
            returncode=completed.returncode,
        )

    return HermesGatewayResult(
        ok=True,
        provider="hermes_openai_codex",
        model=model,
        text=text,
        fallback_used=False,
        returncode=completed.returncode,
    )
