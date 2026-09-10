import requests, json

s = requests.get('http://localhost:8000/index/status').json()
print('Status:', json.dumps(s, indent=2))

r = requests.get('http://localhost:8000/search?q=deep+learning').json()
print('\nResults for deep learning:', r['total_results'])
for res in r.get('results', []):
    pct = res.get('relevance_pct', '?')
    fname = res.get('filename', '?')
    print(f'  score={pct}%  file={fname}')
