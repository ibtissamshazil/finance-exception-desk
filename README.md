# Finance Exception Desk

A working local demo for the Week 37A finance review lab.
The demo contains ten fictional invoices and ten purchase orders.
Python rules calculate exceptions. Explanations cite source evidence. Humans record review decisions.

## Start

Requires Python 3.10 or later. No packages, account, or API key are required for offline mode.

**Windows:** Extract the ZIP, then double-click `start_demo.cmd`.
Keep the console open while using the demo. Press Ctrl+C in that console to stop.

**Any platform:** Open a terminal in this folder and run:

```sh
python app.py --open
```

Open <http://127.0.0.1:8765> if the browser does not open automatically.
If that port is busy, run `python app.py --port 8766 --open`.

Do not open `index.html` directly. The dashboard needs its Python server.

## Try the examples

1. Select **AED 3,500 overage**, then click **Run review**.
2. Compare the AED 21,500 invoice with its AED 18,000 purchase order.
3. Open **Source evidence**, **Structured JSON**, and **View tool trace**.
4. Record **Hold for evidence**, with a note requesting an amended PO or documented approval.
5. Select **Duplicate pair**. Both invoice copies require investigation.
6. Try **Missing approval**, **Ledger discrepancy**, and **Clean match**.
7. Select **Guardrail test · invented amount**, then run a review.
8. Confirm **Safe fallback** appears. The validated result still shows AED 3,500.
9. Open **Audit trail**, confirm **Audit records verified**, then export the audit JSON.

**Review all 10** runs every invoice using the selected explanation mode.
Each run creates a new immutable review. Earlier reviews and decisions remain in the audit trail.
Each saved review accepts one reviewer decision. Run another review to reconsider a case.
Earlier human decisions remain visible after a new review. Stale browser tabs cannot decide an older review.

| Invoice | Scenario | Expected result |
| --- | --- | --- |
| INV-182 | AED 21,500 versus AED 18,000 PO | AED 3,500 overage; hold |
| INV-183 | Exact invoice, PO, and ledger match | Clean; human review still required |
| INV-184 | Duplicate supplier reference ST-771 | Investigate INV-185 |
| INV-185 | Second copy of ST-771 | Investigate INV-184 |
| INV-186 | AED 12,500 without approval history | Request missing approval |
| INV-187 | AED 5,200 invoice; AED 5,000 ledger | AED 200 reconciliation difference |
| INV-188 | AED 3,000 versus AED 4,500 PO | Within limit; ledger matches |
| INV-189 | Referenced PO-MISSING is absent | Hold; do not invent PO context |
| INV-190 | Different invoice and PO suppliers | Verify supplier records |
| INV-191 | Missing invoice amount | Hold; do not calculate a PO variance |

The dataset contains eight exception cases and two clean cases.
The nine known invoice amounts total AED 76,900. This includes both duplicate records.
PO-88 exists but no invoice references it. INV-189 deliberately references a missing order.

## Explanation modes

- **Offline demo:** Deterministic sample explanations. No model call or external connection occurs.
- **Live AI:** OpenRouter `openrouter/free`, or optional OpenAI Responses, with strict structured output.
- **Invented amount:** Deliberately produces a false AED 9,999 explanation. Validation rejects it.
- **Broken JSON:** Deliberately produces malformed JSON. The application uses a safe fallback.

Live AI uses approved source sentences and an approved reviewer action.
The application checks every evidence entry, identifier, reason, action, and human-review flag.
The model cannot add free-form claims. This constraint prevents unsupported narrative in this teaching exercise.
The orchestrator calls Python tools in a fixed order; the model does not select or execute tools.

The `confidence` field satisfies the slide's schema. Offline confidence is deterministic, not a calibrated probability.

## Live AI with OpenRouter

The configured local copy reads your supplied token from `.env` automatically.
When credentials exist, the dashboard selects live mode by default.
The delivery ZIP excludes `.env`. Copy `.env.example` to `.env` when setting up another copy.
For GitHub clones, copy `.env.example` to `.env` and set your own API key.

```dotenv
LLM_PROVIDER=openrouter
OPENROUTER_API_KEY=your-key-here
OPENROUTER_MODEL=openrouter/free
```

Store the raw key after `OPENROUTER_API_KEY=`, without the `Bearer` prefix.
Restart the server after changing settings. Explicit environment variables override values in `.env`.
The application accepts only its five documented settings from `.env`; it ignores unrelated environment assignments.
OpenRouter receives synthetic source facts and the approved review schema. No original slide file or credentials enter the prompt.
The key travels only in the HTTPS authorization header to the configured provider's fixed API endpoint.
The browser cannot download `.env`. API responses and audit exports contain no API key.
`.gitignore` excludes `.env`, runtime databases, and Python bytecode.

The model remains `openrouter/free`; no paid model fallback is configured.
Free-model availability and rate limits apply. OpenRouter chooses a compatible free model for each request.
The audit records the actual model returned by OpenRouter.
Each request has a 60-second timeout. Failed or invalid responses produce a labeled offline fallback.
The application never prints API credentials or provider error bodies.

References: [OpenRouter free router](https://openrouter.ai/openrouter/free) and [structured output](https://openrouter.ai/docs/guides/features/structured-outputs).

For optional OpenAI use, set `LLM_PROVIDER=openai`, `OPENAI_API_KEY`, and `OPENAI_MODEL` in `.env`.
OpenAI mode uses `store: false`. OpenAI requests can incur API charges.

## Files and records

| File | Purpose |
| --- | --- |
| `app.py` | Read-only tools, Decimal rules, review validator, HTTP API, and SQLite audit storage |
| `index.html` | Responsive dashboard; no build step or external assets |
| `sample_data.json` | Editable fictional invoices, POs, and policy |
| `example_reviews.json` | Ten saved offline examples with source evidence and tool traces |
| `test_app.py` | Unit and HTTP integration tests |
| `start_demo.cmd` | Windows launcher |
| `MEMORY.md` | Project context, conventions, and verification notes |
| `.env.example` | Credential-free settings template |
| `.gitignore` | Excludes local credentials and runtime records |
| `openrouter_example.json` | Successful, validated live response for INV-182 |

The application creates `data/finance_demo.sqlite3` on first startup.
The database stores immutable review snapshots, decisions, model versions, validation results, source hashes, and UTC audit timestamps.
SQLite commits each review or decision with its audit event in one transaction.
Concurrent writes acquire the database write lock before extending the hash chain.
The audit export includes complete event snapshots and linked SHA-256 hashes.
Audit verification also checks agreement with the saved review and decision tables.
`example_reviews.json` contains ready-to-read outputs. Starting the app creates a fresh exercise database.

To start a separate exercise without removing records, select another database path:

```sh
python app.py --db data/second-exercise.sqlite3 --open
```

## Tests

```sh
python -m unittest -v test_app.py
```

Tests use temporary databases and a temporary loopback server. They do not modify the exercise database.
Tests cover exact and cent variances, invalid money, duplicate pairs, missing and inconsistent records, and source immutability.
They also cover fabricated output, missing API credentials, reviewer controls, durable audit records, concurrent writes, and HTTP guards.

For restricted environments, set `TEMP` and `TMP` to an accessible writable folder before running tests.
Allow local loopback connections for the HTTP integration tests.

## API

| Route | Method | Behavior |
| --- | --- | --- |
| `/api/state` | GET | List sample cases, deterministic findings, and saved reviews |
| `/api/sample-data` | GET | Download the synthetic source dataset |
| `/api/review` | POST | Review `{ "invoice_id": "INV-182", "mode": "demo" }` |
| `/api/decision` | POST | Record `review_id`, `decision`, `actor`, and optional `note` |
| `/api/audit` | GET | Return audit events and hash-chain validation |
| `/api/export` | GET | Download the audit as JSON |

Decision values are `hold`, `escalate`, and `mark_reviewed`.
Only clean cases accept `mark_reviewed`. This value never approves an invoice or payment.
The server rejects unknown IDs, foreign-origin writes, invalid JSON, and unsupported routes.

## Limits

This is a local teaching demo, not a production finance system.
No payment endpoint, invoice-edit tool, invoice-approval tool, scheduler, or banking connection exists.
Reviewer names are self-entered. The demo has no authenticated users or production authorization controls.
An administrator can rewrite or truncate all matching records together. This demo has no external audit anchor.
SQLite triggers block ordinary updates and deletes. They do not defend against a database administrator.
The data format is fixed to this single-currency sample schema. It does not parse uploaded invoices.
Do not replace the sample dataset with sensitive records or expose the server beyond loopback.

Potential future checks: browser reload during a live request, prolonged database contention, and deployment-specific authentication.

## Delivery verification

Twenty-four unit and HTTP integration tests pass on Python 3.11.
A live OpenRouter request uses `openrouter/free` and returns a validated AED 3,500 explanation.
The router selects `dots-studio/dots-3-note-preview:free` for that request.
The live result appears in `openrouter_example.json`. The OpenAI adapter uses a mocked response during verification.
Independent Claude review checks calculations, request controls, rendering, audit behavior, and human decisions.
Regression tests cover stale reviews, earlier decision visibility, audit table changes, interrupted responses, and deeply nested JSON.
