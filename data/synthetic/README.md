Synthetic cash-flow and customer transaction datasets generated deterministically for demo purposes — no real data.

Each scenario folder holds the raw records of the fictional company DemoCo, for every customer and supplier:
`ar_invoices.csv` (customer invoices), `ar_receipts.csv` (customer payments), `ap_invoices.csv` (supplier invoices)
and `bank_balances.csv`. The forecast is made on the as-of date (28 September 2026).

- `ar_receipts.csv` stops on the day before the as-of date: payments received afterwards belong to the hidden future
  used only to check the forecast.
- `ar_invoices.csv` also lists invoices issued after the as-of date (also part of the hidden future). The forecast
  engine reads only invoices issued on or before the as-of date (`engine/_loader.py`), and estimates future sales itself.
