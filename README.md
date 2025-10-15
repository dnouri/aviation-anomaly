# Repository Coverage

[Full report](https://htmlpreview.github.io/?https://github.com/dnouri/aviation-anomaly/blob/python-coverage-comment-action-data/htmlcov/index.html)

| Name                                     |    Stmts |     Miss |     Cover |   Missing |
|----------------------------------------- | -------: | -------: | --------: | --------: |
| aviation\_anomaly/api.py                 |      139 |       38 |     72.7% |82, 97-99, 103-104, 138, 167, 197-255, 311-315, 363-365, 378-380, 400-410, 455 |
| aviation\_anomaly/auth.py                |       86 |       45 |     47.7% |48-60, 74-88, 99-112, 123-127, 135-150, 173, 183-191, 213, 219 |
| aviation\_anomaly/cli.py                 |      397 |      221 |     44.3% |36-38, 42-44, 117, 143, 147-151, 198-269, 335-478, 532-545, 549-550, 558, 561, 575-576, 596-601, 621-625, 639-642, 661-663, 668-670, 718-769 |
| aviation\_anomaly/config.py              |      104 |       11 |     89.4% |42, 59, 76, 92, 111, 119, 167-173 |
| aviation\_anomaly/data\_access.py        |       48 |        6 |     87.5% |     58-66 |
| aviation\_anomaly/extraction.py          |      115 |       30 |     73.9% |63-100, 256, 275-293 |
| aviation\_anomaly/h3\_aggregation.py     |      231 |       52 |     77.5% |37, 40, 77-82, 111, 135-136, 172, 195-198, 234, 269, 282-285, 296, 309-312, 345, 369-372, 396, 420-423, 446, 470-473, 496, 498, 522-525, 548, 571-574 |
| aviation\_anomaly/incident\_detection.py |       65 |       23 |     64.6% |60, 157-173, 186-225 |
| aviation\_anomaly/logging.py             |       39 |        0 |    100.0% |           |
| aviation\_anomaly/pmtiles\_generation.py |       64 |       23 |     64.1% |122, 133, 185, 188, 211-240 |
| aviation\_anomaly/segmentation.py        |       89 |       22 |     75.3% |32, 136-141, 176-179, 208-223 |
| aviation\_anomaly/tile\_generation.py    |       50 |       34 |     32.0% |52-55, 72-132 |
|                                **TOTAL** | **1427** |  **505** | **64.6%** |           |


## Setup coverage badge

Below are examples of the badges you can use in your main branch `README` file.

### Direct image

[![Coverage badge](https://raw.githubusercontent.com/dnouri/aviation-anomaly/python-coverage-comment-action-data/badge.svg)](https://htmlpreview.github.io/?https://github.com/dnouri/aviation-anomaly/blob/python-coverage-comment-action-data/htmlcov/index.html)

This is the one to use if your repository is private or if you don't want to customize anything.

### [Shields.io](https://shields.io) Json Endpoint

[![Coverage badge](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/dnouri/aviation-anomaly/python-coverage-comment-action-data/endpoint.json)](https://htmlpreview.github.io/?https://github.com/dnouri/aviation-anomaly/blob/python-coverage-comment-action-data/htmlcov/index.html)

Using this one will allow you to [customize](https://shields.io/endpoint) the look of your badge.
It won't work with private repositories. It won't be refreshed more than once per five minutes.

### [Shields.io](https://shields.io) Dynamic Badge

[![Coverage badge](https://img.shields.io/badge/dynamic/json?color=brightgreen&label=coverage&query=%24.message&url=https%3A%2F%2Fraw.githubusercontent.com%2Fdnouri%2Faviation-anomaly%2Fpython-coverage-comment-action-data%2Fendpoint.json)](https://htmlpreview.github.io/?https://github.com/dnouri/aviation-anomaly/blob/python-coverage-comment-action-data/htmlcov/index.html)

This one will always be the same color. It won't work for private repos. I'm not even sure why we included it.

## What is that?

This branch is part of the
[python-coverage-comment-action](https://github.com/marketplace/actions/python-coverage-comment)
GitHub Action. All the files in this branch are automatically generated and may be
overwritten at any moment.