import os
import logging
import requests
import threading
import time
from datetime import datetime
from random import uniform
from flask import Flask, jsonify, render_template_string
from waitress import serve

# ---------- CONFIGURATION ----------
EMAIL = os.environ.get("EMAIL", "")
PASSWORD = os.environ.get("PASSWORD", "")
BASE_URL = "https://stexsms.com/mapi/v1"
MAX_LOGS = 100
POLL_SECONDS = 30                # base interval between successful polls
INFO_TIMEOUT = 15                # read timeout
MAX_RETRIES = 2                  # retries for timeouts only
RATE_LIMIT_BACKOFF_BASE = 60     # initial backoff on 429 (seconds)
MAX_BACKOFF = 600                # never wait more than 10 minutes
# -----------------------------------

app = Flask(__name__)
logs_data = []
seen_log_ids = set()

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(message)s')
logger = logging.getLogger(__name__)


def monitor_task():
    """Background thread: login to stexsms and continuously pull logs."""
    global logs_data, seen_log_ids

    if not EMAIL or not PASSWORD:
        logger.error("EMAIL and PASSWORD environment variables must be set!")
        return

    session = requests.Session()
    headers = {
        "user-agent": "Mozilla/5.0 (Linux; Android 10) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Mobile Safari/537.36",
        "content-type": "application/json",
        "accept": "application/json, text/plain, */*",
        "origin": "https://stexsms.com"
    }

    def login():
        try:
            resp = session.post(
                f"{BASE_URL}/mauth/login",
                json={"email": EMAIL, "password": PASSWORD},
                headers=headers,
                timeout=10
            )
            if resp.status_code == 200:
                token = resp.json().get("data", {}).get("token")
                if token:
                    headers["mauthtoken"] = token
                    logger.info("Login successful")
                    return True
            logger.warning(f"Login failed. Status: {resp.status_code}")
        except Exception as e:
            logger.error(f"Login error: {e}")
        return False

    login()
    info_url = f"{BASE_URL}/mdashboard/console/info"

    backoff = POLL_SECONDS
    consecutive_rate_limits = 0

    while True:
        success = False
        for attempt in range(1 + MAX_RETRIES):
            try:
                resp = session.get(info_url, headers=headers, timeout=INFO_TIMEOUT)

                # Token expired
                if resp.status_code == 401:
                    logger.warning("Token expired – re-login")
                    login()
                    continue

                # Rate limited – 429
                if resp.status_code == 429:
                    retry_after = resp.headers.get("Retry-After")
                    if retry_after:
                        try:
                            wait = int(retry_after)
                        except ValueError:
                            wait = RATE_LIMIT_BACKOFF_BASE
                    else:
                        wait = min(RATE_LIMIT_BACKOFF_BASE * (2 ** consecutive_rate_limits), MAX_BACKOFF)
                    # Add random jitter: ±20%
                    wait = int(wait * uniform(0.8, 1.2))
                    logger.warning(f"Rate limited (429). Backing off for {wait}s")
                    time.sleep(wait)
                    consecutive_rate_limits += 1
                    break   # exit retry loop, then outer loop will also sleep backoff

                # Success
                if resp.status_code == 200:
                    data = resp.json().get("data", {}).get("logs", [])
                    for item in reversed(data):
                        log_id = str(item.get('id', ''))
                        if log_id and log_id not in seen_log_ids:
                            log_entry = {
                                "id": log_id,
                                "app": item.get('app_name', 'Unknown'),
                                "number": item.get('number', 'N/A'),
                                "range": str(item.get('range', 'N/A')),
                                "country": item.get('country', 'N/A'),
                                "message": item.get('sms', 'No Message'),
                                "received_at": datetime.now().strftime("%H:%M:%S")
                            }
                            logs_data.insert(0, log_entry)
                            seen_log_ids.add(log_id)
                            if len(logs_data) > MAX_LOGS:
                                logs_data.pop()

                    if len(seen_log_ids) > 1000:
                        seen_log_ids = set(list(seen_log_ids)[-500:])

                    # Reset backoff on success
                    backoff = POLL_SECONDS
                    consecutive_rate_limits = 0
                    success = True
                    break

                # Any other status
                logger.warning(f"Unexpected status {resp.status_code}")
                break

            except requests.exceptions.Timeout:
                if attempt < MAX_RETRIES:
                    logger.info(f"Timeout attempt {attempt+1}, retrying...")
                    time.sleep(1)
                else:
                    logger.warning(f"Timeout after {MAX_RETRIES+1} attempts")
                    # Increase backoff after repeated timeouts
                    backoff = min(backoff * 1.5, MAX_BACKOFF)
            except Exception as e:
                logger.error(f"Polling error: {e}")
                break

        # Compute sleep before next poll
        if not success:
            # If we got a 429, backoff already increased; for other failures, increase slightly
            if consecutive_rate_limits == 0:
                backoff = min(backoff * 1.5, MAX_BACKOFF)
            # Add small jitter to avoid exact synchronisation
            backoff += uniform(-2, 2)
            backoff = max(backoff, POLL_SECONDS)
            logger.info(f"Sleeping for {backoff:.0f}s before next poll")
        else:
            backoff = POLL_SECONDS + uniform(-2, 2)
            backoff = max(backoff, POLL_SECONDS)

        time.sleep(backoff)


# ---------- FRONTEND (unchanged) ----------
HTML_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
    <title>TSB Console Zone (Live)</title>
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <style>
        body { font-family: 'Segoe UI', sans-serif; background: #f0f2f5; margin: 0; padding: 10px; color: #333; }
        .container { max-width: 600px; margin: auto; }
        .header { background: #007bff; padding: 15px; border-radius: 12px; margin-bottom: 15px; text-align: center; color: white; box-shadow: 0 4px 6px rgba(0,0,0,0.1); }
        .header h2 { margin: 0; font-size: 1.2rem; text-transform: uppercase; letter-spacing: 1px; }
        .card { background: #fff; border-radius: 10px; padding: 12px; margin-bottom: 10px; border-left: 5px solid #007bff; box-shadow: 0 2px 8px rgba(0,0,0,0.05); }
        .row { display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px; border-bottom: 1px solid #eee; padding-bottom: 5px; }
        .app-name { font-weight: bold; color: #0056b3; font-size: 0.9rem; }
        .sync-time { font-size: 0.7rem; color: #6c757d; font-weight: 600; }
        .data-grid { display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 8px; margin-top: 5px; }
        .sms-box { background: #fff4f4; border: 1px dashed #ffc1c1; padding: 10px; border-radius: 6px; margin-top: 8px; }
        .sms-text { color: #d63031; font-weight: bold; font-family: 'Courier New', monospace; font-size: 1rem; word-break: break-all; }
        .label { font-size: 0.65rem; color: #95a5a6; text-transform: uppercase; }
        .val { font-size: 0.8rem; color: #2d3436; font-weight: 600; }
        .copy-number { cursor: pointer; transition: background-color 0.2s; padding: 2px 4px; border-radius: 4px; }
        .copy-number:hover { background-color: #e9f2ff; }
        #status { text-align: center; margin-top: 20px; color: #aaa; font-size: 0.8rem; }
    </style>
</head>
<body>
    <div class="container">
        <div class="header"><h2>TSB Console Live</h2></div>
        <div id="logs"></div>
        <div id="status"></div>
    </div>
    <script>
        const REFRESH_MS = 5000;

        function formatTime() {
            return new Date().toLocaleTimeString();
        }

        async function loadLogs() {
            try {
                const res = await fetch('/api/logs');
                const data = await res.json();
                const container = document.getElementById('logs');
                const status = document.getElementById('status');

                container.innerHTML = data.map(log => `
                    <div class="card">
                        <div class="row">
                            <span class="app-name">${log.app}</span>
                            <span class="sync-time">${log.received_at}</span>
                        </div>
                        <div class="data-grid">
                            <div>
                                <div class="label">Number</div>
                                <div class="val copy-number" title="Click to copy">${log.number}</div>
                            </div>
                            <div>
                                <div class="label">Range</div>
                                <div class="val">${log.range}</div>
                            </div>
                            <div>
                                <div class="label">Country</div>
                                <div class="val">${log.country}</div>
                            </div>
                        </div>
                        <div class="sms-box">
                            <div class="label">OTP / SMS Content</div>
                            <div class="sms-text">${log.message}</div>
                        </div>
                    </div>
                `).join('') || '<p style="text-align:center;color:#aaa;">Waiting for SMS...</p>';

                status.innerText = `Last update: ${formatTime()}`;
            } catch(e) {
                console.error('Load error:', e);
            }
        }

        document.getElementById('logs').addEventListener('click', function(e) {
            const target = e.target.closest('.copy-number');
            if (!target) return;
            const text = target.innerText.trim();
            if (!text) return;
            navigator.clipboard.writeText(text).then(() => {
                const orig = target.style.backgroundColor;
                target.style.backgroundColor = '#d4edda';
                target.title = 'Copied!';
                setTimeout(() => {
                    target.style.backgroundColor = orig;
                    target.title = 'Click to copy';
                }, 800);
            }).catch(() => {
                const inp = document.createElement('input');
                inp.value = text;
                document.body.appendChild(inp);
                inp.select();
                document.execCommand('copy');
                document.body.removeChild(inp);
                target.title = 'Copied!';
                setTimeout(() => { target.title = 'Click to copy'; }, 800);
            });
        });

        loadLogs();
        setInterval(loadLogs, REFRESH_MS);
    </script>
</body>
</html>
"""


@app.route('/')
def home():
    return render_template_string(HTML_TEMPLATE)

@app.route('/api/logs')
def get_logs():
    return jsonify(logs_data)


if __name__ == "__main__":
    threading.Thread(target=monitor_task, daemon=True).start()
    port = int(os.environ.get("PORT", 8080))
    logger.info(f"Starting server on port {port}")
    serve(app, host='0.0.0.0', port=port, threads=4)
