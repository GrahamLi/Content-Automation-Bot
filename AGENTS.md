# Repository Guidelines

## Project Structure & Modules
- `main.py`: Entry point to fetch content, summarize, and publish.
- `content_automation_bot.py`: Utilities for YouTube transcripts, LLM summarization, and LINE broadcast.
- `config.json`: Keys and source definitions (YouTube, LINE, LLM). Do not commit real secrets.
- `output/`: Generated Markdown articles (dated filenames).
- `processed_ids.txt`, `failed_ids.txt`, `corrected_code.txt`: Run-state tracking; safe to regenerate.

## Setup, Run, and Development
- Python: Use 3.10+ and a virtualenv.
- Install deps and run locally:
```
python -m venv .venv
.\.venv\Scripts\activate   # Windows
# source .venv/bin/activate  # macOS/Linux
pip install -r requirements.txt
python main.py
```
- Optional but recommended for YouTube videos without transcripts: install the Whisper STT stack and ffmpeg.
  - `pip install --upgrade openai-whisper ffmpeg-python`
  - Install the ffmpeg binary via your OS package manager (e.g. `brew install ffmpeg`, `sudo apt install ffmpeg`).
  - Set `WHISPER_MODEL` to override the default `base` model if needed.

## Coding Style & Naming
- Indentation: 4 spaces; follow PEP 8.
- Naming: `snake_case` for functions/variables, `UPPER_CASE` for constants, modules `snake_case.py`.
- Structure: keep functions focused; prefer type hints and docstrings; isolate side effects in `if __name__ == "__main__":`.

## Testing Guidelines
- Current state: no committed tests.
- If adding tests, use `pytest` with `tests/` and files named `test_*.py`.
- Run tests: `pytest -q`. Mock network/Google/LINE calls; avoid writing to `output/` in unit tests.

## Commit & PR Guidelines
- Commits: imperative mood ("Add X"), concise subject (≤72 chars), body explains “why”.
- PRs: clear description, linked issues, impacted modules, config changes, and sample generated file path from `output/`. Include screenshots if UI-facing.

## Security & Configuration
- Secrets: never commit real `YOUTUBE_API_KEY`, `LLM_API_KEY`, or `LINE_CHANNEL_ACCESS_TOKEN`.
- Provide `config.json.example` with placeholders; prefer environment variables for local overrides.
- Consider ignoring bulky artifacts in `output/` if they are not needed in version control.

