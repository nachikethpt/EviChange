# Evidence-gated claims about land-cover change: a Quang Ninh case study (draft)

**Status:** draft written 2026-10-25. Sections:
- **Introduction and discussion:** written below.
- **Methods:** `docs/methods_draft.md`.
- **Related work:** `docs/related_work.md` (check the [PK] and [U] citations first).
- **Results:** a skeleton. Every number comes from `scripts/results_tables.py` (Tables 1–7, Figure 1) once the 30 sites
  are adjudicated, so no result is written here before it exists.

**[TBD]** marks decisions still open before the Phase 4 freeze.

## Abstract (skeleton)

Vision-language models (VLMs) can describe what changed between two satellite images. Their descriptions mix what the
imagery shows with what the model expects to see. We test whether making a VLM cite structured change-detector
evidence, then checking every claim with a deterministic verifier, reduces the unsupported claims that reach a user. Our
case study is a coal-mining coast in Quang Ninh, Vietnam, with Sentinel-2 imagery from 2018/19 and 2022/23 and 30
self-labelled sites. We compare three ways of producing claims:
- a template,
- an ungated VLM (Qwen2.5-VL-7B) that sees only the images,
- the same VLM gated by evidence.

A frontier model run ungated is a secondary comparison. Post-gate hallucination was **[R1]** % for gated and **[R2]** %
for ungated, a difference of **[R3]** points (95 % CI **[R4]**). Gating kept **[R5]** true claims per site, against
**[R6]** for ungated. **[One sentence on what the result means, written after the result.]**

## 1. Introduction

Satellite change detection tells an analyst *where* land cover changed. Decision makers want to know *what* changed,
how much, and why. VLMs promise to supply those answers in plain language. They now accept image pairs (TEOChat,
EarthDial, CCExpert; `related_work.md` § 1) and can be asked to compare a before and an after scene. For monitoring,
that convenience is also the risk. A fluent sentence about "open-pit mining expanding into forest" carries the same
apparent authority whether the imagery shows it or the model inferred it from context. On change tasks, general VLMs
score close to chance (GPT-4o 0.17 and Qwen2-VL 0.20 on GEOBench-VLM's change task). Remote-sensing hallucination
benchmarks still evaluate single images and never count a hallucinated *change* or a hallucinated *cause* of change.

Two remedies come from the language-model literature, and neither is enough on its own:
- **Retrieval or tool grounding** gives the model the right inputs, but grounded systems still produce unsupported
  statements (17–33 % for retrieval-augmented legal tools).
- **Citation** lets a reader check a statement, but audits find that about half of cited content does not support the
  sentence it is attached to. Learned attribution checkers reach only about 80 % macro-F1.

Remote-sensing agents such as Change-Agent and RS-Agent ground their *inputs* in detector outputs. None of them checks
its *output* sentences against those outputs.

EviChange closes that loop for one well-defined case. A threshold change detector produces a structured evidence record
for an area: regions, areas, locations, index changes and land-cover classes. The VLM must write claims that cite
fields of this record, and must abstain on causes, legality and the future, which no imagery can show. A deterministic
verifier then checks every claim against the cited fields before the user sees it. Because the claim is bound to the
evidence in the model's own output schema, checking needs no learned parser or judge. That is the design choice this
study tests.

We ask:
1. Does evidence gating lower the share of false or unverifiable claims that reach the user (post-gate hallucination),
   compared with the same VLM used ungated?
2. What does gating cost in informativeness: true claims per site, recall of real change types, abstention?
3. How much of what remains is the detector's error rather than the model's (faithful-but-false claims)?
4. How well does a deterministic verifier agree with human judgement of evidential support, and how does it compare
   with a learned NLI verifier?

Contributions:
- A claim schema and a deterministic verifier for bi-temporal land-cover change claims: 32 reason codes, with
  extensions for shoreline and coastal built-up area.
- A blinded two-axis evaluation (truth against ground truth, support against the evidence) that separates generation
  errors from detection errors. It is applied to four claim-generation conditions on 30 self-labelled sites, with
  pre-specified paired statistics.
- A 10 m Sentinel-2 study of a coast where earlier work is Landsat-based and spans decades. It includes a 24-month
  shoreline and coastal built-up series.
- An open web GIS that runs the same pipeline for any area, as a tool. It is validated only in Quang Ninh.

## 2. Related work

See `docs/related_work.md`. For the paper, condense it to about one page, organised as: temporal remote-sensing VLMs;
hallucination measurement; attribution and verification; index-based change detection in Quang Ninh; evaluation of
small human-labelled studies.

## 3. Methods

See `docs/methods_draft.md`.

## 4. Results (skeleton: fill from `docs/results/` after adjudication)

### 4.1 Ground truth and detector
- Detector precision **[Table 7]**, background change rate **[Table 7]**.
- The Phase 3 labels already show 8 of 10 background sites labelled as changed. The detector misses lasting change
  away from its regions, so the background stratum is not a "no change" control (`eval_audit.md`, finding 1).
- Label agreement: κ **[0.63, CI]** on 10 sites; change types identical on 3 of 10.

### 4.2 Hallucination before and after the gate (primary result)
- Table 1 and Figure 1: hallucination and post-gate hallucination per condition.
- **Primary result:** gated − ungated post-gate rate, **[R3] [R4]**, paired site bootstrap. Exact Wilcoxon p
  **[Table 6]**, on **[n]** sites with a rate in both conditions.
- Per stratum (Table 2). The background stratum is read through the D18 rule for claims about the detector **[TBD]**.

### 4.3 What gating costs
- Table 4: true claims per site, change-type recall, abstention, and missed change at background sites **[TBD: D18]**.
- Retention: claims kept by the gate, against all claims emitted (Table 1, *Passed* / *Claims*).

### 4.4 Where the remaining errors come from
- Faithful-but-false claims (Table 1). These are the detector's errors carried through a correct citation.
- By claim type (Table 5): which levels (L1–L3, shoreline, coastal built) carry the residual hallucinations.

### 4.5 The verifier
- Table 3: catch rate, precision of rejections, and κ against human support, per condition.
- Ablation (`scripts/verifier_ablation.py`): the rule verifier against an NLI verifier on the same claims, with an
  exact McNemar test.

### 4.6 Secondary comparisons
- Gated Qwen against ungated GPT (D16), and gated against fine-tuned gated (D17). Holm-adjusted **[TBD]**.

### 4.7 Coastal extension
- Phase 14 extraction accuracy (`scripts/phase14_report.py`):
  - Dynamic World classes, by κ;
  - shoreline position, by RMSE and bias;
  - coastal built-up cells;
  - CCDC change month, within ± 1 month (`scripts/ccdc_change_month.py`).

## 5. Discussion (draft; revise against the results)

**What a gate guarantees, and what it does not.** The verifier guarantees that a passed claim agrees with the
*evidence record*. It does not guarantee that the claim is true about the ground. Any gate built on a detector inherits
the detector's errors, and the faithful-but-false rate measures exactly that. In this design, a lower post-gate
hallucination rate means fewer claims the evidence cannot back. If gated still has a high faithful-but-false rate, the
next improvement is a better detector, not a better prompt. We expect this especially on spoil heaps and reclaimed
land, where NDBI confuses bare soil with built-up surfaces and Dynamic World is weakest.

**A gate can win by saying less.** Any filter can lower its error rate by deleting claims. Conformal factuality and
abstention studies show this. We therefore report the post-gate rate together with the following, and judge gating by
all of them together:
- retention;
- true claims per site;
- change-type recall;
- missed change at background sites.

**[TBD: whether gating kept enough true claims to be useful, with numbers.]**

**Background sites.** Eight of ten random background sites changed, by the labels. Over four years, much of a mining
coast changes. In this setting, a model that says "something changed" is right more often than a detector that missed
the change. The background stratum therefore tests the *detector's* coverage as much as any model's honesty. How
claims that restate the detector are adjudicated (D18) decides how this shows up in the numbers, which is why the rule
was fixed before the claims existed.

**Deterministic against learned verification.** **[TBD after the ablation.]** The deterministic verifier is exact
within its claim grammar, and its errors come from the heuristic text fallback used on unstructured claims. The NLI
verifier needs no grammar but is probabilistic. The ablation shows which errors matter for this task.

**Limitations.**
- The ground truth is self-labelled, and the main labeller built the system. The adjudicator is on the same team, so
  blinding is partial: condition, verdict and region ids are hidden, but writing style is not.
- n = 30 sites: only differences of about 20 points or more are reliably detectable.
- One area, one date pair, 10 m imagery, and a threshold detector whose 0.10 threshold has no literature standard.
- Shoreline positions carry tide noise; only the 24-month trends are reported.
- The general-area app is a capability, not validated outside Quang Ninh.

**Outlook.**
- Report the gate's operating point (retention against residual unsupported rate) as a curve, not one number.
- Replace the threshold detector with a trained one where labels allow; the gate design does not change.
- Extend the claim grammar (counts, distances to features) so more of what a model wants to say can be checked.

## 6. Conclusion

**[Write after the results: two or three sentences on the primary result, the informativeness cost, and the
evidence-not-truth caveat.]**
