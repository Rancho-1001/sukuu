"""The fee catalogue through HTTP.

Money assertions here are deliberately literal - ``"250.00"``, quoted. The
format is a decision the frontend depends on, so a change to it should break a
test rather than a currency display.
"""

from __future__ import annotations

from uuid import uuid4

import pytest

from app.models import BillingPeriod, UserRole

pytestmark = pytest.mark.db


def a_name() -> str:
    return f"Fee {uuid4().hex[:10]}"


class TestCreate:
    def test_an_admin_defines_a_fee(self, api, admin_headers):
        response = api.post(
            "/fee-types",
            json={
                "name": a_name(),
                "description": "Termly tuition",
                "default_amount": "250.00",
                "billing_period": "term",
            },
            headers=admin_headers,
        )
        assert response.status_code == 201, response.text
        body = response.json()
        assert body["default_amount"] == "250.00"
        assert body["billing_period"] == "term"
        assert body["description"] == "Termly tuition"

    def test_money_leaves_as_a_string(self, api, admin_headers):
        """A JSON number is a double once a browser parses it. The models
        refuse to store that float; the API should not hand one out either."""
        body = api.post(
            "/fee-types",
            json={"name": a_name(), "default_amount": 250, "billing_period": "term"},
            headers=admin_headers,
        ).json()
        assert body["default_amount"] == "250.00"

    @pytest.mark.parametrize("amount", ["0", "0.00", "-1.00"])
    def test_a_non_positive_amount_is_refused(self, api, admin_headers, amount):
        response = api.post(
            "/fee-types",
            json={"name": a_name(), "default_amount": amount, "billing_period": "term"},
            headers=admin_headers,
        )
        assert response.status_code == 422
        assert response.json()["errors"][0]["field"] == "default_amount"

    def test_a_third_decimal_place_is_refused(self, api, admin_headers):
        """NUMERIC(12, 2) would round it on the way in. A price list that
        quietly changes the price is worse than one that rejects the input."""
        response = api.post(
            "/fee-types",
            json={"name": a_name(), "default_amount": "250.005", "billing_period": "term"},
            headers=admin_headers,
        )
        assert response.status_code == 422

    def test_an_amount_too_large_for_the_column_is_refused(self, api, admin_headers):
        """12 digits is the column. Without the check this is a 500 from
        Postgres, after the request has already been audited."""
        response = api.post(
            "/fee-types",
            json={"name": a_name(), "default_amount": "12345678901.00", "billing_period": "term"},
            headers=admin_headers,
        )
        assert response.status_code == 422

    def test_an_unknown_billing_period_is_refused(self, api, admin_headers):
        response = api.post(
            "/fee-types",
            json={"name": a_name(), "default_amount": "10.00", "billing_period": "fortnightly"},
            headers=admin_headers,
        )
        assert response.status_code == 422
        assert response.json()["errors"][0]["field"] == "billing_period"

    def test_a_blank_description_is_stored_as_absent(self, api, admin_headers):
        """Otherwise a form submitting its untouched field leaves "" behind,
        and every consumer has to treat "" and null alike forever."""
        body = api.post(
            "/fee-types",
            json={
                "name": a_name(),
                "description": "   ",
                "default_amount": "10.00",
                "billing_period": "term",
            },
            headers=admin_headers,
        ).json()
        assert body["description"] is None

    def test_a_duplicate_name_is_a_conflict(self, api, admin_headers):
        name = a_name()
        payload = {"name": name, "default_amount": "10.00", "billing_period": "term"}
        assert api.post("/fee-types", json=payload, headers=admin_headers).status_code == 201

        response = api.post("/fee-types", json=payload, headers=admin_headers)
        assert response.status_code == 409
        assert "already exists" in response.json()["detail"]

    @pytest.mark.parametrize("role", [UserRole.STAFF, UserRole.PARENT])
    def test_only_admins_may_define_fees(self, api, headers_for, role):
        """The spec is explicit: a bursar records payments and cannot touch
        the fee structure."""
        response = api.post(
            "/fee-types",
            json={"name": a_name(), "default_amount": "10.00", "billing_period": "term"},
            headers=headers_for(role),
        )
        assert response.status_code == 403


class TestList:
    def test_filtering_by_billing_period(self, api, admin_headers, make_fee_type):
        one_off = make_fee_type(billing_period=BillingPeriod.ONE_TIME)
        make_fee_type(billing_period=BillingPeriod.TERM)

        body = api.get("/fee-types?billing_period=one_time", headers=admin_headers).json()
        assert one_off.id in [item["id"] for item in body["items"]]
        assert all(item["billing_period"] == "one_time" for item in body["items"])

    def test_searching_by_name(self, api, admin_headers, make_fee_type):
        fee_type = make_fee_type(name=f"Uniform {uuid4().hex[:8]}")
        body = api.get(f"/fee-types?q={fee_type.name}", headers=admin_headers).json()
        assert [item["id"] for item in body["items"]] == [fee_type.id]

    def test_the_page_reports_its_bounds(self, api, admin_headers, make_fee_type):
        make_fee_type()
        body = api.get("/fee-types?limit=1", headers=admin_headers).json()
        assert len(body["items"]) == 1
        assert body["limit"] == 1
        assert body["total"] >= 1

    @pytest.mark.parametrize("role", [UserRole.ADMIN, UserRole.STAFF])
    def test_staff_may_read_the_catalogue(self, api, headers_for, role):
        assert api.get("/fee-types", headers=headers_for(role)).status_code == 200

    def test_parents_may_not(self, api, parent_headers):
        assert api.get("/fee-types", headers=parent_headers).status_code == 403


class TestUpdate:
    def test_an_admin_changes_the_default_amount(self, api, admin_headers, make_fee_type):
        fee_type = make_fee_type(default_amount="250.00")
        response = api.patch(
            f"/fee-types/{fee_type.id}", json={"default_amount": "300.00"}, headers=admin_headers
        )
        assert response.status_code == 200
        assert response.json()["default_amount"] == "300.00"

    def test_an_omitted_field_is_left_alone(self, api, admin_headers, make_fee_type):
        fee_type = make_fee_type(name="Tuition " + uuid4().hex[:6])
        body = api.patch(
            f"/fee-types/{fee_type.id}", json={"default_amount": "300.00"}, headers=admin_headers
        ).json()
        assert body["name"] == fee_type.name

    def test_changing_the_default_does_not_rewrite_existing_bills(
        self, api, admin_headers, make_fee_type, make_student, make_fee_assignment, db_session
    ):
        """An assignment stores what a particular student was actually billed.
        Editing a price list must not change what a parent owes - possibly to
        less than they have already paid."""
        from decimal import Decimal

        fee_type = make_fee_type(default_amount="250.00")
        assignment = make_fee_assignment(make_student(), fee_type)

        api.patch(
            f"/fee-types/{fee_type.id}", json={"default_amount": "400.00"}, headers=admin_headers
        )

        db_session.refresh(assignment)
        assert assignment.amount == Decimal("250.00")

    def test_renaming_onto_an_existing_name_is_a_conflict(self, api, admin_headers, make_fee_type):
        first = make_fee_type()
        second = make_fee_type()
        response = api.patch(
            f"/fee-types/{second.id}", json={"name": first.name}, headers=admin_headers
        )
        assert response.status_code == 409

    def test_an_unknown_fee_type_is_404(self, api, admin_headers):
        response = api.patch("/fee-types/99999999", json={"name": "x"}, headers=admin_headers)
        assert response.status_code == 404

    @pytest.mark.parametrize("role", [UserRole.STAFF, UserRole.PARENT])
    def test_only_admins_may_update(self, api, headers_for, make_fee_type, role):
        fee_type = make_fee_type()
        response = api.patch(
            f"/fee-types/{fee_type.id}", json={"default_amount": "1.00"}, headers=headers_for(role)
        )
        assert response.status_code == 403
