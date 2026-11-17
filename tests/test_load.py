import pandas as pd
import logging
import pytest
import psycopg2
import os
from dotenv import load_dotenv
from psycopg2 import sql
from datetime import datetime, timezone

from etl.load import load_inspections, get_watermark

load_dotenv()

DB_USER = os.environ["DB_USER"]
DB_PASSWORD = os.environ["DB_PASSWORD"]

DB_HOST = os.getenv("DB_HOST", "localhost")
DB_PORT = int(os.getenv("DB_PORT", "5432"))

sample_df = pd.DataFrame([
    {
        "inspection_id": 100,
        "inspection_date": pd.Timestamp("2026-10-14"),
        "aka_name": "Cheesecake Factory",
        "address": "9238 W CEDAR AVE",
        "city": "CHICAGO",
        "state": "IL",
        "zip": "60284",
        "facility_type": "Restaurant",
        "risk": "Risk 2 (Medium)",
        "results": "Pass",
        "facility_type": "Restaurant",
        "latitude": 93.95050,
        "longitude": 29.53821,
        "violation_code": pd.NA,
        "violation_title": pd.NA,
        "violation_comment": pd.NA
    },
    {
        "inspection_id": 101,
        "inspection_date": pd.Timestamp("2026-10-15"),
        "aka_name": "Cheesecake Factory",
        "address": "5873 E OAK ST",
        "city": "CHICAGO",
        "state": "IL",
        "zip": "60132",
        "facility_type": "Restaurant",
        "risk": "Risk 1 (High)",
        "results": "Fail",
        "latitude": 93.7382,
        "longitude": 29.3421,
        "violation_code": 51,
        "violation_title": "Plumbing Installed; Proper Backflow Devices",
        "violation_comment": pd.NA
    },
    {
        "inspection_id": 101,
        "inspection_date": pd.Timestamp("2026-10-15"),
        "aka_name": "Cheesecake Factory",
        "address": "5873 E OAK ST",
        "city": "CHICAGO",
        "state": "IL",
        "zip": "60132",
        "facility_type": "Restaurant",
        "risk": "Risk 1 (High)",
        "results": "Fail",
        "latitude": 93.7382,
        "longitude": 29.3421,
        "violation_code": 10,
        "violation_title": "Adequate Handwashing Sinks Properly Supplied And Accessible",
        "violation_comment": "Talked with district manager."
    },
])


@pytest.fixture
def db_connection():

    db_name = "load_test"

    conn = psycopg2.connect(
        host=DB_HOST,
        port=DB_PORT,
        database="postgres",
        user=DB_USER,
        password=DB_PASSWORD
    )

    conn.autocommit = True

    try:
        with conn.cursor() as cur:

            # Check whether the test database exists
            cur.execute(
                "SELECT 1 FROM pg_database WHERE datname = %s",
                (db_name,)
            )

            # Create database if it doesn't exist
            exists = cur.fetchone()
            if not exists:
                cur.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(db_name)))

    finally:
        conn.close()


    conn = psycopg2.connect(
        host=DB_HOST,
        database=db_name,
        user=DB_USER,
        password=DB_PASSWORD,
        port=DB_PORT
    )

    conn.autocommit = False

    try:
        with conn.cursor() as cur:
            cur.execute("""
                DROP SCHEMA public CASCADE;
                CREATE SCHEMA public;
            """)

            with open("db/init/01_schema.sql", "r") as f:
                cur.execute(f.read())

        conn.commit()

        yield conn

    finally:
        conn.rollback()
        conn.close()


def test_load(db_connection):

    load_inspections(sample_df, db_connection)

    cur = db_connection.cursor()
    
    cur.execute("SELECT COUNT(*) FROM public.establishments")
    assert cur.fetchone()[0] == 2

    cur.execute("SELECT COUNT(*) FROM public.inspections")
    assert cur.fetchone()[0] == 2

    cur.execute("SELECT COUNT(*) FROM public.violations")
    assert cur.fetchone()[0] == 2

    cur.execute("SELECT COUNT(*) FROM public.inspection_violations")
    assert cur.fetchone()[0] == 2


def test_load_idempotency(db_connection):

    load_inspections(sample_df, db_connection)
    load_inspections(sample_df, db_connection)
    
    cur = db_connection.cursor()
        
    cur.execute("SELECT COUNT(*) FROM public.establishments")
    assert cur.fetchone()[0] == 2
    
    cur.execute("SELECT COUNT(*) FROM public.inspections")
    assert cur.fetchone()[0] == 2
    
    cur.execute("SELECT COUNT(*) FROM public.violations")
    assert cur.fetchone()[0] == 2
    
    cur.execute("SELECT COUNT(*) FROM public.inspection_violations")
    assert cur.fetchone()[0] == 2

def test_load_updates_existing_records(db_connection):
    # First, load the original sample records.
    load_inspections(sample_df, db_connection)

    # Simulate changes received from the API.
    updated_df = sample_df.copy()
    updated_df.loc[
        updated_df["inspection_id"] == 101, "results"
    ] = "Pass"

    updated_df.loc[
        updated_df["inspection_id"] == 101, "facility_type"
    ] = "Grocery Store"

    updated_df.loc[
        updated_df["violation_code"] == 10, "violation_comment"
    ] = "Issue corrected after reinspection."

    # Load the changed records again.
    load_inspections(updated_df, db_connection)

    with db_connection.cursor() as cur:
        # Verify the existing inspection was updated.
        cur.execute(
            "SELECT result FROM public.inspections WHERE inspection_id = 101"
        )
        assert cur.fetchone()[0] == "Pass"

        # Verify the establishment was updated.
        cur.execute(
            """
            SELECT facility_type
            FROM public.establishments
            WHERE street_address = %s
            """,
            ("5873 E OAK ST",),
        )
        assert cur.fetchone()[0] == "Grocery Store"

        # Verify the violation comment was updated.
        cur.execute(
            """
            SELECT comment
            FROM public.inspection_violations
            WHERE inspection_id = 101 AND violation_code = 10
            """
        )
        assert cur.fetchone()[0] == "Issue corrected after reinspection."

        # Verify UPSERT did not create duplicate records.
        for table, expected in [
            ("establishments", 2),
            ("inspections", 2),
            ("violations", 2),
            ("inspection_violations", 2),
        ]:
            cur.execute(f"SELECT COUNT(*) FROM public.{table}")
            assert cur.fetchone()[0] == expected

def test_watermark_saved_after_load(db_connection):
    timestamp = datetime(
        2026, 11, 15, 10, 7, 21,
        tzinfo=timezone.utc
    )

    # Load sample inspections and save the checkpoint.
    load_inspections(
        sample_df,
        db_connection,
        new_watermark=timestamp
    )

    # Verify the checkpoint was saved.
    saved_watermark = get_watermark(db_connection)

    assert saved_watermark == timestamp

    # Verify the inspection records were also loaded.
    with db_connection.cursor() as cur:
        cur.execute(
            "SELECT COUNT(*) FROM public.inspections"
        )
        assert cur.fetchone()[0] == 2

def test_watermark_failure_rolls_back_load(db_connection):
    # An invalid timestamp should cause PostgreSQL to reject
    # the watermark update after attempting to load records.
    invalid_timestamp = "not-a-valid-timestamp"

    with pytest.raises(psycopg2.Error):
        load_inspections(
            sample_df,
            db_connection,
            new_watermark=invalid_timestamp
        )

    # Verify the failed transaction did not save inspections.
    with db_connection.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM public.inspections")
        assert cur.fetchone()[0] == 0

        cur.execute("SELECT COUNT(*) FROM public.establishments")
        assert cur.fetchone()[0] == 0

        cur.execute("SELECT COUNT(*) FROM public.etl_watermark")
        assert cur.fetchone()[0] == 0
