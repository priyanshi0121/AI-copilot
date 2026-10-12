"""Steady synthetic traffic so Prometheus rate() queries always have data.

This is the in-bundle replacement for the curlimages/curl loop that
docker-compose runs as a separate container.
"""
import os
import time

import requests

PAY_URL = os.environ.get("LOADGEN_PAY_URL", "http://127.0.0.1:5002/pay")
ORDER_URL = os.environ.get("LOADGEN_ORDER_URL", "http://127.0.0.1:5001/order")
INTERVAL_S = float(os.environ.get("LOADGEN_INTERVAL_S", "1"))


def main():
    session = requests.Session()
    while True:
        for method, url in (("post", PAY_URL), ("get", ORDER_URL)):
            try:
                getattr(session, method)(url, timeout=10)
            except requests.RequestException:
                pass  # service not up yet / restarting — keep the loop alive
        time.sleep(INTERVAL_S)


if __name__ == "__main__":
    main()
