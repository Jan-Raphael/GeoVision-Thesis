"""The registration form's role list must match the enum the server validates against.

This is a **cross-boundary contract**, and it broke in the only way such a
contract can: silently, in one direction. The dashboard offered
`project_manager`, which `ProfessionalRole` does not define — the server splits
that idea into `manager` and `project_handler` — so every visitor who picked the
most natural-sounding option on the list got "Request validation failed" and no
account. The same list also omitted `foreman` and `surveyor`, so two trades
could not describe themselves at all.

Neither half's tests could see it. The backend's tests build users from the enum
and always pass; the frontend's tests render whatever list the file holds and
also always pass. Only something that reads *both* can tell they disagree, which
is what this does. It parses the literal out of the TSX rather than importing it,
because the two projects are separate toolchains by design and a Python test
cannot execute TypeScript — the parse is the price of catching a whole class of
drift for a few lines.

Related in spirit to ADR-033: green tests on both sides of a boundary say
nothing about the boundary itself.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from app.domain.enums import ProfessionalRole

pytestmark = pytest.mark.unit

# backend/tests/unit/ -> backend/tests -> backend -> repo root
_DASHBOARD_AUTH = Path(__file__).resolve().parents[3] / "dashboard" / "src" / "pages" / "auth.tsx"

_ROLES_BLOCK = re.compile(r"const ROLES[^=]*=\s*\[(.*?)\];", re.DOTALL)
_VALUE = re.compile(r"value:\s*'([a-z_]+)'")


def _dashboard_roles() -> list[str]:
    """The `value` of every option in the registration form's ROLES list."""
    source = _DASHBOARD_AUTH.read_text(encoding="utf-8")
    block = _ROLES_BLOCK.search(source)
    assert block is not None, (
        f"Could not find a `const ROLES = [...]` literal in {_DASHBOARD_AUTH.name}. "
        "If the list moved or changed shape, update this test to match - do not "
        "delete it, or the two sides can drift again unnoticed."
    )
    return _VALUE.findall(block.group(1))


@pytest.mark.skipif(not _DASHBOARD_AUTH.exists(), reason="dashboard/ is not checked out")
class TestRegistrationRoleOptions:
    """The form's options and the server's enum, compared both ways."""

    def test_every_offered_role_is_accepted_by_the_server(self) -> None:
        """An option the server rejects is a dead end for whoever picks it."""
        server = {role.value for role in ProfessionalRole}
        offered = _dashboard_roles()

        invalid = [value for value in offered if value not in server]
        assert not invalid, (
            f"The registration form offers {invalid}, which ProfessionalRole does not define. "
            f"Choosing one returns 422 and creates no account. Valid values: {sorted(server)}"
        )

    def test_every_server_role_is_offered(self) -> None:
        """A role the form omits is a person who cannot describe themselves."""
        offered = set(_dashboard_roles())

        missing = [role.value for role in ProfessionalRole if role.value not in offered]
        assert not missing, (
            f"ProfessionalRole defines {missing}, which the registration form does not offer."
        )

    def test_the_order_matches_the_enum(self) -> None:
        """Kept in enum order so the two lists stay readable side by side.

        Not a correctness requirement on its own — it is what makes the previous
        two assertions easy to fix by eye when they fail.
        """
        assert _dashboard_roles() == [role.value for role in ProfessionalRole]
