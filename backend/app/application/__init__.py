"""Application layer - use cases that orchestrate the domain.

One class per use case (`CreateProject`, `PairDevice`, `IngestImage`...).
Depends on domain interfaces only; receives concrete implementations by
injection. May not import `api/` or `infrastructure/`.
"""
