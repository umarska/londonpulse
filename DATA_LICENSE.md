# Data licence and attribution

Contains public sector information licensed under the [Open Government Licence v2.0](https://www.nationalarchives.gov.uk/doc/open-government-licence/version/2/).

The cycle hire observations are from **Transport for London (TfL), Number of Bicycle Hires**, published through the Greater London Authority's [London Datastore](https://data.london.gov.uk/dataset/number-of-bicycle-hires-2r84d). The dataset catalogue identifies the licence as Open Government Licence v2.0. The workbook's rights holder is Transport for London.

The pinned source is [tfl-daily-cycle-hires.xlsx](https://data.london.gov.uk/download/2r84d/ac29363e-e0cb-47cc-a97a-e216d900a6b0/tfl-daily-cycle-hires.xlsx), retrieved on 5 October 2026. Its SHA-256 is `82b9bd20ca2dd06fc3906e6287c7ff98022d48f0e015add99d818cf99adab829`. The daily observations cover 30 July 2010 to 31 August 2026. The publisher may subsequently revise this file; the training pipeline rejects a changed checksum until the revision has been reviewed.

`data/processed/daily.csv` contains the workbook's daily date/count columns, with the calendar made explicit. `data/processed/provenance.json` records the source, licence, checksums, coverage and data-quality checks. Forecast exports and figures retain attribution to the underlying data. No TfL or Santander logos are included, and this project has no official affiliation or endorsement.

Two source details affect interpretation:

- The workbook's metadata sheet still names an August 2025 end date, while the daily data and the London Datastore catalogue extend to August 2026. The dates in the daily observations determine this project's coverage.
- The publisher records zeros for 10–11 September 2022 and documents a scheme shutdown for a system upgrade. Those values are preserved. They do not establish zero underlying demand; the metadata describes the service interruption as having no data available. From August 2017, delayed system events can also revise daily counts, which the publisher says usually stabilise after two weeks.

The [MIT licence](LICENSE) applies to this project's software and original explanatory material. The source observations retain their separate data licence and attribution.
