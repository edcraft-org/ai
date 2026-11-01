# Verification notes — 1 November 2026

This is an editing record, not a report chapter or a literature reference.

## Evidence checks

Headline values were recomputed from completed `state.json` and `records.jsonl` files, rather than copied from the October update narrative. The working verification script is outside the report sources. No experiment was rerun, relabelled or rescored, and no production code or research data was changed.

| Evidence | Confirmed result and treatment |
|---|---|
| Latest OpenAI authoring | 45 complete blocks; 15 unique requests; technical passes 14 / 22 / 30; delivered passes 21 / 29 for the checked strategies; one technical pass withheld for a difficulty mismatch in each checked strategy |
| OpenAI controlled repair | 97/120 completed; strict successes 76 regeneration / 95 revision; 77 regeneration technical passes include one constraint violation |
| Partial SoCLaaS authoring | 21/30 completed; technical passes 7 / 12 / 13; two revision technical passes violate recorded constraints; call failures are counted separately from job outcomes |
| Selected four structured judges | 240 recorded assessments; 210 usable labels; 200 reference matches; 95.2% conditional agreement and 83.3% usable matching outcomes across all requests |
| Missing difficulty labels | 11 output-budget failures, 18 missing structured labels, one explicit unable-to-assess response; checked directly in saved response fields; all eleven budget failures ended at 16,384 completion tokens |
| Full five-configuration panel | 300 assessments; 270 usable labels; 244 matches; retained in Appendix B without presenting it as the selected four-configuration result |
| Fast difficulty decisions | 240 records, 184 matches; all 56 errors adjacent; 30 hard-to-medium errors; no easy–hard confusion |
| Live cascade | 30 questions; 16 first-stage acceptances, all matching; 14 escalations, 12 matching and two unresolved; 28/30 overall |
| Relevance | Six complete methods; 92 development and 36 test pairs each; correct test decisions 32, 34, 35, 35, 34, 32 |

The primary authoring endpoint includes withheld final candidates. The report separately identifies workflow completion. Equal candidate opportunities are not described as equal inference budgets. The 97-case repair aggregate is partial and is not added to the main authoring sample. Difficulty agreement uses the development-informed project reference, not learner calibration. Scores and thresholds remain uncalibrated preferences unless independently evaluated otherwise.

The replay cascade's saved latency calculation omits first-stage cost on escalated cases. The report uses measured live-cascade latency instead. Historical model-family labels are not treated as proof of immutable provider weights. The latest authoring records retain requested and served identifiers.

## External reference checks

Bibliographic names, publication/version dates and the claims below were checked against the linked publisher, author or official documentation sources. Short quotations were not added to the report. The bibliography contains no EdCraft self-reference.

| Reference | Primary source checked | Claim retained / important boundary |
|---|---|---|
| NBME (2024) | [Official October 2024 guide](https://www.nbme.org/sites/default/files/2021-02/NBME_Item%20Writing%20Guide_R_6.pdf) | Focused questions, homogeneous/plausible options and item analysis; the URL's 2021 directory is not its publication year |
| Thomas et al. (2019) | [Author-hosted paper](https://www2.seas.gwu.edu/~simha/research/andy-sigcse.pdf) | Alternative-execution-path distractors and template-authoring effort; first author is Anderson Thomas; possible errors are not established student misconceptions |
| PrairieLearn (n.d.-a) | [Official server.py documentation](https://docs.prairielearn.com/question/server/) | Parameters, correct answers and seeded variants |
| PrairieLearn (n.d.-b) | [Official AI authoring documentation](https://docs.prairielearn.com/question/ai-generation/) | File generation, follow-up revision and instructor checks; no claim that PrairieLearn lacks testing |
| Madaan et al. (2023) | [NeurIPS proceedings](https://proceedings.nips.cc/paper_files/paper/2023/hash/91edff07232fb1b55a505a9e9f6c0ff3-Abstract-Conference.html) | Same-model generation, critique and revision; no head-to-head superiority claim over Self-Debugging |
| Chen et al. (2024) | [ICLR paper, Section 5.2.2 and Tables 2–3](https://proceedings.iclr.cc/paper_files/paper/2024/file/2460396f2d0d421885997dd1612ac56b-Paper-Conference.pdf) | Execution and explanation for debugging; unit tests improve performance in their evaluated tasks; conference year 2024 |
| MacIver et al. (2019) | [JOSS paper](https://joss.theoj.org/papers/10.21105/joss.01891) | Property-based input generation and reduction; Hypothesis does have a published software paper |
| Hypothesis (n.d.) | [Official custom-strategy documentation](https://hypothesis.readthedocs.io/en/latest/tutorial/custom-strategies.html) | Custom input strategies; bibliography title corrected to the actual page title; 6.170.9 identifies the experiment runtime, not a frozen version of the live documentation |
| Sweller (2010) | [Publisher abstract and metadata](https://link.springer.com/article/10.1007/s10648-010-9128-5) | Element interactivity; report does not attribute its own easy/medium/hard thresholds to this theory; full text was not needed for a narrower claim |
| Xie et al. (2018) | [Author-hosted paper](https://faculty.washington.edu/ajko/papers/Xie2018TracingStrategies.pdf) | Systematic tracing and external memory improved study performance; evidence concerns assessment conditions rather than universal difficulty thresholds |
| Zotos et al. (2025) | [Version 2](https://arxiv.org/abs/2508.03294v2) | Direct estimates and supervised prediction using solving uncertainty; findings concern their machine-learning true/false questions |
| Li et al. (2026) | [Version 2](https://arxiv.org/abs/2512.18880v2) | Problem-solving strength does not reliably imply human-difficulty alignment; 2026 matches the cited revision |
| Brant et al. (2026) | [Version 1](https://arxiv.org/abs/2602.06631v1) | ENEM benchmark against IRT parameters; underestimation and moderate ranking performance, not a claim that all models always underestimate |
| Hayes and Krippendorff (2007) | [Authors' manuscript](https://chukharev.github.io/520/Hayes_Krippendorff_2007.pdf) | Independent observer agreement; publisher DOI returned 403, so the full manuscript and its journal metadata were checked instead |
| Zur et al. (2023) | [EDM proceedings, Appendix A](https://educationaldatamining.org/EDM2023/proceedings/2023.EDM-short-papers.20/index.html) | Question–objective classification; OpenStax positives inherit subsection objectives rather than individual pair verification |
| Reimers and Gurevych (2019) | [ACL Anthology](https://aclanthology.org/D19-1410/) | Independently computed sentence embeddings and cosine similarity; pages 3982–3992 |
| Zhang et al. (2025) | [Version 3](https://arxiv.org/abs/2506.05176v3), [official model card](https://huggingface.co/Qwen/Qwen3-Reranker-0.6B) | Instruction/query/document reranking with yes/no scoring; embeddings also support instructions; retrieval performance is not educational validation |
| MCP (2025) | [Pinned 18 June tools specification](https://modelcontextprotocol.io/specification/2025-06-18/server/tools) | Tool names, schemas and invocation; interaction policy remains an implementation choice |
| CRUXEval (n.d.) | [Pinned source revision](https://github.com/facebookresearch/cruxeval/tree/190faf16d175b5847b0af05d937872b1fb395942) | Program/input/output provenance, not project MCQ or difficulty labels |

Access dates were refreshed to 1 November 2026 where included. No publication year was inferred from an access date. Published source titles retain their original spelling; report prose uses British spelling. The supplied format's first-mention rule for three-to-five-author citations is implemented in `main.tex`.

## Document checks and deliberate limits

All 19 bibliography keys are used, and cross-references resolve through LaTeX labels. The PDF was rebuilt and every page rendered for visual inspection. The main report remains within the supplied 55-page format limit; preliminary pages, references and appendices are excluded from that count.

The scope remains implemented Python authoring. The decision-first cascade is experimental; UI approval, additional domains and source-grounded authoring remain planned. Milestone dates were preserved rather than rechecked against GitHub. The original Word document, production checkout and experiment artifacts were not edited.
