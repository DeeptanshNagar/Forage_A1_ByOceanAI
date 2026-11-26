# Factory vs hand-written agent

Hand-written agent: `demos\hand_written\hr_agent.json` · factory agent: final_agent.json (v1)

| eval | n | composite | pass | answerable ok | refusal P | refusal R | halluc. | grounded | retrieval hit@k | fact cov. | citation valid | contract ok |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| factory (all) | 28 | 0.925 | 89.3% | 85.0% | 100.0% | 100.0% | 5.0% | 95.0% | 100.0% | 0.892 | 100.0% | 100.0% |
| hand-written (all) | 28 | 0.791 | 64.3% | 60.0% | 100.0% | 75.0% | 0.0% | 100.0% | 100.0% | 0.742 | 95.5% | 92.9% |
| factory held-out | 10 | 0.844 | 80.0% | 71.4% | 100.0% | 100.0% | 14.3% | 85.7% | 100.0% | 0.762 | 100.0% | 100.0% |
| hand-written held-out | 10 | 0.688 | 50.0% | 57.1% | 100.0% | 33.3% | 0.0% | 100.0% | 100.0% | 0.690 | 100.0% | 90.0% |

## Where each wins

| outcome | cases | ids |
|---|---|---|
| factory | 7 | ans-004, ans-012, ans-013, ref-015, ref-017, edg-023, edg-025 |
| hand | 0 |  |
| both_pass | 18 | ans-001, ans-002, ans-003, ans-006, ans-007, ans-008, ans-009, ans-010, ans-014, ref-016, ref-018, ref-019, ref-020, ref-021, ref-022, edg-026, edg-027, edg-028 |
| both_fail | 3 | ans-005, ans-011, edg-024 |

## Pass counts per category

| category | n | factory passes | hand passes |
|---|---|---|---|
| answerable | 14 | 12 | 9 |
| edge | 6 | 5 | 3 |
| refuse | 8 | 8 | 6 |
