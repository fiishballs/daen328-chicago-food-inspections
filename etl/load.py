import os, sys
import pandas as pd
import psycopg2
import logging
from sqlalchemy import create_engine, text
from dotenv import load_dotenv

from etl.extract import extract_data
from etl.transform import transform_data

load_dotenv()

DB_NAME = os.environ["DB_NAME"]
DB_USER = os.environ["DB_USER"]
DB_PASSWORD = os.environ["DB_PASSWORD"]
DB_HOST = os.environ["DB_HOST"]
DB_PORT = os.environ["DB_PORT"]
DB_PARAMS = {"dbname": DB_NAME, "user": DB_USER, "password": DB_PASSWORD,
             "host": DB_HOST, "port": DB_PORT}

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)


def clean(value):
    if pd.isna(value):
        return None
    if hasattr(value, "item"):
        return value.item()
    return value


def load_inspections(df, conn):
    with conn:
        with conn.cursor() as cur:

            # establishments table
            establishments = df[["aka_name", "address", "city", "state", "zip", "facility_type",
                                 "latitude", "longitude"]].drop_duplicates(["aka_name", "address"])
            for _, row in establishments.iterrows():
                cur.execute(
                    '''INSERT INTO public.establishments (name, street_address, city, state, zip, 
                       facility_type, latitude, longitude) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                       ON CONFLICT (name, street_address) DO NOTHING;''',
                    (row["aka_name"], clean(row["address"]), clean(row["city"]), clean(row["state"]),
                     clean(row["zip"]), clean(row["facility_type"]), clean(row["latitude"]), clean(row["longitude"])))

            # inspections table
            cur.execute("SELECT name, street_address, establishment_id FROM public.establishments;")
            establishment_ids = {(name, address): establishment_id
                                 for name, address, establishment_id in cur.fetchall()}
                
            inspections = df[["inspection_id", "inspection_date", "risk", "results", "aka_name", "address"]] \
                                .drop_duplicates("inspection_id")
            for _, row in inspections.iterrows():
                est_id = establishment_ids[(row["aka_name"], row["address"])]
                cur.execute(
                    '''INSERT INTO public.inspections (inspection_id, establishment_id, 
                       inspection_date, risk, result) VALUES (%s, %s, %s, %s, %s)
                       ON CONFLICT (inspection_id) DO NOTHING;''',
                    (row["inspection_id"], est_id, row["inspection_date"], clean(row["risk"]), row["results"]))

            # violations table
            violations = df[["violation_code", "violation_title"]].dropna().drop_duplicates("violation_code")
            for _, row in violations.iterrows():
                cur.execute(
                    '''INSERT INTO public.violations (violation_code, description)
                       VALUES (%s, %s) ON CONFLICT (violation_code) DO NOTHING;''',
                    (row["violation_code"], row["violation_title"]))

            # inspection_violations table
            for _, row in df.dropna(subset=["violation_code"]).iterrows():
                cur.execute(
                    '''INSERT INTO public.inspection_violations (inspection_id, violation_code, comment)
                       VALUES (%s, %s, %s) ON CONFLICT (inspection_id, violation_code) DO NOTHING;''',
                    (row["inspection_id"], row["violation_code"], clean(row["violation_comment"])))

    logger.info("Load finished and committed.")


def main():

    data = extract_data(1000, True)
    df = transform_data(data)

    # reject rows that don't meet NOT NULL constraints
    reject_rows = df["aka_name"].isna() | df["inspection_id"].isna() \
                  | df["inspection_date"].isna() | df["results"].isna()
    valid = df[~reject_rows].copy()

    logger.info(f"Rows read: {len(df)}")
    logger.info(f"Good rows: {len(valid)}")

    engine = create_engine(f"postgresql+psycopg2://{DB_USER}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/{DB_NAME}")
    conn = psycopg2.connect(**DB_PARAMS)

    # make sure load results aligned with expectations
    TABLES = ["establishments", "inspections", "violations", "inspection_violations"]

    def table_counts(schema, tables):
        with engine.connect() as conn:
            return {t: conn.execute(text(f"SELECT COUNT(*) FROM {schema}.{t};")).scalar() for t in tables}

    before_counts = table_counts("public", TABLES)

    # load database
    load_inspections(valid, conn)
    conn.close()

    after_counts = table_counts("public", TABLES)

    # count number of added rows for each table
    added_vals = {}
    for t, c in after_counts.items():
        added_vals[t] = c - before_counts[t]

    run_results = pd.DataFrame({"before": before_counts, "after": after_counts, "added": added_vals})
    logger.info(run_results)


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        logger.error(f"LOAD FAILED: {exc}")
        sys.exit(1)