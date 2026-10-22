# v0.3 difficulty results: GLM5.3 Flash and Qwen

Evaluated on 22 October 2026: 30 questions, assessed twice per model, using the
same frozen v0.3 prompts/schema and 16,384-token output budget. The reference is
15 easy, 9 medium and 6 hard questions. GLM5.3 Flash (`x-test-1`) is the SoCLaaS
default; its serving alias does not pin immutable weights.

| Measure | Qwen3.6:35b | GLM5.3 Flash |
| --- | ---: | ---: |
| Overall agreement | 47/60 (78.3%) | 51/54 (94.4%) |
| Agreement on identical scored slots | 43/54 (79.6%) | 51/54 (94.4%) |
| Execution burden | 68.3% | 98.1% |
| Changing state | 73.3% | 88.9% |
| Conceptual interaction | 70.0% | 94.4% |
| Overall and all three dimensions correct | 36/60 | 48/54 |
| Exact event count | 12/60 | 48/54 |
| Median successful response | 9.45 seconds | 31.97 seconds |
| Successful-response p95 | 30.87 seconds | 177.60 seconds |
| Scored slots / planned slots | 60/60 | 54/60 |

On the same 54 slots, GLM gained 14.8 percentage points: GLM alone was correct on
10 slots, Qwen alone on 2. The descriptive paired family-cluster bootstrap 95%
interval was +1.9 to +27.8 points (2,000 resamples, seed 86).

Transport failures are excluded from accuracy. Six final GLM slots were excluded;
63 transport failures occurred across 117 returned attempts, with four interrupted
unreturned requests recorded separately. One output-budget failure and two missing
labels remained nonmatches. Completed outcomes were preserved during recovery.

All questions informed rubric development. These are descriptive agreement results
on an AI-assisted reference with user-approved boundaries, not unseen accuracy or
learner calibration. Qwen's initial calls had finite deadlines; its retries and GLM
used no local deadlines. Serving conditions and recovery policies also differed.
The stopped v0.4 experiment scored 41/58 (70.7%); v0.3 remained the selected rubric.
Production judging retains its v0.2 contract.

The original live production workflow failed at the 60-second judge deadline.
With 300-second transport, 310-second judge and 330-second tool limits, the
follow-up author/edit/check/replay smoke passed in 150.58 seconds. Both stages
produced finalized artifacts; GLM assessments took 45.24 and 58.75 seconds.
