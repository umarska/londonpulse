# Validation record

Release checks completed on **5 October 2026**, using Python 3.12 and the recorded environment in `requirements-lock.txt`.

## Automated and numerical checks

- **32 pytest checks passed.** These cover the source checksum and observation grain, temporal partitions, past-only features, reproduction of all 602 final forecasts, independently calculated scores and range coverage, portable inference, bounded CSV parsing and API responses.
- JavaScript syntax checking passed for `static/app.js`.
- The offline fitting and scoring pipeline completed using the pinned daily snapshot. Four model families were compared on the same validation and final test dates. The fitted model and exported results are included.
- The notebook completed top to bottom: **26 cells, 11 executed code cells, no error outputs**. It independently recalculates model scores, source reconciliation, calibration ranks, bounds and diagnostic summaries. Its five figures and rendered HTML were visually checked.

## App checks

The running app was checked in a real browser. The saved outlook, historical week selection, stepping controls, observed-outcome reveal, evidence and method views loaded correctly. Uploading the included 90-day example produced the same seven forecasts as the saved outlook, with the supplied-history label. An insufficient history displayed the validation message and kept the dialogue open.

A 390-pixel viewport check confirmed that the outlook and method views fit the available page width without horizontal page overflow. The ordinary desktop view was inspected and saved as `app-preview.jpg`. The checked app reported no browser console warnings or errors.

## Practical boundaries

The source is a revised historical snapshot ending on 31 August 2026. Its publication vintages are unavailable. Prediction ranges were calibrated and evaluated for Sunday origins; coverage for other origin weekdays remains unassessed. These limitations are disclosed in the app, notebook and model card.

The Docker recipe is included but **was not executed**, because Docker was unavailable in the build environment. No hosted production service or live data-feed integration is claimed. The GitHub workflow runs the tests and JavaScript syntax check on Python 3.12.
