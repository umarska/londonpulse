# LondonPulse model card

## Purpose

LondonPulse is a reproducible research model for **aggregate daily London cycle hires**, forecasting the seven dates after a completed observation day. It can support exploration of city-wide demand patterns and comparison of forecasting methods. It does not estimate unmet demand, unique users, station occupancy or where bicycles should be redistributed.

The app ships a historical outlook from the pinned **31 August 2026** source cutoff. It has no live feed. The point model is fitted through **31 December 2023**, so both replay and snapshot forecasts depend on that historical relationship remaining useful. The project has no TfL or Santander affiliation or endorsement.

## Model and inputs

The selected model is **standardised Ridge regression**, with regularisation `alpha=100`. It uses **21 features**: horizon; origin count; lagged counts; trailing means, standard deviations and change; recent counts for the target weekday; and known target-date calendar encodings. It predicts daily hires directly, with predictions clipped at zero. A single model covers all seven horizons.

The model requires at least **35 consecutive days** of ordered, finite, whole-number counts. Uploaded CSVs use `date` in `YYYY-MM-DD` form and `hires`. Missing dates, duplicates, negative counts, non-finite values and fractional counts are rejected. The local API accepts at most 3,000 daily rows and a CSV smaller than 500 kB. Uploads are processed in memory, without model refitting or a new calibration.

Future actual weather, service closures, bank holidays and events are not explicit inputs. Future observed hires are excluded. Lagged observations may partly reflect those factors but do not identify their causal effects.

## Data and protocol

Source: **Transport for London, Number of Bicycle Hires**, via [London Datastore](https://data.london.gov.uk/dataset/number-of-bicycle-hires-2r84d), licensed under [Open Government Licence v2.0](https://www.nationalarchives.gov.uk/doc/open-government-licence/version/2/). The verified snapshot has 5,877 daily observations from 30 July 2010 to 31 August 2026. Daily columns are extracted separately from monthly and annual totals; source provenance and checksums are recorded.

The source documents a September 2022 scheme shutdown and stores zero daily entries. These are retained with their limitation. The metadata sheet is older than the actual series coverage. Counts may be revised after publication. This experiment uses a single revised October 2026 snapshot, not an archive of the vintages originally available at each origin.

| Stage | Target dates | Forecast rows / origins | Role |
|---|---|---|---|
| Initial fitting | 1 Jan 2015–31 Dec 2022 | 20,454 rows / daily origins | Fit candidate configurations |
| Validation | 2 Jan–31 Dec 2023 | 364 forecasts / 52 Sunday origins | Select by MAE |
| Final refit | 1 Jan 2015–31 Dec 2023 | 23,009 rows / daily origins | Fit each family's winning configuration |
| Calibration | 8 Jan–29 Dec 2024 | 357 forecasts / 51 Sunday origins | Freeze daily range radii |
| Final test | 6 Jan 2025–30 Aug 2026 | 602 forecasts / 86 Sunday origins | Report untouched later outcomes |

Training uses overlapping origins and repeated target dates. Evaluation uses non-overlapping whole weeks. Recent observed counts are updated at later origins, while fitted parameters and radii remain fixed. Every evaluation truth is traceable to a date in the tracked daily snapshot. The features stop at the origin, but revised source vintages mean this is not a strict as-published historical replay.

## Measured performance

| Measure | Final test result |
|---|---:|
| Mean absolute error | 2,870.58 hires/day |
| Root mean squared error | 3,984.85 hires/day |
| Weighted absolute percentage error | 11.31% |
| MAE reduction versus previous-week weekday | 19.66% |
| MAE reduction versus four-week weekday mean | 14.99% |
| Empirical daily range coverage | 543/602 (90.20%) |
| Mean daily range width | 12,667.45 hires |

Ridge wins the prespecified validation MAE comparison and has lower final MAE and RMSE than the tested histogram gradient boosting model. These scores describe the recorded periods and configurations, not a universal superiority claim. The [executed notebook](../notebooks/londonpulse_analysis.ipynb) independently recalculates all four model scores, calibration radii, exported truths and diagnostics.

## Prediction ranges

Absolute residuals from 51 calibration forecasts per horizon determine a nominal 90% daily radius, using ordered rank 47. Bounds are `max(0, prediction − radius)` and `prediction + radius`. Temporal dependence and distribution shifts prevent a guaranteed coverage probability for future observations or individual subgroups.

Day 3/Wednesday coverage is **69/86 (80.2%)**, despite 90.2% aggregate coverage. Sunday origins align weekdays with horizons, so the experiment cannot isolate these effects. Calibration and evaluation did not assess non-Sunday origins; the illustrative Monday-origin outlook and arbitrary uploaded histories have that additional limitation. Daily bounds cannot be added to form a calibrated weekly total range, and there is no simultaneous seven-day coverage claim.

## Appropriate use and limitations

- Use the app and notebook to inspect aggregate patterns and evaluate the recorded experiment. Planning decisions need further evidence about local availability, forecast freshness and service constraints.
- Do not treat the point prediction as a demand guarantee. Completed hires depend on the ability to access and operate the service and differ from unmet demand.
- The fixed model can become stale after structural changes. No performance claim is established for another city, another scheme or an arbitrary uploaded history.
- Weather, bank holidays, special events, closures and changes in price or fleet are not explicitly modelled. Their effect is not inferred causally from forecast errors.
- Ranges may be broad, over-cover or under-cover at different horizons and periods. Overall coverage should be read with width and subgroup diagnostics.
- Keep the bundled model file trusted. The app accepts count histories, never uploaded serialised model objects.

Software: [MIT](../LICENSE). Data: [Open Government Licence v2.0 and attribution](../DATA_LICENSE.md). Contains public sector information licensed under the Open Government Licence v2.0; source: Transport for London via London Datastore.
