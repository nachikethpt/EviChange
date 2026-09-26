# EviChange multi-agent pipeline

Runnable LangGraph proof of concept for the EviChange workflow:
Orchestrator → Ingestion → Preprocessing → DL Analysis → Geo-VLM → Publishing.
The current tools return deterministic mock data, so no GPU, API key, or Earth
Engine account is required.

## Run

```powershell
python -m pip install -r requirements.txt
python run_demo.py
```

If `python` is not available in a terminal, use the Python launcher instead:

```powershell
py -m pip install -r requirements.txt
py run_demo.py
```

The project code is in `agents/`. `agents.graph.run_pipeline` is the integration
entry point; replace marked `SWAP-IN` functions in `agents/tools.py` when real
imagery, preprocessing, models, and prompts are ready.
