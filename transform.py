import pandas as pd
import logging

def clean_inspection_ids(df):
    """Convert inspection IDs into nullable integers."""

    cleaned = df.copy()

    cleaned["inspection_id"] = pd.to_numeric(
        cleaned["inspection_id"], 
        errors="coerce"
    ).astype("Int64") 

    return cleaned


def clean_inspection_dates(df):
    """Convert inspection dates into datetime values."""
    cleaned = df.copy()

    cleaned["inspection_date"] = pd.to_datetime(
        cleaned["inspection_date"],
        errors="coerce"
    )

    return cleaned


def clean_facility_type(df):
    """Fill missing facility types and standardize whitespace."""
    cleaned = df.copy()

    cleaned["facility_type"] = (
        cleaned["facility_type"]
        .astype("string")
        .str.strip()
        .replace("", pd.NA)
        .fillna("Unknown")
    )

    return cleaned


def clean_coordinates(df):
    """Convert latitude and longitude to numeric values."""
    cleaned = df.copy()

    for column in ["latitude", "longitude"]:
        cleaned[column] = pd.to_numeric(
            cleaned[column],
            errors="coerce"
        )

    return cleaned


def clean_categories(df):
    """Standardize risk and inspection result labels."""
    cleaned = df.copy()

    for column in ["risk", "results"]:
        cleaned[column] = (
            cleaned[column]
            .astype("string")
            .str.strip()
            .str.lower()
            .str.title()
            .replace("", pd.NA)
        )

    return cleaned


def remove_duplicate_inspections(df):
    """Remove duplicate known IDs while preserving missing IDs."""
    cleaned = df.copy()

    has_id = cleaned["inspection_id"].notna()

    known_ids = cleaned[has_id].drop_duplicates(
        subset=["inspection_id"],
        keep="last"
    )

    missing_ids = cleaned[~has_id]

    cleaned = pd.concat([known_ids, missing_ids])

    return cleaned.sort_index().reset_index(drop=True)


def transform_data(df):
    """Run all cleaning steps and log data quality metrics."""

    logging.info("Starting data transformation")

    cleaned = clean_inspection_ids(df)
    cleaned = clean_inspection_dates(cleaned)
    cleaned = clean_facility_type(cleaned)
    cleaned = clean_coordinates(cleaned)
    cleaned = clean_categories(cleaned)
    cleaned = remove_duplicate_inspections(cleaned)

    report = generate_quality_report(df, cleaned)

    logging.info("Rows received: %s", report["rows_received"])
    logging.info("Rows after cleaning: %s", report["rows_after_cleaning"])
    logging.info("Duplicates removed: %s", report["duplicates_removed"])
    logging.info("Missing inspection IDs: %s", report["missing_inspection_ids"])
    logging.info("Missing facility types: %s", report["missing_facility_types"])
    logging.info("Missing coordinates: %s", report["missing_coordinates"])

    logging.info("Data transformation completed")

    return cleaned


def generate_quality_report(original_df, cleaned_df):
    """Summarize data quality before and after transformation."""

    report = {
        "rows_received": len(original_df),
        "rows_after_cleaning": len(cleaned_df),
        "duplicates_removed": (
            len(original_df) - len(cleaned_df)
        ),
        "missing_inspection_ids": (
            cleaned_df["inspection_id"].isna().sum()
        ),
        "missing_facility_types": (
            cleaned_df["facility_type"].isna().sum()
        ),
        "missing_coordinates": (
            cleaned_df[["latitude", "longitude"]]
            .isna()
            .any(axis=1)
            .sum()
        )
    }

    return report
