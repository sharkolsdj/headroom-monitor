# Supplementary figures for the proposal

These figures support the three-page proposal *Headroom Monitor — spotting a cash shortage before it happens*
(LHoFT Best Case Study Competition 2026, case Financial Navigator by A352). They are screenshots of the
[interactive demo](../../frontend/demo) and a diagram of the method. All data is synthetic (fictional company DemoCo).

| File | What it shows |
|---|---|
| [Figure1_S2_warning_and_13week_chart.png](Figure1_S2_warning_and_13week_chart.png) | Test case S2 as the CFO sees it on 28 September: (1) the warning, (2) the explanation in plain words, (3) the causes, (4) the 13-week forecast with likely range, the "all paid on time" line and the suggested plan, (5) the suggested plan for the CFO to approve. |
| [Figure1_compact_S2_warning_cause_chart.png](Figure1_compact_S2_warning_cause_chart.png) | Compact version of Figure 1 used in the proposal: the warning, its cause and the 13-week forecast (with the "all paid on time" line and the suggested plan). |
| [Figure2_how_it_works.png](Figure2_how_it_works.png) | How Headroom Monitor works: data already in Financial Navigator, a deterministic forecast engine (no AI in the numbers), and a decision card where the CFO approves every action. |
| [Supplementary_monte_carlo_1000_futures.png](supplementary_monte_carlo.md) | How the uncertainty in the case study (S2) is computed: the 1,000 simulated futures of the bank balance (grey lines), with the expected balance (blue, the middle run), the likely range (80% of the runs) and the minimum to keep (€510k, red). Right: where the 1,000 runs end in week 6; 653 fall below the minimum, hence the 65% probability of the warning. Made with [scripts/mc_paths_figure.py](../../scripts/mc_paths_figure.py) from the engine's own Monte Carlo (seed 42). |
