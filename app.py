import os
import requests
import threading
import time
from datetime import datetime
from flask import Flask, jsonify, render_template_string
from waitress import serve

# 🔐 Read credentials from environment variables – NEVER hardcode!
EMAIL = os.environ.get("EMAIL", "")
PASSWORD = os.environ.get("PASSWORD", "")

BASE_URL = "https://stexsms.com/mapi/v1"
MAX_LOGS = 100

app = Flask(__name__)

logs_data = []
seen_log_ids = set()

def monitor_task():
    global logs_data, seen_log_ids
    session = requests.Session()
    headers = {
        "user-agent": "Mozilla/5.0 (Linux; Android 10) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Mobile Safari/537.36",
        "content-type": "application/json",
        "accept": "application/json, text/plain, */*",
        "origin": "https://stexsms.com"
    }

    def login():
        try:
            login_url = f"{BASE_URL}/mauth/login"
            payload = {"email": EMAIL, "password": PASSWORD}
            response = session.post(login_url, json=payload, headers=headers, timeout=10)
            if response.status_code == 200:
                token = response.json().get("data", {}).get("token")
                if token:
                    headers["mauthtoken"] = token
                    return True
        except:
            pass
        return False

    login()
    info_url = f"{BASE_URL}/mdashboard/console/info"
    
    while True:
        try:
            resp = session.get(info_url, headers=headers, timeout=5)
            if resp.status_code == 401:
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
                if len(seen_log_ids) > 1000:
                    seen_log_ids = set(list(seen_log_ids)[-500:])
            time.sleep(2)
        except:
            time.sleep(5)

HTML_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
    <title>TSB Console Zone ( Live )</title>
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
    </style>
</head>
<body>
    <div class="container">
        <div class="header"><h2>TSB Console Live</h2></div>
        <div id="logs"></div>
    </div>
    <script>
        let lastCount = 0;
        async function loadLogs() {
            try {
                const res = await fetch('/api/logs');
                const data = await res.json();
                if(data.length === lastCount) return;
                lastCount = data.length;
                const div = document.getElementById('logs');
                div.innerHTML = data.map(log => `
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
                `).join('');
            } catch (e) {}
        }
        setInterval(loadLogs, 2000);
        loadLogs();
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
    # 🚀 Use PORT from Railway environment (default 5000 for local testing)
    port = int(os.environ.get("PORT", 5000))
    serve(app, host='0.0.0.0', port=port, threads=4)