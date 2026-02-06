import requests
import json

response = requests.post('http://localhost:8000/api/query', 
    json={"query_text": "What was discussed?"}, 
    timeout=60)

print(f"Status: {response.status_code}")
print(f"Headers: {dict(response.headers)}")
print(f"Raw Response: {response.text}")

try:
    data = response.json()
    print(f"\nParsed JSON:")
    print(json.dumps(data, indent=2))
except:
    pass
