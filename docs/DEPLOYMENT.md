# Deploying the ForgeAI UI

The Streamlit app (`forge/runner/app_ui.py`) has two tabs:
- **Factory:** upload documents and a brief, watch the stages run, read `REPORT.md`.
- **Chat:** talk to any `final_agent.json`.

## Local

```bash
pip install -e ".[ui]"
forge ui                       # or: streamlit run forge/runner/app_ui.py
```

## Streamlit Community Cloud

1. Push the repo to GitHub.
2. New app → main file `forge/runner/app_ui.py`, Python 3.11, requirements file `requirements-deploy.txt`.
3. Secrets (App settings → Secrets) point the client at a hosted OpenAI-compatible endpoint, since Community Cloud
   cannot run Ollama:
   ```toml
   FORGE_BASE_URL = "https://<your-endpoint>/v1"
   FORGE_API_KEY = "<key>"
   FORGE_AGENT_MODEL = "<model id>"
   FORGE_FACTORY_MODEL = "<model id>"
   FORGE_JUDGE_MODEL = "<a different model id>"
   FORGE_EMBEDDING_BACKEND = "tfidf"   # avoids downloading torch on the free tier
   ```
   Streamlit exposes secrets as environment variables, and `forge/config.py` reads every `FORGE_*` variable.
4. Without an endpoint, toggle **Mock LLM backend** in the sidebar: the full pipeline runs offline, with clearly
   labelled mock results.

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

Add `requirements-deploy.txt` as `requirements.txt` and set the same `FORGE_*` variables as Space secrets. A GPU
Space can instead run Ollama in a Docker Space (`sdk: docker`) using `ollama serve & streamlit run …`, with
`configs/ollama_small.toml` as the config.

## Notes

- Runs write to `runs/`, which is ephemeral on both platforms; download `REPORT.md` / `final_agent.json` from the UI host
  or mount persistent storage.
- The `http_api` tool only reaches allow-listed hosts (Open-Meteo); outbound network must be allowed for agents that use it.
