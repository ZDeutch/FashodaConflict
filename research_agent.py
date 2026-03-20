#!/usr/bin/env python3
"""
Autonomous research dossier builder.

Runs for up to 30 minutes or $10, whichever comes first.
Each iteration researches a specific angle of the topic, building
a comprehensive dossier with sources to help YOU write the paper.

Goal: teach you everything you need to know — NOT write the paper for you.

Usage:
    pip install anthropic
    export ANTHROPIC_API_KEY=your-key
    python research_agent.py
"""

import anthropic
import time
from pathlib import Path
from datetime import datetime

# ── Configuration ─────────────────────────────────────────────────────────────

MODEL         = "claude-sonnet-4-6"   # Good quality, cost-efficient for looping
EFFORT        = "high"                # "max" burns budget fast in a loop
MAX_MINUTES   = 30
MAX_COST_USD  = 10.00
OUTPUT_FILE   = "research_dossier.md"
MAX_PAUSE_CONTINUATIONS = 5           # per task, handles server-side tool limits
MAX_RETRIES   = 5                     # retries on rate limit (429)
RETRY_WAIT_S  = 65                    # seconds to wait — just over 1 min window

# Sonnet 4.6 pricing ($/1M tokens)
PRICE_INPUT  = 3.00
PRICE_OUTPUT = 15.00

# ── Research tasks ─────────────────────────────────────────────────────────────
# Each task is a focused research question. The agent works through them in order,
# stopping when time or budget runs out.

RESEARCH_TASKS = [
    (
        "Fashoda Conflict — Core Facts",
        "Research the Fashoda Conflict (1898) thoroughly. I need to understand it well enough "
        "to write a paper. Cover: the timeline of events (with specific dates), the geographic "
        "and strategic importance of Fashoda and the Upper Nile, key figures on both sides "
        "(Marchand, Kitchener, Delcassé, Salisbury), what each side wanted, how the standoff "
        "unfolded, and how it was resolved. Explain WHY it mattered. Cite all sources with URLs."
    ),
    (
        "Dreyfus Affair — Core Facts",
        "Research the Dreyfus Affair (1894–1906) thoroughly. I need to understand it well enough "
        "to write a paper. Cover: the accusation and original trial (1894), the imprisonment on "
        "Devil's Island, Picquart's discovery of Esterhazy, Zola's J'accuse (1898), the retrial "
        "at Rennes (1899), the pardon, and the full exoneration (1906). Explain the role of "
        "antisemitism, the press, the Catholic Church, and the military. Cite all sources with URLs."
    ),
    (
        "France in the 1890s — Political & Social Context",
        "Explain the political and social context of France in the 1890s — the background I need "
        "to understand both crises. Cover: the Third Republic and its instability, the Panama "
        "scandal, the Boulanger Affair, the rise of French nationalism and antisemitism "
        "(Drumont, La Libre Parole), the role of the Catholic Church vs. secular republicans, "
        "civil-military tensions, and how the public mood shaped reactions to both events. "
        "Cite sources with URLs."
    ),
    (
        "Colonial Context — Scramble for Africa & the Nile",
        "Explain the imperial context I need for writing about the Fashoda Conflict. What was "
        "the Scramble for Africa? Why did Britain and France both want control of the Upper Nile "
        "and Sudan? What was the significance of Egypt and the Suez Canal? What were French "
        "colonial ambitions across Africa (the trans-African Cape-to-Cairo vs. Atlantic-to-Red Sea "
        "plans)? What happened at the Battle of Omdurman just before Fashoda? Cite sources with URLs."
    ),
    (
        "Scholarly Sources — Fashoda Conflict",
        "Find me the key scholarly books, journal articles, and academic sources on the Fashoda "
        "Conflict. For each source give: author, full title, publisher/journal, year, and if "
        "available a URL or DOI. Include both classic older scholarship and more recent work. "
        "Also note what argument or perspective each work takes — what is the historiographical "
        "debate around Fashoda? Was it a triumph or humiliation for France? A turning point in "
        "Anglo-French relations? Search academic databases and Google Scholar."
    ),
    (
        "Scholarly Sources — Dreyfus Affair",
        "Find me the key scholarly books, journal articles, and academic sources on the Dreyfus "
        "Affair. For each source: author, full title, publisher/journal, year, URL or DOI if "
        "available. Include Michael Burns, Ruth Harris, Piers Paul Read, Frederick Brown, and "
        "others. What are the main historiographical debates — about antisemitism, the role of "
        "the army, the significance for French democracy and Jewish identity? Search for recent "
        "scholarship too."
    ),
    (
        "Primary Sources Available Online",
        "Find primary sources for both events that are available online. I need:\n"
        "- Zola's J'accuse (original French and English translation) — URLs\n"
        "- Contemporary newspaper coverage (Le Figaro, Le Temps, The Times of London)\n"
        "- Dreyfus's own letters or memoir excerpts\n"
        "- Diplomatic dispatches or government documents related to Fashoda\n"
        "- Marchand's account or memoir\n"
        "- Any digitized archives (Gallica, British Newspaper Archive, etc.)\n"
        "Give direct URLs wherever possible."
    ),
    (
        "Connections — Both Crises Happening Simultaneously in 1898",
        "In 1898, both the Fashoda Conflict and the Dreyfus Affair were at their peak simultaneously "
        "in France. Research how these two crises interacted:\n"
        "- How did French politicians and the press handle both at once?\n"
        "- Did the Fashoda crisis affect the Dreyfus case or vice versa?\n"
        "- What does it tell us about French national identity, foreign vs. domestic politics?\n"
        "- Find historians who have written about this overlap specifically.\n"
        "Cite sources."
    ),
    (
        "Comparative Themes for the Paper",
        "I'm writing a comparative paper on the Fashoda Conflict and Dreyfus Affair. Research "
        "the following themes and find sources for each:\n"
        "1. Nationalism: how did both events reflect/inflame French nationalism?\n"
        "2. The role of the press in shaping public opinion in both crises\n"
        "3. Civil-military relations: the army's role in both events\n"
        "4. Justice and institutional failure (Dreyfus) vs. diplomatic failure (Fashoda)\n"
        "5. France's sense of national humiliation in the 1890s\n"
        "6. Antisemitism and racism as connecting threads\n"
        "For each theme, suggest specific sources."
    ),
    (
        "Key Figures — Deep Dive",
        "Give me detailed profiles of the most important figures I need to know for both events:\n"
        "- Alfred Dreyfus: background, personality, what happened to him\n"
        "- Émile Zola: his role, what J'accuse argued, consequences for him\n"
        "- Colonel Picquart: why he matters\n"
        "- Major Marchand: his mission, character, how he handled Fashoda\n"
        "- Lord Kitchener: his role at Fashoda and Omdurman\n"
        "- Théophile Delcassé: French foreign minister, how he resolved Fashoda\n"
        "Include sources for each person."
    ),
]

# ── Cost tracking ─────────────────────────────────────────────────────────────

def tokens_to_cost(input_tokens: int, output_tokens: int) -> float:
    return (input_tokens / 1_000_000 * PRICE_INPUT) + \
           (output_tokens / 1_000_000 * PRICE_OUTPUT)

# ── Per-task research with pause_turn handling ────────────────────────────────

SYSTEM_PROMPT = """\
You are a research assistant helping a student gather sources and learn history.

Your job is to TEACH, not to write the paper. For every response:
- Explain facts clearly so the student genuinely understands them
- Always include specific dates, names, places, and causes
- Explain WHY things matter historically — don't just list facts
- Use web search to find accurate, up-to-date information

CITATION RULES — follow these exactly:
1. Every factual claim must be followed by a full MLA citation in parentheses, e.g.:
   (Burns, Michael. *France and the Dreyfus Affair: A Documentary History*. Bedford/St. Martin's, 1999.)
2. After each citation, include a DIRECT QUOTE from that source (use the exact words).
   Format it as: > "Exact quote from the source." — Author, Title, p. X
   If you cannot find a direct quote, note: [direct quote unavailable — paraphrased from source]
3. At the end of each section, include a **Works Cited** block with full MLA entries for every
   source used, formatted as:
   Last, First. *Title*. Publisher, Year. URL (if available).
   For articles: Last, First. "Article Title." *Journal Name*, vol. X, no. X, Year, pp. X–X. URL.
   For websites: Last, First. "Page Title." *Site Name*, Date Published, URL. Accessed Day Mon. Year.

Format your response in clear Markdown with headers and subheaders.
Do NOT write a paper or essay. Write research notes and source lists.\
"""

def research_one_task(
    client: anthropic.Anthropic,
    tools: list,
    task_prompt: str,
) -> tuple[str, int, int]:
    """
    Run one research task, handling pause_turn continuations.
    Returns (text_output, total_input_tokens, total_output_tokens).
    """
    messages = [{"role": "user", "content": task_prompt}]
    total_input = 0
    total_output = 0
    all_text: list[str] = []

    for _ in range(MAX_PAUSE_CONTINUATIONS):
        # Retry loop for rate limits
        response = None
        chunks: list[str] = []
        for attempt in range(MAX_RETRIES):
            try:
                chunks = []
                with client.messages.stream(
                    model=MODEL,
                    max_tokens=4096,
                    thinking={"type": "adaptive"},
                    output_config={"effort": EFFORT},
                    system=SYSTEM_PROMPT,
                    tools=tools,
                    messages=messages,
                ) as stream:
                    for event in stream:
                        if event.type == "content_block_delta":
                            if event.delta.type == "text_delta":
                                print(event.delta.text, end="", flush=True)
                                chunks.append(event.delta.text)
                    response = stream.get_final_message()
                break  # success — exit retry loop

            except anthropic.RateLimitError:
                if attempt < MAX_RETRIES - 1:
                    wait = RETRY_WAIT_S * (attempt + 1)
                    print(
                        f"\n  ⏳ Rate limited. Waiting {wait}s "
                        f"(attempt {attempt + 1}/{MAX_RETRIES})...",
                        flush=True,
                    )
                    time.sleep(wait)
                else:
                    raise

        if response is None:
            break

        total_input  += response.usage.input_tokens
        total_output += response.usage.output_tokens
        all_text.extend(chunks)

        messages.append({"role": "assistant", "content": response.content})

        if response.stop_reason == "end_turn":
            break
        elif response.stop_reason == "pause_turn":
            # Server-side tool hit its iteration limit — continue
            messages = [
                {"role": "user", "content": task_prompt},
                {"role": "assistant", "content": response.content},
            ]
        else:
            break

    return "".join(all_text).strip(), total_input, total_output

# ── Main loop ─────────────────────────────────────────────────────────────────

def run():
    client = anthropic.Anthropic()
    tools = [{"type": "web_search_20260209", "name": "web_search"}]

    output_path = Path(OUTPUT_FILE)
    start_time  = time.time()
    total_cost  = 0.0

    # Write dossier header
    output_path.write_text(
        f"# Research Dossier: Fashoda Conflict & Dreyfus Affair\n\n"
        f"*Built by autonomous research agent — {datetime.now().strftime('%Y-%m-%d %H:%M')}*  \n"
        f"*Budget: ${MAX_COST_USD:.2f} or {MAX_MINUTES} min | Model: {MODEL}*\n\n"
        f"---\n\n"
        f"**How to use this dossier:** Each section below was researched separately. "
        f"Read through it to learn the material, follow the source links, and use it "
        f"as the foundation for writing your own paper.\n\n"
        f"---\n\n",
        encoding="utf-8",
    )

    print(f"{'='*62}")
    print(f"  Research Dossier Builder")
    print(f"  Model: {MODEL} | Effort: {EFFORT}")
    print(f"  Budget: ${MAX_COST_USD:.2f} or {MAX_MINUTES} min")
    print(f"  Output: {output_path.resolve()}")
    print(f"{'='*62}\n")

    completed = 0

    for i, (title, prompt) in enumerate(RESEARCH_TASKS):
        elapsed_min = (time.time() - start_time) / 60

        # ── Check limits before starting each task ──
        if elapsed_min >= MAX_MINUTES:
            print(f"\n⏱  Time limit reached ({elapsed_min:.1f} min). Stopping.")
            break
        if total_cost >= MAX_COST_USD:
            print(f"\n💰 Budget reached (${total_cost:.2f}). Stopping.")
            break

        print(f"\n{'─'*62}")
        print(f"[{i+1}/{len(RESEARCH_TASKS)}] {title}")
        print(f"  Elapsed: {elapsed_min:.1f} min | Spent: ${total_cost:.3f}\n")

        try:
            text, inp, out = research_one_task(client, tools, prompt)
        except Exception as e:
            print(f"\n  ✗ Error: {e}")
            continue

        iter_cost   = tokens_to_cost(inp, out)
        total_cost += iter_cost
        elapsed_min = (time.time() - start_time) / 60
        completed  += 1

        print(
            f"\n\n  ↳ {inp:,} in / {out:,} out tokens | "
            f"${iter_cost:.3f} this section | ${total_cost:.3f} total"
        )

        # Append section to dossier
        if text:
            with open(output_path, "a", encoding="utf-8") as f:
                f.write(f"## {i+1}. {title}\n\n")
                f.write(text)
                f.write("\n\n---\n\n")

    # ── Footer ────────────────────────────────────────────────────────────────
    elapsed_min = (time.time() - start_time) / 60
    with open(output_path, "a", encoding="utf-8") as f:
        f.write(
            f"*Session ended {datetime.now().strftime('%Y-%m-%d %H:%M')} — "
            f"{completed} sections | {elapsed_min:.1f} min | ${total_cost:.3f}*\n"
        )

    print(f"\n{'='*62}")
    print(f"  Completed {completed}/{len(RESEARCH_TASKS)} sections")
    print(f"  Time: {elapsed_min:.1f} min | Total cost: ${total_cost:.3f}")
    print(f"  Dossier saved to: {output_path.resolve()}")
    print(f"{'='*62}")


if __name__ == "__main__":
    run()
