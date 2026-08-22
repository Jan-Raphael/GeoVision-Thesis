"""`scripts/seed_db.py`'s constants actually mean what their comments say.

`DEV_PASSWORD_HASH` was an unparseable placeholder (an all-zeros digest) from
the day the script was written until the E2E suite's first real run against a
live stack caught it: every seeded login failed, silently, because nothing
short of an actual `verify_password` call could have noticed. No unit test
ever exercised it, since unit tests don't log in against seeded data. This
pins it so a future "cleanup" of the constant can't reintroduce the same
unverifiable placeholder.
"""

from __future__ import annotations

import pytest

from app.core.security import verify_password
from scripts.seed_db import DEV_PASSWORD_HASH

pytestmark = pytest.mark.unit


def test_dev_password_hash_actually_verifies_against_geovision_dev() -> None:
    assert verify_password("geovision-dev", DEV_PASSWORD_HASH) is True


def test_dev_password_hash_rejects_a_wrong_password() -> None:
    assert verify_password("not-the-password", DEV_PASSWORD_HASH) is False
