# Forecasting methods

LondonPulse predicts the next seven daily totals for London's cycle hire scheme. One forecast origin is the end of a calendar day: its count is already available, and horizons 1–7 refer to the following dates. The unit is hires per day across the whole scheme. It is not a forecast of people, journeys by location, bicycle availability or unmet demand.

## Source and observation grain

The source is Transport for London's [Number of Bicycle Hires](https://data.london.gov.uk/dataset/number-of-bicycle-hires-2r84d), published through the London Datastore under [Open Government Licence v2.0](https://www.nationalarchives.gov.uk/doc/open-government-licence/version/2/). Only columns B/C of the workbook's `Data` sheet are used: date and daily hire count. Adjacent monthly and annual totals are excluded rather than mixed with daily observations.

The pinned source file is verified against its SHA-256 before extraction. The processed calendar retains every day between the first and last observation. Missing counts remain blank, and any origin requiring missing history or targets is excluded. Duplicated or unordered source dates and invalid counts are rejected. The saved snapshot has no missing daily counts or duplicated dates.

The source reports zeros on 10–11 September 2022 and documents a full scheme shutdown for a back-office upgrade. These zeros are preserved, with the operational interruption disclosed. They are not evidence of zero underlying demand. The workbook's metadata sheet has an older end date than the daily observations; the daily rows and dataset catalogue establish the August 2026 cutoff. Delayed system events may revise the publisher's counts, so a later download need not reproduce this snapshot exactly. See [data licence and attribution](../DATA_LICENSE.md).

This is a retrospective backtest using one revised source snapshot retrieved in October 2026. Original publication vintages at each historical origin are not available in the project. Older counts usually stabilise after two weeks, but this experiment cannot prove that every historical input equals the value published at its origin. The causal feature boundary excludes future dates; it does not reconstruct historical data releases.

## Information available at the origin

The direct forecasting table has one row per origin and horizon. It requires 35 consecutive daily observations ending at the origin, and uses 21 features:

- Horizon and the count at the origin; counts 1, 7, 14 and 28 days earlier.
- Trailing 7-day and 28-day means and population standard deviations; the change between the latest and preceding 7-day means.
- The last observed occurrence of the target weekday, and its mean and population standard deviation over the four most recent occurrences.
- Sine/cosine encodings of the target weekday, month and day of year; elapsed calendar years from the series start.

The rolling windows include the origin. For horizon `h`, the four matching weekdays are at `origin + h − 7k`, for `k = 1, 2, 3, 4`. All are on or before the origin, including horizon 7's origin itself. Day-of-year encoding uses a 365.2425-day divisor. Future calendar dates are known in advance; future observed counts, actual future weather and retrospective event labels are not features. No random train/test shuffle is used.

## Chronological experiment

Fit rows have target dates in 2015–2022. The available 2010–2014 history can supply lagged observations but is not part of the fitting target population. Candidate models are compared on whole seven-day validation forecasts with Sunday origins during 2023. Mean absolute error is the prespecified selection criterion.

After selection, each fitted model family is refitted using targets through 31 December 2023. Calibration then uses Sunday-origin weeks in 2024, while the final test uses Sunday-origin weeks from 2025 through the final complete week in the snapshot. A week belongs to an evaluation partition only if its origin and all seven targets meet the partition boundaries. Partial boundary weeks are omitted. Weekly evaluation targets do not overlap, although successive origins use overlapping historical windows. Fitting uses daily origins, so fitting rows do overlap.

The final model remains fixed during the test. Recent observed counts become available at each later origin and are legitimate inputs, but there is no model refit on calibration or test targets. The saved outlook starts from 31 August 2026, with the same fixed model and calibration ranges. It is a historical snapshot rather than a live forecast for today's date.

## Comparators and model selection

The experiment evaluates four families on identical forecast rows:

1. **Seasonal naive:** repeat the last observed count for each target weekday.
2. **Four-week weekday mean:** average the last four observed counts for that weekday.
3. **Ridge regression:** a linear model using standardised features, with its regularisation chosen on validation weeks.
4. **Histogram gradient boosting:** a nonlinear tree ensemble with bounded candidate configurations, selected on the same validation weeks.

Predictions are clipped at zero because negative hire counts have no valid interpretation. Hyperparameters and candidate scores are retained in `artifacts/results.json`. The final test does not select the model or its hyperparameters. A complex model need not beat every baseline on every metric or subgroup; the README and notebook report the measured comparisons.

## Scores and diagnostics

For actual count `y` and prediction `p`, MAE is `mean(|p − y|)` and RMSE is `sqrt(mean((p − y)²))`, in hires per day. WAPE is `100 × sum(|p − y|) / sum(|y|)`, so it weights errors against the total observed hire volume rather than averaging daily percentage errors. sMAPE is `100 × mean(2|p − y| / (|y| + |p|))`, with a zero contribution when both counts are zero.

Horizon, weekday and monthly diagnostics describe where errors and interval coverage differ in the held-out sample. Because every evaluation origin is a Sunday, horizons 1–7 always correspond to Monday–Sunday. Horizon and weekday scores are therefore the same grouping; this experiment cannot distinguish a horizon effect from a weekday effect. The diagnostics are descriptive assessments of the final model, not an additional tuning step or evidence of causal mechanisms. The notebook independently recomputes the main scores and calibration quantities from exported CSV rows rather than importing the scoring helper.

## Empirical prediction ranges

For each horizon separately, absolute forecast errors from the earlier calibration year determine a radius. With `n` calibration forecasts and a 90% nominal target, the radius is the `ceil((n + 1) × 0.90)`-th smallest absolute error. Each range is `[max(0, prediction − radius), prediction + radius]`.

This uses a finite-sample rank correction, but temporal observations are not independent and exchangeable. It therefore does **not** establish a 90% probability for a particular day or a coverage guarantee under distribution shifts. The range describes an individual day's outcome, not the whole week or the weekly total. Adding daily bounds does not produce a calibrated interval for a weekly sum. Actual test coverage and mean range width are both reported, including coverage by month and horizon, so wide ranges cannot be mistaken for precise forecasts.

Calibration and final evaluation cover Sunday origins only. The illustrative snapshot outlook originates on Monday, 31 August 2026. Its point model was fitted using daily origins, but range coverage for non-Sunday origins has not been separately assessed. Uploads can also have other origin weekdays and inherit that limitation.

## Limits of use

The model captures patterns in observed aggregate hires. Weather, disruption, events, pricing, fleet changes and user behaviour can alter those patterns. Recent counts are a proxy for these effects, not a complete measurement of them. A model fitted through 2023 can become stale. Ranges calibrated in 2024 can over-cover or under-cover in later periods.

The project supports reproducible research and discussion of aggregate capacity. It cannot prescribe station-level redistribution or quantify unmet demand. Uploaded histories receive the same fixed model and radii; histories from another scheme or a different distribution have no validated coverage claim. Uploads are validated and processed in memory rather than saved.
