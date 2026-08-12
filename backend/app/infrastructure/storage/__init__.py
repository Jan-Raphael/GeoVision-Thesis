"""S3/MinIO object storage adapter (Module 04).

Image binaries never enter PostgreSQL (ADR-005): object storage holds the
bytes, the database holds the keys.
"""
