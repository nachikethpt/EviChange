# Evidence gates close remote sensing's hallucination gap

EviChange draws on five bodies of work that have not yet been joined: bi-temporal remote-sensing vision-language models (VLMs), hallucination measurement, attribution and claim verification, index-based land-change monitoring, and small-sample evaluation statistics. The central finding is that **no prior work found measures how many unsupported change claims reach a user after a deterministic evidence gate**, in remote sensing or in any other domain. The searches behind this review were broad but not exhaustive, so the paper should say "to our knowledge". Each neighbouring literature leaves a specific opening:

- **Temporal RS VLMs.** They have multiplied since mid-2024 (ChangeChat, CDChat, TEOChat, EarthDial, CCExpert and others). Almost all are trained on sub-metre to ~3 m imagery and scored with n-gram caption metrics, which reward template matching rather than factual support.
- **General VLMs on change tasks.** They score poorly. On GEOBench-VLM the best model (LLaVA-OneVision) reaches only 41.7 % multiple-choice accuracy, about twice random [V], and per-model change-task scores near 0.2 are reported but [U] (see § 1).
- **RS hallucination benchmarks.** These appeared in 2024–2026 (RSPOPE, RSHallu, RSHBench, VHM, GeoArbiter). All are single-image, and none counts hallucinated *changes* or hallucinated *causes* of change.
- **Attribution research.** Citing a source does not make a claim supported. About half of generative-search sentences are not fully supported by their citations, and learned attribution checkers reach only ~80% macro-F1.
- **Tool-using RS agents.** Change-Agent, RS-Agent, GeoLLM-Engine and ThinkGeo ground the LLM's *inputs* in tool outputs but never check its *output* claims.

The closest formal relative of EviChange's gate is conformal factuality, which filters claims to a statistical correctness target using a learned scorer. EviChange swaps that for a deterministic check of typed record fields. The Quang Ninh literature is dominated by Landsat and decade-long intervals. It documents coal-mine spoil dumped into the sea at Cam Trung and Cam Thinh, and a more than fourfold growth of Ha Long's urban area. That supplies both a validation target and a resolution gap that 10 m Sentinel-2 can fill. Finally, the evaluation literature sets firm requirements for a 30-site study:

- site-level (cluster) resampling;
- Wilson intervals only for site-level proportions;
- exact paired tests with pre-specified handling of zero differences;
- kappa reported as a pilot-scale reliability check.

## How to read the verification tags

The notes behind this review were compiled in a session where arxiv.org, MDPI, Taylor & Francis and several other publisher sites could not be fetched directly. Facts therefore rest on search-result abstracts, venue pages, GitHub READMEs and repository records. The authors must check every tagged item before submission. The notes used several tag vocabularies, and this report keeps each item's original status under one scheme:

| Tag in this report | Meaning | Tags in the notes it covers |
|---|---|---|
| **[V]** | Bibliographic details (and any quoted figure) confirmed in the research session via search results or the official venue or repository listing | [V], [V-search] |
| **[PK]** | From prior knowledge or memory; citation believed correct, but **not re-verified**. Numbers marked [PK] must be re-checked before quoting | "prior knowledge, not re-verified", [PK], [BK], [K], [UNVERIFIED] where it means "from memory" |
| **[U]** | Seen only in an aggregator, secondary page or snippet, or details incomplete or conflicting. **Do not cite without checking** | [U], [SNIPPET], [UNVERIFIED] where it means "secondary/aggregator" |
| **[computed]** | Number calculated by the research team, not taken from a source | [computed] |

Items with no tag in the remote-sensing VLM section come from search results that quote the papers, CVF pages or GitHub READMEs, which is the [V] level. The notes do not mark them individually.

## Verification log (2026-10-25)

Checked by web search after the review was written; the tags in the text are updated to match.

| Item | Result |
|---|---|
| Change-Agent venue | **V**: IEEE TGRS 2024, doi:10.1109/TGRS.2024.3425815 |
| EarthDial downstream count | **V**: 44 datasets (CVPR 2025, pp. 14303–14313) |
| Abstention survey | **V**: Wen, Yao, Feng, Xu, Tsvetkov, Howe & Wang, TACL 13:529–556, doi:10.1162/tacl_a_00754 |
| SourceCheckup | **V**: Wu, Wu et al., Nature Communications 16:3615 (2025); 50–90 % not fully supported; GPT-4o + search ≈ 30 % of statements unsupported |
| Magesh et al. | **V**: Journal of Empirical Legal Studies 22:216–242 (2025); 17–33 % hallucination |
| HallusionBench | **V**: GPT-4V 31.42 % question-pair accuracy (CVPR 2024) |
| FActScore | **V**: ChatGPT 58 % (EMNLP 2023, doi:10.18653/v1/2023.emnlp-main.741) |
| SAFE / LongFact | **V**: 72 % agreement with crowd annotators; right in 76 % of 100 disagreements (NeurIPS 2024) |
| GEOBench-VLM | **Corrected**: best overall is LLaVA-OneVision 41.7 %, not GPT-4o; per-model change-task scores still **U** |
| DDFAV / RSPOPE | arXiv:2411.02733 only; no journal version found |
| Nguyen et al. 2022 | **V**: Giang Cong Nguyen, Khac Vu Dang, Tuan Anh Vu, Anh Khac Nguyen & Christiane Weber, Remote Sensing 14(5):1241 |
| Vu et al. 2024 | **V**: Anh Tuan Vu, Duc Anh Ngo, Thi Phuong Hao Nguyen & Cong Giang Nguyen, Eur. J. Remote Sens. 57(1), doi:10.1080/22797254.2024.2398108 |
| Duong Thi Loi et al. 2021 | **V**: Vietnam J. Earth Sci. 43(3):249–272, doi:10.15625/2615-9783/16066 |
| Pelich et al. 2021 (notes) | **V, title differs**: “Coastline detection based on Sentinel-1 time series for ship- and flood-monitoring applications”, IEEE GRSL 18(10):1771–1775, doi:10.1109/LGRS.2020.3008011 |
| Quang Ninh PSInSAR (IJRS 2021) | **Not found**: confirm the DOI or drop |
| Bui, Maier & Austin 2014 | Figures V, journal still unconfirmed |

Not re-checked here (still as tagged): the remaining [PK] canon (FEVER, SciFact, TabFact, FactCC, QAGS, SummaC, AlignScore,
CoVe, SelfCheckGPT, ProgramFC, the index and change-detection classics) and the 2025–2026 preprints tagged [U].

## Temporal remote-sensing VLMs learned sub-metre change, not Sentinel-2 change

### A first wave of single-image models, then a temporal second wave

The first generation of remote-sensing VLMs adapted general instruction-tuned models to overhead imagery one image at a time.

- **GeoChat** (CVPR 2024) injects RS knowledge into LLaVA by freezing the visual encoder and projector and LoRA-tuning the LLM ([ResearchGate](https://www.researchgate.net/publication/385038529_GeoChatGrounded_Large_Vision-Language_Model_for_Remote_Sensing); [Kuckreja et al., arXiv:2311.15826](https://arxiv.org/abs/2311.15826)). Its LLaVA-1.5/Vicuna-7B base and its ~318k-instruction GeoChat_Instruct set are [PK].
- **LHRS-Bot** appeared at ECCV 2024 and **EarthGPT** in IEEE TGRS 2024 ([Awesome-RS-MLLM list](https://github.com/ZhanYang-nwpu/Awesome-Remote-Sensing-Multimodal-Large-Language-Model)). LHRS-Bot's LLaMA-2-7B/CLIP base and EarthGPT's multi-sensor MMRS-1M data are [PK] ([Muhtar et al., arXiv:2402.02544](https://arxiv.org/abs/2402.02544); [Zhang et al., arXiv:2401.16822](https://arxiv.org/abs/2401.16822)).
- **RSGPT** (2023) and **SkyEyeGPT** (2024) appear in the same list ([Awesome-RS-MLLM list](https://github.com/ZhanYang-nwpu/Awesome-Remote-Sensing-Multimodal-Large-Language-Model)). RSGPT's RSICap/RSIEval sets (arXiv 2307.15266) and SkyEyeGPT's SkyEye-968k set and later ISPRS JPRS version are [PK].
- **GeoGround** for visual grounding was found only by title; its arXiv id 2411.11904 is [PK] ([VLM-meets-RS survey](https://arxiv.org/pdf/2505.14361)).

Four surveys frame the field:

- Liu et al.'s spatiotemporal VLM survey (*IEEE Geoscience and Remote Sensing Magazine* 2025, DOI 10.1109/MGRS.2025.3598283) ([GitHub](https://github.com/Chen-Yang-Liu/Awesome-RS-SpatioTemporal-VLMs))
- "Vision-Language Modeling Meets Remote Sensing" ([arXiv:2505.14361](https://arxiv.org/pdf/2505.14361))
- a survey of RS foundation models ([arXiv:2503.22081](https://arxiv.org/pdf/2503.22081))
- a survey of data-driven RS VLMs ([arXiv:2610.31304](https://arxiv.org/html/2610.31304))

Since mid-2024 a second wave has taken **bi- or multi-temporal input**. The spatiotemporal survey lists ChangeExp, ChangeChat, CDChat, TEOChat, GeoLLaVA, VisTA, RSUniVLM, EarthDial, UniRS, Falcon, DynamicVL and Change-Agent among them ([Awesome-RS-SpatioTemporal-VLMs](https://github.com/Chen-Yang-Liu/Awesome-RS-SpatioTemporal-VLMs)).

- **TEOChat** (Irvin et al., ICLR 2025) is a LLaVA-style assistant trained on TEOChatlas. That set has **554,071 examples**, of which 245,210 are temporal, drawn from xBD, S2Looking, QFabric and fMoW sequences of 1–8 images. The authors claim it beats GPT-4o and Gemini-1.5 Pro at modelling image sequences, but the numbers sit in table images the session could not read ([GitHub](https://github.com/ermongroup/teochat); [HF dataset](https://huggingface.co/datasets/jirvin16/TEOChatlas)).
- **EarthDial** (Soni et al., CVPR 2025) fine-tunes InternVL2 with a Phi-3-mini LLM on **more than 11.11M instruction pairs** spanning RGB, SAR and multispectral data, and handles bi- and multi-temporal change detection ([CVF](https://openaccess.thecvf.com/content/CVPR2025/papers/Soni_EarthDial_Turning_Multi-sensory_Earth_Observations_to_Interactive_Dialogues_CVPR_2025_paper.pdf)). The CVPR paper, the IBM Research listing and the MBZUAI record all say **44 downstream datasets** [V], so cite 44 (the poster's 37 applications is a different count) ([CVPR poster](https://cvpr.thecvf.com/virtual/2025/poster/34460)). Whether its multispectral data is Sentinel-2 specifically could not be confirmed.
- **CDChat** (IGARSS 2025) uses a shared ViT-L/14 encoder for both dates and trains on SYSU-CD and LEVIR-CD change text ([README](https://github.com/techmn/cdchat/blob/main/README.md)).
- **ChangeChat** (ICASSP 2025) calls itself the first bi-temporal VLM and uses ChangeChat-87k built from LEVIR-CC/MCI ([ResearchGate](https://www.researchgate.net/publication/390536998_ChangeChat_An_Interactive_Model_for_Remote_Sensing_Change_Analysis_via_Multimodal_Instruction_Tuning)).
- **GeoLLaVA** LoRA-tunes LLaVA-NeXT on 100k fMoW pairs ([survey list](https://github.com/Chen-Yang-Liu/Awesome-RS-SpatioTemporal-VLMs)).
- **UniRS** unifies single-image, bi-temporal and video tasks on VILA-1.5 ([arXiv:2412.20742](https://arxiv.org/pdf/2412.20742)).
- Newer bi-temporal MLLMs were verified by title only: BTCChat ([arXiv:2509.05895](https://arxiv.org/pdf/2509.05895)), RSICCLLM ([arXiv:2606.28266](https://arxiv.org/pdf/2606.28266)), ChangeQuery ([arXiv:2604.22333](https://arxiv.org/pdf/2604.22333)), "Decoding the Delta" ([arXiv:2604.14044](https://arxiv.org/pdf/2604.14044)) and ViLaCD-R1 ([arXiv:2512.23244](https://arxiv.org/pdf/2512.23244)).

The pattern that matters for EviChange is the training data. LEVIR-CD/CC (0.5 m), SYSU-CD, SECOND, xBD, S2Looking, QFabric and fMoW are all very-high-resolution sources. **No model found was trained primarily on 10 m Sentinel-2 bi-temporal data with SWIR**, so EviChange's zero-shot Qwen2.5-VL-7B setting is out of distribution even for RS-specialised temporal VLMs. That conclusion is our inference from the dataset lists.

### Change-captioning benchmarks reward templates, not truth

Change-captioning and change-VQA datasets are almost uniformly VHR. The survey tables list the following ([Awesome-RS-SpatioTemporal-VLMs](https://github.com/Chen-Yang-Liu/Awesome-RS-SpatioTemporal-VLMs)):

| Dataset | Imagery | Resolution | Size |
|---|---|---|---|
| LEVIR-CC | 256×256 px | 0.5 m | 10,077 pairs / 50,385 captions |
| WHU-CDC | WHU-CD | 0.075 m | 7,434 pairs |
| SECOND-CC | SECOND | 0.3–3 m | 6,041 pairs ([arXiv:2501.10075](https://arxiv.org/pdf/2501.10075)) |
| CDVQA | SECOND | not given | 122k QA |
| CC-Foundation (CCExpert) | not given | not given | 200k pairs / 1.2M captions |
| **Dubai-CC** | Landsat-7, 50×50 px | **30 m** | 500 pairs |

Dubai-CC is the **only medium-resolution change-captioning set**. Its origin paper (Hoxha et al., IEEE TGRS 2022) and CDVQA's (Yuan et al., IEEE TGRS 2022) are [PK]. Methods range from non-LLM captioners to MLLM-based ones:

- non-LLM captioners such as RSICCformer (Liu et al., TGRS 2022, [PK]), Chg2Cap ([arXiv:2304.01091](https://arxiv.org/pdf/2304.01091)) and SAT-Cap ([arXiv:2501.08114](https://arxiv.org/html/2501.08114v1));
- MLLM-based captioners such as Semantic-CC ([arXiv:2407.14032](https://arxiv.org/pdf/2407.14032)) and CCExpert, which reports S\*m = 81.80 on LEVIR-CC in a work-in-progress preprint ([arXiv:2411.11360](https://arxiv.org/pdf/2411.11360));
- PromptCC (Liu et al., IEEE TGRS 2023, authors and venue [PK]), which first classifies change vs no-change and then captions with a frozen LLM ([IEEE Xplore](https://ieeexplore.ieee.org/abstract/document/10271701)). That "decide whether change exists first" step is an architectural guard against inventing change on unchanged pairs, and it is the closest captioning precedent for a gate.

Evaluation uses BLEU, METEOR, ROUGE-L, CIDEr-D and SPICE, and these metrics have documented failures:

- On LEVIR-CC's changed subset, **only 11.5% of captions are unique and the three most frequent templates cover 38.3%**, so n-gram scores can reward template matching over semantic accuracy ([HIMEC, arXiv:2608.12502](https://arxiv.org/pdf/2608.12502)).
- Reference-based RS caption metrics correlate *negatively* with a ground-truth preference benchmark ([Chen et al., arXiv:2604.22855](https://arxiv.org/pdf/2604.22855)).
- BLEU lacks a recall term ([IJCAI 2025 survey](https://www.ijcai.org/proceedings/2025/1180.pdf)).
- Lexical metrics can even rank text-only LLMs above VLMs that see the image ([arXiv:2512.00887](https://arxiv.org/html/2512.00887)).

A high CIDEr score therefore says nothing about whether each stated change is supported by the imagery, and that is the property EviChange's unsupported-claim count measures. No study was found that validates an LLM judge for factual correctness in RS change captioning, and no change-captioning dataset exists for 10 m Sentinel-2 or for mining or coastal land cover.

### General VLMs fail on change, and more so outside RGB

Benchmarks consistently report weak general-VLM performance on temporal RS tasks.

- **GEOBench-VLM** (Danish et al., ICCV 2025) finds the best model, **LLaVA-OneVision, at only 41.7% MCQ accuracy, about twice random, with GPT-4o slightly lower** [V, corrected 2026-10-25: earlier notes named GPT-4o as best]. On its farm-pond change-detection task **GPT-4o scores 0.1711 and Qwen2-VL 0.1974** [U: not found in the abstract or category tables; read the ICCV results table before quoting]. The authors read this as evidence that VLMs struggle to use temporal dependencies ([CVF](https://openaccess.thecvf.com/content/ICCV2025/papers/Danish_GEOBench-VLM_Benchmarking_Vision-Language_Models_for_Geospatial_Tasks_ICCV_2025_paper.pdf)). The preprint and published numbers differ, so cite the ICCV version ([ResearchGate](https://www.researchgate.net/publication/386336171_GEOBench-VLM_Benchmarking_Vision-Language_Models_for_Geospatial_Tasks)).
- Zhang & Wang's VLEO benchmark finds GPT-4V good at captioning but poor at localization and counting ([CVPRW 2024](https://openaccess.thecvf.com/content/CVPR2024W/EarthVision/html/Zhang_Good_at_Captioning_Bad_at_Counting_Benchmarking_GPT-4V_on_Earth_CVPRW_2024_paper.html)).
- XLRS-Bench calls both general and RS MLLMs "still insufficient" ([arXiv:2503.23771](https://arxiv.org/pdf/2503.23771)).
- Zero-shot VILA-1.5 scored **6.22 CIDEr-D on LEVIR-CC** and hallucinated a non-existent object ([UniRS, arXiv:2412.20742](https://arxiv.org/pdf/2412.20742)).
- BTCChat compared against TEOChat only after fine-tuning TEOChat on LEVIR-CC ([arXiv:2509.05895](https://arxiv.org/pdf/2509.05895)).
- VRSBench (NeurIPS 2024 D&B) is single-image and has no change task [PK].

Direct evidence on medium-resolution and multispectral input is thin but points the same way:

- GEOBench-VLM accuracy drops on Sentinel-2 bands packed into three pseudo-RGB channels ([ICCV supplemental](https://openaccess.thecvf.com/content/ICCV2025/supplemental/Danish_GEOBench-VLM_Benchmarking_Vision-Language_ICCV_2025_supplemental.pdf)).
- On the human-annotated Sentinel2Cap set, zero-shot Qwen3-VL-8B does best on RGB and slightly worse on 20 m multispectral bands that lie outside its pretraining ([arXiv:2605.03189](https://arxiv.org/html/2605.03189v1)).
- TimeSenCLIP argues that VHR-designed architectures favour spatial context over the spectral and temporal signal that matters at medium resolution ([ISPRS JPRS 2026](https://www.sciencedirect.com/science/article/pii/S0924271626001577)).
- Llama3-MS-CLIP shows multispectral pretraining helps ([arXiv:2503.15969](https://arxiv.org/pdf/2503.15969)).

**No published zero-shot Qwen2.5-VL-7B result on a bi-temporal RS change benchmark was found**, and no controlled 10 m-vs-sub-metre comparison exists. EviChange's SWIR composites will likely sit further from the VLM's pretraining than true RGB does. That inference argues for gating SWIR-derived claims on index evidence. At 10 m, a 256-pixel chip spans ~2.56 km, so the object-level claims VHR captioners make (individual buildings, roads) become high-risk.

### Tool-using RS agents call detectors but do not audit their own sentences

Change-Agent is the nearest precedent for an LLM orchestrating a change detector (Liu, Chen, Zhang, Qi, Zou & Shi, IEEE TGRS 2024, doi:10.1109/TGRS.2024.3425815 [V]; arXiv:2403.19646). Its MCI model, trained on LEVIR-MCI, acts as the "eyes" with pixel-level detection and captioning branches. An LLM acts as the "brain" for counting and **change-cause analysis** ([arXiv](https://arxiv.org/html/2403.19646v3)). Change-Agent offers causes; EviChange deliberately abstains on them.

- **GeoLLM-Engine** (CVPRW 2024) generated more than 500k multi-tool tasks over 1.1M images and scores task completion ([CVF](https://openaccess.thecvf.com/content/CVPR2024W/EarthVision/html/Singh_GeoLLM-Engine_A_Realistic_Environment_for_Building_Geospatial_Copilots_CVPRW_2024_paper.html)).
- **RS-Agent** reports more than 95% task-planning accuracy over 18 tasks ([arXiv:2406.07089](https://arxiv.org/html/2406.07089v3)).
- **ThinkGeo** evaluates 436/486 agentic tasks over 14 tools and reports "persistent challenges in … robust multimodal grounding" ([arXiv:2505.23752](https://arxiv.org/pdf/2505.23752)). A secondary review says SAR final-answer accuracy falls below 6% for all models while tool-call accuracy stays high [U] ([Moonlight review](https://www.themoonlight.io/en/review/thinkgeo-evaluating-tool-augmented-agents-for-remote-sensing-tasks)).
- Remote Sensing ChatGPT ([arXiv:2401.09083](https://arxiv.org/abs/2401.09083), [PK]), GeoGPT ([arXiv:2307.07930](https://arxiv.org/abs/2307.07930), [PK]) and the two distinct "GeoAgent" papers ([arXiv:2410.18792](https://arxiv.org/abs/2410.18792); ACL Findings 2024, both [PK]) complete the picture.

The general-domain pattern is the same: ReAct, Toolformer, Visual ChatGPT, ViperGPT and VisProg ground inputs or compute answers, but none checks free-text claims against tool output ([ReAct](https://arxiv.org/abs/2210.03629); [Toolformer](https://arxiv.org/abs/2302.04761); [Visual ChatGPT](https://arxiv.org/abs/2303.04671); [ViperGPT](https://arxiv.org/abs/2303.08128); [VisProg](https://arxiv.org/abs/2211.11559); all [PK]). The ThinkGeo gap between well-formed tool calls and wrong answers supports checking claims against evidence rather than trusting that a tool was called.

## Hallucination metrics remain single-image and response-level

### Taxonomies give EviChange its "false" and "unverifiable" labels

The NLG literature splits hallucination into **intrinsic** (contradicts the source) and **extrinsic** (cannot be verified from the source). Maynez et al. introduced the split for summarization and noted that extrinsic content can still be true, which separates faithfulness from factuality ([ACL 2020](https://arxiv.org/abs/2005.00661), [PK]). Ji et al. then systematized it across NLG tasks ([ACM Computing Surveys 2023](https://arxiv.org/abs/2202.03629), [PK]). Huang et al. recast it for LLMs as factuality vs faithfulness hallucination ([arXiv:2311.05232](https://arxiv.org/abs/2311.05232); ACM TOIS 2025, [PK]). Multimodal surveys type hallucinations as object/category, attribute and relation errors and blame language priors overriding vision ([Bai et al.](https://arxiv.org/abs/2404.18930); [Liu et al.](https://arxiv.org/abs/2402.00253); both [PK]).

RS-specific taxonomies are new:

- RSHBench separates factual grounding errors from logical errors [V] ([arXiv:2603.02754](https://arxiv.org/abs/2603.02754)).
- RSHallu adds an image-level category; its full category list could not be retrieved [V] ([arXiv:2602.10799](https://arxiv.org/abs/2602.10799)).

Kalai et al. explain why models hallucinate at all: benchmarks score abstention as zero, so guessing is rewarded [V] ([OpenAI](https://openai.com/index/why-language-models-hallucinate/); [arXiv:2509.04664](https://arxiv.org/abs/2509.04664)).

The mapping to EviChange is direct. A "false" claim is intrinsic hallucination relative to the image pair and ground truth. An "unverifiable" claim, such as a cause ("due to mining") or a function ("a new port"), is extrinsic hallucination. **No published taxonomy covers temporal or change hallucination.** EviChange can propose change-specific types: existence of change, change class, magnitude or extent, location, and cause.

### Benchmarks probe objects; claim-level metrics come from text factuality

VLM hallucination benchmarks fall into three families.

- **Caption-level object metrics.** CHAIR matches mentioned objects to COCO labels and reports instance-level CHAIR_i and caption-level CHAIR_s ([Rohrbach et al., EMNLP 2018](https://arxiv.org/abs/1809.02156), [PK]).
- **Yes/no probes.** POPE samples random, popular and adversarial negatives. Its authors argue that CHAIR is unstable across prompts ([Li et al., EMNLP 2023](https://arxiv.org/abs/2305.10355), CHAIR critique [V], details [PK]). AMBER combines generative and discriminative tracks ([arXiv:2311.07397](https://arxiv.org/abs/2311.07397), [PK]).
- **Judge-scored free-form QA.** MMHal-Bench has GPT-4 rate 96 free-form answers on a 0–6 scale ([Sun et al.](https://arxiv.org/abs/2309.14525), [PK]). GAVIE/LRV-Instruction introduced negative instructions so models learn to reject false premises ([ICLR 2024](https://arxiv.org/abs/2306.14565), [PK]).

Other benchmarks add diagnostic depth. HallusionBench separates language hallucination from visual illusion and reports GPT-4V at 31.42% question-pair accuracy, the best of 15 models, all others below 16% [V] ([CVPR 2024](https://arxiv.org/abs/2310.14566)). M-HalDetect annotates descriptions below the sentence level ([AAAI 2024](https://arxiv.org/abs/2308.06394), [PK]). **FaithScore**, the closest VLM analogue to EviChange's metric, splits answers into atomic facts and checks each against the image with a visual-entailment model ([Findings EMNLP 2024](https://arxiv.org/abs/2311.01477), [PK]).

Meta-evaluation counsels caution. The HQM study finds that closed-ended benchmarks have stronger validity but weaker test-retest reliability. Free-form benchmarks lose reliability partly through variance in the LLM judge [V] ([arXiv:2406.17115](https://arxiv.org/abs/2406.17115)). MLLM-as-a-Judge finds that multimodal judges agree with humans on pairwise comparisons but "diverge significantly" on scoring [V] ([ICML 2024](https://proceedings.mlr.press/v235/chen24h.html)). By contrast, HALP reports **97% agreement** between a GPT-4 labeller and a 3-expert consensus (Fleiss' κ = 0.89) in a narrowly specified task [V] ([arXiv:2603.05465](https://arxiv.org/abs/2603.05465)). This supports EviChange's use of human ground truth for the primary endpoint. It also sets a standard: any automatic judge should come with a reported human-agreement statistic.

EviChange's claim-level rate (false plus unverifiable claims over total claims) follows the **decompose-then-verify** paradigm from long-form text factuality:

- **FActScore** reports ChatGPT biographies at **58%** supported atomic facts, with an automated estimator within ~2% of humans [V in the grounding notes; PK in the hallucination notes, so re-check] ([Min et al., EMNLP 2023](https://arxiv.org/abs/2305.14251)).
- **SAFE/LongFact** adds a search-based verifier and the recall-aware F1@K. Its ~72% agreement with crowd annotators is [PK, numbers verify] ([Wei et al., NeurIPS 2024](https://arxiv.org/abs/2403.18802)).
- **VeriScore** argues that not every claim is verifiable and extracts only verifiable ones [V] ([Findings EMNLP 2024](https://arxiv.org/abs/2406.19276)).
- **RAGAS** faithfulness scores statements against retrieved context ([EACL 2024](https://arxiv.org/abs/2309.15217), [PK]).

The decomposition step is a documented weak point:

- scores shift with the decomposition method [V] ([Wanner et al., arXiv:2403.11903](https://arxiv.org/abs/2403.11903); authors and venue [PK]);
- FActScore over-decomposes and VeriScore drops context [V] ([Hu et al., arXiv:2411.02400](https://arxiv.org/abs/2411.02400); NAACL 2025 venue [PK]);
- fixed-atomicity decomposition suits some inputs poorly [V] ([arXiv:2503.15354](https://arxiv.org/abs/2503.15354));
- domain text breaks generic decomposers [V] ([MedScore, arXiv:2505.18452](https://arxiv.org/abs/2505.18452)).

EviChange has the VLM emit atomic claims in a fixed schema. That **sidesteps decomposition sensitivity and makes the denominator deterministic**. Unlike FActScore and SAFE, which assume every claim can be verified, EviChange treats "unverifiable" as a reportable failure.

### Remote-sensing hallucination work is single-image

RS-specific hallucination research dates from 2024–2026.

- **RSPOPE** (from DDFAV) ports POPE to RS ([arXiv:2411.02733](https://arxiv.org/abs/2411.02733)). No journal version was found (2026-10-25); cite the arXiv preprint (Li, Qu & Zhang 2024) [V]. RSHallu later criticized it for detecting only object hallucinations.
- **CHOICE** finds RS-specific VLMs underperform general ones on hallucination detection, except VHM, and shows that "can't judge" behaviour changes scores [V] ([arXiv:2411.18145](https://arxiv.org/abs/2411.18145); author list [PK]).
- **VHM** (AAAI 2025) is trained on an "honest" set of deceptive questions and is still the best on HnstD in 2026. Its authors concede it cannot do change detection [V] ([AAAI](https://ojs.aaai.org/index.php/AAAI/article/view/32683); [SkyNative, arXiv:2605.17949](https://arxiv.org/abs/2605.17949)).
- **RSHallu** releases RSHalluEval (2,023 QA pairs), RSHalluCheck (15,396) and RSHalluShield (30k). It finds LHRS-Bot most and VHM least hallucination-prone; headline numbers were not retrieved [V] ([arXiv:2602.10799](https://arxiv.org/abs/2602.10799)).
- **RSHBench/RADAR** traces hallucinations to grounding failures in large scenes and misread small targets. Its training-free attention-guided zoom reports about 10% lower hallucination rates; these are the authors' figures, not independently replicated [V] ([arXiv:2603.02754](https://arxiv.org/abs/2603.02754)).

Three audits locate where RS hallucinations concentrate:

- FarSLIP hand-audited 200 MLLM-generated captions: **88% accurate for brief captions vs 80% for long ones**, with errors concentrated in counting and vague spatial wording [V] ([arXiv:2511.14901](https://arxiv.org/abs/2511.14901)).
- Anderson et al. ground caption generation in map data and report lower hallucination; the exact rate was not retrieved [V] ([arXiv:2501.14905](https://arxiv.org/abs/2501.14905)).
- **GeoArbiter**, a single-author 2026 preprint and the most directly relevant, finds that RS MLLMs assert image-unverifiable facts such as facility function, and that retrieved OSM records override contradicting visual evidence. A deterministic tag filter injects only image-unverifiable facts. It retains **84.69–87.15% of the retrieval accuracy gain while cutting claim-level hallucination by 9.58–26.34%** [V] ([arXiv:2608.00877](https://arxiv.org/abs/2608.00877)).

Temporal work (TEOChat, BTCChat, Delta-QA with its "temporal blindness" finding, HM-Bench, DynamicVL, MONITRS) reports no hallucination rates [V] ([Delta-QA, arXiv:2604.14044](https://arxiv.org/abs/2604.14044); [HM-Bench, arXiv:2604.08884](https://arxiv.org/abs/2604.08884); [MONITRS, arXiv:2507.16228](https://arxiv.org/abs/2507.16228)). JL1-CC&QA filters MLLM-written change captions through an LLM judge and then human experts. That implies such captions need hallucination filtering, but the dataset is known only via an aggregator [U] ([EmergentMind](https://www.emergentmind.com/papers/2606.31745)). **No paper quantifies hallucinated causes of change**, even though an explicit search was made for one. GeoArbiter's verifiability argument and PromptCC's change/no-change gate are the closest RS precedents for EviChange's deterministic gate.

### Filters trade informativeness for correctness

Mitigations fall into four groups:

- **Training.** R-Tuning refusal data ([NAACL 2024](https://arxiv.org/abs/2311.09677), [PK]); Fact-RLHF and FDPO ([PK]); VHM honesty data.
- **Decoding.** VCD ([CVPR 2024](https://arxiv.org/abs/2311.16922), [PK]); OPERA ([CVPR 2024](https://arxiv.org/abs/2311.17911), [PK]).
- **Grounding.** Self-RAG ([ICLR 2024](https://arxiv.org/abs/2310.11511), [PK]); map grounding; RADAR.
- **Post-hoc correction.** CoVe ([arXiv:2309.11495](https://arxiv.org/abs/2309.11495), [PK]); RARR ([arXiv:2210.08726](https://arxiv.org/abs/2210.08726), [PK]); SelfCheckGPT ([arXiv:2303.08896](https://arxiv.org/abs/2303.08896), [PK]); Woodpecker ([arXiv:2310.16045](https://arxiv.org/abs/2310.16045), [PK]); LURE ([ICLR 2024](https://arxiv.org/abs/2310.00754), [PK]).

The abstention survey by Wen et al. frames withholding as a hallucination mitigation ([TACL 2025](https://aclanthology.org/2025.tacl-1.26.pdf)). Its author list is [V] as "Wen, Yao, Feng, Xu, Tsvetkov, Howe, Wang" in one note and [PK] with different names in another, so check it.

OpenAI's SimpleQA comparison shows why accuracy alone hides hallucination [V] ([OpenAI](https://openai.com/index/why-language-models-hallucinate/)):

| Model | Abstention | Error | Accuracy |
|---|---|---|---|
| gpt-5-thinking-mini | 52% | 26% | ~22% |
| o4-mini | 1% | 75% | ~24% |

AbstentionBench finds that reasoning LLMs fail to abstain on unanswerable questions [V] ([arXiv:2506.09038](https://arxiv.org/abs/2506.09038)).

**Conformal factuality** is the formal ancestor of claim gating. Mohri & Hashimoto remove sub-claims below a conformally calibrated threshold to reach **80–90% correctness guarantees** while keeping most of the output [V] ([ICML 2024](https://proceedings.mlr.press/v235/mohri24a.html)). Cherian, Gibbs & Candès argue the original removes too many claims and add conditional guarantees ([NeurIPS 2024](https://arxiv.org/abs/2406.09714); title and authors [PK]). Coherent factuality handles dependent claims [V] ([arXiv:2505.17126](https://arxiv.org/abs/2505.17126)). Selective-prediction theory supplies the risk-coverage framing ([Geifman & El-Yaniv, NeurIPS 2017](https://arxiv.org/abs/1705.08500), [PK]; [Kamath et al., ACL 2020](https://arxiv.org/abs/2006.09462), [PK]; [Kadavath et al.](https://arxiv.org/abs/2207.05221), [PK]). Recent work stresses that systems need guarantees on the *returned* answers, not just higher post-filter accuracy [V] ([arXiv:2607.04430](https://arxiv.org/abs/2607.04430)).

The implication for EviChange is concrete. A gate can lower its hallucination rate simply by deleting content, so the post-gate unsupported rate must be reported alongside:

- the number of claims retained;
- recall of true changes;
- the count of true claims the gate wrongly rejected;
- ideally, a risk-coverage curve comparable to Mohri & Hashimoto's.

**No RS study was found that measures informativeness lost to filtering.**

## Citations alone do not make claims supported

### Every attribution audit finds about half of cited content unsupported

Attributed generation rests on AIS, the "According to P, s" human-annotation framework ([Rashkin et al., Computational Linguistics 2023](https://arxiv.org/abs/2112.12870), [PK]). Every careful audit since then finds that citations frequently fail to support the statements they are attached to:

- **ALCE**: even the best models "lack complete citation support 50% of the time" on ELI5. Its NLI judge (TRUE/T5-11B) "cannot detect … 'partially support'" [V] ([Gao et al., EMNLP 2023](https://arxiv.org/pdf/2305.14627)).
- **Generative search engines**: a human audit of four engines found only **51.5% of sentences fully supported** by their citations, and only **74.5% of citations supporting** their sentence [V] ([Liu, Zhang & Liang, Findings EMNLP 2023](https://arxiv.org/pdf/2304.09848)).
- **SourceCheckup**, across seven LLMs and about 58,000 statement-source pairs: **50–90% of medical responses are not fully supported**, and GPT-4o with web search still leaves ~30% of statements unsupported [V] ([Wu et al., Nature Communications 2025](https://pmc.ncbi.nlm.nih.gov/articles/PMC12003634/)). Cite the published figures; the preprint's are different.
- **Tow Center** (non-peer-reviewed): AI search engines misidentified the source article in **more than 60% of 1,600 queries** [V] ([CJR, March 2025](https://www.cjr.org/tow_center/we-compared-eight-ai-search-engines-theyre-all-bad-at-citing-news.php)). The author names Jaźwińska & Chandrasekar are [PK].

Checking attribution automatically is itself unreliable. On **AttributionBench**, a fine-tuned GPT-3.5 reaches only **~80% macro-F1**, and errors cluster on nuanced information including **explicit numerical details** [V] ([Li et al., Findings ACL 2024](https://arxiv.org/html/2402.15089v1)). "According to …" prompting nudges models toward quoting sources but guarantees nothing ([Weller et al., EACL 2024](https://arxiv.org/abs/2305.13252), [PK]). Further attribution work includes [Attributed QA](https://arxiv.org/abs/2212.08037), [GopherCite](https://arxiv.org/abs/2203.11147), [WebGPT](https://arxiv.org/abs/2112.09332), [AttrScore](https://arxiv.org/abs/2305.06311), [ExpertQA](https://arxiv.org/abs/2309.07852) and the [attribution survey](https://arxiv.org/abs/2311.03731) (all [PK]).

All of this work attributes to **unstructured passages**, so support has to be judged by an imperfect learned model. EviChange instead cites **typed fields of a structured evidence record**, which turns support into a deterministic comparison of value, unit, class label or spatial relation. AttributionBench's weakness on numbers is exactly where rule-based checking is strongest. ALCE's citation-recall and citation-precision vocabulary carries over directly, but EviChange computes those quantities exactly instead of estimating them with NLI. **No study was found that measures citation accuracy when the citations point to structured fields in VLM output.**

### Grounding inputs reduces hallucination but does not eliminate it

Retrieval and structured inputs lower error rates without removing them:

- RAGTruth annotates about 18,000 RAG responses at the word level, including data-to-text writing, and documents hallucination across all tasks [V] ([Niu et al., ACL 2024](https://arxiv.org/pdf/2401.00396)).
- Commercial legal RAG tools (Lexis+ AI, Westlaw AI) **hallucinate 17–33% of the time**, despite "hallucination-free" marketing [V] ([Magesh et al., JELS 2025](https://law.stanford.edu/publications/hallucination-free-assessing-the-reliability-of-leading-ai-legal-research-tools)).

The closest analogue to EviChange's input is **data-to-text**, where generators have long stated facts absent from the source table:

- RotoWire introduced extractive checks of generated records against box-score tables. It is an early program-like check of numeric claims against structured data ([Wiseman et al., EMNLP 2017](https://arxiv.org/abs/1707.08052), [PK]).
- WikiBio's divergent references train models to hallucinate ([Lebret et al., EMNLP 2016](https://arxiv.org/abs/1603.07771), [PK]).
- PARENT aligns n-grams to the source table ([Dhingra et al., ACL 2019](https://arxiv.org/abs/1906.01081), [PK]).
- ToTTo models still hallucinate even with highlighted cells ([Parikh et al., EMNLP 2020](https://arxiv.org/abs/2004.14373), [PK]).

EviChange differs in two ways. The generator *declares* which fields each claim uses, so no information-extraction model has to infer the alignment. And values are compared deterministically rather than by n-gram overlap.

### Learned verifiers are probabilistic; program-based ones still need a parser

Claim verification has evolved through four stages:

- **Retrieval-plus-verdict benchmarks.** FEVER labels claims Supported / Refuted / **NotEnoughInfo**, the direct ancestor of EviChange's "uncertain" verdict ([Thorne et al., NAACL 2018](https://arxiv.org/abs/1803.05355), [PK]). SciFact attaches rationale sentences, analogous to cited fields ([EMNLP 2020](https://arxiv.org/abs/2004.14974), [PK]). TabFact verifies statements against tables, with Table-BERT and LPA at roughly 65–68% vs ~92% for humans at release [PK; exact numbers to be checked] ([ICLR 2020](https://arxiv.org/abs/1909.02164)). FEVEROUS mixes text and tables ([PK]).
- **Summarization-consistency scorers.** [FactCC](https://arxiv.org/abs/1910.12840), [QAGS](https://arxiv.org/abs/2004.04228), [SummaC](https://arxiv.org/abs/2111.09525), [AlignScore](https://arxiv.org/abs/2305.16739) (training-set size from memory) and [TRUE](https://arxiv.org/abs/2204.04991), all [PK].
- **Cheap grounded checkers.** MiniCheck-FT5 matches GPT-4 on LLM-AggreFact at **~400× lower cost** [V] ([Tang et al., EMNLP 2024](https://aclanthology.org/2024.emnlp-main.499)).
- **LLM self-verification.** [CoVe](https://arxiv.org/abs/2309.11495), [SelfCheckGPT](https://arxiv.org/abs/2303.08896), [FacTool](https://arxiv.org/abs/2307.13528) and SAFE, all [PK]. Its limits are documented: intrinsic self-correction often fails or degrades accuracy ([Huang et al., ICLR 2024](https://arxiv.org/abs/2310.01798), [PK]), and LLM judges show position and verbosity biases ([Zheng et al., NeurIPS 2023](https://arxiv.org/abs/2306.05685), [PK]).

Program-based verification comes closest to EviChange: [ProgramFC](https://arxiv.org/abs/2305.12744), [Program of Thoughts](https://arxiv.org/abs/2211.12588), [Binder](https://arxiv.org/abs/2210.02875) and [Dater](https://arxiv.org/abs/2301.13808), all [PK]. But each still uses a learned parser to turn free text into a program, and that translation is the error source. EviChange has the generator emit claims already bound to fields. The trade-off is explicit:

- **Gained:** exactness on numbers, units and labels; bit-for-bit reproducibility; auditable reason codes; and no false "supported" verdicts *within the claim grammar*.
- **Lost:** coverage. Anything outside the schema has to go to "uncertain" or be abstained on.

The "unsupported" verdict merges FEVER's "refuted" and "no evidence" cases, and the paper could separate them. **No head-to-head comparison of a deterministic schema verifier against NLI or LLM verifiers on the same claims was found.** EviChange could run that comparison as an ablation (MiniCheck, AlignScore or an LLM judge vs the rule verifier).

### Guardrails enforce form and policy, not evidential support

NeMo Guardrails provides programmable topical and fact-checking rails, but its fact-checking rail is LLM- or AlignScore-based ([Rebedea et al., EMNLP 2023 Demos](https://arxiv.org/abs/2310.10501), [PK]). Llama Guard is a learned safety classifier ([arXiv:2312.06674](https://arxiv.org/abs/2312.06674), [PK]). Constrained decoding guarantees well-formed output, not true output ([Outlines](https://arxiv.org/abs/2307.09702); [JSONSchemaBench](https://arxiv.org/abs/2501.10868); authorship and venue details [PK]). Strict formats can also degrade reasoning ([Tam et al., EMNLP 2024 Industry](https://arxiv.org/abs/2408.02483), [PK]), so EviChange should check whether its claim schema hurts narrative quality. EviChange's abstention on causes, legality and forecasts resembles NeMo's topical rails and the query-perspective abstention in Wen et al.'s survey. The difference is that the rule rests on **evidence observability** (no field of the record can entail a cause), not on policy. Two error sources survive a deterministic gate, and the paper should say so: false positives from the detector inside the evidence record, and claims mis-bound to fields.

## Index differencing and Dynamic World set the evidence layer; Quang Ninh lacks 10 m work

### Index differencing is classical, cheap and threshold-dependent

EviChange's detector rests on four normalized-difference indices:

- NDVI (Rouse et al. 1974, [NASA NTRS](https://ntrs.nasa.gov/citations/19740022614); Tucker 1979, [RSE](https://doi.org/10.1016/0034-4257(79)90013-0)); the NTRS identifier is unverified;
- NDBI ([Zha et al. 2003, IJRS](https://doi.org/10.1080/01431160304987));
- NDWI ([McFeeters 1996](https://doi.org/10.1080/01431169608948714));
- MNDWI, which swaps NIR for SWIR to suppress built-up noise ([Xu 2006](https://doi.org/10.1080/01431160600589179)).

All of these are [PK]; check the DOIs via Crossref. AWEI is an alternative water index used in Vietnamese shoreline work ([Feyisa et al. 2014](https://doi.org/10.1016/j.rse.2013.08.029), [PK]).

NDBI's known weakness is critical in a coal basin. **Bare soil and built-up land both reflect strongly in SWIR**, so NDBI confuses them ([He et al. 2010](https://doi.org/10.1080/01431161.2010.481681); [Rasul et al. 2018](https://doi.org/10.3390/land7030081); IBI as a remedy, [Xu 2008](https://doi.org/10.1080/01431160802039957); all [PK]). A positive ΔNDBI over an opencast pit or spoil dump will often mean fresh overburden, not buildings. That is an argument for cross-checking against Dynamic World's bare and built classes.

The classic change-detection reviews call image and index differencing "algebra-based" methods whose critical step is choosing the threshold ([Singh 1989](https://doi.org/10.1080/01431168908903939); [Lu et al. 2004](https://doi.org/10.1080/0143116031000139863); [Hussain et al. 2013](https://doi.org/10.1016/j.isprsjprs.2013.03.006); [Zhu 2017](https://doi.org/10.1016/j.isprsjprs.2017.06.013); all [PK]). **No source establishes |Δindex| > 0.10 as a standard threshold.** EviChange should justify it empirically (histogram, Otsu threshold or sensitivity analysis) or present it as a conservative heuristic.

Deep-learning detectors such as FC-Siam on Sentinel-2 OSCD ([Daudt et al. 2018](https://doi.org/10.1109/ICIP.2018.8451652)), STANet/LEVIR-CD ([Chen & Shi 2020](https://doi.org/10.3390/rs12101662)) and ChangeFormer ([arXiv:2201.01293](https://arxiv.org/abs/2201.01293)), reviewed by [Shi et al. 2020](https://doi.org/10.3390/rs12101688) (all [PK]), need labelled pairs, which Quang Ninh lacks. Interpretable thresholds also produce exactly the typed fields a deterministic verifier can check. The preprocessing references are Sen2Cor ([Main-Knorn et al. 2017](https://doi.org/10.1117/12.2278218)) and Earth Engine ([Gorelick et al. 2017](https://doi.org/10.1016/j.rse.2017.06.031)), both [PK]. Dense time-series methods (CCDC, [Zhu & Woodcock 2014](https://doi.org/10.1016/j.rse.2014.01.011); LandTrendr, [Kennedy et al. 2010](https://doi.org/10.1016/j.rse.2010.07.008) and its [GEE port](https://doi.org/10.3390/rs10050691); BFAST, [Verbesselt et al. 2010](https://doi.org/10.1016/j.rse.2009.08.014); all [PK]) are the natural extension. No CCDC, LandTrendr or BFAST application to Quang Ninh was found.

### Dynamic World is weakest on the classes mining landscapes contain

Dynamic World V1 provides near-real-time, **10 m, 9-class probabilistic land cover** from every Sentinel-2 L1C scene with less than 35% cloud ([Brown et al., Scientific Data 2022](https://doi.org/10.1038/s41597-022-01307-4), DOI and table [V], author list [PK]; [GEE catalog](https://developers.google.com/earth-engine/datasets/catalog/GOOGLE_DYNAMICWORLD_V1), [V]).

- It agrees **73.8%** with expert consensus. The abstract claims it beats the next-best global product by 7.5%, but the CONUS-only LCMAP scores 75.0% in the same table, so the comparison is not like-for-like [V] ([PMC Table 10](https://pmc.ncbi.nlm.nih.gov/articles/PMC9184477/table/Tab10)).
- Shrub/scrub user's accuracy is about 54.7% [V, snippet] ([PMC Table 8](https://pmc.ncbi.nlm.nih.gov/articles/PMC9184477/table/Tab8)).
- Venter et al.'s independent comparison puts overall accuracy at Esri 75%, DW 72% and WorldCover 65%. The weakest classes were **shrub/scrub 47%, grass 34%, bare 57% and flooded vegetation 53%** [V] ([Remote Sensing 2022](https://doi.org/10.3390/rs14164101)).
- ESA WorldCover is the annual 11-class alternative ([v100](https://doi.org/10.5281/zenodo.5571936); [v200](https://doi.org/10.5281/zenodo.7254221); [PK]).

These weak classes are exactly the transitional covers of a mining coast: reclaimed spoil slopes, mangrove fringes and revegetated dumps. Expect confusion between bare and built (pits vs coal yards), between flooded vegetation, water and trees (mangroves), and between shrub, grass and trees (dumps). Using a period composite of DW labels, rather than single-date labels that flicker, to *label* regions found by index differencing avoids using DW as the detector itself. **No DW accuracy assessment for Vietnam and no DW-based mining study in Vietnam was found.**

### Quang Ninh studies are Landsat-scale and document artificial land gain

Two global mining-footprint datasets exist:

- **Maus et al.**: 21,060 polygons covering 57,277 km² ([2020](https://doi.org/10.1038/s41597-020-00624-w)), updated to 44,929 polygons covering 101,583 km² ([2022](https://doi.org/10.1038/s41597-022-01547-4)). Citations are [PK]; the figures were [V] via a secondary source ([ESSD preprint](https://essd.copernicus.org/preprints/essd-2025-583/essd-2025-583-manuscript-version5.pdf)).
- **Tang & Werner**: **74,548 polygons covering ~66,000 km²**, about 10% of them inside protected areas, available as an Earth Engine asset [V] ([Communications Earth & Environment 2023](https://doi.org/10.1038/s43247-023-00805-6)).

Whether either dataset covers the Cam Pha and Hon Gai opencasts was not checked. Methods context from other coal regions uses NDVI and LandTrendr on dumps and reclamation ([Baorixile](https://www.ncbi.nlm.nih.gov/pmc/articles/PMC9332278/); [Antaibao](https://doi.org/10.3390/land11030325); [HLS NDVI](https://doi.org/10.3390/rs15215257); [Huaibei](https://www.ncbi.nlm.nih.gov/pmc/articles/PMC8583168/); [V, titles]).

The Quang Ninh literature is modest and Landsat-dominated:

- **Nguyen et al.** build Landsat change matrices for 1991, 2001 and 2019. They tie Cam Pha's artificial surfaces to opencast mines and report **waste rock dumped into the sea replacing water at Cam Trung and Cam Thinh** [V] ([Remote Sensing 2022](https://doi.org/10.3390/rs14051241)).
- **Hens et al.** find that **39.9% of the 1988 land cover had changed by 1998**, with the coal-mining area up about 75% [V citation; figures from snippet, full text not read] ([EDS 2000](https://doi.org/10.1023/A:1011466108499)).
- **Vu et al.** use Random Forest object-based classification of six Landsat dates and find Ha Long's 2023 urban area **more than 4× its 2000 extent**, with land reclaimed from the bay a significant contributor [V] ([EuJRS 2024](https://doi.org/10.1080/22797254.2024.2398108)).
- A Sentinel-1 PSInSAR study finds underground-mining subsidence up to ~14.5 mm/yr in Ha Long and Mong Duong [**U**: a 2026-10-25 search did not find this paper in IJRS; confirm the DOI resolves before citing, else drop it] ([IJRS 2021](https://doi.org/10.1080/01431161.2021.1875513)). Optical index deltas cannot capture that process.
- **Bui et al.** report mangrove loss of ~927.5 ha in Ha Long and ~1,144.4 ha in Mong Cai to shrimp ponds [figures V; Bui, Maier & Austin, Dec 2014, pp. 441–455; **journal still U**: check the Deakin record] ([Deakin figshare](https://deakin.figshare.com/articles/journal_contribution/Land_cover_and_land_use_change_related_to_shrimp_farming_in_coastal_areas_of_Quang_Ninh_Vietnam_using_remotely_sensed_data/20861860)).
- Several Vietnamese mangrove studies of Quang Yen, Tien Yen and the Hai Phong–Quang Ninh coast are [U] ([VNUF](https://journal.vnuf.edu.vn/en/article/download/728/642/1281); [VJMST](https://vjst.vast.vn/jmst/article/view/6348)), as is a post-mining land-use planning paper ([ResearchGate](https://www.researchgate.net/publication/268138819_Development_of_methods_for_post-mining_land_use_planning_for_coal_mines_in_urban_areas_in_Quang_Ninh_Vietnam)).
- News reports (non-peer-reviewed) describe sea-encroachment projects around Ha Long Bay, which the province disputes ([VietNamNet](https://vietnamnet.vn/en/sea-encroachment-projects-in-quang-ninh-result-in-environmental-concerns-2056842.html); [Viet Nam News](https://vietnamnews.vn/environment/1298807/quang-ninh-refutes-allegations-of-sea-encroachment-in-ha-long-bay.html)).

Legality is contested even in the press. That is a concrete reason for EviChange to abstain on legality claims. The Cam Trung/Cam Thinh spoil-into-sea finding is a strong validation target: a negative ΔMNDWI paired with a positive ΔNDBI along the coast should flag artificial accretion. **No peer-reviewed study quantifies post-2015 sea reclamation in Ha Long, Cam Pha or Van Don, and none maps dump revegetation from NDVI in Quang Ninh.** The notes recommend a Vietnamese-language search of HUMG's *Journal of Mining and Earth Sciences*.

### Shoreline work uses MNDWI plus DSAS, with one Cam Pha study

The standard toolchain has three parts:

- **Extract the waterline.** CoastSat thresholds MNDWI-like indices with sub-pixel contouring, at roughly 10 m accuracy ([Vos et al. 2019a](https://doi.org/10.1016/j.envsoft.2019.104528); [2019b](https://doi.org/10.1016/j.coastaleng.2019.04.004); [PK]).
- **Measure change on transects.** DSAS computes NSM, EPR and LRR with confidence intervals along shore-normal transects ([Himmelstoss et al. 2021](https://doi.org/10.3133/ofr20211091); [Thieler et al. 2009](https://doi.org/10.3133/ofr20081278); [PK]).
- **Handle tides.** Boak & Turner explain why tide and wave set-up must be accounted for ([2005](https://doi.org/10.2112/03-0071.1), [PK]), and Bishop-Taylor et al. show how tide-modelled compositing removes tidal bias ([2021](https://doi.org/10.1016/j.rse.2021.112734), [PK]).

At global scale, about 24% of sandy beaches erode faster than 0.5 m/yr ([Luijendijk et al. 2018](https://doi.org/10.1038/s41598-018-24630-6), [PK]). Land gain exceeds loss globally, driven largely by human reclamation in East Asia ([Mentaschi et al. 2018](https://doi.org/10.1038/s41598-018-30904-w), [PK]), and the JRC surface-water record underpins much of this work ([Pekel et al. 2016](https://doi.org/10.1038/nature20584), [PK]). Sentinel-1 coastlines from averaged backscatter agree 80–90% with OSM [V for method and figures; DOI U] ([Pelich et al. 2021](https://upcommons.upc.edu/entities/publication/aad3fe60-2021-4559-b47b-960ba2e518b9)).

For Vietnam, **Lappe et al.** find over 1986–2021 that about half the coast shows no significant change, **27.7% is erosional and 27.1% accretional**, with accretion up to +47 m/yr, mostly on artificial coasts [V for figures and DOI; exact title PK] ([Remote Sensing 2022](https://doi.org/10.3390/rs14102476)). The only Cam Pha shoreline paper, **Duong Thi Loi et al.**, extracts the 2018 coastline with NDWI and compares it with a 1999 map. It finds accretion-dominated change, with **95.0% overall accuracy for Sentinel-2A vs 87.5% for Landsat 8** [V] ([VJES 2021](https://doi.org/10.15625/2615-9783/16066)). Other Vietnamese shoreline work comes from Quang Nam, Thanh Hoa, Quang Tri and Hung Yen ([JMSE](https://www.mdpi.com/2077-1312/9/10/1124); [Thanh Hoa](https://apcz.umk.pl/BOGPGS/article/view/48290); [Cua Tung](https://vjol.vista.gov.vn/vawr/en/article/view/99942)), plus central-Vietnam monsoon-driven seasonal shifts ([OOS2025](https://meetingorganizer.copernicus.org/OOS2025/OOS2025-918.html)).

Cam Pha's accretion on embanked and spoil coasts is consistent with Lappe et al.'s finding that the fastest accretion is artificial. **No Sentinel-1 shoreline series for any Quang Ninh coast, and no CoastSat or DSAS application to Ha Long or Cam Pha after 2018, was found.** The notes give Hon Gai's spring tidal range as roughly 3–4 m, but **that figure is unsourced and needs a citation**, for example tide tables or a VJES/VJMST paper, before EviChange relies on it for tide filtering.

## Thirty sites demand cluster-aware, paired, pre-registered statistics

### Claims nest within sites, so i.i.d. intervals are too narrow

Claims from the same site share imagery and context, so a claim-level i.i.d. interval understates uncertainty by roughly the square root of the design effect 1 + (m − 1)ρ. That is the textbook Kish formula, [PK]. With m = 5 claims and ρ = 0.3, the true SE is about **1.48× the naive SE** [computed]. Miller reports clustered SEs **more than 3× naive ones** and recommends clustered SEs plus inference on paired item-level differences [V] ([arXiv:2411.00640](https://arxiv.org/pdf/2411.00640)). Bowyer et al. show that CLT error bars "dramatically underestimate uncertainty" below a few hundred datapoints [V] ([ICML 2025](https://proceedings.mlr.press/v267/bowyer25a.html)).

Resampling whole sites is the standard fix. Field & Welsh show the **cluster bootstrap gives consistent variance estimates under both random-effect and transformation models** [V] ([JRSS-B 2007](https://ideas.repec.org/a/bla/jorssb/v69y2007i3p369-390.html)). Cameron, Gelbach & Miller find that asymptotic cluster-robust tests over-reject with 5–30 clusters and that the wild cluster bootstrap-t restores nominal size [V] ([REStat 2008](https://www.nber.org/papers/t0344)). Webb warns that wild-cluster procedures break down below about 11 clusters [V] ([World Bank blog](https://blogs.worldbank.org/en/impactevaluations/beware-of-studies-with-a-small-number-of-clusters)). That warning matters for EviChange's 10-site background stratum. Abadie et al. frame clustering as a design question [V] ([QJE 2023](https://ideas.repec.Org/a/oup/qjecon/v138y2023i1p1-35..html)), and Cameron & Miller's practitioner guide is [PK].

Four practices follow:

- Stratify the bootstrap by site type (20 detected, 10 background).
- Resample sites once and compute all three conditions on the same replicate, which preserves pairing.
- Prefer BCa intervals (Davison & Hinkley 1997, DOI [PK]).
- Add a sensitivity check with GEE and a small-sample sandwich correction, or a mixed-effects logistic model (Liang & Zeger 1986 [PK]). Note that the mixed model estimates a site-specific effect on the log-odds scale, a different quantity from the pooled rate.

### Wilson for site proportions; exact paired tests with declared zero handling

Brown, Cai & DasGupta document the "chaotic coverage" of the Wald interval and **recommend Wilson or Jeffreys for small n** [V] ([Statistical Science 2001](https://projecteuclid.org/euclid.ss/1009213286)). Clopper-Pearson is conservative and wider ([American Statistician 2024](https://www.tandfonline.com/doi/full/10.1080/00031305.2024.2350445), secondary). Wilson's 1927 paper and Agresti & Coull 1998 are [PK]. Wilson assumes independent trials, so EviChange should apply it only to site-level proportions, such as the share of sites with at least one unsupported claim. For the background stratum, 0/10 gives a Wilson interval of [0, 0.278] and 5/10 gives [0.237, 0.763] [computed]. That shows how imprecise the background estimates will be. No source supports a numeric "small n" cutoff, so don't cite one.

Per-site paired differences will contain many zeros and ties. Wilcoxon's rule drops zeros, and this is the default in R and SciPy. Pratt's rule ranks zeros and then discards their ranks ([Pratt, JASA 1959](https://graphpad.com/guides/prism/latest/statistics/how_the_wilcoxon_matched_pairs_test_works.htm), via secondary sources). Different R routines return different p-values on the same data ([R-help](https://stat.ethz.ch/pipermail/r-help/2011-April/274932.html), low-authority source). With k non-zero differences the smallest two-sided exact p is 2/2^k, so **five informative sites can never reach p < 0.05** [computed]. With 20 non-zero sites, a sign test needs 15 of 20 in one direction [PK but standard]. Five reporting rules follow:

- Pre-specify one zero-handling rule and report the other as a sensitivity check.
- Report counts of improvements, ties and worsenings.
- Make sure exact p-values condition on ties; the SciPy and `coin` tie behaviour is [PK].
- Pair p-values with a site-bootstrap CI on the mean or Hodges–Lehmann difference.
- Consider matched-pairs rank-biserial correlation (Kerby 2014 [PK]).

Wilcoxon 1945 is [PK].

### Ten double-labelled sites make kappa a pilot check

Kappa suffers the "high agreement, low kappa" paradox under skewed prevalence ([Feinstein & Cicchetti 1990](https://scholarhub.vn/publication/:slug/99d46fd7-7674-4728-9c1a-4edb5f5f85c5)). Byrt et al. give prevalence and bias indices and PABAK ([1993, via epiR docs](https://search.r-project.org/CRAN/refmans/epiR/html/epi.kappa.html)). Gwet's AC1 is more stable under high agreement [V] ([BJMSP 2008](https://agreestat.com/papers/bjmsp2008_interrater.pdf)). Sim & Wright tabulate sample-size requirements; their specific values were not retrieved ([Physical Therapy 2005](https://research.birmingham.ac.uk/en/publications/the-kappa-statistic-in-reliability-studies-use-interpretation-and/)). Krippendorff's alpha (Hayes & Krippendorff 2007), the other sample-size tables (Donner & Eliasziw 1992, Cantor 1996) and Cohen 1960 are [PK].

Ten clustered sites fall far short of the dozens to hundreds of independent items those tables imply. So EviChange should present kappa as a **pilot-scale reliability check** and report, separately for each axis (truth and evidence support):

- raw agreement;
- prevalence and bias indices;
- kappa with a site-bootstrap CI;
- AC1 as a pre-declared sensitivity analysis.

### Human-evaluation and accuracy-assessment norms

NLG human evaluation is poorly standardized. Howcroft et al. found **more than 200 different quality-criterion terms across 165 papers** ([INLG 2020](https://aclanthology.org/2020.inlg-1.23)). Belz et al. found **only about 13% of papers** were reproducible in practice ([Insights 2023](https://aclanthology.org/2023.insights-1.1)). Card et al. show typical human-rating designs are underpowered ([EMNLP 2020](https://aclanthology.org/2020.emnlp-main.745)), and Dror et al. find significance testing is often missing or misapplied ([ACL 2018](https://aclanthology.org/P18-1128/)). The best-practice guides of van der Lee et al. ([INLG 2019](https://aclanthology.org/W19-8643/); [CSL 2021](https://research.tilburguniversity.edu/en/publications/human-evaluation-of-automatically-generated-text-current-trends-a/), DOI [PK]) and the Human Evaluation Datasheet ([Shimorina & Belz](https://arxiv.org/pdf/2103.09710), venue [PK]) support:

- blinded, shuffled presentation of claims across conditions;
- separate truth and evidence-support axes;
- a documented adjudication protocol;
- a "guess the condition" check against broken blinding;
- an explicit self-labelling limitation;
- a timestamped analysis plan with one primary endpoint and Holm correction for the secondary comparisons (Holm 1979 [PK]).

From remote sensing, Olofsson et al. require a probability sampling design, a reference labelling process more accurate than the map, and analysis consistent with the design [V] ([RSE 2014](https://eprints.nottingham.ac.uk/44846/)). Stehman & Foody emphasize design-based inference and transparency [V] ([RSE 2019](https://nottingham-repository.worktribe.com/output/2306994)). EviChange's 20-detected plus 10-background design is a stratified sample. Pooled rates are a population estimate only if weighted by stratum share; otherwise they should be labelled "unweighted pooled sample rate". Background sites need a documented random draw. If the 20 detected regions were chosen purposively, the paper should say so. **No prior work applies Olofsson/Stehman stratified estimation to generated text claims.** This analogy is our own.

## Conclusion

The literature makes EviChange's contribution unusually clean to state. Each field has the piece the others lack. RS VLMs have bi-temporal perception but no claim-level truth metric. Hallucination research has claim-level metrics but no change claims. Attribution research shows that citation does not mean support, but its fixes are learned and probabilistic. Data-to-text and program-based verification show structured evidence can be checked mechanically, but they keep a learned parser in the loop. Moving the binding of claims to evidence into the generator's output schema makes a fully deterministic verifier possible, and this design choice is the one most worth defending. It turns the attribution judge's ~80% F1 ceiling into exact checks, within an explicitly bounded claim grammar.

The same literature also lays out the reviewer objections in advance. A gate can win on hallucination rate by deleting claims (conformal factuality, SimpleQA abstention). A detector's own errors pass straight through a "supported" verdict, and Dynamic World is weakest on exactly the bare, shrub and flooded-vegetation classes of a mining coast. A threshold of 0.10 has no literature standard. Thirty self-labelled sites support only cluster-aware, paired, pre-registered inference, with kappa as a pilot check. Reporting retention, recall and false rejections next to the residual unsupported rate, and framing the gate's guarantee as one about the *evidence record* rather than about ground truth, answers most of these objections before they are raised.

## Gaps EviChange fills

- **A measured endpoint nobody reports.** The rate of unsupported claims reaching users after a deterministic evidence gate. It was not found in remote sensing or in any other domain (to our knowledge; the search was not exhaustive).
- **Claim-level hallucination for bi-temporal change.** Existing RS hallucination benchmarks (RSPOPE, RSHallu, RSHBench, CHOICE, GeoArbiter) are single-image. Change captioners and temporal VLMs (TEOChat, BTCChat, Delta-QA) report no hallucination rates.
- **Hallucinated causes of change.** No paper quantifies them. EviChange both measures and abstains on causes, legality and forecasts, as a matter of evidence observability, in direct contrast to Change-Agent's cause analysis.
- **Citations to structured fields.** These are checked deterministically, whereas attribution work cites passages and relies on NLI or LLM judges. No head-to-head deterministic-vs-learned verifier comparison exists.
- **Output-side verification for RS tool agents.** Change-Agent, RS-Agent, GeoLLM-Engine and ThinkGeo verify tool use or task success, not the sentences they emit.
- **10 m Sentinel-2 with SWIR.** This is outside every temporal RS VLM's training data and every change-captioning dataset; Dubai-CC at 30 m is the only medium-resolution set. No zero-shot Qwen2.5-VL-7B change result was found.
- **Short-interval 10 m change mapping in Quang Ninh.** Prior work is Landsat-based and spans decades. There is no Sentinel-1 shoreline series, no post-2018 DSAS or CoastSat study of Ha Long or Cam Pha, no Dynamic World accuracy assessment for Vietnam, and no quantified post-2015 sea reclamation.
- **Accuracy-assessment design applied to generated text.** EviChange carries stratified, design-based accuracy-assessment practice (Olofsson et al., Stehman & Foody) over to the evaluation of generated text claims.
