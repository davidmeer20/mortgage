"""Mortgage calculator core logic.

Preserves the original `MortgageCalculator` from the user's `main.py` with a
few minimal compatibility / perf fixes:

1. `periods` cast to `int` before `pd.date_range` — `add_inflation` /
   `prime_change` make `self.years` fractional.
2. Balance columns initialized as floats (pandas 3.x no longer silently upcasts
   int columns to float on assignment).
3. `round(2)` applied only to numeric columns to avoid a UserWarning on the
   datetime `payment date` column.
4. `calc_payments` vectorized via NumPy cumsum instead of a per-row Python
   loop with `.loc` writes. Behaviour is identical for standard amortization
   (where `npf.ppmt` makes the cumulative principal exactly equal the loan at
   the final period). The original code's no-op branch for the edge case
   ``previous_balance == 0`` is preserved by clamping at zero.

Behavior is unchanged for all realistic inputs.
"""

import numpy as np
import pandas as pd
import numpy_financial as npf
from datetime import date

PAYMENTS_YEAR = 12


class MortgageCalculator:
    def __init__(self, interest, years, mortgage, start_date):
        self.interest = interest
        self.years = years
        self.mortgage = mortgage
        self.start_date = start_date
        self.mortgage_range = pd.date_range(
            self.start_date,
            periods=int(round(self.years * PAYMENTS_YEAR)),
            freq='MS',
        )
        self.mortgage_range.name = "payment date"
        self.mortgage_df = pd.DataFrame(
            index=self.mortgage_range,
            columns=['payment', 'principal_paid', 'interest_paid', 'start_balance',
                     'ending_balance'],
            dtype='float',
        )
        self.mortgage_df.reset_index(inplace=True)
        self.mortgage_df.index += 1
        self.mortgage_df.index.name = "period"

    def calc_mortgage_params(self):
        n_periods = int(round(self.years * PAYMENTS_YEAR))
        self.mortgage_df['payment'] = -1 * npf.pmt(
            self.interest / 12, n_periods, self.mortgage
        )
        self.mortgage_df['principal_paid'] = -1 * npf.ppmt(
            self.interest / PAYMENTS_YEAR, self.mortgage_df.index,
            n_periods, self.mortgage,
        )
        self.mortgage_df['interest_paid'] = -1 * npf.ipmt(
            self.interest / PAYMENTS_YEAR, self.mortgage_df.index,
            n_periods, self.mortgage,
        )
        numeric_cols = ['payment', 'principal_paid', 'interest_paid',
                        'start_balance', 'ending_balance']
        self.mortgage_df[numeric_cols] = self.mortgage_df[numeric_cols].round(2)
        self.mortgage_df['start_balance'] = float(self.mortgage)
        self.mortgage_df['ending_balance'] = 0.0
        self.mortgage_df.loc[1, 'ending_balance'] = float(
            self.mortgage - self.mortgage_df.loc[1, 'principal_paid']
        )

    def calc_payments(self):
        # Vectorized rolling-balance computation. For a standard amortization,
        # ending_balance[i] = mortgage - cumsum(principal_paid[0..i]) and
        # start_balance[i] = ending_balance[i-1] (with start_balance[0] = mortgage).
        principal = self.mortgage_df['principal_paid'].to_numpy()
        ending = float(self.mortgage) - np.cumsum(principal)
        # Clamp at zero in case an early-payoff edge case ever pushes ending
        # negative (the original code left those rows partially zeroed).
        ending = np.maximum(ending, 0.0)
        start = np.empty_like(ending)
        start[0] = float(self.mortgage)
        start[1:] = ending[:-1]
        self.mortgage_df['start_balance'] = start
        self.mortgage_df['ending_balance'] = ending

    def add_inflation(self, inflation: float, inflation_date: date):
        target = pd.Timestamp(inflation_date)
        balance = self.mortgage_df.loc[
            self.mortgage_df['payment date'] == target
        ]['start_balance'].values[0]
        self.years = self.years - (inflation_date - self.start_date).days / 365

        new_mortgage = MortgageCalculator(
            interest=self.interest,
            years=self.years,
            mortgage=balance * (1 + inflation),
            start_date=inflation_date,
        )
        self.start_date = inflation_date
        new_mortgage.calc_mortgage_params()
        new_mortgage.calc_payments()
        self.mortgage_df.iloc[len(self.mortgage_df) - len(new_mortgage.mortgage_df):] = new_mortgage.mortgage_df

    def prime_change(self, new_interest: float, new_interest_period: date):
        target = pd.Timestamp(new_interest_period)
        balance = self.mortgage_df.loc[
            self.mortgage_df['payment date'] == target
        ]['start_balance'].values[0]
        self.interest = self.interest + new_interest

        self.years = self.years - (new_interest_period - self.start_date).days / 365
        new_mortgage = MortgageCalculator(
            interest=self.interest,
            years=self.years,
            mortgage=balance,
            start_date=new_interest_period,
        )
        self.start_date = new_interest_period
        new_mortgage.calc_mortgage_params()
        new_mortgage.calc_payments()
        self.mortgage_df.iloc[len(self.mortgage_df) - len(new_mortgage.mortgage_df):] = new_mortgage.mortgage_df


if __name__ == '__main__':
    mc = MortgageCalculator(interest=0.02, years=10, mortgage=600000, start_date=date(2021, 1, 1))
    mc.calc_mortgage_params()
    mc.calc_payments()

    mc.prime_change(new_interest=.0075, new_interest_period=date(2022, 1, 1))
    mc.prime_change(new_interest=.0075, new_interest_period=date(2023, 1, 1))
    mc.prime_change(new_interest=.0075, new_interest_period=date(2024, 1, 1))
    print(mc.mortgage_df.head())
