
import logging
import requests
import pandas as pd

from transform import transform_data

# Display INFO-level logs in the terminal
logging.basicConfig(
    level=logging.INFO,
    format="%(levelname)s - %(message)s"
)

# Fetch 1000 records from the Chicago Food Inspections API
url = "https://data.cityofchicago.org/resource/4ijn-s7e5.json"

response = requests.get(
    url,
    params={"$limit": 1000},
    timeout=30
)

response.raise_for_status()

# Convert API response to a DataFrame
raw_df = pd.DataFrame(response.json())

print("\nOriginal shape:", raw_df.shape)

# Run our transformation pipeline
cleaned_df = transform_data(raw_df)

print("\nCleaned shape:", cleaned_df.shape)

# Check the cleaned data
print("\nCleaned data types:")
print(cleaned_df[
    [
        "inspection_id",
        "inspection_date",
        "facility_type",
        "latitude",
        "longitude",
        "risk",
        "results"
    ]
].dtypes)

print("\nFirst five cleaned records:")
print(cleaned_df.head())


# Check whether the transformation is idempotent
cleaned_again = transform_data(cleaned_df)

pd.testing.assert_frame_equal(
    cleaned_df,
    cleaned_again
)

print("\nIdempotency test: PASSED")


print("\n===== FINAL DATA QUALITY CHECK =====")

print("\nMissing values by column:")
print(
    cleaned_df.isna()
    .sum()
    .sort_values(ascending=False)
)

print("\nInspection results:")
print(
    cleaned_df["results"].value_counts(dropna=False)
)

print("\nRisk categories:")
print(
    cleaned_df["risk"].value_counts(dropna=False)
)

print("\nFacility types (top 10):")
print(
    cleaned_df["facility_type"].value_counts().head(10)
)
