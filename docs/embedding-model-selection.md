# Embedding model selection

Reviewed on 21 October 2026. This is an evaluation of published online performance,
not a new live model comparison on the EdCraft questions. It covers three OpenAI
models usable through the existing provider, with no new dependency or service.
It does not rank every embedding model available from other providers.

## Comparable published evidence

The [official OpenAI embedding guide](https://developers.openai.com/api/docs/guides/embeddings#embedding-models)
reports the following MTEB comparison. Scores are aggregate benchmark values on a
0–100 scale, not probabilities of an EdCraft question being relevant. The guide's
comparison is not a current ranking of the entire MTEB leaderboard.

| Model | Published MTEB score | Standard input price per million tokens | Decision |
| --- | ---: | ---: | --- |
| `text-embedding-3-large` | 64.6 | US$0.13 | Provisional default: highest score in this comparable set. |
| `text-embedding-3-small` | 62.3 | US$0.02 | Lower-cost override; historical EdCraft baseline. |
| `text-embedding-ada-002` | 61.0 | US$0.10 | Small has a higher published score and a lower price. |

Prices come from the official model pages for
[large](https://developers.openai.com/api/docs/models/text-embedding-3-large),
[small](https://developers.openai.com/api/docs/models/text-embedding-3-small) and
[ada-002](https://developers.openai.com/api/docs/models/text-embedding-ada-002).
The [embedding guide](https://developers.openai.com/api/docs/guides/embeddings)
documents default dimensions of 3,072 for large and 1,536 for small. The provider
requests the default dimension and records the actual returned dimension.

## Selection and practical cost

Use `text-embedding-3-large` provisionally because quality is the priority here,
its published score is 2.3 points above small on the same comparison, and the
existing adapter supports it without another model call or infrastructure change.
This is an engineering inference from general benchmark evidence, not a measured
improvement in educational relevance. Neither model establishes concept coverage.

Large costs 6.5 times as much per input token. For scale, the earlier 19-case run
used 4,892 embedding input tokens. At the published standard rates, that input
volume would cost approximately US$0.000636 with large or US$0.000098 with small.
These are estimates for equal token volume, not measured new-run charges. Request
volume, latency and deployment limits still matter at production scale; no latency
improvement is claimed from this online comparison.

`EDCRAFT_EMBEDDING_MODEL=text-embedding-3-small` retains the lower-cost option.
The default and example configuration now use large. Every assessment still
records its exact model, comparison text, preprocessing and metric. Scores from
different models should not be treated as interchangeable or assigned a shared
pass cutoff. Provider model IDs do not identify immutable weight revisions.

## Limits of the evidence

These published results do not test English learning objectives against complete
Python MCQs serialized as JSON. There are no human relevance labels in our frozen
held-out set. The prior small-model run showed misleading similarity rankings;
the online benchmark does not demonstrate that large fixes those failures.

No extra live API evaluations were performed for this selection. Existing v1
records remain unchanged and continue to identify small and the separate quality
judge used at that time. A future domain comparison should use predeclared human
relevance labels, include shared-word/missing-concept controls, and compare ranking
behavior and latency without tuning on the held-out set. Local or other-provider
models need their own adapter and comparable task evidence before adoption.
