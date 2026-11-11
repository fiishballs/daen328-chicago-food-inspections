import json
import requests
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
        print(results[0])
        

    results_df = pd.DataFrame.from_records(all_data)

    return results_df