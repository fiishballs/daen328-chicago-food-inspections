import json
import requests

url = "https://data.cityofchicago.org/resource/4ijn-s7e5.json"

response = requests.get(url)

print(response.status_code)

data = response.json()

with open ("chicago_data.json", "w") as file:
    json.dump(data, file, indent=4)

print(data[0])