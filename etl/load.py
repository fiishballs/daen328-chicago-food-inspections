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

def get_watermark(conn):
    """Return the last successfully loaded API update timestamp."""
    with conn.cursor() as cur:
        cur.execute("""
            SELECT last_updated_at
            FROM public.etl_watermark
            WHERE pipeline_name = %s
        """, ("chicago_food_inspections",))

        result = cur.fetchone()

    if result is None:
        logger.info("No watermark found. Full extraction required.")
        return None

    watermark = result[0]
    logger.info("Previous successful watermark: %s", watermark)

    return watermark

def load_inspections(df, conn, new_watermark=None):
    with conn:
        with conn.cursor() as cur:

            # establishments table
            establishments = df[["aka_name", "address", "city", "state", "zip", "facility_type",
                                 "latitude", "longitude"]].drop_duplicates(["aka_name", "address"])
            for _, row in establishments.iterrows():
                cur.execute(
                    '''INSERT INTO public.establishments (name, street_address, city, state, zip, 
                       facility_type, latitude, longitude) VALUES (%s, %s, %s, %s, %s, %s, %s, %s) 
                        ON CONFLICT (name, street_address)
                        DO UPDATE SET
                            city = EXCLUDED.city,
                            state = EXCLUDED.state,
                            zip = EXCLUDED.zip,
                            facility_type = EXCLUDED.facility_type,
                            latitude = EXCLUDED.latitude,
                            longitude = EXCLUDED.longitude;
                        ''',
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
                        ON CONFLICT (inspection_id)
                        DO UPDATE SET
                            establishment_id = EXCLUDED.establishment_id,
                            inspection_date = EXCLUDED.inspection_date,
                            risk = EXCLUDED.risk,
                            result = EXCLUDED.result;
                        ''',
                    (row["inspection_id"], est_id, row["inspection_date"], clean(row["risk"]), row["results"]))

            # violations table
            violations = df[["violation_code", "violation_title"]].dropna().drop_duplicates("violation_code")
            for _, row in violations.iterrows():
                cur.execute(
                    '''INSERT INTO public.violations (violation_code, description)
                       VALUES (%s, %s) ON CONFLICT (violation_code)
                       DO UPDATE SET
                           description = EXCLUDED.description;
                       ''',
                    (row["violation_code"], row["violation_title"]))

            # inspection_violations table
            for _, row in df.dropna(subset=["violation_code"]).iterrows():
                cur.execute(
                    '''INSERT INTO public.inspection_violations (inspection_id, violation_code, comment)
                       VALUES (%s, %s, %s) ON CONFLICT (inspection_id, violation_code)
                       DO UPDATE SET
                           comment = EXCLUDED.comment;
                       ''',
                    (row["inspection_id"], row["violation_code"], clean(row["violation_comment"])))
                
            # Save checkpoint in the same transaction as the data load.
            if new_watermark is not None:
                cur.execute(
                    """
                    INSERT INTO public.etl_watermark
                        (pipeline_name, last_updated_at)
                    VALUES (%s, %s)
                    ON CONFLICT (pipeline_name)
                    DO UPDATE SET
                        last_updated_at = GREATEST(
                            public.etl_watermark.last_updated_at,
                            EXCLUDED.last_updated_at
                        );
                    """,
                    ("chicago_food_inspections", new_watermark),
                )


    logger.info("Load finished and committed.")

def main():
    conn = psycopg2.connect(**DB_PARAMS)

    try:
        # Step 1: Read the last successful checkpoint.
        previous_watermark = get_watermark(conn)
        conn.rollback()  # End the read transaction.

        if previous_watermark is None:
            logger.info("Starting initial full extraction.")
            updated_since = None
        else:
            logger.info("Starting incremental extraction.")

            # Convert PostgreSQL timestamp to Socrata UTC format.
            updated_since = (
                pd.Timestamp(previous_watermark)
                .tz_convert("UTC")
                .strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
            )

        # Step 2: Extract records.
        # Never accept partial downloads for a checkpointed pipeline.
        data = extract_data(
            limit=1000,
            return_partial=False,
            updated_since=updated_since
        )

        if data.empty:
            logger.info("No new or updated records. Nothing to load.")
            return

        logger.info("API records extracted: %d", len(data))

        # Step 3: Calculate checkpoint from API metadata.
        if ":updated_at" not in data.columns:
            raise ValueError("API update timestamps are missing.")

        new_watermark = pd.to_datetime(
            data[":updated_at"],
            utc=True,
            errors="raise"
        ).max().to_pydatetime()

        # Step 4: Transform.
        df = transform_data(data)

        reject_rows = (
            df["aka_name"].isna()
            | df["inspection_id"].isna()
            | df["inspection_date"].isna()
            | df["results"].isna()
        )

        valid = df[~reject_rows].copy()

        logger.info("Transformed rows: %d", len(df))
        logger.info("Valid rows: %d", len(valid))
        logger.info("Rejected rows: %d", int(reject_rows.sum()))

        # Do not checkpoint data that was not fully accepted.
        
        rejected_count = int(reject_rows.sum())

        if rejected_count > 0:
            logger.warning(
                "Rejected %d transformed rows due to missing "
                "required fields. These rows will not be loaded.",
                rejected_count
            )

            rejected_ids = (
                df.loc[reject_rows, "inspection_id"]
                .dropna()
                .unique()
            )

            logger.warning(
                "Rejected inspection IDs (first 20): %s",
                rejected_ids[:20].tolist()
            )

        if valid.empty:
            raise ValueError(
                "No valid rows to load. Watermark will not advance."
            )

        # Step 5: Load data and checkpoint in one transaction.
        load_inspections(
            valid,
            conn,
            new_watermark=new_watermark
        )

        logger.info(
            "ETL completed. New watermark: %s",
            new_watermark
        )

    finally:
        conn.close()

if __name__ == "__main__":
    try:
        main()
    except Exception:
        logger.exception("ETL pipeline failed")
        sys.exit(1)
