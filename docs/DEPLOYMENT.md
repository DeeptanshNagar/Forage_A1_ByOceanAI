# Deploying the ForgeAI UI

The Streamlit app (`forge/runner/app_ui.py`) has two tabs:
- **Factory:** upload documents and a brief, watch the stages run, read `REPORT.md`.
- **Chat:** talk to any `final_agent.json`.

## Local

```bash
pip install -e ".[ui]"
forge ui                       # or: streamlit run forge/runner/app_ui.py
```

## Streamlit Community Cloud (the full app, including the Build tab)

1. Go to share.streamlit.io → **Create app** → *Deploy a public app from GitHub*.
2. Repository `DeeptanshNagar/Agent_Smith_ByOceanAI`, branch `main`, main file path
   **`deploy/streamlit/streamlit_app.py`**. Its folder holds the app's `requirements.txt`, so the lean root
   `requirements.txt` stays reserved for the Vercel function.
3. Advanced settings → Python **3.11** → Secrets:
   ```toml
   FORGE_API_KEY = "<Groq API key>"
   ```
   The entry point selects [`configs/cloud_groq.toml`](../configs/cloud_groq.toml): Groq's OpenAI-compatible API,
   `qwen/qwen3.8-27b` for every role, TF-IDF embeddings (no torch), rate-limit-aware retries (waits as long as Groq
   asks, up to 60 s), and small builds (20 evals, 2 iterations) to fit the free tier.
4. Deploy. A build makes a few hundred model calls, so on Groq's free tier expect it to take a while, rate-limit waits
   included, and keep the browser tab open while it runs.
5. Without a key, select **Mock** in the sidebar: the full pipeline runs offline, with clearly labelled mock results.

Differences from the local profile: the judge is the same model family as the agent (Groq's other chat models break the
JSON/tool protocol), so self-preference is less defended; the deterministic checks still veto every LLM pass and the
judge self-test reports its accuracy.

## Vercel (results site + live chat API)

`public/` (static page; its data comes from `python scripts/build_site.py`), `api/chat.py` (Python function) and
`vercel.json`. Set `GROQ_API_KEY` (optionally `GROQ_MODEL`) as a Vercel environment variable, then run `vercel deploy --prod`.
The factory is not hosted there, because a build exceeds serverless time limits.

## Hugging Face Spaces (Streamlit SDK)

Create a Space with SDK = Streamlit and add this `README.md` header in the Space repo:

```yaml
---
title: ForgeAI
sdk: streamlit
app_file: forge/runner/app_ui.py
python_version: "3.11"
---
```

Use `deploy/streamlit/requirements.txt` as `requirements.txt` and set the same `FORGE_*` variables as Space secrets. A GPU
Space can instead run Ollama in a Docker Space (`sdk: docker`) using `ollama serve & streamlit run …`, with
`configs/ollama_small.toml` as the config.

## Notes

- Runs write to `runs/`, which is ephemeral on both platforms; download `REPORT.md` / `final_agent.json` from the UI host
  or mount persistent storage.
- The `http_api` tool only reaches allow-listed hosts (Open-Meteo); outbound network must be allowed for agents that use it.
