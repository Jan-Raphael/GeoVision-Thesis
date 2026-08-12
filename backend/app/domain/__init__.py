"""Domain layer - the innermost ring.

Entities, value objects, enums, repository *interfaces*, and pure business
rules. This package must import **nothing** from `api/`, `application/`,
`infrastructure/`, or any framework (no FastAPI, no SQLAlchemy, no torch).

That constraint is enforced by the `domain-purity` contract in
`backend/.importlinter`, not just by convention. It is what makes the
permission matrix and the progress rules unit-testable without a database.

Populated in Module 02.
"""
