# AI engine

The "AI" features live in the API package and are deterministic, tested code:

- Categorization rules: `services/api/app/services/categorization.py`
- Forecasts and insights: `services/api/app/domain/forecast.py`, `services/api/app/domain/insights.py`
- Read-only assistant: `services/api/app/services/assistant.py`

AI is never the source of truth for money. Every number comes from the ledger through tested
Python/SQL code; the assistant only chooses which report to run and fills in a template. An
optional language model (stretch goal S3) may only map a question to an allowed intent or rephrase
an answer that already exists.
