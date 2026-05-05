import os
import logging
import requests
import threading
import time
from datetime import datetime
from flask import Flask, jsonify, render_template_string
from waitress import serve

# ---------- CONFIGURATION ----------
EMAIL = os.environ.get("EMAIL", "")
PASSWORD = os.environ.get("PASSWORD", "")
BASE_URL = "https://stexsms.com/mapi/v1"
MAX_LOGS = 100
POLL_SECONDS = 5            # fetch data every 5 seconds
# -----------------------------------

app = Flask(__name__)
logs_data = []
seen_log_ids = set()

# Basic logging setup (visible in Railway logs)
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

    # Initial login
    login()

    info_url = f"{BASE_URL}/mdashboard/console/info"

    while True:
        try:
            resp = session.get(info_url, headers=headers, timeout=5)
            if resp.status_code == 401:
                logger.warning("Token expired – re-login")
                login()
                continue

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

                # Prevent memory bloat from seen IDs
                if len(seen_log_ids) > 1000:
                    seen_log_ids = set(list(seen_log_ids)[-500:])

            time.sleep(POLL_SECONDS)

        except Exception as e:
            logger.error(f"Polling error: {e}")
            time.sleep(5)

# ---------- FRONTEND (auto‑refreshes every 5s) ----------
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
        const REFRESH_MS = 5000;   // auto‑update every 5 seconds

        function formatTime() {
            const now = new Date();
            return now.toLocaleTimeString();
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
                            <div><div class="label">Number</div><div class="val">${log.number}</div></div>
                            <div><div class="label">Range</div><div class="val">${log.range}</div></div>
                            <div><div class="label">Country</div><div class="val">${log.country}</div></div>
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

        // Initial load + periodic refresh
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

# ---------- MAIN ----------
if __name__ == "__main__":
    # Start background monitoring thread
    threading.Thread(target=monitor_task, daemon=True).start()

    # Use PORT from Railway environment (default 5000 for local runs)
    port = int(os.environ.get("PORT", 5000))
    logger.info(f"Starting server on port {port}")
    serve(app, host='0.0.0.0', port=port, threads=4)