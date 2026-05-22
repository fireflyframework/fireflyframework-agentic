# Reporting methodology

This document defines the metrics used in our quarterly financial reporting.
Any analysis that surfaces these terms must compute them as defined here.

## Operating Efficiency

Operating Efficiency (OE) for a business unit in a given quarter is defined as:

    OE = total_revenue_usd / headcount_at_end_of_quarter

where `total_revenue_usd` is the sum of `revenue_usd` across all products and
regions for that business unit and quarter (from `quarterly_revenue`), and
`headcount_at_end_of_quarter` is the headcount in `headcount_snapshots` at the
last calendar day of the quarter (e.g. `2024-09-30` for Q3 2024).

Blank `revenue_usd` cells in `quarterly_revenue` are treated as zero for this
calculation — a blank reflects "no recorded revenue," not "missing data."

## YoY growth

Year-over-year growth for a business unit between two years is:

    YoY = (total_revenue_{this_year} - total_revenue_{prior_year}) / total_revenue_{prior_year}

with the same blanks-as-zero rule for `revenue_usd`.
