"""A parent discovering their own children.

The gap this fills is worth stating: every other student route is either
staff-only or keyed by an id, so before this a parent-facing screen had no
starting point. The alternative -- letting parents call the staff roster with a
`parent_id` filter -- would put family privacy behind a query parameter, which
is one forgotten argument away from listing the whole school.
"""

from __future__ import annotations

import pytest

from app.models import StudentStatus, UserRole

pytestmark = pytest.mark.db

URL = "/me/children"


class TestAParentsOwnChildren:
    def test_a_parent_sees_their_children(self, api, token_for, make_student):
        parent, headers = token_for(UserRole.PARENT)
        first = make_student(first_name="Ama", parent=parent)
        second = make_student(first_name="Kofi", parent=parent)

        response = api.get(URL, headers=headers)
        assert response.status_code == 200, response.text
        assert {child["id"] for child in response.json()} == {first.id, second.id}

    def test_nobody_elses_children_are_included(self, api, token_for, make_user, make_student):
        parent, headers = token_for(UserRole.PARENT)
        mine = make_student(parent=parent)
        theirs = make_student(parent=make_user(UserRole.PARENT))
        unattached = make_student()

        ids = {child["id"] for child in api.get(URL, headers=headers).json()}
        assert ids == {mine.id}
        assert theirs.id not in ids
        assert unattached.id not in ids

    def test_there_is_no_parameter_to_forget(self, api, token_for, make_user, make_student):
        """The answer comes from the token. A parent_id in the query string is
        ignored rather than honoured, so it cannot be used to look sideways."""
        parent, headers = token_for(UserRole.PARENT)
        mine = make_student(parent=parent)
        other_parent = make_user(UserRole.PARENT)
        make_student(parent=other_parent)

        response = api.get(f"{URL}?parent_id={other_parent.id}", headers=headers)
        assert [child["id"] for child in response.json()] == [mine.id]

    def test_a_parent_with_no_children_gets_an_empty_list(self, api, parent_headers):
        """Not a 404. Nothing is missing - there is simply nobody enrolled yet,
        and the screen needs to say so rather than break."""
        response = api.get(URL, headers=parent_headers)
        assert response.status_code == 200
        assert response.json() == []

    def test_the_class_comes_with_them(self, api, token_for, make_class, make_student):
        """So the picker can label two children by class without a request each."""
        parent, headers = token_for(UserRole.PARENT)
        make_student(parent=parent, school_class=make_class(name="Grade 5B"))

        child = api.get(URL, headers=headers).json()[0]
        assert child["school_class"]["name"] == "Grade 5B"

    def test_an_inactive_child_is_still_listed(self, api, token_for, make_student):
        """A withdrawn pupil's arrears are still owed, and the parent still has
        to be able to reach the bill to pay it."""
        parent, headers = token_for(UserRole.PARENT)
        make_student(parent=parent, status=StudentStatus.INACTIVE)

        assert len(api.get(URL, headers=headers).json()) == 1

    def test_no_credentials_are_exposed(self, api, token_for, make_student):
        parent, headers = token_for(UserRole.PARENT)
        make_student(parent=parent)
        assert "password" not in api.get(URL, headers=headers).text.lower()


class TestWhoMayAsk:
    @pytest.mark.parametrize("role", [UserRole.ADMIN, UserRole.STAFF])
    def test_staff_and_admins_use_the_roster_instead(self, api, headers_for, role):
        """403 rather than an empty list: they have no children here, and
        answering [] would suggest this route is where they should look."""
        assert api.get(URL, headers=headers_for(role)).status_code == 403

    def test_anonymous_is_rejected(self, api):
        assert api.get(URL).status_code == 401
