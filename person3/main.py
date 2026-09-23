from fastapi import FastAPI

app = FastAPI()

@app.get("/")
def home():
    return {"status": "EviChange API is running"}

@app.post("/evidence")
def get_evidence():
    # Person 1 will eventually fill this with real change-detection output
    return {"status": "stub", "mask": None, "magnitude": None, "confidence": None}

@app.post("/interpret")
def interpret():
    # Person 2 will eventually fill this with VLM-generated claims
    return {"status": "stub", "claims": []}

@app.post("/verify")
def verify():
    # This is yours to build out — verifier + abstention logic
    return {"status": "stub", "label": "uncertain", "confidence": 0.0}
