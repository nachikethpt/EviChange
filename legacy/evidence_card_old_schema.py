"""
Evidence Card generator (Student 1's module).

Computes deterministic, checkable spectral evidence from a bi-temporal
Sentinel-2 patch pair. This is the "ground truth" the verification gate
checks VLM claims against -- everything here is arithmetic on band
values, nothing is model-generated or subjective.

Expects 4-band patches (Blue, Green, Red, NIR) as numpy arrays shaped
(4, H, W), plus optional SWIR/DEM/boundary inputs for BSI and boundary
overlap. Falls back gracefully when those extras aren't available yet.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, asdict
from datetime import date
from typing import Optional

import numpy as np

# Band indices for a 4-band (B, G, R, NIR) patch
BLUE, GREEN, RED, NIR = 0, 1, 2, 3

# Thresholds -- these are starting points; tune against real data once
# the study-area imagery is confirmed. Documented here so Student 3's
# gate and the eventual report can cite exactly what was used.
CHANGE_MASK_THRESHOLD = 0.15   # normalized difference magnitude counted as "changed" per pixel
SIGNIFICANT_FRACTION = 0.05    # fraction of patch pixels changed to call the patch "significantly changed"


@dataclass
class EvidenceCard:
    """Structured, JSON-serializable evidence for one bi-temporal patch pair."""
    site_id: str
    date_before: str
    date_after: str
    ndvi_delta_mean: float          # mean (NDVI_after - NDVI_before); negative = vegetation loss
    ndbi_delta_mean: float          # mean (NDBI_after - NDBI_before); positive = more built-up/bare
    change_mask_fraction: float     # fraction of pixels exceeding CHANGE_MASK_THRESHOLD
    change_direction: str           # "increase" | "decrease" | "none" -- of disturbed/bare surface
    boundary_overlap: Optional[bool]  # True/False if a concession boundary was supplied, else None
    data_quality: str               # "high" | "medium" | "low" -- placeholder until real cloud-% wiring

    def to_json(self) -> str:
        return json.dumps(asdict(self), indent=2)


def _ndvi(patch: np.ndarray) -> np.ndarray:
    nir, red = patch[NIR].astype(np.float32), patch[RED].astype(np.float32)
    return (nir - red) / (nir + red + 1e-8)


def _ndbi_proxy(patch: np.ndarray) -> np.ndarray:
    """
    True NDBI needs a SWIR band, which a plain 4-band (B,G,R,NIR) patch
    doesn't have. Until Student 1 wires in the real SWIR band from the
    Sentinel-2 export, this proxy uses (Red - NIR)/(Red + NIR) -- bare
    ground and built-up/disturbed surfaces are relatively bright in Red
    and comparatively dim in NIR versus vegetation, so this trends the
    same direction as true NDBI even though it's a weaker signal.
    Swap this out for real NDBI the moment SWIR is available -- don't
    ship the proxy in the final report without flagging it as such.
    """
    red, nir = patch[RED].astype(np.float32), patch[NIR].astype(np.float32)
    return (red - nir) / (red + nir + 1e-8)


def generate_evidence_card(
    patch_before: np.ndarray,
    patch_after: np.ndarray,
    site_id: str,
    date_before: str,
    date_after: str,
    boundary_mask: Optional[np.ndarray] = None,
    data_quality: str = "medium",
) -> EvidenceCard:
    """
    Build an Evidence Card from a before/after 4-band patch pair.

    patch_before, patch_after: numpy arrays, shape (4, H, W), bands in
        order (Blue, Green, Red, NIR).
    boundary_mask: optional boolean array, shape (H, W), True where the
        pixel falls inside a known mining concession boundary. If
        omitted, boundary_overlap is reported as None (unknown) rather
        than guessed.
    """
    if patch_before.shape != patch_after.shape:
        raise ValueError(f"Shape mismatch: before {patch_before.shape} vs after {patch_after.shape}")

    ndvi_before, ndvi_after = _ndvi(patch_before), _ndvi(patch_after)
    ndbi_before, ndbi_after = _ndbi_proxy(patch_before), _ndbi_proxy(patch_after)

    ndvi_delta = ndvi_after - ndvi_before
    ndbi_delta = ndbi_after - ndbi_before

    # A pixel counts as "changed" if either index moved more than the threshold
    changed_pixels = (np.abs(ndvi_delta) > CHANGE_MASK_THRESHOLD) | (np.abs(ndbi_delta) > CHANGE_MASK_THRESHOLD)
    change_fraction = float(np.mean(changed_pixels))

    ndbi_delta_mean = float(np.mean(ndbi_delta))
    if change_fraction < SIGNIFICANT_FRACTION:
        change_direction = "none"
    elif ndbi_delta_mean > 0:
        change_direction = "increase"   # more bare/disturbed surface than before
    else:
        change_direction = "decrease"

    boundary_overlap = None
    if boundary_mask is not None:
        if boundary_mask.shape != changed_pixels.shape:
            raise ValueError(f"boundary_mask shape {boundary_mask.shape} doesn't match patch {changed_pixels.shape}")
        # "Overlap" = a meaningful share of the CHANGED pixels fall inside the boundary
        changed_in_boundary = np.sum(changed_pixels & boundary_mask)
        boundary_overlap = bool(changed_in_boundary > 0 and changed_in_boundary / max(np.sum(changed_pixels), 1) > 0.3)

    return EvidenceCard(
        site_id=site_id,
        date_before=date_before,
        date_after=date_after,
        ndvi_delta_mean=float(np.mean(ndvi_delta)),
        ndbi_delta_mean=ndbi_delta_mean,
        change_mask_fraction=change_fraction,
        change_direction=change_direction,
        boundary_overlap=boundary_overlap,
        data_quality=data_quality,
    )


if __name__ == "__main__":
    # Quick self-test with synthetic data -- swap for real Sentinel-2
    # patches (via rasterio) the moment they're available.
    rng = np.random.default_rng(42)

    print("Self-test: synthetic 'mining expansion' patch pair")
    before = np.stack([
        rng.normal(400, 30, (64, 64)),   # Blue
        rng.normal(550, 30, (64, 64)),   # Green
        rng.normal(300, 30, (64, 64)),   # Red -- vegetation, low red
        rng.normal(3200, 100, (64, 64)),  # NIR -- vegetation, high NIR
    ])
    after = before.copy()
    # Simulate a new bare patch appearing in one quadrant
    after[RED, :20, :20] += 700     # bare soil reflects more in red
    after[NIR, :20, :20] -= 2000    # and much less in NIR than vegetation

    card = generate_evidence_card(before, after, site_id="test_site_01",
                                    date_before="2024-01-15", date_after="2024-08-20")
    print(card.to_json())