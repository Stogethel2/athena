# Research Debate Engine

Multi-model AI research pipeline. Three models — Claude, GPT, and Gemini — independently research a topic, debate each other's findings, then synthesize the best points into a single verified result file.

---

## How It Works

```
Phase 0  Web Search    DuckDuckGo fetches up to 8 live sources
Phase 1  Research      All 3 models analyze the same data in parallel
Phase 2  Cross-Debate  Each model critiques the other two's answers
Phase 3  Synthesis     Claude merges the best points from all three
```

Output is saved automatically to `results/ddmmyyyy-topic-slug/result.md`.

---

## Setup

### Docker (recommended)

**1. Copy the env template and fill in your keys**

```bash
cp .env.example .env
# Edit .env and set ANTHROPIC_API_KEY and OPENROUTER_API_KEY
```

**2. Start the service**

```bash
docker compose up -d
# Open http://localhost:8889 in your browser
```

**3. Stop**

```bash
docker compose down
```

Saved results are written to `./results/` on your host — they persist across restarts and rebuilds.

---

### Local (Python venv)

**1. Install dependencies**

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

**2. Set API keys in `~/.zshrc`**

```bash
export ANTHROPIC_API_KEY='sk-ant-...'     # Claude (direct)
export OPENROUTER_API_KEY='sk-or-v1-...'  # GPT + Gemini via OpenRouter
```

**3. Load keys and run**

```bash
export $(grep -E "ANTHROPIC_API_KEY|OPENROUTER_API_KEY" ~/.zshrc | sed 's/export //' | xargs)
source .venv/bin/activate
uvicorn app:app --reload --port 8000
# Open http://localhost:8000 in your browser
```

---

## Usage

### Web UI

```bash
# Docker:  http://localhost:8889
# Local:   http://localhost:8000
```

Type a topic and watch all pipeline phases stream progressively. Click model tabs to read Claude, GPT, and Gemini's individual responses. The final synthesis renders as formatted markdown.

### CLI

```bash
source .venv/bin/activate

# Full pipeline: web search → research → debate → synthesis → save result
python debate_engine.py "your research topic"

# Quick debate only: no web search, no synthesis, no file saved
python debate_engine.py --debate "your topic"
```

### Examples

```bash
python debate_engine.py "Granblue Fantasy Relink Vane endgame build"
python debate_engine.py "best Python async patterns 2025"
python debate_engine.py "React vs Vue for large-scale apps"
```

> **Tip:** Keep search queries under 6 words. DuckDuckGo returns 0 results for long queries.

---

## Output

Each session creates one file:

```
results/
  15052026-vane-endgame-build/
    result.md
```

`result.md` contains:
- Synthesized answer (best points merged from all three models)
- Scored/ranked table when the topic involves items or comparisons
- Individual model answers (Phase 2)
- Web sources used

Never overwrite an existing result — create a new dated folder instead.

---

## Models

| Model | Provider | Notes |
|---|---|---|
| `claude-opus-4-6` | Anthropic (direct) | Primary synthesizer, adaptive thinking |
| `openai/gpt-5.5` | OpenRouter | |
| `google/gemini-3.1-pro-preview` | OpenRouter | |

To change a model, edit the constants at the top of `debate_engine.py`:

```python
CLAUDE_MODEL  = "claude-opus-4-6"
GPT_MODEL     = "openai/gpt-5.5"
GEMINI_MODEL  = "google/gemini-3.1-pro-preview"
```

---

## Revising a Result

If the result needs improvement after a session:

1. Edit `results/ddmmyyyy-topic/result.md` directly (Claude is the primary reviser)
2. Run `--debate` mode with the revised content as context for GPT and Gemini to review
3. Only merge revisions supported by 2+ models
4. Append a `## Revision History` section at the bottom

---

## Project Structure

```
research/
  debate_engine.py        Main pipeline (CLI + callback API)
  app.py                  FastAPI server (web UI backend)
  static/
    index.html            Single-file chat UI
  Dockerfile              Container build definition
  docker-compose.yml      Port 8889 → 8000, results volume
  requirements.txt        Python dependencies
  .env.example            API key template (copy to .env)
  .gitignore              Excludes .env and .venv
  CLAUDE.md               Full project guide for Claude
  README.md               This file
  results/
    ddmmyyyy-topic/
      result.md
```

---

## Known Issues

| Issue | Status |
|---|---|
| Long or Thai queries return 0 results | Auto-fixed — engine condenses topic to ≤6 words, retries in English if needed |
| `duckduckgo_search` deprecated + rate-limited | Fixed — use `ddgs` package instead |
| ResourceWarning on exit | Cosmetic only, does not affect output |
