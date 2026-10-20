import json
import requests
import pandas as pd

url = "https://data.cityofchicago.org/resource/4ijn-s7e5.json"

response = requests.get(url)

print(response.status_code)

data = response.json()

df = pd.DataFrame(data)

print(df.head())
print("\n DF Info:")
print(df.info())