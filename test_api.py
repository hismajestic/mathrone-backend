import urllib.request
import json

try:
    url = 'http://localhost:8000/api/v1/news/4ce52a51-13fe-4880-b397-6885d07891d4'
    with urllib.request.urlopen(url) as response:
        data = json.loads(response.read().decode())
        print('Success! Post data:')
        print(f'Title: {data["title"]}')
        print(f'ID: {data["id"]}')
except Exception as e:
    print(f'Error: {e}')