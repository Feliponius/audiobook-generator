Problem:
The audiobook-generator dashboard server still launches conversion children in a context that fails immediately with ModuleNotFoundError (historically bs4, now numpy), even though the exact manual command works when invoked directly with /home/philip/audiobook-generator/venv/bin/python.

Verified facts:
- monitor_server.py already has resolve_library_pipeline_python(root) and chooses <root>/venv/bin/python when present.
- Direct manual run succeeds:
  /home/philip/audiobook-generator/venv/bin/python /home/philip/audiobook-generator/epub_to_audiobook.py <real epub> --outdir ... --tts-engine kokoro --mode hls-tts --kokoro-voice af_heart --kokoro-workers 2 --rewrite-policy script-only
- Live monitor_server process environment still includes Hermes venv context:
  - VIRTUAL_ENV=/home/philip/.hermes/hermes-agent/venv
  - PATH contains Hermes venv/bin early
- API-triggered conversion attempts append immediate import failures to conversion.log instead of running.

Task:
Patch monitor_server.py so child conversion processes launch in a project-venv-clean environment, independent of the parent Hermes venv.

Requirements:
1. Add a helper that builds a child env for library conversions.
2. When <project_root>/venv/bin/python exists, child env should:
   - set VIRTUAL_ENV to <project_root>/venv
   - prepend <project_root>/venv/bin to PATH
   - remove PYTHONHOME if present
   - remove PYTHONPATH if present
3. If no project venv exists, fall back safely to current env + sys.executable behavior.
4. Pass this env explicitly to subprocess.Popen for /api/library/start conversions.
5. Append one short launch banner line to conversion.log before spawning, including the resolved python path, so future verification is easy.
6. Keep existing tests passing and add/adjust tests for the child env helper if appropriate.
7. Do not change the already-completed delete/reader/theme work.

After coding, run the targeted tests you changed or relied on and summarize the diff/results.
