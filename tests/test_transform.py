
import pandas as pd
import logging

from transform import (
    clean_inspection_ids,
    clean_inspection_dates,
    clean_facility_type,
    clean_coordinates,
    clean_categories,
    remove_duplicate_inspections,
    transform_data,
    generate_quality_report,
)


def test_clean_inspection_ids():
    sample = pd.DataFrame({
        "inspection_id": [
            "2645162",
            " 2645203 ",
            None,
            "invalid"
        ]
    })

    result = clean_inspection_ids(sample)

    assert str(result["inspection_id"].dtype) == "Int64"
    assert result["inspection_id"].iloc[0] == 2645162
    assert result["inspection_id"].iloc[1] == 2645203
    assert pd.isna(result["inspection_id"].iloc[2])
    assert pd.isna(result["inspection_id"].iloc[3])


def test_clean_inspection_dates():
    sample = pd.DataFrame({
        "inspection_date": [
            "2026-10-14T00:00:00.000",
            "2026-10-15T00:00:00.000",
            None,
            "invalid"
        ]
    })

    result = clean_inspection_dates(sample)

    assert pd.api.types.is_datetime64_any_dtype(
        result["inspection_date"]
    )

    assert result["inspection_date"].iloc[0] == pd.Timestamp("2026-10-14")
    assert result["inspection_date"].iloc[1] == pd.Timestamp("2026-10-15")
    assert pd.isna(result["inspection_date"].iloc[2])
    assert pd.isna(result["inspection_date"].iloc[3])

def test_clean_facility_type():
    sample = pd.DataFrame({
        "facility_type": [
            " Restaurant ",
            "School",
            None,
            "",
            "   "
        ]
    })

    result = clean_facility_type(sample)

    assert result["facility_type"].tolist() == [
        "Restaurant",
        "School",
        "Unknown",
        "Unknown",
        "Unknown"
    ]


def test_clean_coordinates():
    sample = pd.DataFrame({
        "latitude": [
            "41.8958532118424",
            None,
            "invalid"
        ],
        "longitude": [
            "-87.67388067675769",
            "-87.7000",
            None
        ]
    })

    result = clean_coordinates(sample)

    assert pd.api.types.is_numeric_dtype(result["latitude"])
    assert pd.api.types.is_numeric_dtype(result["longitude"])

    assert abs(result["latitude"].iloc[0] - 41.8958532118424) < 1e-8
    assert abs(result["longitude"].iloc[0] - (-87.67388067675769)) < 1e-8

    assert pd.isna(result["latitude"].iloc[1])
    assert pd.isna(result["latitude"].iloc[2])
    assert pd.isna(result["longitude"].iloc[2])


def test_clean_categories():
    sample = pd.DataFrame({
        "risk": [
            " Risk 1 (HIGH) ",
            "risk 2 (medium)",
            None,
            ""
        ],
        "results": [
            "PASS",
            " fail ",
            "PASS W/ CONDITIONS",
            None
        ]
    })

    result = clean_categories(sample)

    assert result["risk"].iloc[0] == "Risk 1 (High)"
    assert result["risk"].iloc[1] == "Risk 2 (Medium)"
    assert pd.isna(result["risk"].iloc[2])
    assert pd.isna(result["risk"].iloc[3])

    assert result["results"].iloc[0] == "Pass"
    assert result["results"].iloc[1] == "Fail"
    assert result["results"].iloc[2] == "Pass W/ Conditions"
    assert pd.isna(result["results"].iloc[3])


def test_remove_duplicate_inspections():
    sample = pd.DataFrame({
        "inspection_id": [1001, 1002, 1001, 1003],
        "results": ["Pass", "Fail", "Pass", "Pass"]
    })

    result = remove_duplicate_inspections(sample)

    assert len(result) == 3
    assert result["inspection_id"].tolist() == [
        1002, 1001, 1003
    ]

    assert result["inspection_id"].is_unique


def test_transform_data():
    sample = pd.DataFrame({
        "inspection_id": ["1001", "1002", "1001"],
        "inspection_date": [
            "2026-10-14",
            "2026-10-15",
            "2026-10-14"
        ],
        "facility_type": [
            " Restaurant ",
            None,
            " Restaurant "
        ],
        "latitude": ["41.89", None, "41.89"],
        "longitude": ["-87.67", None, "-87.67"],
        "risk": ["RISK 1 (HIGH)", "risk 2 (medium)", "RISK 1 (HIGH)"],
        "results": ["PASS", "FAIL", "PASS"]
    })

    result = transform_data(sample)

    assert len(result) == 2
    assert result["inspection_id"].is_unique

    assert str(result["inspection_id"].dtype) == "Int64"
    assert pd.api.types.is_datetime64_any_dtype(
        result["inspection_date"]
    )

    assert result["facility_type"].tolist() == [
        "Unknown",
        "Restaurant"
    ]

    assert result["results"].tolist() == [
        "Fail",
        "Pass"
    ]


def test_generate_quality_report():
    original = pd.DataFrame({
        "inspection_id": [1001, 1002, 1001],
        "facility_type": ["Restaurant", None, "Restaurant"],
        "latitude": [41.89, None, 41.89],
        "longitude": [-87.67, None, -87.67]
    })

    cleaned = pd.DataFrame({
        "inspection_id": [1002, 1001],
        "facility_type": ["Unknown", "Restaurant"],
        "latitude": [None, 41.89],
        "longitude": [None, -87.67]
    })

    report = generate_quality_report(original, cleaned)

    assert report["rows_received"] == 3
    assert report["rows_after_cleaning"] == 2
    assert report["duplicates_removed"] == 1
    assert report["missing_inspection_ids"] == 0
    assert report["missing_facility_types"] == 0
    assert report["missing_coordinates"] == 1


def test_remove_duplicates_with_missing_ids():
    sample = pd.DataFrame({
        "inspection_id": [1001, None, None, 1001, 1002],
        "facility_type": [
            "Restaurant",
            "School",
            "Grocery Store",
            "Restaurant",
            "Bakery"
        ]
    })

    result = remove_duplicate_inspections(sample)

    assert len(result) == 4

    assert result["inspection_id"].isna().sum() == 2

    assert result["facility_type"].tolist() == [
        "School",
        "Grocery Store",
        "Restaurant",
        "Bakery"
    ]


def test_transform_data_logging(caplog):
    sample = pd.DataFrame({
        "inspection_id": ["1001", "1001"],
        "inspection_date": ["2026-10-14", "2026-10-14"],
        "facility_type": ["Restaurant", "Restaurant"],
        "latitude": ["41.89", "41.89"],
        "longitude": ["-87.67", "-87.67"],
        "risk": ["Risk 1 (High)", "Risk 1 (High)"],
        "results": ["Pass", "Pass"]
    })

    with caplog.at_level(logging.INFO):
        result = transform_data(sample)

    assert len(result) == 1
    assert "Starting data transformation" in caplog.text
    assert "Rows received: 2" in caplog.text
    assert "Rows after cleaning: 1" in caplog.text
    assert "Duplicates removed: 1" in caplog.text
    assert "Data transformation completed" in caplog.text
