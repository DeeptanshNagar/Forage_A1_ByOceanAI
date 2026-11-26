"""Entry point for Streamlit Community Cloud: the full ForgeAI UI (build, results, chat) on a hosted model API.

Main file path on Streamlit Cloud: deploy/streamlit/streamlit_app.py
Secrets (root level, exposed as environment variables): FORGE_API_KEY = "<Groq API key>"
"""
import os
import runpy
from pathlib import Path

os.environ.setdefault("FORGE_UI_CONFIG", "configs/cloud_groq.toml")
runpy.run_path(str(Path(__file__).resolve().parents[2] / "forge" / "runner" / "app_ui.py"), run_name="__main__")
