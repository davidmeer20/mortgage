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
        self.mortgage_range = pd.date_range(self.start_date, periods=self.years * PAYMENTS_YEAR, freq='MS')
        self.mortgage_range.name = "payment date"
        self.mortgage_df = pd.DataFrame(index=self.mortgage_range, columns=['payment', 'principal_paid', 'interest_paid',
                                                                            'ending_balance'], dtype='float')
        self.mortgage_df.reset_index(inplace=True)
        self.mortgage_df.index += 1
        self.mortgage_df.index.name = "period"

    def calc_mortgage_params(self):
        self.mortgage_df['payment'] = -1 * npf.pmt(self.interest / 12, self.years * PAYMENTS_YEAR, self.mortgage)
        self.mortgage_df['principal_paid'] = -1 * npf.ppmt(self.interest / PAYMENTS_YEAR, self.mortgage_df.index,
                                             self.years * PAYMENTS_YEAR, self.mortgage)
        self.mortgage_df['interest_paid'] = -1 * npf.ipmt(self.interest / PAYMENTS_YEAR, self.mortgage_df.index,
                                                           self.years * PAYMENTS_YEAR, self.mortgage)
        self.mortgage_df = self.mortgage_df.round(2)
        self.mortgage_df['ending_balance'] = 0
        self.mortgage_df.loc[1, 'ending_balance'] = self.mortgage - self.mortgage_df.loc[1, 'principal_paid']

    def calc_payments(self):

        for period in range(2, len(self.mortgage_df) + 1):
            previous_balance = self.mortgage_df.loc[period - 1, 'ending_balance']
            principal_paid = self.mortgage_df.loc[period, 'principal_paid']
            if previous_balance == 0:
                self.mortgage_df.loc[period, ['payment', 'principal_paid', 'interest_paid', 'ending_balance']] == 0
                continue
            elif principal_paid <= previous_balance:
                self.mortgage_df.loc[period, 'ending_balance'] = previous_balance - principal_paid

    def add_inflation(self, inflation: float, inflation_date):
        self.mortgage = self.mortgage * (1 + inflation)
        self.years = self.years - (inflation_date - self.start_date).days / 365
        self.start_date = inflation_date

        new_mortgage = MortgageCalculator(interest=self.interest, years=self.years,
                                          mortgage=self.mortgage, start_date=self.start_date)
        new_mortgage.calc_mortgage_params()
        new_mortgage.calc_payments()
        self.mortgage_df.iloc[len(self.mortgage_df) - len(new_mortgage.mortgage_df):] = new_mortgage.mortgage_df
        return new_mortgage

    def prime_change(self, new_interest: float, new_interest_period):
        self.interest = new_interest
        self.years = self.years - (new_interest_period - self.start_date).days / 365
        new_mortgage = MortgageCalculator(interest=self.interest, years=self.years,
                                          mortgage=self.mortgage, start_date=new_interest_period)
        new_mortgage.calc_mortgage_params()
        new_mortgage.calc_payments()
        self.mortgage_df.iloc[len(self.mortgage_df) - len(new_mortgage.mortgage_df):] = new_mortgage.mortgage_df
        return new_mortgage


if __name__ == '__main__':
    mc = MortgageCalculator(interest=0.02, years=12, mortgage=300000, start_date=date(2021, 12, 1))
    mc.calc_mortgage_params()
    mc.calc_payments()
    new_inf = mc.add_inflation(inflation=0.005, inflation_date=date(2022, 12, 1))
    new_prime = mc.prime_change(new_interest=.025, new_interest_period= date(2023, 12, 1))
    print('a')