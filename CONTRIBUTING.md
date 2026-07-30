# Contributing

repo-steward is a small read-only service. Keep changes deterministic and narrowly
scoped. Do not add write-capable GitHub methods, persistence, or telemetry without an
explicit design decision and security review.

## Development

Use Python 3.12 or newer:

```bash
make install
make check
```

Add tests for behavior changes. Rules need stable IDs, precise evidence, transparent
deductions, and documentation. Never put real credentials or third-party repository
data in fixtures. By contributing, you agree that your contribution is licensed under
Apache License 2.0.
