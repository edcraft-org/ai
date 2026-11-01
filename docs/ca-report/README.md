# EdCraft CA report LaTeX source

This project converts the current Word report and combines its methodology and technical-design chapters. The original Word document is unchanged.

## Edit and compile

- `main.tex` controls document formatting and the order of sections.
- `sections/` contains editable report text, separated by chapter and appendix.
- `sections/methodology-and-system-design.tex` retains the author's edited Sections 3.1–3.4.
- `sections/methodology-continuation.tex` completes Sections 3.5–3.7.
- `references.bib` contains the original references and the approved additions.
- `figures/*.tex` contains editable vector diagrams that compile with the report.
- `figures/*.puml` provides the corresponding PlantUML sources for manual editing.

With TeX Live or MacTeX installed, run this command from the project folder:

```sh
latexmk -pdf -interaction=nonstopmode -halt-on-error main.tex
```

Run the command from `docs/ca-report/`; the result is `main.pdf`. On Overleaf, upload the contents of this directory, choose `main.tex` as the main document, and use pdfLaTeX. The project uses biber for references, which latexmk and Overleaf run automatically. The report compiles without Java, Graphviz or PlantUML.

## Conversion scope

Source: the author's `EdCraft CA Report - 28 Oct.docx`, saved 1 November 2026. Its SHA-256 at conversion was:

```text
11b743f54370950134826df26d399a16bcba3823071d9d5a92973e377abdc389
```

- The author's latest Introduction, literature review, evaluation, discussion, research plan, conclusion and appendix text are retained.
- Word paragraphs accidentally styled as headings are converted to body paragraphs without rewriting their text.
- The old Chapters 3 and 4 become one Chapter 3, Methodology and system design. The already edited Sections 3.1–3.4 are retained; the duplicated old technical-design chapter is removed.
- Later chapters are automatically renumbered: Evaluation 4, Discussion 5, Research plan 6, Conclusion 7.
- Section, table, figure and appendix references use LaTeX labels. The table of contents and bibliography are regenerated.
- Existing data tables are retained. Table C1 remains in a landscape appendix.
- The two workflow diagrams are rebuilt as editable vectors to reflect application-controlled checks and complete-proposal revisions. Matching PlantUML sources are included alongside the diagrams.
- Approved references missing from the Word bibliography are added. The Hypothesis software documentation remains alongside the 2019 paper.

## Items deliberately left for the author

- The abstract still contains `[Insert some results here]`, as in the current Word report.
- The existing evaluation numbers are retained. New experiment results have not been inserted or silently substituted.
- The combined chapter describes the updated implementation. Appendix B retains the older experiment commit. Verify that final evaluation wording identifies which implementation each study used.
- The decision-first difficulty cascade is described as an evaluated extension, distinct from the implemented authoring policy inspected during this edit.
- Dates and milestone plans are preserved from the source rather than refreshed from GitHub.

The layout uses A4 paper, 12-point Times-style text and 1.5 line spacing for the main report, with compact references and appendices. Roman preliminary numbering and Arabic numbering from the Introduction are generated automatically. Pagination necessarily differs from Word.

Generated PDFs, LaTeX build files and source bundles are ignored by Git. To remove intermediate build files while retaining the PDF, run `latexmk -c`.

The source package was verified by building in a clean folder, resolving reference keys and inspecting every rendered page. At conversion it had 16 main-text pages and 26 pages in total; edits will change pagination.
