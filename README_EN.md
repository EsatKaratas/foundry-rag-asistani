# Valorant Knowledge Assistant

*[Türkçe README](README.md) · English*

[![Deterministic tests](https://github.com/EsatKaratas/foundry-rag-asistani/actions/workflows/deterministic-tests.yml/badge.svg)](https://github.com/EsatKaratas/foundry-rag-asistani/actions/workflows/deterministic-tests.yml)

A question-answering assistant that runs **fully offline**, built with Microsoft
Foundry Local, SQLite and the RAG (Retrieval-Augmented Generation) pattern. It
answers questions from a knowledge base of 15 documents about Valorant. No internet
connection, cloud account or API key is required, and no data leaves the machine.

The problem this project focuses on is this: **what happens when a question has no
answer in the documents?** A plain RAG setup starts making things up. For that
reason every question passes through three checks before generation and two after
it, and most of those checks never consult the model — the decision is made in code.

Whether each check is actually necessary was
[measured by disabling them one at a time](#ablation-study-is-every-layer-actually-needed):
a RAG pipeline with no checks fabricates answers for 3 of the 4 unanswerable
questions.

**Interface:** chat history, token-by-token streaming, a knowledge-base panel in the
sidebar (documents and chunk counts), and a **decision trace** under every answer
showing which check made the decision and why.

To change the knowledge base, edit the `.txt` files in `data/` and run
`python ingest.py`.

![Interface](docs/gorseller/arayuz.png)

## Screenshots

**Answer and decision trace.** Every answer carries a trace of the pipeline's
decisions. Note the last row in the example below: the model skipped the citation
line, so the code added it.

![Answer and decision trace](docs/gorseller/cevap.png)

**A question the documents cannot answer.** The cosine score of **0.598** clears the
threshold — the text looks "relevant" — but none of the question's distinctive words
appear in the documents, so the lexical gate stops the answer. The user is also told
which words are missing.

![Refusal](docs/gorseller/bilmiyorum.png)

**Sources panel.** The chunks the answer relies on, with similarity scores; words
matched by the lexical gate are highlighted inside the text.

![Sources panel](docs/gorseller/kaynaklar.png)

## Architecture

```
User (Streamlit interface)
        │
        ▼
  answer_query()  ──────────────►  retrieval.py (get_top_chunks)
   (app.py)                              │
        │                                ▼
        │                        SQLite (rag.db) — chunks + embedding vectors
        │                                ▲
        ▼                                │
  Foundry Local (qwen3-4b, chat)         ingest.py (splits and vectorises documents)
  http://127.0.0.1:<port>/v1             │
        ▲                                ▼
        └──────── Foundry Local (qwen3-embedding-0.6b, embeddings) ────────┘
```

- **Client layer:** Streamlit interface (`app.py`)
- **Pipeline layer:** `answer_query()` — retrieval, prompt construction, LLM call
- **Data layer:** SQLite (`rag.db`), single table `chunks(id, source, chunk_index, content, embedding)`
- **AI layer:** Microsoft Foundry Local, exposing a local OpenAI-compatible REST endpoint

## Models

| Model | Role | Size |
|---|---|---|
| `qwen3-4b` | Chat / answer generation | 2.6 GB |
| `qwen3-embedding-0.6b` | Embeddings (text → vector) | 478 MB |

**Note on model choice:** the reference material suggested `phi-3.5-mini`. In testing
that model produced inconsistent and hallucinated output in Turkish (English was
fine), so `qwen3-4b` was used instead — same 3–5B parameter range, and it meets the
1–3 second per question target.

## Installation

```bash
# 1) Install Foundry Local (once)
winget install Microsoft.FoundryLocal

# 2) Install dependencies
pip install -r requirements.txt

# 3) Start the Foundry Local service
foundry server start

# 4) Download and load the models (once)
foundry model download qwen3-4b
foundry model download qwen3-embedding-0.6b
foundry model load qwen3-4b
foundry model load qwen3-embedding-0.6b
```

## Running

```bash
# Process the documents (data/*.txt -> rag.db)
python ingest.py

# Start the interface
python -m streamlit run app.py

# Run the functional test suite
python test_qa.py

# Run the ablation study
python ablation.py
```

The interface opens at `http://localhost:8501`.

## File Structure

| File | Role |
|---|---|
| `common.py` | Connects to Foundry Local (dynamic port discovery), model names |
| `ingest.py` | Splits documents into chunks, vectorises them, writes to SQLite |
| `retrieval.py` | Embeds the question, finds the most relevant chunks by cosine similarity |
| `lexical_gate.py` | Lexical relevance gate — catches topic drift deterministically |
| `app.py` | Streamlit interface + LLM integration (the "generate" step of RAG) |
| `test_qa.py` | End-to-end test suite — answerable, unanswerable and edge-case questions |
| `test_deterministic.py` | Unit tests for the model-independent layers (no GPU needed) |
| `ablation.py` | Ablation study — measures each defence layer's contribution |
| `data/` | Knowledge base — 15 Valorant documents (.txt) |
| `TEST_RESULTS.md` | Results of the latest test run (generated) |
| `ABLATION_RESULTS.md` | Results of the ablation study (generated) |

## Design Principle: never ask the model for something code can compute

Every check in this system follows from a single principle, which was adopted after
three separate approaches were measured and failed.

**Choosing a popular topic makes the problem harder.** Because Valorant is widely
known, the model can answer from its training data rather than the retrieved
context: *"Valorant was released in 2020"* — correct, but absent from these
documents. Such answers look right, which makes them hard to spot.

**A cosine threshold alone was not enough.** When every document is about the same
topic, the score stops measuring *"does this chunk answer the question"* and starts
measuring *"is this text about Valorant"*. Measured values: questions with no answer
in the documents still scored **0.53 – 0.60**. The upper threshold was raised from
0.50 to 0.75, but that was not the real fix.

**Having the model judge its own output did not work.** A post-generation
groundedness check (*"is the information in this answer present in the context?"*)
was tried with three different prompts:

| Prompt tried | Result |
|---|---|
| "Is this information in the context?" | The model approved its own hallucination as grounded |
| "Is everything in the answer present in the text?" | It also rejected valid answers |
| "Is anything fabricated?" | It mistook correctly paraphrased answers for fabrication |

The reason is simple: a model that already "knows" the fact makes the same mistake
when checking. A model cannot be expected to catch its own error.

**Conclusion:** nothing that can be computed exactly in code is asked of the model.
This principle is applied in four places — number verification, proper-noun
grounding, the lexical gate and answer length. The model is used only for the
grey-zone relevance decision, where no exact criterion exists.

## Test Results

`data/` contains **15 documents** about Valorant (80 chunks). `python test_qa.py`
runs a main suite of 19 questions (15 answerable + 4 unanswerable) plus 3 edge cases:

- **19 / 19 main tests passed** — every document is covered by at least one question
- **3 / 3 edge-case tests passed** (empty query, whitespace-only query, very general question)
- **Average time: 1.61 seconds per question** (measured on a freshly started server),
  within the 1–3 second target. Most unanswerable questions are rejected in
  **0.07 seconds**, because the lexical gate decides without any LLM call.

**Two layers of testing.** `test_qa.py` runs end to end and requires Foundry Local, a
GPU and loaded models. Most of the defence layers, however, are fully deterministic;
those are tested as **pure functions** in `test_deterministic.py` (22 tests, no model
required), which runs on GitHub Actions on every push. The badge's scope is
deliberately narrow: passing means *"the deterministic rules are intact"*, not
*"the system works"*.

The suite does not only check whether an answer was produced; for answerable
questions it also inspects the **content**: length limit, whether the context was
copied verbatim, and whether the citation line is present. These checks exist for a
reason: while the tests were fully passing, the interface was observed reproducing
the context word for word — the suite only asked "was an answer produced", so it did
not count that as a failure.

**Why edge cases are reported separately:** there is no single "correct answer" for
these inputs; what matters is that the system handles them soundly. The criterion is
**did not crash + returned a reasonable answer**. Had they been put in the main suite
with a "must say I don't know" expectation, a general question like "tell me
everything" would land in the 0.30–0.75 grey zone and go to the relevance grader —
and since GPU inference is not fully deterministic, the result could vary between
runs.

**How the copy metric was calibrated.** The first version said *"any 120-character
verbatim span is a copy"*. Adding new documents tripped it, and the investigation
surfaced two things. First, the metric itself was flawed: in an answer that repeats
the context three times, the longest verbatim span is only a third of the total
length, so **the very failure it was meant to catch slipped through**. It was
rewritten to measure the **total covered ratio** and verified against three shapes of
regurgitation. Second, the model really was copying: 83% of that answer was verbatim.
An explicit anti-copy instruction was added to the prompt and tried three times —
**all three produced identical output**. Instructions do not fix it. The model is
good at extraction and weak at synthesis; when a question's answer sits in a single
source sentence, expect near-verbatim output.

## Ablation Study: is every layer actually needed?

Claiming that five defence layers are all necessary is just that — a claim. It can
only be proven by switching each layer off and measuring. `python ablation.py`
disables each one in turn and re-runs the suite:

| Configuration | Main suite | Contribution |
|---|---|---|
| **Full system** | **19/19** | baseline |
| Lexical gate off | 18/19 | **1 case** |
| Proper-noun check off | 18/19 | **1 case** |
| LLM relevance grader off | 19/19 | 0 cases |
| Number verification off | 19/19 | 0 cases |
| Cosine threshold off | 19/19 | 0 cases |
| **Bare RAG** (no defences) | **16/19** | **3 cases** |

Three conclusions:

**1. Bare RAG loses 3 of the 4 unanswerable questions.** These checks are not
decoration; the project does not work without them.

**2. The two largest contributions come from deterministic checks.** The lexical gate
and the proper-noun check — neither makes an LLM call.

**3. Three layers contribute 0 cases in this suite.** That does not mean they should
be deleted; more likely **the test suite does not contain the failure type they
defend against**. Exactly such a gap was found (below) and added to the suite.

This table was measured three times as the knowledge base grew (6, 10 and 15
documents). The number of cases each layer saves did not change, so the results are
not an artefact of one corpus size.

### The gap the ablation exposed

When the result "the LLM relevance grader contributes 0 cases" appeared, the layer
was not deleted. The question asked first was: *what does this layer defend against,
and does the suite measure it?* It did not. The missing case was **a question whose
words appear in the documents but whose answer does not**:

```
Question: "What are the names of the Duelist agents?"
Answer  : "Jett, Sage, Raze and Breach. (Source: ajan_rolleri.txt)"
```

**No agent name appears anywhere in the documents.** The system invented them and
cited a source on top of it — making false information look trustworthy (the content
is wrong too: Sage is a sentinel, Breach an initiator). No check caught it: the
lexical gate passed it because `duelist` matched, and the number check saw no digits.

The fix generalises the number check: **proper nouns that appear in the answer but
nowhere in the context**. A model paraphrasing does not invent new proper nouns; if
one appears, that information did not come from the context. Before being added it
was tested against the valid answers: **0 false rejections**.

## Design Decisions and Limitations

- **Vector search:** SQLite has no native vector type, so embeddings are stored as
  JSON-serialised text and cosine similarity is brute-forced in Python/NumPy. This is
  sufficient for small corpora (a few hundred chunks); at scale a dedicated vector
  index (FAISS, pgvector, …) would be required.

- **Why the `openai` client instead of `foundry-local-sdk`:** the SDK describes itself
  as a *"control-plane SDK"* and `FoundryLocalManager` exposes only model/service
  management methods (`discover_eps`, `download_and_register_eps`,
  `start_web_service`, `stop_web_service`); it has **no inference method**, and
  `openai` is already one of its own dependencies. Since Foundry Local exposes an
  OpenAI-compatible local REST endpoint, inference goes directly to that endpoint
  through the `openai` client — the SDK is not bypassed, its own inference path is
  used directly. Service management (port discovery, model loading) goes through the
  `foundry` CLI, because the service port changes between restarts and is read from
  `foundry server status -o json`.

- **The `/no_think` directive:** `qwen3-4b` is a reasoning model and by default emits
  a long internal reasoning block before answering. This caused both slowness and, on
  some questions, a risk of never finishing. Adding `/no_think` to the system prompt
  disabled that step and cut the average time by roughly a factor of ten.

- **Output cleaning:** the model occasionally injects single CJK characters into
  Turkish answers (a known small-model flaw). These are stripped with a regex before
  display.

- **Lexical gate (hybrid search):** if none of the question's distinctive words appear
  in the retrieved text, that text cannot be answering the question — however high
  the cosine score looks.

  The definition of *"distinctive"* is critical: `valorant` appears in every document
  and therefore distinguishes nothing, so words with high document frequency are
  filtered out (a plain application of **IDF**). Two adaptations were needed for
  Turkish: character normalisation (documents are written without Turkish
  diacritics while users type `görevi`) and coarse stem matching (an agglutinative
  language: `turnuva` → `turnuvalarında`).

  **Measured weakness — synonyms:** because the gate compares words, it can reject
  valid questions phrased differently. In a trial of 9 paraphrased questions **5 were
  falsely rejected**. One cause was subtle: in "how does the ultimate charge?" the word
  `yetenek` (ability) does exist in the documents but is **filtered out as too
  ubiquitous**, leaving only synonyms behind.

  *Tried and rejected:* falling back to ubiquitous words when no distinctive word
  matches. Measured: it rescues 3 of the 5 paraphrases but **breaks 3 of the 4
  unanswerable questions** (the ubiquitous word `valorant` lets everything through).
  Dropped.

  *Adopted:* a small knowledge-base-specific **domain glossary** (`ALIASES` — 13
  entries such as `para→kredi`, `bomba→spike`, `ulti→nihai`). The paraphrase pass rate
  rose from **4/9 to 6/9** with no regression on unanswerable questions. The remaining
  3 failures come from **retrieval**, not the gate: the corresponding word appears
  nowhere in the retrieved chunks. The glossary is corpus-specific and must be revised
  when the documents change.

  The gate is **tolerant**: a single match is enough. The goal is not to filter valid
  questions but to catch those with no lexical support at all. If a question has no
  distinctive words ("tell me everything"), the gate abstains. It was measured against
  the whole suite before integration: **0 false rejections**. Because it runs before
  any LLM call, it is also fast: unanswerable questions are rejected in **0.08 seconds**.

- **Three-zone relevance decision:** for chunks that pass the lexical gate,
  - `score >= 0.75` → certainly relevant, no LLM call (deterministic and fast)
  - `score < 0.30` → certainly irrelevant, no LLM call
  - in between (grey zone) → sent to the **relevance grader**

  **Why a relevance grader:** small language models cannot reliably follow an
  open-ended instruction such as "do not answer if the context lacks the answer"
  (tested — it hallucinated). The same model is markedly better at the **binary
  classification** task *"does this text answer this question? YES/NO"*. Each grey-zone
  chunk is graded with that question and only those that pass reach generation. (Known
  in the literature as retrieval grading / the CRAG pattern.)

- **Groundedness check (last line of defence):** if the answer contains a number that
  never appears in the context, it is rejected and the fallback message is returned.
  This check is deliberately **deterministic** — an LLM-based groundedness check was
  tried and failed because the model approved its own hallucination.

- **Proper-noun grounding:** if the answer contains a proper noun absent from the
  context, the answer is rejected (`lexical_gate.ungrounded_proper_nouns`). Two rules
  keep false positives low: sentence-initial words are ignored (every sentence starts
  with a capital) and comparison uses normalised coarse stems.

  **Known limitation — lower case:** since the check looks at capitalised words, an
  invented name written in lower case (`jett, sage, raze`) is missed. This was measured
  and confirmed. A case-insensitive version was tried: flag every content word in the
  answer that **appears nowhere in the corpus**. It was dropped after measurement — in
  15 valid answers, 13 ordinary Turkish words (`fakat`, `zararlı`, `bozabilir`) are
  absent from the corpus, so the rule would reject half of the valid answers. The
  capitalisation rule is a better trade-off than its measured alternative.

- **Citations are added in code:** rule 5 of the system prompt asks the model to end
  its answer with `(Source: file.txt)`. When a test was added for this rule, it turned
  out **the model skips it in roughly a third of answers**. The filename is already
  known from the retrieval step, so the line is added in code when missing
  (`ensure_source_citation`). The prompt rule remains; when the model writes it
  correctly the function does nothing.

- **Answer length is enforced in code:** rule 1 of the system prompt says "at most 3
  sentences", but that is a request, not a guarantee — on vague questions the model
  produced 1000–1300 character answers. `limit_answer()` enforces two limits together:
  at most 3 units (a sentence **or** a list line, since the model sometimes produces
  lists without punctuation) and 700 characters. The character limit applies even when
  a single unit exceeds it, cutting at a word boundary.

- **Repetition-loop detection:** small models occasionally fall into a loop repeating
  the same phrase dozens of times. Observed example: the answer to *"what is a
  crossfire?"* repeated the same clause about twenty times over 1000+ characters. Such
  output **cannot be fixed by trimming** — a trimmed version is still meaningless.

  The criterion is deterministic: the **unique-word ratio**. In a healthy answer most
  words differ (measured values above 0.7); in a looping output the same few words
  repeat, so the ratio collapses (threshold 0.35; answers under 30 words are not
  evaluated). When a loop is detected the answer is generated once more; if the second
  attempt also loops, nothing is shown to the user. The same check is part of the test
  suite.

- **Empty-query guard:** an empty or whitespace-only query used to go straight to the
  embedding API, where Foundry Local returned HTTP 400
  (`Embedding input at index 0 is null, empty...`), crashing the application with an
  uncaught exception. The guard sits at the top of `retrieve_and_gate()`, so both the
  non-streaming and streaming paths are covered.

## Decision Trace Panel

A RAG pipeline is invisible from the outside: only the answer (or "I don't know")
appears on screen, with no indication of **which check** produced it. That makes
debugging harder and leaves the user uncertain — did the assistant look and fail to
find, or did it never look?

For that reason a **🔍 Decision trace** panel was added under every answer. Real
output:

```
Question: "What does armour do?"
  ✅ Retrieval           3 chunks retrieved · top score 0.540
  ✅ 1. Cosine threshold 0.540 ≥ 0.3
  ✅ 2. Lexical support  matched: zirh (searched: zirh, yarar)
  ✅ 3. Relevance grader 3/3 chunks accepted · 3 sent to the LLM
  ✅ 4. Groundedness     numbers and proper nouns in the answer appear in the context
  ➖ 6. Citation line    the model did not write it — added in code

Question: "How large is the Valorant tournament prize pool?"
  ✅ Retrieval           3 chunks retrieved · top score 0.598
  ✅ 1. Cosine threshold 0.598 ≥ 0.3
  ⛔ 2. Lexical support  searched: turnu, odul, havuz — none appear in the text
```

The second example shows at a glance why cosine similarity is not enough: a score of
**0.598** looks perfectly "relevant", yet none of the question's words appear in the
text. The panel also makes visible which decisions were made **without any LLM call**.

## Why "I don't know"

On its own, "I don't have that information in my documents" leaves the user stuck:
was the question misunderstood, or is the information genuinely absent? The lexical
gate already computes this, so it is shown to the user as well:

```
Question: "How large is the Valorant tournament prize pool?"
  I don't have that information in my documents.
  These words never appear in the documents: "turnuvalarinda", "odul"
  — this topic is not in the knowledge base.
```

This note appears only when **the lexical gate is the rejecting layer**; the other
checks reject for different reasons, and a missing-word list would be misleading
there. The answer itself does not change; this is an additional explanation below it.

The visual counterpart of the same idea is in the sources panel: words matched by the
lexical gate are **highlighted** inside the document text, so the basis for the
decision is visible rather than merely described.

## Operational Note — GPU memory and timing

Foundry Local accumulates GPU memory across many consecutive requests, and generation
times slow down noticeably. **This is not a code defect**, it is the service's memory
behaviour. Measured values (RTX 4060 Ti, 8 GB VRAM):

| State | GPU memory | Average time |
|---|---|---|
| Service freshly started | 5581 MiB | **1.43 s/question** |
| After one test run | 7798 MiB | — |
| After several consecutive runs | ~7900 MiB (96%) | 4.7 – 8.6 s/question |

The distinguishing evidence: the slowdown affects **only questions that generate**;
gate-rejected questions return in 0.07 seconds in every state, because they never
reach the GPU.

All timings in this document were therefore measured on a freshly started service.
To reproduce them:

```bash
foundry server restart
foundry model load qwen3-embedding-0.6b
foundry model load qwen3-4b
```

## References

Resources followed in this project:

**Primary reference (community content):**
- [Building Your First Local RAG Application with Foundry Local](https://techcommunity.microsoft.com/blog/azuredevcommunityblog/building-your-first-local-rag-application-with-foundry-local/4501968)
  — Microsoft Tech Community

**Official Microsoft Learn documentation:**
- [What is Foundry Local?](https://learn.microsoft.com/en-us/azure/foundry-local/what-is-foundry-local)
- [Foundry Local documentation](https://learn.microsoft.com/en-us/azure/foundry-local/)
  — installation and "Get started" steps
- [Tutorial: Build a RAG application](https://learn.microsoft.com/en-us/azure/foundry-local/tutorials/tutorial-build-rag-app)
  — in particular the "Generate document embeddings" and "Search for relevant
  documents" sections; `get_top_chunks()` here is the tutorial's `find_relevant()`
  moved onto SQLite
- [Prompt engineering techniques](https://learn.microsoft.com/en-us/azure/foundry/openai/concepts/prompt-engineering)
  — system message design and prompt construction basics
- [Tutorial: Use a SQLite database in a Windows app](https://learn.microsoft.com/en-us/windows/apps/develop/data-access/sqlite-data-access)
  — advantages of SQLite for local storage

**Other:**
- [SQLite documentation](https://www.sqlite.org/) — database engine

**AI assistance:** Claude (Anthropic) was used during development, particularly for
debugging, code review and documentation. All measurements in this document were
produced by running the system on this machine and can be reproduced with
`python test_qa.py` and `python ablation.py`.

### About the knowledge base

The 15 documents in `data/` were written for this project; they are not copied from
any source. The content is deliberately kept **patch-independent**: instead of agent
names, map lists, weapon prices and similar details that change between releases, it
describes the game's durable mechanics (economy logic, role functions, round flow,
positioning principles). The knowledge base therefore does not go stale with every
game update.

Official sources for verifying game information or extending the knowledge base:

- [VALORANT Beginner's Guide](https://playvalorant.com/en-us/news/announcements/beginners-guide/)
  — Riot Games' official introductory guide
- [VALORANT Support](https://support-valorant.riotgames.com/hc/en-us)
  — official support documentation on game mechanics and systems
- [playvalorant.com](https://playvalorant.com/en-us/) — the game's official site

To change the knowledge base, add `.txt` files to `data/` and run `python ingest.py`.
