# The ten test scenarios

Headroom Monitor was tested on ten scenarios of DemoCo, a fictional Luxembourg building-supplies distributor. All data are synthetic.
For each scenario, the generator created one year of history and the 13 weeks that really follow (28 September to 27 December 2026).
The forecast is made on 28 September from the history only and is then compared week by week with what really happened.
Scenarios 9 and 10 were generated only after the forecast engine was frozen, and run once, to check that the engine was not tuned to the first eight.

- **Forecast error (4 weeks ahead):** gap between the forecast and the real bank balance in week 4, in euros and as a share of the real balance. In the two sector slowdowns (scenarios 3 and 10) the gap is large in euros too: the forecast expected money that the customers of the slowing sector paid much later.
- **Cash below the minimum?** Whether the real balance fell below the minimum (four weeks of fixed costs, €510k), in which week, and how many weeks before it the feature warned (the warning is given on 28 September).

| # | Scenario | Forecast error, 4 weeks ahead | Cash below the minimum? | Dataset | Demo |
|---|---|---|---|---|---|
| 1 | **Large customer slows down** (the case study)<br>One of the largest customers has been paying later and later, and a large winter-stock bill falls due in early November. | 5% (€72k) | Yes, week 6: warned 5 weeks ahead | [S2](../data/illustrative/S2) · [Excel](../data/illustrative/S2/S2_sample_dataset.xlsx) | [open](https://headroom-monitor.netlify.app/#S2) |
| 2 | **Normal quarter**<br>Business as usual: customers pay with their usual delays and no large one-off payments are due. | 6% (€81k) | No (no false alarm) | [S1](../data/illustrative/S1) · [Excel](../data/illustrative/S1/S1_sample_dataset.xlsx) | [open](https://headroom-monitor.netlify.app/#S1) |
| 3 | **Construction sector slowdown**<br>Construction customers start paying much later and two small customers go bankrupt during the quarter. | 245% (€1.42m) | Yes, week 3: **missed** | [S3](../data/illustrative/S3) · [Excel](../data/illustrative/S3/S3_sample_dataset.xlsx) | [open](https://headroom-monitor.netlify.app/#S3) |
| 4 | **One-week payment spike**<br>A large supplier bill, payroll charges and VAT all fall in the same week of November. | 4% (€87k) | Yes, week 7: warned 6 weeks ahead | [S4](../data/illustrative/S4) · [Excel](../data/illustrative/S4/S4_sample_dataset.xlsx) | [open](https://headroom-monitor.netlify.app/#S4) |
| 5 | **Seasonal slowdowns**<br>Payment history shows slowdowns in August and December. | 7% (€88k) | No (no false alarm) | [S5](../data/illustrative/S5) · [Excel](../data/illustrative/S5/S5_sample_dataset.xlsx) | [open](https://headroom-monitor.netlify.app/#S5) |
| 6 | **New customer, slow payer**<br>An installer onboarded six weeks ago turns out to be a slow payer, with little history to judge it by. | 2% (€28k) | No (no false alarm) | [S6](../data/illustrative/S6) · [Excel](../data/illustrative/S6/S6_sample_dataset.xlsx) | [open](https://headroom-monitor.netlify.app/#S6) |
| 7 | **Partial payments**<br>Three customers pay part of each invoice on time and the rest three to six weeks later. | 3% (€35k) | No (no false alarm) | [S7](../data/illustrative/S7) · [Excel](../data/illustrative/S7/S7_sample_dataset.xlsx) | [open](https://headroom-monitor.netlify.app/#S7) |
| 8 | **Late month-end close**<br>The accountant closes September 15–20 days late, with corrections to the September figures. | 3% (€42k) | No (no false alarm) | [S8](../data/illustrative/S8) · [Excel](../data/illustrative/S8/S8_sample_dataset.xlsx) | [open](https://headroom-monitor.netlify.app/#S8) |
| 9 | **Unseen test: customer drift**<br>Generated at random after the engine was frozen and run once. A large customer drifts to paying much later and a large inventory bill falls due. | 17% (€221k) | Yes, week 7: warned 6 weeks ahead | [H1](../data/illustrative/H1) · [Excel](../data/illustrative/H1/H1_sample_dataset.xlsx) | [open](https://headroom-monitor.netlify.app/#H1) |
| 10 | **Unseen test: sector slowdown**<br>Generated at random after the engine was frozen and run once. One construction segment slows sharply and some small customers go bankrupt. | 60% (€903k) | No (no false alarm) | [H2](../data/illustrative/H2) · [Excel](../data/illustrative/H2/H2_sample_dataset.xlsx) | [open](https://headroom-monitor.netlify.app/#H2) |

**Known limit (scenario 3).** In the construction-sector crisis, customers suddenly paid a month or more later. The feature raised a sector alert but expected only about one week of extra delay, so it missed the shortfall of week 3.

Week-by-week results for every scenario are in the demo, tab *Assumptions & track record*. Each dataset folder contains a README, the CSV files and a formatted Excel copy.
