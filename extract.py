import pandas as pd
from sodapy import Socrata

def extract_data():

    client = Socrata("data.cityofchicago.org", None)
    all_data = []

    while True:
        results = client.get("4ijn-s7e5", limit=2000, offset=len(all_data))
        if not results:
            break
        all_data.extend(results)
        print(f"Total records so far: {len(all_data)}")
        

    results_df = pd.DataFrame.from_records(all_data)

    return results_df


if __name__ == "__main__":
    extract_data()