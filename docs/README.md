# Documentation

This directory contains design documents and planning notes for the Audiobook Generator project.

## Files

- `audiobook-library-prd.md` — Original Product Requirements Document
- `architecture.md` — System architecture notes (to be written)

## Design Principles

1. **Single-user, trust-based** — No auth, designed for tailnet/private network
2. **Mobile-first** — Android is the primary target
3. **Low-babysitting** — Should run unattended
4. **Script-first cleanup** — Deterministic text processing before LLM
5. **Privacy-first** — Local TTS, no cloud dependencies
