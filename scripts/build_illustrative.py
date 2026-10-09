"""Build the small illustrative dataset for every scenario (data/illustrative/<ID>) from frozen engine outputs.

Values are copied from the engine outputs (CLAUDE.md rule 1); this script only selects, rounds and labels.

Writes three CSV files and a README a reader can scan in one minute:
  weekly_forecast.csv  13-week cash plan (receipts, payments by type, closing balance, range, on-time and stress lines)
  top_customers.csv    10 largest customers by open receivables, with usual and recent delay
  open_invoices.csv    open invoices of those customers, with predicted payment date and range
"""
import csv, json, os, shutil
ROOT = os.path.join(os.path.dirname(__file__), '..')
DATASETS = ['S1_normal', 'S2_big_customer', 'S3_sector_crisis', 'S4_outflow_spike', 'S5_seasonality',
            'S6_new_customer', 'S7_partial_payments', 'S8_month_end_close', 'H1_drift', 'H2_sector']
TITLE = {'S1_normal': 'normal quarter', 'S2_big_customer': 'a large customer slows down',
         'S3_sector_crisis': 'construction sector slowdown', 'S4_outflow_spike': 'one-week payment spike',
         'S5_seasonality': 'seasonal slowdowns', 'S6_new_customer': 'new customer, slow payer',
         'S7_partial_payments': 'partial payments', 'S8_month_end_close': 'late month-end close',
         'H1_drift': 'unseen test, customer drift', 'H2_sector': 'unseen test, sector slowdown'}
# Scenario-specific wording for the README (S2 is the case study).
CAUSE_NOTE = {'S2_big_customer': ' (mostly the winter-stock order)'}


def build(DS):
  SHORT = DS.split('_')[0]
  SRC = os.path.join(ROOT, 'data', 'demo', DS)
  OUT = os.path.join(ROOT, 'data', 'illustrative', SHORT)
  os.makedirs(OUT, exist_ok=True)
  F = json.load(open(os.path.join(SRC, 'forecast.json')))
  C = json.load(open(os.path.join(SRC, 'customers.json')))
  A = json.load(open(os.path.join(SRC, 'actual.json')))['weeks']
  sc, band, T = F['scenarios'], F['mc_band'], F['threshold']
  PAY = {'P1': 'supplier_invoices_received', 'P2': 'purchases_for_new_sales', 'P3': 'known_commitments', 'P4': 'payroll_rent_overheads_tax', 'P5': 'vat'}

  rows = []
  for i, w in enumerate(sc['expected']['weeks']):
      b = band[str(w['week'])]
      r = {'week': w['week'], 'week_start': w['week_start'], 'opening_eur': round(w['opening']),
           'receipts_eur': round(w['receipts'])}
      for k, name in PAY.items():
          r[f'pay_{name}_eur'] = round(w['payments_by_source'].get(k, 0))
      r.update({'payments_total_eur': round(w['payments']), 'closing_expected_eur': round(w['closing']),
                'closing_p10_eur': round(b['p10']), 'closing_p90_eur': round(b['p90']),
                'prob_below_safety_level': round(b['p_below_threshold'], 3),
                'closing_if_all_paid_on_time_eur': round(sc['on_time']['weeks'][i]['closing']),
                'closing_stress_largest_customer_plus30d_eur': round(sc['stress']['weeks'][i]['closing']),
                'safety_level_eur': round(T), 'closing_actual_eur': round(A[i]['closing_balance'])})
      rows.append(r)
  with open(os.path.join(OUT, 'weekly_forecast.csv'), 'w', newline='') as f:
      wr = csv.DictWriter(f, fieldnames=list(rows[0])); wr.writeheader(); wr.writerows(rows)

  top = sorted(C, key=lambda c: -c['total_owed'])[:10]
  with open(os.path.join(OUT, 'top_customers.csv'), 'w', newline='') as f:
      wr = csv.writer(f)
      wr.writerow(['customer', 'segment', 'owed_eur', 'overdue_eur', 'usual_delay_days', 'recent_delay_days', 'note'])
      for c in top:
          wr.writerow([c['cust_code'], c['segment'], round(c['total_owed']), round(c['overdue_amount']),
                       round(c['typical_delay_days'], 1), None if c['recent_delay_days'] is None else round(c['recent_delay_days'], 1), c['sentence']])
  inv = []
  for c in top:
      for i in c['open_invoices']:
          inv.append([c['cust_code'], i['invoice_id'], i['due_date'], round(i['outstanding']), i['days_overdue'] or 0,
                      i['p50_date'], i['p10_date'], i['p90_date'], i['remind_by']])
  inv.sort(key=lambda x: (x[0], x[2]))
  with open(os.path.join(OUT, 'open_invoices.csv'), 'w', newline='') as f:
      wr = csv.writer(f)
      wr.writerow(['customer', 'invoice', 'due_date', 'outstanding_eur', 'days_overdue', 'predicted_payment', 'earliest_likely', 'latest_likely', 'remind_by'])
      wr.writerows(inv)

  e = lambda v: ("−" if v < 0 else "") + f"€{abs(v):,.0f}"
  first = next((r for r in rows if r['closing_expected_eur'] < T), None)
  L = [f"# {SHORT} — Illustrative dataset: {TITLE[DS]}", "",
       f"Fictional company DemoCo Building Supplies S.à r.l. · forecast made on {F['as_of']} · engine tag `phase3-frozen-r1`.",
       f"All data is synthetic. Files: `weekly_forecast.csv`, `top_customers.csv`, `open_invoices.csv`, and the same three tables formatted in Excel: `{SHORT}_sample_dataset.xlsx`.", "",
       "## Opening position", "", "| Item | Value |", "|---|---|",
       f"| Cash at bank | {e(F['opening_balance'])} |", f"| Safety level (4 weeks of fixed costs) | {e(T)} |",
       f"| Owed by customers (all open invoices) | {e(sum(c['total_owed'] for c in C))} |",
       f"| Of which overdue | {e(sum(c['overdue_amount'] for c in C))} |", "",
       "## 13-week cash plan (expected)", "",
       "| Week | Starts | Receipts | Payments | Closing | Likely range | If all paid on time | Actual |", "|---|---|---|---|---|---|---|---|"]
  for r in rows:
      flag = ' ⚠' if r['closing_expected_eur'] < T else ''
      L.append(f"| {r['week']} | {r['week_start']} | {e(r['receipts_eur'])} | {e(r['payments_total_eur'])} | **{e(r['closing_expected_eur'])}**{flag} | {e(r['closing_p10_eur'])} – {e(r['closing_p90_eur'])} | {e(r['closing_if_all_paid_on_time_eur'])} | {e(r['closing_actual_eur'])} |")
  if first:
      L += ["", f"⚠ = below the safety level. First week below: **week {first['week']}** ({first['week_start']}), "
            f"when payments reach {e(first['payments_total_eur'])}, of which {e(first['pay_supplier_invoices_received_eur'])} of supplier invoices{CAUSE_NOTE.get(DS, '')}.", "",
            f"**Effect of late payments:** if every customer paid on the due date, week {first['week']} would close at {e(first['closing_if_all_paid_on_time_eur'])} "
            f"instead of {e(first['closing_expected_eur'])}: delays keep {e(first['closing_if_all_paid_on_time_eur']-first['closing_expected_eur'])} in customers' hands."]
  else:
      L += ["", "The expected balance stays above the safety level in all 13 weeks."]
  L += ["", "## Top 10 customers by open receivables", "", "| Customer | Segment | Owed | Overdue | Usual delay | Last 90 days |", "|---|---|---|---|---|---|"]
  for c in top:
      rd = '–' if c['recent_delay_days'] is None else f"{c['recent_delay_days']:.0f} days"
      L.append(f"| {c['cust_code']} | {c['segment'].replace('_',' ')} | {e(c['total_owed'])} | {e(c['overdue_amount'])} | {c['typical_delay_days']:.0f} days | {rd} |")
  L += ["", "Delay = days between the due date and payment."]
  n_od = sum(1 for x in inv if x[4] > 0)
  L += ["", "## Open invoices of these customers", "",
        f"{len(inv)} open invoices, of which {n_od} already overdue. Each one, with its predicted payment date, likely range and remind-by date, is in `open_invoices.csv`."]
  L += ["", "## Planned payments to suppliers", "", "Supplier invoices already received and known large bills, by week (from `weekly_forecast.csv`).", "",
        "| Week | Starts | Supplier invoices received | Purchases for new sales | Known large bills |", "|---|---|---|---|---|"]
  for r in rows:
      L.append(f"| {r['week']} | {r['week_start']} | {e(r['pay_supplier_invoices_received_eur'])} | {e(r['pay_purchases_for_new_sales_eur'])} | {e(r['pay_known_commitments_eur'])} |")
  L += ["", "## Recurring outflows", "", "Payroll, rent, overheads, tax advances and VAT, by week.", "",
        "| Week | Starts | Payroll, rent, overheads, tax | VAT |", "|---|---|---|---|"]
  for r in rows:
      L.append(f"| {r['week']} | {r['week_start']} | {e(r['pay_payroll_rent_overheads_tax_eur'])} | {e(r['pay_vat_eur'])} |")
  open(os.path.join(OUT, 'README.md'), 'w').write('\n'.join(L) + '\n')
  DEMO = os.path.join(ROOT, 'frontend', 'demo', 'sample')
  os.makedirs(DEMO, exist_ok=True)
  for fn in ('weekly_forecast.csv', 'top_customers.csv', 'open_invoices.csv'):
      shutil.copy(os.path.join(OUT, fn), os.path.join(DEMO, SHORT + '_' + fn))
  print('ok', SHORT, len(rows), len(inv))


if __name__ == '__main__':
    for ds in DATASETS:
        build(ds)
