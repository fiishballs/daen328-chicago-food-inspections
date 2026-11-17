import pandas as pd
import logging
import pytest
import psycopg2
import os
from dotenv import load_dotenv
from psycopg2 import sql

from load import load_inspections

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

            with open("db/01_schema.sql", "r") as f:
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


def test_load_upsert(db_connection):

    changed_df = sample_df.copy()
    changed_df.loc[changed_df["inspection_id"] == 101, "risk"] = "Risk 2 (Medium)"
    changed_df.loc[changed_df["inspection_id"] == 101, "zip"] = "62040"
    changed_df.loc[changed_df["inspection_id"] == 101, "violation_title"] = "Plumbing Installed"
    changed_df.loc[changed_df["inspection_id"] == 101, "violation_comment"] = "Manager corrected issue"

    load_inspections(sample_df, db_connection)
    load_inspections(changed_df, db_connection)

    cur = db_connection.cursor()

    cur.execute("SELECT risk FROM public.inspections WHERE inspection_id = 101")
    assert cur.fetchone()[0] == "Risk 2 (Medium)"

    cur.execute("SELECT zip FROM public.establishments WHERE name = 'Cheesecake Factory'")
    assert cur.fetchone()[0] == "62040"

    cur.execute("SELECT description FROM public.violations WHERE violation_code = 51")
    assert cur.fetchone()[0] == "Plumbing Installed"

    cur.execute("SELECT comment FROM public.inspection_violations WHERE inspection_id = 101")
    assert cur.fetchone()[0] == "Manager corrected issue"