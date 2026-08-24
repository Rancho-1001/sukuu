"""Every error the API returns has the same envelope.

The value of this file is that it fails the moment a route starts answering in
a different shape - which is what happens by default the first time someone
raises ``HTTPException(422, detail={"field": ...})`` because it seemed tidier
locally.
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from pydantic import BaseModel

from app.api.errors import register_error_handlers, unprocessable
from app.schemas.common import Money


class Body(BaseModel):
    """Declared at module scope, not inside the fixture: with postponed
    annotations a locally-defined model is a name FastAPI cannot resolve when
    it reads the route signature."""

    amount: Money
    label: str


@pytest.fixture
def error_api():
    """A minimal app that can be made to fail in each of the ways that matter."""
    app = FastAPI()
    register_error_handlers(app)

    @app.post("/echo")
    def echo(body: Body) -> dict[str, str]:
        return {"amount": str(body.amount)}

    @app.get("/missing")
    def missing() -> None:
        raise HTTPException(404, "Student not found")

    @app.get("/unprocessable")
    def bad_reference() -> None:
        raise unprocessable("class_id", "does not exist")

    with TestClient(app) as client:
        yield client


class TestValidationErrors:
    def test_detail_is_a_sentence_not_a_list(self, error_api):
        """The default FastAPI shape puts a list here. A client rendering it
        gets "[object Object]", which is how the inconsistency reaches users."""
        response = error_api.post("/echo", json={"amount": "-5.00", "label": "x"})
        assert response.status_code == 422
        assert isinstance(response.json()["detail"], str)

    def test_field_errors_are_addressable(self, error_api):
        response = error_api.post("/echo", json={"amount": "-5.00", "label": "x"})
        errors = response.json()["errors"]
        assert [e["field"] for e in errors] == ["amount"]
        assert "greater than 0" in errors[0]["message"]

    def test_the_body_prefix_is_stripped_from_field_names(self, error_api):
        """``["body", "amount"]`` is FastAPI's business, not the form's."""
        response = error_api.post("/echo", json={"amount": "10.00"})
        assert response.json()["errors"][0]["field"] == "label"

    def test_several_bad_fields_are_all_reported(self, error_api):
        """One error at a time turns filling in a form into a guessing game."""
        response = error_api.post("/echo", json={})
        fields = {e["field"] for e in response.json()["errors"]}
        assert fields == {"amount", "label"}

    def test_a_third_decimal_place_is_rejected(self, error_api):
        """NUMERIC(12, 2) would round it. Rounding money without saying so is
        how a ledger drifts."""
        response = error_api.post("/echo", json={"amount": "10.005", "label": "x"})
        assert response.status_code == 422
        assert response.json()["errors"][0]["field"] == "amount"

    def test_a_json_number_is_still_accepted(self, error_api):
        """Money leaves as a string; that must not make it string-only on the
        way in, or every client has to quote its own numbers."""
        response = error_api.post("/echo", json={"amount": 250, "label": "x"})
        assert response.status_code == 200


class TestOtherErrors:
    def test_http_exceptions_keep_the_same_key(self, error_api):
        body = error_api.get("/missing").json()
        assert body == {"detail": "Student not found"}

    def test_unprocessable_names_the_field(self, error_api):
        response = error_api.get("/unprocessable")
        assert response.status_code == 422
        assert response.json()["detail"] == "class_id: does not exist"


class TestAgainstTheRealApp:
    def test_a_login_without_credentials_uses_the_shape(self, client):
        """Proof the handler is registered on the real app and not only in the
        fixture above."""
        response = client.post("/auth/login", data={})
        assert response.status_code == 422
        assert isinstance(response.json()["detail"], str)
        assert {e["field"] for e in response.json()["errors"]} == {"username", "password"}
