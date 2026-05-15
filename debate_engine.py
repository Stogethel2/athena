import os
import re
import asyncio
from datetime import datetime
from pathlib import Path
import anthropic
from openai import AsyncOpenAI
from ddgs import DDGS


def _load_env_file() -> None:
    """Load API keys from project .env (does not override existing env vars)."""
    env_path = Path(__file__).parent / ".env"
    if not env_path.exists():
        return
    from dotenv import load_dotenv

    load_dotenv(env_path)


def _load_zshrc() -> None:
    """Fallback: keys from ~/.zshrc when not already set."""
    zshrc = Path.home() / ".zshrc"
    if not zshrc.exists():
        return
    pat = re.compile(r"^export\s+([A-Z_][A-Z0-9_]*)=(.+)$")
    for line in zshrc.read_text(encoding="utf-8").splitlines():
        m = pat.match(line.strip())
        if m:
            key, val = m.group(1), m.group(2).strip().strip("'\"")
            if key not in os.environ:
                os.environ[key] = val


_load_env_file()
_load_zshrc()


# Models — อัพเดทตรงนี้เมื่อ model ใหม่ออก
CLAUDE_MODEL  = "claude-opus-4-6"                  # Anthropic direct
GPT_MODEL     = "openai/gpt-5.5"                   # OpenRouter → OpenAI
GEMINI_MODEL  = "google/gemini-3.1-pro-preview"    # OpenRouter → Google

# Clients
def _require_api_key(name: str) -> str:
    key = os.environ.get(name)
    if not key:
        raise RuntimeError(
            f"{name} is not set. Copy .env.example → .env and fill in your keys."
        )
    return key


_anthropic_key = _require_api_key("ANTHROPIC_API_KEY")
_openrouter_key = _require_api_key("OPENROUTER_API_KEY")

claude_client = anthropic.AsyncAnthropic(api_key=_anthropic_key)
openrouter_client = AsyncOpenAI(
    base_url="https://openrouter.ai/api/v1",
    api_key=_openrouter_key,
)

_RESULTS_DIR = Path(__file__).parent / "results"

SYSTEM = (
    "You are a research assistant. Prioritize factual accuracy, "
    "cite your reasoning, and clearly acknowledge uncertainty."
)

SEP = "=" * 60


# ── Web Search ────────────────────────────────────────────────

async def web_search(query: str, max_results: int = 8) -> str:
    """ค้นหาข้อมูลจากเว็บ คืน formatted text พร้อม source URL"""
    def _search():
        with DDGS() as ddgs:
            results = list(ddgs.text(query, max_results=max_results))
        lines = []
        for i, r in enumerate(results, 1):
            lines.append(f"[{i}] {r['title']}\n{r['body']}\nSource: {r['href']}\n")
        return "\n".join(lines)

    return await asyncio.to_thread(_search)


# ── Model Callers ─────────────────────────────────────────────

async def ask_claude(prompt: str) -> str:
    async with claude_client.messages.stream(
        model=CLAUDE_MODEL,
        max_tokens=16000,
        thinking={"type": "adaptive"},
        system=SYSTEM,
        messages=[{"role": "user", "content": prompt}],
    ) as stream:
        message = await stream.get_final_message()
    return next((b.text for b in message.content if b.type == "text"), "")


async def ask_gpt(prompt: str) -> str:
    response = await openrouter_client.chat.completions.create(
        model=GPT_MODEL,
        messages=[
            {"role": "system", "content": SYSTEM},
            {"role": "user", "content": prompt},
        ],
    )
    return response.choices[0].message.content


async def ask_gemini(prompt: str) -> str:
    response = await openrouter_client.chat.completions.create(
        model=GEMINI_MODEL,
        messages=[
            {"role": "system", "content": SYSTEM},
            {"role": "user", "content": prompt},
        ],
    )
    return response.choices[0].message.content


# ── Prompt Builders ───────────────────────────────────────────

def _search_query_prompt(topic: str) -> str:
    return (
        f"Convert this topic into a concise web search query (max 6 words, use the most relevant language for searching — English or Thai):\n\n"
        f"Topic: {topic}\n\n"
        "Reply with ONLY the search query, nothing else."
    )


def _research_prompt(topic: str, search_results: str, context: str = "") -> str:
    context_section = (
        f"\n\nExisting research on this topic (already known — do not repeat, only add or refine):\n"
        f"{context[:3000]}\n"  # cap to avoid overflow
        f"\nYour task: research the follow-up question in light of the above context.\n"
    ) if context else ""
    return (
        f"Research Topic: {topic}\n\n"
        f"Web Search Results (fresh data):\n{search_results}\n"
        f"{context_section}"
        "Using both the search results above AND your training knowledge, "
        "provide a comprehensive, accurate answer. "
        "Cite specific facts and note any conflicting information."
    )


def _cross_prompt(topic: str, others: dict[str, str]) -> str:
    others_text = "\n\n".join(f"[{name}]:\n{resp}" for name, resp in others.items())
    return (
        f"Topic: {topic}\n\n"
        f"Other AI models answered:\n{others_text}\n\n"
        "Critically review their responses. Where do you agree? "
        "Where do you disagree and why? What did they get wrong or miss? "
        "Provide your final, most accurate position."
    )


def _rewrite_prompt(topic: str, all_answers: dict[str, str]) -> str:
    answers_text = "\n\n".join(
        f"[{name}]:\n{str(resp)[:3000]}" for name, resp in all_answers.items()
    )
    return (
        f"Topic: {topic}\n\n"
        f"Three AI models each researched this topic independently:\n\n{answers_text}\n\n"
        "Rewrite the above into ONE clear, easy-to-read summary. "
        "Merge the strongest points from all three. Remove repetition. "
        "Use plain language. No need to credit individual models."
    )


def _synthesis_prompt(topic: str, all_answers: dict[str, str], context: str = "") -> str:
    answers_text = "\n\n".join(
        f"[{name}]:\n{resp}" for name, resp in all_answers.items()
    )
    context_instruction = (
        f"\n\nExisting research context (for reference):\n{context[:2000]}\n"
        f"\nIntegrate new findings with the existing context. Do not repeat what is already covered — only add, correct, or refine.\n"
    ) if context else ""
    return (
        f"Topic: {topic}\n\n"
        f"Three AI models researched and debated this topic. Here are their final positions:\n\n"
        f"{answers_text}\n"
        f"{context_instruction}\n"
        "Your task: synthesize the BEST points from ALL three responses into one definitive answer.\n\n"
        "Rules:\n"
        "- Include a fact only if supported by 2+ models OR if only one model raised it but it is clearly credible\n"
        "- Where models disagreed, state which position is more credible and why\n"
        "- Explicitly note what each model contributed uniquely (credit by name)\n"
        "- Flag anything that all models were uncertain about\n"
        "- Do NOT simply pick one model's answer — actively merge the strongest parts of each\n\n"
        "Structure your synthesis with clear sections and produce the most complete, accurate answer possible."
    )


# ── Result Writer ─────────────────────────────────────────────

def _save_result(
    topic: str,
    synthesis: str,
    final_answers: dict[str, str],
    search_results: str,
) -> Path:
    date_str = datetime.now().strftime("%d%m%Y")
    slug = re.sub(r"[^a-z0-9]+", "-", topic.lower()).strip("-")[:40]
    folder = _RESULTS_DIR / f"{date_str}-{slug}"
    folder.mkdir(parents=True, exist_ok=True)
    out = folder / "result.md"

    sources = ""
    for line in search_results.splitlines():
        if line.startswith("Source:"):
            sources += f"- {line[7:].strip()}\n"

    per_model = "\n\n---\n\n".join(
        f"### {name}\n\n{resp}" for name, resp in final_answers.items()
        if resp and not str(resp).startswith("[Error")
    )

    content = f"""# {topic}

**Date:** {datetime.now().strftime("%d/%m/%Y")}
**Models:** Claude (`{CLAUDE_MODEL}`) · GPT (`{GPT_MODEL}`) · Gemini (`{GEMINI_MODEL}`)
**Method:** Synthesized from all three models — best points merged

---

## Synthesized Answer

{synthesis}

---

## Individual Model Answers (Phase 2)

{per_model}

---

## Sources

{sources.strip() or "_No web sources retrieved — based on model training knowledge._"}
"""
    out.write_text(content, encoding="utf-8")
    return out


# ── Follow-up Result Appender ─────────────────────────────────

def _append_result(
    save_folder: str,
    topic: str,
    synthesis: str,
    final_answers: dict[str, str],
    search_results: str,
) -> Path:
    folder = _RESULTS_DIR / save_folder
    out = folder / "result.md"

    sources = ""
    for line in search_results.splitlines():
        if line.startswith("Source:"):
            sources += f"- {line[7:].strip()}\n"

    per_model = "\n\n---\n\n".join(
        f"### {name}\n\n{resp}" for name, resp in final_answers.items()
        if resp and not str(resp).startswith("[Error")
    )

    section = f"""

---

## Follow-up: {topic}

**Date:** {datetime.now().strftime("%d/%m/%Y")}

### Synthesized Answer

{synthesis}

### Individual Model Answers

{per_model}

### Sources

{sources.strip() or "_No web sources retrieved._"}
"""
    existing = out.read_text(encoding="utf-8") if out.exists() else ""
    out.write_text(existing + section, encoding="utf-8")
    return out


# ── Main Flow ─────────────────────────────────────────────────

async def research_debate(
    topic: str,
    on_event=None,
    context: str = "",
    save_folder: str | None = None,
    mode: str = "economy",
) -> None:
    """
    Research pipeline. mode="economy": Phase 0+1 + rewrite (no save).
    mode="report": full Phase 0–3 + cross-debate + save result.md.

    on_event: optional async callable(event: dict) — called at key pipeline moments
    """
    if mode not in ("economy", "report"):
        mode = "economy"
    async def _emit(event: dict):
        if on_event is None:
            return
        try:
            await on_event(event)
        except Exception:
            pass

    async def _run_and_emit(name: str, coro, phase: int):
        try:
            result = await coro
        except Exception as e:
            result = e
        content = str(result) if not isinstance(result, str) else result
        await _emit({"type": "model_response", "phase": phase, "model": name, "content": content})
        return result

    print(f"\n{SEP}\nRESEARCH DEBATE: {topic}\n{SEP}")

    # ── Phase 0: Web Search ──────────────────────────────────
    print("\n[Phase 0: Web Search]")
    query = await ask_claude(_search_query_prompt(topic))
    query = query.strip().strip('"').strip("'")
    print(f"Searching: \"{query}\"...")
    await _emit({"type": "searching", "query": query})
    try:
        search_results = await web_search(query)
        lines = [line for line in search_results.splitlines() if line.startswith("[")]
        print(f"Found {len(lines)} results ✓")
        if not lines:
            raise ValueError("0 results")
        await _emit({"type": "search_done", "count": len(lines), "query": query})
    except Exception as e:
        print(f"Search failed ({e}) — retrying with English query...")
        try:
            en_query = await ask_claude(
                f"Translate this search query to English (max 6 words): {query}"
            )
            en_query = en_query.strip().strip('"').strip("'")
            print(f"Retrying: \"{en_query}\"...")
            search_results = await web_search(en_query)
            lines = [line for line in search_results.splitlines() if line.startswith("[")]
            print(f"Found {len(lines)} results ✓")
            await _emit({"type": "search_done", "count": len(lines), "query": en_query})
        except Exception as e2:
            print(f"Search failed ({e2}) — proceeding with training data only")
            await _emit({"type": "search_failed"})
            search_results = "No web search results available."

    # ── Phase 1: Research ────────────────────────────────────
    print(f"\n{SEP}\n[Phase 1: Research — All models analyze the same data]\n{SEP}")
    await _emit({"type": "phase_start", "phase": 1, "label": "Research"})
    research_p = _research_prompt(topic, search_results, context)
    r1 = await asyncio.gather(
        _run_and_emit("Claude", ask_claude(research_p), 1),
        _run_and_emit("GPT",    ask_gpt(research_p),    1),
        _run_and_emit("Gemini", ask_gemini(research_p), 1),
        return_exceptions=True,
    )
    claude_r1, gpt_r1, gemini_r1 = r1

    for name, model, resp in [
        ("Claude", CLAUDE_MODEL, claude_r1),
        ("GPT", GPT_MODEL, gpt_r1),
        ("Gemini", GEMINI_MODEL, gemini_r1),
    ]:
        print(f"\n--- {name} ({model}) ---")
        print(resp if not isinstance(resp, Exception) else f"[Error: {resp}]")

    if mode == "economy":
        print(f"\n{SEP}\n[Economy: Rewrite — Merging Phase 1 answers]\n{SEP}")
        await _emit({"type": "phase_start", "phase": 3, "label": "Synthesis"})
        phase1_answers = {
            "Claude": claude_r1 if not isinstance(claude_r1, Exception) else str(claude_r1),
            "GPT":    gpt_r1    if not isinstance(gpt_r1,    Exception) else str(gpt_r1),
            "Gemini": gemini_r1 if not isinstance(gemini_r1, Exception) else str(gemini_r1),
        }
        print("Rewriting...")
        try:
            rewrite = await ask_claude(_rewrite_prompt(topic, phase1_answers))
        except Exception as e:
            rewrite = f"[Rewrite failed: {e}]"
        print(f"\n{SEP}\n[Synthesized Answer]\n{SEP}")
        print(rewrite)
        await _emit({"type": "synthesis", "content": rewrite})
        return

    # ── Phase 2: Cross-Debate ────────────────────────────────
    print(f"\n{SEP}\n[Phase 2: Cross-Debate — Each model critiques the others]\n{SEP}")
    await _emit({"type": "phase_start", "phase": 2, "label": "Cross-Debate"})
    r2 = await asyncio.gather(
        _run_and_emit("Claude", ask_claude(_cross_prompt(topic, {"GPT": gpt_r1,    "Gemini": gemini_r1})), 2),
        _run_and_emit("GPT",    ask_gpt(  _cross_prompt(topic, {"Claude": claude_r1, "Gemini": gemini_r1})), 2),
        _run_and_emit("Gemini", ask_gemini(_cross_prompt(topic, {"Claude": claude_r1, "GPT": gpt_r1})),    2),
        return_exceptions=True,
    )
    claude_r2, gpt_r2, gemini_r2 = r2

    for name, model, resp in [
        ("Claude", CLAUDE_MODEL, claude_r2),
        ("GPT", GPT_MODEL, gpt_r2),
        ("Gemini", GEMINI_MODEL, gemini_r2),
    ]:
        print(f"\n--- {name} ({model}) ---")
        print(resp if not isinstance(resp, Exception) else f"[Error: {resp}]")

    # ── Phase 3: Synthesis ───────────────────────────────────
    print(f"\n{SEP}\n[Phase 3: Synthesis — Merging best points from all models]\n{SEP}")
    await _emit({"type": "phase_start", "phase": 3, "label": "Synthesis"})

    # ใช้ Phase 2 เป็น input (fallback ไป Phase 1 ถ้า Phase 2 error)
    final_answers = {
        "Claude": claude_r2 if not isinstance(claude_r2, Exception) else claude_r1,
        "GPT":    gpt_r2    if not isinstance(gpt_r2,    Exception) else gpt_r1,
        "Gemini": gemini_r2 if not isinstance(gemini_r2, Exception) else gemini_r1,
    }

    # Claude เป็น primary reviser — synthesize ข้อดีจากทุก model
    print("Synthesizing...")
    try:
        synthesis = await ask_claude(_synthesis_prompt(topic, final_answers, context))
    except Exception as e:
        synthesis = (
            f"[Synthesis failed: {e}]\n\n"
            f"Fallback — Claude's Phase 2 answer:\n{final_answers['Claude']}"
        )

    print(f"\n{SEP}\n[Synthesized Answer]\n{SEP}")
    print(synthesis)
    await _emit({"type": "synthesis", "content": synthesis})

    # ── Save result.md ───────────────────────────────────────
    if save_folder:
        result_path = _append_result(save_folder, topic, synthesis, final_answers, search_results)
    else:
        result_path = _save_result(topic, synthesis, final_answers, search_results)
    print(f"\n{SEP}\n[Saved] {result_path}\n{SEP}")
    await _emit({"type": "saved", "path": str(result_path)})


async def debate(topic: str) -> None:
    """Quick debate mode — ไม่มี web search, ไม่มี verdict"""
    print(f"\n{SEP}\nDEBATE: {topic}\n{SEP}")

    print("\n[Round 1: Initial Positions]")
    r1 = await asyncio.gather(
        ask_claude(topic), ask_gpt(topic), ask_gemini(topic),
        return_exceptions=True,
    )
    claude_r1, gpt_r1, gemini_r1 = r1
    for name, model, resp in [
        ("Claude", CLAUDE_MODEL, claude_r1),
        ("GPT",    GPT_MODEL,    gpt_r1),
        ("Gemini", GEMINI_MODEL, gemini_r1),
    ]:
        print(f"\n--- {name} ({model}) ---")
        print(resp if not isinstance(resp, Exception) else f"[Error: {resp}]")

    print(f"\n{SEP}\n[Round 2: Cross-Review]\n{SEP}")
    r2 = await asyncio.gather(
        ask_claude(_cross_prompt(topic, {"GPT": gpt_r1, "Gemini": gemini_r1})),
        ask_gpt(_cross_prompt(topic, {"Claude": claude_r1, "Gemini": gemini_r1})),
        ask_gemini(_cross_prompt(topic, {"Claude": claude_r1, "GPT": gpt_r1})),
        return_exceptions=True,
    )
    for name, model, resp in [
        ("Claude", CLAUDE_MODEL, r2[0]),
        ("GPT",    GPT_MODEL,    r2[1]),
        ("Gemini", GEMINI_MODEL, r2[2]),
    ]:
        print(f"\n--- {name} ({model}) ---")
        print(resp if not isinstance(resp, Exception) else f"[Error: {resp}]")


# ── Entry Point ───────────────────────────────────────────────

if __name__ == "__main__":
    import sys
    args = sys.argv[1:]

    if args and args[0] == "--debate":
        # Quick debate (no web search, no verdict)
        topic = " ".join(args[1:]) or "What is the most important challenge facing humanity?"
        asyncio.run(debate(topic))
    else:
        # Default: full research + debate + verdict
        topic = " ".join(args) or "What is the most important challenge facing humanity?"
        asyncio.run(research_debate(topic))
