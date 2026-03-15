"""
Entry point for GitHub Actions weekly scan.
Calls the deployed app's /api/trigger-scan endpoint.

Usage:
  APP_URL=https://your-app.com SCAN_SECRET=your-secret python run_scan.py
"""
import os
import sys
import time

import requests

APP_URL = os.environ.get('APP_URL', '').rstrip('/')
SCAN_SECRET = os.environ.get('SCAN_SECRET', '')

if not APP_URL or not SCAN_SECRET:
    print('ERROR: APP_URL and SCAN_SECRET environment variables are required.')
    sys.exit(1)

url = f'{APP_URL}/api/trigger-scan'
headers = {'Authorization': f'Bearer {SCAN_SECRET}'}

max_retries = 4
delay = 2

for attempt in range(1, max_retries + 1):
    try:
        print(f'Attempt {attempt}: POST {url}')
        response = requests.post(url, headers=headers, timeout=300)
        response.raise_for_status()
        data = response.json()
        print('Scan trigger successful:')
        for result in data.get('results', []):
            print(f"  {result['user']}: {result['status']}"
                  + (f" ({result['emails_found']} emails)" if 'emails_found' in result else ''))
        sys.exit(0)
    except requests.RequestException as e:
        print(f'Error on attempt {attempt}: {e}')
        if attempt < max_retries:
            print(f'Retrying in {delay}s...')
            time.sleep(delay)
            delay *= 2
        else:
            print('All retries exhausted.')
            sys.exit(1)
