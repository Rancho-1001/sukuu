"""Guards on the database fixtures themselves.

A silently broken ``db_session`` rollback is one of the more expensive bugs to meet
later: tests start polluting each other and the failures surface far from the cause.
These three run in well under a second and rule that out.
"""

import pytest
from sqlalchemy import text

pytestmark = pytest.mark.db


def test_engine_fixture_connects(engine):
    with engine.connect() as c:
        assert c.execute(text("select 1")).scalar() == 1


def test_db_session_rolls_back(db_session):
    db_session.execute(text("create table probe_tmp (id int)"))
    db_session.execute(text("insert into probe_tmp values (1)"))
    assert db_session.execute(text("select count(*) from probe_tmp")).scalar() == 1


def test_previous_test_left_nothing_behind(db_session):
    exists = db_session.execute(text("select to_regclass('public.probe_tmp') is not null")).scalar()
    assert exists is False, "rollback did not clean up the previous test's table"
