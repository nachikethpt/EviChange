# Legacy: deprecated claim schema

These files come from the early prototype, which used a **different, incompatible
claim schema** (`claim_type`, `estimated_change_direction`, `confidence`,
`reasoning`) and a patch-level 4-band evidence card with a Red/NIR NDBI proxy.
The full prototype is at `E:\claude\evichange\src\` (kept outside this repo).

They are **not imported by anything** and are kept only for provenance. The
current contract is `agents/schema.py`; see `docs/decisions.md` (D1) for why the
old schema was deprecated and which three ideas were carried into
`agents/verifier.py`.
