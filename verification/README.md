# Publication verification

Executed on 2026-10-21 against the separate public checkout:

| Check | Result |
| --- | --- |
| `python -m pytest tests -q` (Python 3.11) | 938 passed |
| `npm ci` then `npm run test:frontend` (Node 24) | 86 passed |
| `node scripts/check-demo-browser.cjs` (isolated Edge, static server) | 18 passed |
| All 12 demonstration answer SHA-256 values | Match exported saved answer text |
| Compressed original evaluation artifacts | Decompressed bytes match original SHA-256 |
| Allowlisted checkout secret-pattern and forbidden-file scan | No findings |

No real model, Embedding or Reranker calls were made for publication checks. API/unit tests use mocks or temporary databases. Static browser checks only issue same-origin GET requests; they do not access the production MySQL database or `/ask`, `/auth`, `/records` APIs.

`local-demo-browser.json` records the browser checklist. The GitHub workflow runs offline backend/frontend checks again on a fresh Linux runner; its live status should be checked separately from these local Windows results.

Publication portability adjustments are limited to the public checkout: the configuration-location test resolves the actual application directory instead of assuming its folder is named `doctrace`; `pytest.ini` limits collection to `tests` instead of collecting local backup copies; the static demo server explicitly serves JavaScript MIME types on Windows.
