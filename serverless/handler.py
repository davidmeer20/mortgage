try:
    import unzip_requirements
except ImportError:
    pass


import pandas as pd
import numpy_financial as npf
from datetime import date
import json

PAYMENTS_YEAR = 12


class MortgageCalculator:
    def __init__(self, interest, years, mortgage, start_date):
        self.interest = interest
        self.years = years
        self.mortgage = mortgage
        self.start_date = start_date
        self.mortgage_range = pd.date_range(self.start_date, periods=self.years * PAYMENTS_YEAR, freq='MS')
        self.mortgage_range.name = "payment date"
        self.mortgage_df = pd.DataFrame(index=self.mortgage_range,
                                        columns=['payment', 'principal_paid', 'interest_paid', 'start_balance',
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
        self.mortgage_df['start_balance'] = self.mortgage
        self.mortgage_df['ending_balance'] = 0
        self.mortgage_df.loc[1, 'ending_balance'] = self.mortgage - self.mortgage_df.loc[1, 'principal_paid']

    def calc_payments(self):
        for period in range(2, len(self.mortgage_df) + 1):
            previous_balance = self.mortgage_df.loc[period - 1, 'ending_balance']
            principal_paid = self.mortgage_df.loc[period, 'principal_paid']
            if previous_balance == 0:
                self.mortgage_df.loc[period, 'start_balance'] = 0
                var = self.mortgage_df.loc[period, ['payment', 'principal_paid', 'interest_paid',
                                                    'start_balance', 'ending_balance']] == 0
                continue
            elif principal_paid <= previous_balance:
                self.mortgage_df.loc[period, 'ending_balance'] = previous_balance - principal_paid
                self.mortgage_df.loc[period, 'start_balance'] = previous_balance

    def add_inflation(self, inflation: float, inflation_date: date):
        balance = self.mortgage_df.loc[self.mortgage_df['payment date'] ==
                                       inflation_date.strftime("%Y-%m-%d")]['start_balance'].values[0]
        self.years = self.years - (inflation_date - self.start_date).days / 365

        new_mortgage = MortgageCalculator(interest=self.interest, years=self.years,
                                          mortgage=balance * (1 + inflation), start_date=inflation_date)
        self.start_date = inflation_date
        new_mortgage.calc_mortgage_params()
        new_mortgage.calc_payments()
        self.mortgage_df.iloc[len(self.mortgage_df) - len(new_mortgage.mortgage_df):] = new_mortgage.mortgage_df

    def prime_change(self, new_interest: float, new_interest_period: date):
        balance = self.mortgage_df.loc[self.mortgage_df['payment date'] ==
                                       new_interest_period.strftime("%Y-%m-%d")]['start_balance'].values[0]
        self.interest = self.interest + new_interest

        self.years = self.years - (new_interest_period - self.start_date).days / 365
        new_mortgage = MortgageCalculator(interest=self.interest, years=self.years,
                                          mortgage=balance, start_date=new_interest_period)
        self.start_date = new_interest_period
        new_mortgage.calc_mortgage_params()
        new_mortgage.calc_payments()
        self.mortgage_df.iloc[len(self.mortgage_df) - len(new_mortgage.mortgage_df):] = new_mortgage.mortgage_df


def get_mortgage_data(event, context):
    query_string_params = event.get("queryStringParameters")

    interest = float(query_string_params.get("interest"))
    years = int(query_string_params.get("years"))
    mortgage = float(query_string_params.get("mortgage"))
    start_date = query_string_params.get("start_date")
    new_interest = float(query_string_params.get("new_interest"))
    print(f"EVENT IS: {event}")
    print(f"START DATE IS: {start_date}")

    mc = MortgageCalculator(interest=interest, years=years, mortgage=mortgage, start_date=date(2021, 1, 1))

    mc.calc_mortgage_params()
    mc.calc_payments()

    mc.prime_change(new_interest=new_interest, new_interest_period=date(2022, 1, 1))
    mc.prime_change(new_interest=new_interest, new_interest_period=date(2023, 1, 1))
    mc.prime_change(new_interest=new_interest, new_interest_period=date(2024, 1, 1))
    return {"statusCode": 200, "body": mc.mortgage_df.to_json()}

# if __name__ == '__main__':
#     mc = MortgageCalculator(interest=0.02, years=10, mortgage=600000, start_date=date(2021, 1, 1))
#     mc.calc_mortgage_params()
#     mc.calc_payments()
#
#     mc.prime_change(new_interest=.0075, new_interest_period=date(2022, 1, 1))
#     mc.prime_change(new_interest=.0075, new_interest_period=date(2023, 1, 1))
#     mc.prime_change(new_interest=.0075, new_interest_period=date(2024, 1, 1))
#     print(f"Mortgage is: {mc.mortgage} and interest is: {mc.interest}")
#     # mc.add_inflation(inflation=0.05, inflation_date=date(2025, 1, 1))
#     # mc.add_inflation(inflation=0.05, inflation_date=date(2026, 1, 1))
#
#     print('a')
