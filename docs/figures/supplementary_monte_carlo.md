# Supplementary figure: the 1,000 simulated futures of the case study

![The 1,000 simulated futures of the bank balance in the case study, and where they end in week 6](Supplementary_monte_carlo_1000_futures.png)

**Case study (DemoCo, forecast made on 28 September 2026): 1,000 simulated futures of the bank balance.**
Left: each grey line is one simulated future of the next 13 weeks; in each one, every customer pays on a date drawn from its own past payments. The blue line is the expected balance (the middle future), the blue band is the likely range (the 800 central futures, 80% of the runs), and the red dashed line is the minimum DemoCo must keep (€510k, four weeks of fixed costs).
Right: where the 1,000 futures end in week 6, when the supplier bills fall due. 653 of them fall below the minimum (red) and 347 stay above (blue): hence the 65% probability shown in the warning.

In week 6: expected balance €442k · likely range €232k–€652k · probability below the minimum 65%.

All data are synthetic. The figure is made by [scripts/mc_paths_figure.py](../../scripts/mc_paths_figure.py) from the engine's own Monte Carlo (1,000 runs, seed 42); its values match the demo week by week.
