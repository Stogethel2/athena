# Research Debate Engine — Project Guide

## Purpose

Multi-model research pipeline where Claude, GPT, and Gemini independently research a topic, debate each other's findings, and produce a single verified result file per session.

## Models

| Role | Model | Provider |
|---|---|---|
| Claude | `claude-opus-4-6` | Anthropic (direct) |
| GPT | `openai/gpt-5.5` | OpenRouter |
| Gemini | `google/gemini-3.1-pro-preview` | OpenRouter |

## API Keys

Stored in `.env` (Docker) or `~/.zshrc` (local venv):

```
ANTHROPIC_API_KEY   — Claude direct
OPENROUTER_API_KEY  — GPT + Gemini via OpenRouter
```

Docker loads keys automatically via `env_file: .env`.  
Local: `export $(grep -E "ANTHROPIC_API_KEY|OPENROUTER_API_KEY" ~/.zshrc | sed 's/export //' | xargs)`

## How to Run

**Docker (port 8889):**
```bash
cp .env.example .env   # fill in keys first
docker compose up -d
# Open: http://localhost:8889
```

**Local venv:**
```bash
source .venv/bin/activate

# Full research + debate + verdict (default)
python debate_engine.py "your research topic here"

# Quick debate only (no web search, no verdict)
python debate_engine.py --debate "your topic"
```

## Web UI

A browser-based chat interface is available via FastAPI.

```bash
# Docker (recommended):
docker compose up -d
# Open: http://localhost:8889

# Local venv:
source .venv/bin/activate
uvicorn app:app --reload --port 8000
# Open: http://localhost:8000
```

- Submit a topic in the chat box; pipeline phases render progressively.
- **Economy** (default): toggle unpressed — Phase 0 + Phase 1 + lightweight rewrite; no save, no sidebar entry.
- **Report**: toggle pressed — full Phase 0–3, saves `result.md`, sidebar refreshes.
- Click model tabs (Claude / GPT / Gemini) in Phase 1 and Phase 2 (report only) to read each model's response.
- Phase 3 synthesis is rendered as formatted markdown.
- The saved file path is shown at the bottom of each response (report mode only).
- `debate_engine.research_debate()` accepts optional `on_event`, `mode` (`economy` | `report`, default `economy`), and `save_folder` — CLI path passes nothing and runs full report pipeline.

## Pipeline Modes (Web UI)

| Mode | Toggle | Phases | Saves `result.md` | Sidebar |
|------|--------|--------|-------------------|---------|
| Economy (default) | Unpressed | 0 + 1 + rewrite | No | No |
| Report | Pressed | 0 + 1 + 2 + 3 | Yes | Yes |

`POST /api/chat` accepts `mode: "economy" | "report"` (default `"economy"`). Economy follow-ups may pass `folder` for context only — existing `result.md` is not modified unless `mode` is `report`.

## Pipeline Phases

```
Phase 0  Web Search      — DuckDuckGo fetches fresh sources (up to 8 results)
Phase 1  Research        — All 3 models analyze the same data simultaneously
Phase 2  Cross-Debate    — Each model critiques the other two's answers (report mode only)
Phase 3  Synthesis       — Claude merges answers (full synthesis in report; rewrite in economy)
```

Phase 3 rules:
- No winner is picked — all models contribute
- A fact is included if supported by 2+ models, OR if one model raised it credibly
- Disagreements are resolved explicitly (state which position is more credible and why)
- Each model's unique contribution is credited by name
- Uncertainties shared across all models are flagged

## Source Quality Requirements

Research must draw from **multiple independent sources**. A claim is only considered reliable when:

- Cited by **2+ independent sources** (community posts, papers, videos, etc.)
- Sourced from: YouTube, Reddit, Facebook groups, web boards, research papers, or relevant communities
- **Not** accepted from a single person or single source alone

If web search returns no results, models must explicitly flag training-data uncertainty and cite reasoning.

## Output File Convention

Each session produces **one result file**:

```
results/
  ddmmyyyy-short-title/
    result.md
```

Examples:
```
results/15052026-vane-endgame-build/result.md
results/22052026-python-async-patterns/result.md
```

Rules:
- One `result.md` per session — never overwrite, create a new dated folder instead
- `short-title` is kebab-case, max 5 words
- Date format: `ddmmyyyy` (day first)

## result.md Structure

```markdown
# [Topic]

**Date:** DD/MM/YYYY  
**Models:** Claude (claude-opus-4-6) · GPT (gpt-5.5) · Gemini (gemini-3.1-pro-preview)  
**Method:** Synthesized from all three models — best points merged

---

## [Ranked/Scored Section — if topic involves items, builds, or comparisons]

When the topic involves things that can be ranked (sigils, skills, tools, options, products, etc.),
include a scored table BEFORE the full answer. Format:

| Tier | Item | Score | Why |
|---|---|---|---|
| S | Item name | 10/10 | Reason — must equip/use |
| A | Item name | 8/10 | Highly recommended |
| B | Item name | 6/10 | Situationally good |
| C | Item name | 4/10 | Optional / safety net |

- Use S/A/B/C tiers + numeric score (1–10)
- Include copies/quantity column if relevant
- Add a "Sub-category" table if the topic has multiple groups (e.g., primary sigils vs. sub-traits)
- Always explain the WHY — a score without reasoning is useless

## Key Findings

[Bullet points of facts supported by 2+ sources or 2+ models]

## [Winner Model] — Full Answer

[Winner's full Phase 2 response]

## Corrections & Caveats

[From the verdict phase: facts that were wrong or uncertain across all models]

## Sources

[Web search URLs cited during research, if any]
```

## Revision Workflow

When improvements are needed after a session:

1. **Claude** is the primary reviser — edits `result.md` directly
2. **GPT and Gemini** review the revised draft (run `--debate` mode with the revised content as context)
3. Only merge revisions supported by 2+ models
4. Append a `## Revision History` section at the bottom of `result.md`

## Dependency Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install anthropic openai ddgs fastapi uvicorn
```

## Known Issues

- Web search auto-generates a short query from the topic (Claude condenses to ≤6 words, retries in English if Thai returns 0)
- Use `ddgs` package — `duckduckgo_search` is deprecated and gets rate-limited: `pip install ddgs`
- Claude requires `max_tokens=16000` minimum when using adaptive thinking
- ResourceWarning on exit (unclosed transport) — cosmetic only, does not affect output
