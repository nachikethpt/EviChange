from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from verifier import verify_claim

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # fine for local dev; you'd restrict this in production
    allow_methods=["*"],
    allow_headers=["*"],
)

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


class Claim(BaseModel):
    statement: str
    location: str
    confidence: float

class Evidence(BaseModel):
    magnitude: float
    confidence: float

class VerifyRequest(BaseModel):
    claim: Claim
    evidence: Evidence
    threshold: float = 0.5


@app.post("/verify")
def verify(request: VerifyRequest):
    result = verify_claim(request.claim.dict(), request.evidence.dict(), request.threshold)
    return result