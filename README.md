# Plan your mortgage

A local Streamlit app wrapping the original `MortgageCalculator` logic, with
a UI inspired by the wireframe mock.

## Setup

```powershell
# from c:\Users\dmeer\code\mortgage-app
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

## Run

```powershell
streamlit run app.py
```

Streamlit will open the app in your browser (default: http://localhost:8501).

## Project layout

- `mortgage_calculator.py` — original calculator (numpy_financial-based amortization,
  with `prime_change` and `add_inflation` event support). Preserved from `main.py`,
  with a minimal `int(...)` cast so fractional `years` after events still work.
- `app.py` — Streamlit UI: inputs, KPI cards, downpayment-vs-loan split,
  amortization chart and table, plus a Simulation tab to add Prime change and
  Inflation events.
- `requirements.txt` — pinned-floor dependencies.

## Notes on the calculator behavior

- `prime_change(new_interest, new_interest_period)` **adds** `new_interest` to
  the current rate (i.e. it's a delta, not a replacement). So `+25 bp` is
  passed as `0.0025`.
- `add_inflation(inflation, inflation_date)` multiplies the **remaining
  balance** at `inflation_date` by `(1 + inflation)` and reschedules the
  remaining periods.
- Events are applied in the order their dates fall, oldest first.
