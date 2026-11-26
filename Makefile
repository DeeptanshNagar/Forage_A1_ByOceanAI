# ForgeAI make targets. On Windows use Git Bash / WSL make, or run the commands directly.
PY ?= python
SMALL = --config configs/ollama_small.toml

.PHONY: install test mock-demo demo-hr demo-procurement demos models synth ui baseline-hr regress-demo

install:
	$(PY) -m pip install -e ".[dev,synth]"

test:
	$(PY) -m pytest tests -q

mock-demo:
	$(PY) -m forge run --mock --brief-file tests/fixtures/cooking_faq/brief.txt --docs tests/fixtures/cooking_faq/docs \
		--non-interactive --run-id mock_demo

models:
	ollama pull qwen2.5:3b-instruct
	ollama pull llama3.2:3b

synth:
	$(PY) scripts/synthesize_docs.py

demo-hr:
	$(PY) -m forge run $(SMALL) --brief-file demos/brief_hr.txt --docs demos/sources/hr --non-interactive \
		--run-id demo_hr --copy-to demos/run_hr

demo-procurement:
	$(PY) -m forge run $(SMALL) --brief-file demos/brief_procurement.txt --docs demos/sources/procurement \
		--non-interactive --run-id demo_procurement --copy-to demos/run_procurement

demos: demo-hr demo-procurement

baseline-hr:
	$(PY) -m forge baseline $(SMALL) --run-id demo_hr --agent demos/hand_written/hr_agent.json

ui:
	$(PY) -m forge ui
