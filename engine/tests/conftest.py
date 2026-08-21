"""Shared fixtures: one real ingest into a temp DB, plus raw xlsx access."""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import pytest

ENGINE_DIR = Path(__file__).resolve().parents[1]
ROOT = ENGINE_DIR.parent
XLSX = ROOT / "program_z.xlsx"

sys.path.insert(0, str(ENGINE_DIR))

from planz import db as planz_db  # noqa: E402
from planz import ingest  # noqa: E402


@pytest.fixture(scope="session")
def ingest_counts_and_db(tmp_path_factory):
    db_path = tmp_path_factory.mktemp("db") / "planz_test.db"
    counts = ingest.run(XLSX, db_path)
    return counts, db_path


@pytest.fixture(scope="session")
def counts(ingest_counts_and_db):
    return ingest_counts_and_db[0]


@pytest.fixture(scope="session")
def conn(ingest_counts_and_db):
    connection = planz_db.connect(ingest_counts_and_db[1])
    yield connection
    connection.close()


@pytest.fixture(scope="session")
def forecast_db(ingest_counts_and_db):
    """Forecast run once on the temp DB; shared by forecast and MPS tests."""
    from planz import forecast as planz_forecast
    _, db_path = ingest_counts_and_db
    info = planz_forecast.run(db_path)
    return info, db_path


@pytest.fixture(scope="session")
def raw_xl():
    with pd.ExcelFile(XLSX) as xl:
        yield xl
