from concurrent.futures import ThreadPoolExecutor, as_completed
import json, urllib.request

URL = "http://localhost:8080"

def send(i):
    payload = json.dumps({"intent": f"What was Apple's stock price in {2010+i}? See if the there are news explaining this behavior", "max_tasks": 4}).encode()
    req = urllib.request.Request(f"{URL}/run", data=payload, headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=400) as r:
        return i, json.loads(r.read())["result"][:80]

# Fire more requests than the concurrency limit to force queuing
with ThreadPoolExecutor(max_workers=5) as pool:
    futures = [pool.submit(send, i) for i in range(5)]
    for f in as_completed(futures):
        i, result = f.result()
        print(f"[{i}] {result}")