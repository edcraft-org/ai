# EdCraft CA report LaTeX source

Editable source for **LLM-Assisted Verifiable Assessment Designer**. The report was converted from the author's Word document and revised on 1 November 2026 using the current experiment records. The Word source remains unchanged.

## Edit and compile

- `main.tex` controls formatting and chapter order.
- `sections/` contains the report text and appendices.
- `references.bib` contains the 19 external references checked for this revision.
- `figures/*.tex` contains editable vector diagrams; matching PlantUML sources are in `figures/*.puml`.
- `verification-notes.md` records evidence checks, reference verification and remaining qualifications. It is not part of the printed report.

Run from `docs/ca-report/` with TeX Live or MacTeX:

```sh
latexmk -pdf -interaction=nonstopmode -halt-on-error main.tex
```

The result is `main.pdf`. On Overleaf, upload this directory's contents, select `main.tex` and use pdfLaTeX. Biber handles references automatically. Compilation does not require Java, Graphviz or PlantUML. Generated PDFs, build files and source ZIPs are ignored by Git.

## Current evidence and scope

- The complete OpenAI three-strategy study is the main authoring comparison: 45 paired model–request comparisons, covering 15 requests across three configurations.
- The controlled-repair panel is explicitly partial (97/120); the SoCLaaS panel is separate and incomplete (21/30).
- The selected four structured difficulty configurations remain in the main text, with all five in Appendix B. Conditional agreement and successful assessment coverage are both reported.
- The fast decision and live cascade results are included. The cascade is an evaluated extension, not a claim of integration into production authoring.
- Relevance remains a comparison of methods. Original and adopted reranker configurations retain their separate historical scores.
- Older authoring, reuse and quality-review evidence remains labelled as historical in Appendix A. Old and new results are not pooled.
- The prose uses British spelling and retains “this project” instead of introducing first-person claims. Material limitations and numerical definitions remain explicit.
- The abstract, evaluation, discussion and conclusion use the same current authoring results. Section and appendix references are generated from LaTeX labels.

The layout retains A4, 12-point Times-style body text, 1.5 line spacing and a landscape user-stories appendix. First mentions of references with three to five authors list those authors, following the supplied report-format guidance. At this revision the report has 18 main-text pages, excluding preliminary pages, references and appendices. Rebuild after edits to refresh pagination and cross-references.

## Provenance and remaining work

Original conversion source: `EdCraft CA Report - 28 Oct.docx`, saved 1 November 2026. Its SHA-256 at conversion was:

```text
11b743f54370950134826df26d399a16bcba3823071d9d5a92973e377abdc389
```

The latest authoring protocol records application base `09a956d44fc2f8c1f1c76455be1fe949dc94f1ac` and separately hashes its experimental wrapper. Appendix B identifies the records and source versions. Raw experiment artifacts remain in the original experiment checkout; they have not been copied into this report branch or published.

Milestone dates and personal/title-page details have been preserved. They were not refreshed from GitHub during this results and prose revision. Human review of the draft is still required, particularly for final submission wording and the planned-work timetable.
