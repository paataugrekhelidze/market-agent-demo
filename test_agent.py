#!/usr/bin/env python3
"""
Usage:
    python test_agent.py "Find top 3 companies with 8% stock moves in 2014"
    python test_agent.py --url http://localhost:8080 "your prompt here"
    python test_agent.py --max-tasks 3 "your prompt here"
"""
import argparse
import json
import sys
import urllib.request
import urllib.error


def run(prompt: str, url: str, max_tasks: int) -> str:
    payload = json.dumps({"intent": prompt, "max_tasks": max_tasks}).encode()
    req = urllib.request.Request(
        f"{url}/run",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req) as resp:
            body = json.loads(resp.read())
            return body["result"]
    except urllib.error.HTTPError as e:
        detail = e.read().decode()
        print(f"HTTP {e.code}: {detail}", file=sys.stderr)
        sys.exit(1)
    except urllib.error.URLError as e:
        print(f"Connection error: {e.reason}", file=sys.stderr)
        print(f"Is the agent running at {url}?", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Send a prompt to the market agent.")
    parser.add_argument("prompt", help="The intent/question to send to the agent.")
    parser.add_argument("--url", default="http://localhost:8080", help="Agent base URL.")
    parser.add_argument("--max-tasks", type=int, default=5, help="Max pipeline steps.")
    args = parser.parse_args()

    print(f"Sending prompt to {args.url} ...\n")
    result = run(args.prompt, args.url, args.max_tasks)
    print(result)