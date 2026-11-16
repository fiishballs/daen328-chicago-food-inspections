import pandas as pd
import logging
import re

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


def clean_name(df):
    """Standardize establishment name."""
    cleaned = df.copy()

    cleaned["aka_name"] = (
        cleaned["aka_name"]
        .astype("string")
        .str.strip()
        .str.title()
        .replace("", pd.NA)
    )

    return cleaned



def clean_violations(df):
    """Split violations into rows and extract code, title, and comment."""
    cleaned = df.copy()

    # Avoid reparsing violations that have already been transformed
    parsed_columns = {
        "violation_code",
        "violation_title",
        "violation_comment"
    }

    if parsed_columns.issubset(cleaned.columns):
        return cleaned

    def split_violations(violations):
        if pd.isna(violations):
            return [pd.NA]

        return violations.split("|")

    cleaned["violations"] = cleaned["violations"].apply(split_violations)
    cleaned = cleaned.explode("violations")

    def parse_violations(violation):
        empty = {
            "violation_code": pd.NA,
            "violation_title": pd.NA,
            "violation_comment": pd.NA
        }

        if pd.isna(violation) or not str(violation).strip():
            return pd.Series(empty)

        violation = str(violation).strip()

        # Match a numeric violation code at the start
        match = re.match(r"^(\d+)\.\s*(.*)", violation)

        if not match:
            return pd.Series(empty)

        code = match.group(1)
        description = match.group(2)

        # Separate the title from inspector comments
        parts = re.split(
            r"\s*-\s*Comments:\s*",
            description,
            maxsplit=1,
            flags=re.IGNORECASE
        )

        title = parts[0].strip().title()
        comment = parts[1].strip() if len(parts) > 1 else pd.NA

        return pd.Series({
            "violation_code": code,
            "violation_title": title if title else pd.NA,
            "violation_comment": comment if pd.notna(comment) and comment else pd.NA
        })

    cleaned[
        ["violation_code", "violation_title", "violation_comment"]
    ] = cleaned["violations"].apply(parse_violations)

    return cleaned

    def parse_violations(violation):
        if pd.isna(violation) or violation == "":
            return pd.Series({"violation_code": pd.NA, "violation_title": pd.NA, "violation_comment": pd.NA})
    
        code = re.search(r'\d+', violation)
        comment_start = re.search("comments:", violation, flags=re.IGNORECASE)
        if comment_start:
            violation_title = violation[code.end()+1 : comment_start.start() - 3].strip().title()
            comment = violation[comment_start.end():].strip().capitalize()
        else:
            violation_title = violation[code.end()+1 :].strip().title()
            comment = pd.NA
    
        return pd.Series({"violation_code": code.group(), "violation_title": violation_title, "violation_comment": comment})

    cleaned[["violation_code", "violation_title", "violation_comment"]] = cleaned["violations"].apply(parse_violations)
    return cleaned




def remove_duplicate_inspections(df):
    """Combine repeated violation comments while preserving unique observations."""
    cleaned = df.copy()

    keys = ["inspection_id", "violation_code"]

    # Keep rows with missing inspection IDs unchanged
    has_id = cleaned["inspection_id"].notna()
    known_ids = cleaned.loc[has_id].copy()
    missing_ids = cleaned.loc[~has_id].copy()

    # Combine distinct comments, preserving their original order
    def combine_comments(series):
        comments = []
        seen = set()

        for value in series:
            if pd.isna(value):
                continue

            comment = str(value).strip()

            if comment and comment not in seen:
                comments.append(comment)
                seen.add(comment)

        return " | ".join(comments) if comments else pd.NA

    # Handle tests or inputs without a violation_comment column
    if "violation_comment" in known_ids.columns:
        combined_comments = known_ids.groupby(
            keys,
            dropna=False,
            sort=False
        )["violation_comment"].transform(combine_comments)

        known_ids["violation_comment"] = combined_comments

    # Retain one row per inspection and violation code
    known_ids = known_ids.drop_duplicates(
        subset=keys,
        keep="last"
    )

    cleaned = pd.concat(
        [known_ids, missing_ids]
    )

    return cleaned.sort_index().reset_index(drop=True)

def transform_data(df):
    """Run all cleaning steps and log data quality metrics."""

    logging.info("Starting data transformation")

    cleaned = clean_inspection_ids(df)
    cleaned = clean_inspection_dates(cleaned)
    cleaned = clean_facility_type(cleaned)
    cleaned = clean_coordinates(cleaned)
    cleaned = clean_categories(cleaned)
    cleaned = clean_name(cleaned)
    
    cleaned = clean_violations(cleaned)
    rows_before_dedup = len(cleaned)
    cleaned = remove_duplicate_inspections(cleaned)

    duplicates_removed = rows_before_dedup - len(cleaned)

    cleaned = remove_duplicate_inspections(cleaned)

    report = generate_quality_report(
        df,
        cleaned,
        duplicates_removed=duplicates_removed
    )

    logging.info("Rows received: %s", report["rows_received"])
    logging.info("Rows after cleaning: %s", report["rows_after_cleaning"])
    logging.info("Duplicates removed: %s", report["duplicates_removed"])
    logging.info("Missing inspection IDs: %s", report["missing_inspection_ids"])
    logging.info("Missing facility types: %s", report["missing_facility_types"])
    logging.info("Missing coordinates: %s", report["missing_coordinates"])

    logging.info("Missing values by column:")

    for column, counts in report["missing_summary"].items():
        logging.info(
            "%s: %s before, %s after",
            column,
            counts["before"],
            counts["after"]
        )

    logging.info("Data transformation completed")

    return cleaned


def generate_quality_report(original_df, cleaned_df, duplicates_removed=None):
    """Summarize data quality before and after transformation."""

    report = {
        "rows_received": len(original_df),
        "rows_after_cleaning": len(cleaned_df),
        "duplicates_removed": (
            duplicates_removed
            if duplicates_removed is not None
            else max(0, len(original_df) - len(cleaned_df))
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

    # Track missing values for each cleaned column
    columns_to_check = [
        "inspection_id",
        "inspection_date",
        "facility_type",
        "latitude",
        "longitude",
        "risk",
        "results",
        "aka_name"
    ]

    missing_summary = {}

    for column in columns_to_check:
        # Only report columns that exist in both DataFrames
        if column not in original_df.columns or column not in cleaned_df.columns:
            continue

        before = original_df[column].isna().sum()
        after = cleaned_df[column].isna().sum()

        missing_summary[column] = {
            "before": int(before),
            "after": int(after)
        }

    report["missing_summary"] = missing_summary


    return report



