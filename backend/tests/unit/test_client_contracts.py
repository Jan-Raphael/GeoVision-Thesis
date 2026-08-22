"""Other places the dashboard restates a server enum, checked the same way.

`test_role_options.py` proved the pattern once (ADR-034): a client literal and
a server enum are two independent sources of truth, and green tests on both
sides say nothing about whether they agree — only something that reads *both*
can catch the drift, and it has already happened once for real. This file
applies the same technique to the other enums the dashboard restates, with one
addition: not every list is supposed to be a complete mirror of its enum, and
getting that distinction right matters as much as the parsing.

Two shapes of "offered vs. accepted" appear below:

- **Exhaustive** (stage filter, camera face): every value the server defines
  should be selectable, because there is no reason to hide one from the
  person filling out the form.
- **Subset, deliberately** (project-status filter, member-role picker): the
  UI intentionally offers fewer options than the enum defines — `archived`
  projects are excluded from the public feed's own query in the first place,
  and a project has exactly one `owner`, assigned at creation, never through
  the "change a collaborator's role" dropdown. For these, only the direction
  that can actually break something is checked: every value the client
  *does* offer must be one the server accepts. The narrower assertion is not
  a smaller safety net than the wider one — asserting completeness here would
  make the test fail the moment the intentional design is followed correctly,
  which teaches whoever hits it to weaken the test rather than trust it.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from app.domain.enums import CameraFace, MacroStage, MembershipRole, ProjectStatus

# backend/tests/unit/ -> backend/tests -> backend -> repo root
_REPO_ROOT = Path(__file__).resolve().parents[3]
_DASHBOARD_SRC = _REPO_ROOT / "dashboard" / "src"
_FEED_TSX = _DASHBOARD_SRC / "pages" / "feed.tsx"
_PAIRING_MODAL_TSX = _DASHBOARD_SRC / "features" / "devices" / "PairingModal.tsx"
_OWNER_PAGES_TSX = _DASHBOARD_SRC / "pages" / "owner-pages.tsx"

_VALUE_FIELD = re.compile(r"value:\s*'([a-z_]*)'")
_QUOTED_STRING = re.compile(r"'([a-z_]+)'")

pytestmark = [
    pytest.mark.unit,
    pytest.mark.skipif(not _DASHBOARD_SRC.exists(), reason="dashboard/ is not checked out"),
]


def _read(path: Path) -> str:
    assert path.exists(), f"{path} does not exist — the dashboard layout may have moved"
    return path.read_text(encoding="utf-8")


def _object_array_values(source: str, const_name: str) -> list[str]:
    """Values from `const NAME: T[] = [ { value: '...', ... }, ... ];`.

    Same object-per-option shape as `auth.tsx`'s `ROLES` — the one difference
    is a leading `''` "any/all" sentinel some of these lists carry, which is
    not a real enum value and is filtered out by the regex requiring at least
    one character... except it isn't, since `''` matches zero characters too.
    Filtered explicitly below instead of fighting the regex with it.
    """
    block = re.search(rf"const {const_name}[^=]*=\s*\[(.*?)\n\];", source, re.DOTALL)
    assert block is not None, f"Could not find `const {const_name} = [...]` in the source"
    return [value for value in _VALUE_FIELD.findall(block.group(1)) if value]


def _flat_array_values(source: str, const_name: str) -> list[str]:
    """Values from `const NAME = ['a', 'b', ...];` — no wrapper objects."""
    block = re.search(rf"const {const_name}\s*=\s*\[(.*?)\];", source, re.DOTALL)
    assert block is not None, f"Could not find `const {const_name} = [...]` in the source"
    return _QUOTED_STRING.findall(block.group(1))


class TestStageFilterOptions:
    """`feed.tsx`'s `STAGES` — every macro stage should be filterable."""

    def _offered(self) -> list[str]:
        return _object_array_values(_read(_FEED_TSX), "STAGES")

    def test_every_offered_stage_is_a_real_macro_stage(self) -> None:
        server = {stage.value for stage in MacroStage}
        invalid = [value for value in self._offered() if value not in server]
        assert not invalid, (
            f"feed.tsx offers stage filter(s) {invalid}, which MacroStage does not define"
        )

    def test_every_macro_stage_is_offered(self) -> None:
        offered = set(self._offered())
        missing = [stage.value for stage in MacroStage if stage.value not in offered]
        assert not missing, f"MacroStage defines {missing}, which the stage filter does not offer"


class TestStatusFilterOptions:
    """`feed.tsx`'s `STATUSES` — deliberately narrower than `ProjectStatus`.

    `archived` is excluded on purpose: the public feed's own query already
    filters archived projects out (`Domain-Model.md` — visibility
    enforcement), so a filter option for a status that can never appear would
    be a dead control.
    """

    def _offered(self) -> list[str]:
        return _object_array_values(_read(_FEED_TSX), "STATUSES")

    def test_every_offered_status_is_accepted_by_the_server(self) -> None:
        server = {status.value for status in ProjectStatus}
        invalid = [value for value in self._offered() if value not in server]
        assert not invalid, (
            f"feed.tsx offers status filter(s) {invalid}, which ProjectStatus does not define"
        )

    def test_archived_is_deliberately_absent(self) -> None:
        """Documents the exclusion, so a future add-back is a decision, not a drift."""
        assert "archived" not in self._offered()


class TestPairingFaceOptions:
    """`PairingModal.tsx`'s `FACES` — every physical camera placement must be selectable."""

    def _offered(self) -> list[str]:
        return _object_array_values(_read(_PAIRING_MODAL_TSX), "FACES")

    def test_every_offered_face_is_accepted_by_the_server(self) -> None:
        server = {face.value for face in CameraFace}
        invalid = [value for value in self._offered() if value not in server]
        assert not invalid, (
            f"PairingModal offers face(s) {invalid}, which CameraFace does not define"
        )

    def test_every_camera_face_is_offered(self) -> None:
        offered = set(self._offered())
        missing = [face.value for face in CameraFace if face.value not in offered]
        assert not missing, (
            f"CameraFace defines {missing}, which the pairing modal does not offer — "
            "an operator could not pair a camera onto that face at all"
        )


class TestMemberRoleOptions:
    """`owner-pages.tsx`'s `ROLES` — deliberately excludes `owner`.

    A project has exactly one owner, set at creation
    (`Domain-Model.md` — `projects.owner_id`); `owner` is not a role this
    dropdown may assign to a collaborator, and the component that renders it
    additionally hides the control entirely for the member whose role already
    is `owner` (`member.membership_role !== 'owner'`).
    """

    def _offered(self) -> list[str]:
        return _flat_array_values(_read(_OWNER_PAGES_TSX), "ROLES")

    def test_every_offered_role_is_accepted_by_the_server(self) -> None:
        server = {role.value for role in MembershipRole}
        invalid = [value for value in self._offered() if value not in server]
        assert not invalid, (
            f"owner-pages.tsx offers member role(s) {invalid}, which MembershipRole does not define"
        )

    def test_owner_is_deliberately_unassignable_here(self) -> None:
        assert "owner" not in self._offered()
