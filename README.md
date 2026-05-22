# Review Agent

Runs deterministic content checks and returns final Markdown.

By default the review step does not call an LLM. Set `REVIEW_ENABLE_LLM_POLISH=true`
to enable the optional polishing pass. `REVIEW_MODEL` defaults to `qwen2.5:14b`.

## API

- `GET /health`
- `POST /api/v1/reviews`

## Verification

```bash
PYTHON=/path/to/python scripts/verify.sh
```
