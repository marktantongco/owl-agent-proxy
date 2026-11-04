#!/usr/bin/env python3
# search.py - DuckDuckGo web search for OpenClaw
# Update the shebang above to point to a Python environment with 'ddgs' installed
import sys
import json
from ddgs import DDGS

def run_search(query):
    try:
        results = list(DDGS().text(query, max_results=5))
        return json.dumps(results)
    except Exception as e:
        return json.dumps({"error": str(e)})

if __name__ == "__main__":
    if len(sys.argv) > 1:
        print(run_search(sys.argv[1]))
    else:
        print(json.dumps({"error": "No query provided"}))
