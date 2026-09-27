def verify_claim(claim: dict, evidence: dict, threshold: float = 0.5) -> dict:
    """
    claim: {
        "statement": str,
        "location": [row, col] or region id,
        "confidence": float  # how confident the VLM was in its own claim
    }
    evidence: {
        "mask": 2D array or region-level change flags,
        "magnitude": float,       # how large the detected change is
        "confidence": float       # how confident the change-detection model is
    }
    Returns: {"label": "supported" | "unsupported" | "uncertain", "confidence": float, "abstain": bool}
    """
    # Combined confidence: how much do the claim and the evidence agree?
    evidence_confidence = evidence.get("confidence", 0.0)
    claim_confidence = claim.get("confidence", 0.0)

    # crude first-pass scoring: average the two signals
    combined_confidence = (evidence_confidence + claim_confidence) / 2

    if combined_confidence >= threshold:
        label = "supported"
    elif combined_confidence >= threshold * 0.5:
        label = "uncertain"
    else:
        label = "unsupported"

    abstain = combined_confidence < threshold

    return {
        "label": label,
        "confidence": round(combined_confidence, 3),
        "abstain": abstain,
    }


if __name__ == "__main__":
    fake_claim = {"statement": "New building constructed in region A", "location": "A", "confidence": 0.7}
    fake_evidence = {"mask": None, "magnitude": 0.8, "confidence": 0.6}

    result = verify_claim(fake_claim, fake_evidence)
    print(result)