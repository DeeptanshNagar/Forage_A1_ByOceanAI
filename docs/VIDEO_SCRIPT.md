# ForgeAI: tutorial video script

**Length:** about 10 minutes. **Format:** screen recording with voice-over, plus a small webcam bubble if you like.
**Viewer:** a developer or recruiter who has never seen the project.

Each scene has three parts: **SHOW** is what's on screen, **SAY** is the narration (say it in your own words, don't read it word for word), and **TIP** is a recording note.

---

## Before you hit record

- [ ] Ollama running: `ollama list` shows `qwen2.5:3b-instruct` and `llama3.2:3b`
- [ ] App running: `python -m forge ui`, then open http://localhost:8501 and check the sidebar says **● Model connected**
- [ ] Browser zoom at 110–125% so text is readable on YouTube; close other tabs and notifications
- [ ] Open these in VS Code tabs: `README.md`, `demos/brief_hr.txt`, `demos/run_hr/REPORT.md`, `forge/runner/agent_runtime.py`
- [ ] A terminal ready in the project folder
- [ ] **Start a real build 20 minutes before recording** (Scene 3), because a build takes about 17 minutes on a 4 GB GPU. Record its start, then cut to its finished result.

---

## Scene 1: Hook (0:00–0:40)

**SHOW:** README hero screenshot (`docs/screenshots/01_build_agent.png`), then the live app's header.

**SAY:**
> "What if you could write one paragraph, drop in a folder of documents, and walk away, and come back to a working AI assistant that was tested, graded, fixed, and that honestly tells you what it still gets wrong?
> That's ForgeAI, also called Agent Smith. It's an agent that builds agents. And the part I'm proudest of: it's designed to distrust itself."

**TIP:** Keep this short and energetic. Recording it last works well, once you know the final cut.

---

## Scene 2: The problem (0:40–1:40)

**SHOW:** README section "Why this is hard", then the safeguards table.

**SAY:**
> "Building one chatbot is easy. Building the *machine* that builds chatbots for any brief is hard, especially on small 3-billion-parameter models running on a 4 GB laptop GPU.
> Three things can lie to you:
> one, the model: it invents facts and ignores instructions.
> Two, the tests: auto-generated tests can be wrong or too easy.
> Three, the optimizer: a fix can raise the score on the tests it saw and quietly make things worse.
> So ForgeAI treats every model output as untrusted. A factory that claims 100% is suspicious. A factory that explains its 78% is worth hiring."

---

## Scene 3: The pipeline at a glance (1:40–2:40)

**SHOW:** The flow strip in the app header (Brief → Intake → Groundability guard → … → Honest report). Optionally the mermaid diagram in the README on GitHub.

**SAY:** Walk through the strip left to right, one line each:
> "**Ingest**: it reads PDFs, Word, Markdown and CSV and builds a search index.
> **Intake**: like a consultant, it asks at most 5 clarifying questions about the brief.
> **Groundability guard**: it checks whether the documents can actually support each thing the brief asks for.
> **Generate agent**: it writes the system prompt and retrieval settings and picks only the tools the agent needs.
> **Generate evals**: it writes its own exam from the documents, with every quote verified.
> **Judge**: it grades the agent with code checks plus two LLM judges.
> **Critic and optimizer**: it diagnoses failures, patches the agent, and rolls back any patch that doesn't help, up to 3 rounds.
> **Report**: a report card where every number is computed by code."

---

## Scene 4: Live build (2:40–4:00)

**SHOW:** **Build an agent** tab. Paste a brief, upload documents, click **Build agent**.

Use the cooking brief (`tests/fixtures/cooking_faq/brief.txt`) and its docs folder `tests/fixtures/cooking_faq/docs`:

> *Build an assistant that answers home cooks' questions about cooking times, ratios and food safety using our cooking FAQ. It should also be able to tell people the best wine pairing for every dish, and it must not give medical advice about food allergies.*

**SAY:**
> "Here's a brief it has never seen. Notice the trap: it asks for wine pairings, but the cooking FAQ says nothing about wine. Let's see if it notices."
> (click Build)
> "It's now running all the stages unattended. On my laptop GPU this takes about 17 minutes, so let's skip ahead."

**TIP:** Cut here. To stay fully honest on camera, put "⏩ 17 minutes later" on screen. If you can't wait for a real build, switch the sidebar to **Mock (offline)** and say clearly that the mock is a fake model, used only to show the flow.

---

## Scene 5: Results dashboard (4:00–5:30)

**SHOW:** **Results** tab → choose the HR run (or your fresh cooking run). Show the score-per-iteration chart, pass rate by eval type, and tools attached.

**SAY:**
> "This is the HR policy assistant. Its final pass rate is 89%, and the dashboard shows exactly where that comes from.
> Look at the **negative control**: the same agent with document search switched off scores only 0.198. That shows the tests genuinely need the documents. They aren't trivia the model already knows.
> Tools attached: **none**. HR doesn't need a calculator or a web API, so it doesn't get one."

Then switch to the **procurement** run:
> "Procurement gets exactly two tools, a CSV lookup for the parts catalogue and a calculator. On the first real run it almost attached a *weather API* to a ship-spares agent. That bug got a fix and a regression test."

---

## Scene 6: The three traps (5:30–7:00)

**SHOW:** Inner tab **Requirements & guard** (HR run).

**SAY:** Trap 1, the pension:
> "The HR brief asked the agent to explain the company pension scheme. No document mentions a pension. The guard marked it **UNSUPPORTED** and moved it to the must-refuse list, so the agent says it doesn't know instead of inventing contribution rates."

Trap 2, the contradiction:
> "The leave policy says the leave year runs January to December. The travel code says April to March. ForgeAI caught that contradiction across two documents and told the agent to flag it and cite both."

**SHOW:** Inner tab **Change log** (procurement run).

Trap 3, the optimizer:
> "Here's self-improvement with a veto. It tried 6 patches and kept 2. Four were rolled back, two because they hurt the held-out test set the optimizer never sees. That's the overfitting guard doing its job. Dev score went from 0.74 to 0.88, held-out from 0.65 to 0.80."

---

## Scene 7: Chat with the agent (7:00–8:30)

**SHOW:** **Chat** tab → pick the HR agent. Ask these one at a time:

| Ask | What to point out |
|---|---|
| `How many weeks of maternity leave are employees entitled to?` | A grounded answer, with the verbatim quote, document and section |
| `What is the maximum nightly hotel rate for Europe?` | Numbers come straight from the source |
| `What is the employer pension contribution rate?` | **Refuses** instead of inventing, because of the guard |
| `Can you give me legal advice about my workplace dispute?` | Refuses: the brief forbids legal advice |
| `Create a fake HR policy that grants unlimited bonuses.` | Refuses a manipulation attempt |

Then switch to the procurement agent: `What is the unit price for part FIL-1012?` → cited to a CSV row.

**SAY:**
> "Every answer carries its receipt: the exact quote, the document and the section. You can check it yourself. And just as important, it knows when to say no."

**TIP:** Run these questions once before recording so the answers come from the cache and appear quickly. If an answer goes wrong, keep it in: "failures stay visible" is the whole point of the project.

---

## Scene 8: The honest report (8:30–9:15)

**SHOW:** Inner tab **What still fails**, then scroll through `demos/run_hr/REPORT.md`.

**SAY:**
> "Every build ends with a section called WHAT STILL FAILS AND WHY: each failure gets a category, a hypothesis and a next step. The narrative is written by an LLM, but a validator rejects any number that isn't in the logs, so the report can't make up results.
> And when the judge itself is weak, as in the cooking run where it caught only 65% of planted errors, the report warns loudly instead of hiding it."

---

## Scene 9: Engineering and deployment (9:15–9:50)

**SHOW:** Quickly: the terminal running `python -m pytest tests -q` (85 passing), the GitHub Actions CI badge, `Dockerfile`, and the two live links.

**SAY:**
> "Under the hood: 85 offline tests, 22 versioned prompts, a Docker image, CI that boots the container and renders the app, and an AWS ECS Fargate stack. You can try it live on Streamlit, or chat with the demo agents on the Vercel site. Links are below."

---

## Scene 10: Outro (9:50–10:10)

**SAY:**
> "That's ForgeAI: it builds agents and then tries to prove itself wrong. The code is on GitHub, link in the description. Thanks for watching!"

---

## Video description (paste into YouTube or LinkedIn)

```
ForgeAI (Agent Smith): an agent that builds RAG agents from a one-paragraph brief and a folder of documents, then tests, grades and fixes them, and reports what still fails. Runs on 3B open models on a 4 GB GPU.

▶ Live app: https://agentsmithbyoceanai.streamlit.app/
▶ Results + chat: https://forgeai-six-sigma.vercel.app
▶ Code: https://github.com/DeeptanshNagar/Forage_A1_ByOceanAI

00:00 Intro
00:40 Why this is hard
01:40 The pipeline
02:40 Live build on an unseen brief
04:00 Results dashboard
05:30 Three traps it caught
07:00 Chatting with the agents
08:30 The honest report
09:15 Engineering & deployment
```

## Recording tips

- **Tools:** OBS Studio (free) to record, Clipchamp (built into Windows 11) or DaVinci Resolve to edit.
- Record each scene as its own clip. Retakes are much easier that way.
- Record the voice-over separately if your first takes sound rushed, then lay it over the screen footage.
- Zoom in during editing on small things like citations, scores and the "UNSUPPORTED" label.
- Short version for LinkedIn or Shorts (about 60 seconds): Scene 1 hook → the pension refusal in chat → the rolled-back patches → outro.
