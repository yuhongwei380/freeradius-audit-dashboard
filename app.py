from flask import Flask, jsonify, render_template, request
import sqlite3
import os
import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

app = Flask(__name__)
DB_FILE = os.getenv("AUDIT_DB_FILE", "audit_logs.db")
FLASK_HOST = os.getenv("FLASK_HOST", "0.0.0.0")
FLASK_PORT = int(os.getenv("FLASK_PORT", "5000"))
LOG_DIR = Path(os.getenv("AUDIT_LOG_DIR", "/logs"))
LOG_FILE = LOG_DIR / "web.log"

def get_db_connection():
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    return conn


def setup_logging():
    LOG_DIR.mkdir(parents=True, exist_ok=True)

    formatter = logging.Formatter(
        "%(asctime)s | %(levelname)s | %(name)s | %(message)s"
    )

    file_handler = RotatingFileHandler(LOG_FILE, maxBytes=1_000_000, backupCount=3)
    file_handler.setFormatter(formatter)

    stream_handler = logging.StreamHandler()
    stream_handler.setFormatter(formatter)

    app.logger.handlers.clear()
    app.logger.setLevel(logging.INFO)
    app.logger.addHandler(file_handler)
    app.logger.addHandler(stream_handler)
    app.logger.propagate = False

    werkzeug_logger = logging.getLogger("werkzeug")
    werkzeug_logger.handlers.clear()
    werkzeug_logger.setLevel(logging.INFO)
    werkzeug_logger.addHandler(file_handler)
    werkzeug_logger.addHandler(stream_handler)
    werkzeug_logger.propagate = False


@app.before_request
def log_request_start():
    app.logger.info("request start | %s %s", request.method, request.path)


@app.after_request
def log_request_end(response):
    app.logger.info(
        "request end | %s %s | status=%s",
        request.method,
        request.path,
        response.status_code,
    )
    return response


def init_db():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS access_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp DATETIME,
            action TEXT,
            username TEXT,
            mac_address TEXT,
            client_ip TEXT,
            details TEXT,
            raw_log TEXT
        )
    ''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS sync_state (
            key TEXT PRIMARY KEY,
            value INTEGER
        )
    ''')
    cursor.execute("INSERT OR IGNORE INTO sync_state (key, value) VALUES ('last_line', 1)")
    conn.commit()
    conn.close()

@app.route('/', methods=['GET'])
def index():
    return render_template('index.html')


@app.route('/api/status', methods=['GET'])
def status():
    return jsonify({
        "status": "running",
        "message": "Audit Web Service is active.",
        "endpoints": {
            "dashboard": "/",
            "get_logs": "/api/audit",
            "summary": "/api/summary"
        }
    })

@app.route('/api/audit', methods=['GET'])
def get_audit_logs():
    action_filter = request.args.get('action')
    username_filter = request.args.get('username')
    mac_filter = request.args.get('mac')
    client_ip_filter = request.args.get('client_ip')
    start_time = request.args.get('start_time')
    end_time = request.args.get('end_time')
    limit = request.args.get('limit', 100, type=int)

    conn = get_db_connection()
    query = "SELECT * FROM access_logs"
    params = []
    conditions = []

    if action_filter:
        conditions.append("action = ?")
        params.append(action_filter.upper())

    if username_filter:
        conditions.append("username LIKE ?")
        params.append(f"%{username_filter}%")

    if mac_filter:
        conditions.append("mac_address LIKE ?")
        params.append(f"%{mac_filter}%")

    if client_ip_filter:
        conditions.append("client_ip LIKE ?")
        params.append(f"%{client_ip_filter}%")

    if start_time:
        conditions.append("timestamp >= ?")
        params.append(start_time)

    if end_time:
        conditions.append("timestamp <= ?")
        params.append(end_time)

    if conditions:
        query += " WHERE " + " AND ".join(conditions)

    query += " ORDER BY id DESC LIMIT ?"
    params.append(limit)

    rows = conn.execute(query, params).fetchall()
    conn.close()

    data = [dict(ix) for ix in rows]
    return jsonify({"status": "success", "total_returned": len(data), "data": data})


@app.route('/api/summary', methods=['GET'])
def get_summary():
    conn = get_db_connection()
    totals = conn.execute('''
        SELECT
            COUNT(*) AS total_logs,
            COUNT(DISTINCT username) AS unique_users,
            COUNT(DISTINCT mac_address) AS unique_devices,
            MAX(timestamp) AS latest_event
        FROM access_logs
    ''').fetchone()

    action_rows = conn.execute('''
        SELECT UPPER(action) AS action, COUNT(*) AS count
        FROM access_logs
        GROUP BY UPPER(action)
        ORDER BY count DESC, action ASC
    ''').fetchall()

    conn.close()

    actions = [dict(row) for row in action_rows]
    return jsonify({
        "status": "success",
        "data": {
            "total_logs": totals["total_logs"],
            "unique_users": totals["unique_users"],
            "unique_devices": totals["unique_devices"],
            "latest_event": totals["latest_event"],
            "actions": actions
        }
    })

if __name__ == '__main__':
    try:
        setup_logging()
        init_db()
        app.logger.info("web service starting | db=%s | host=%s | port=%s", DB_FILE, FLASK_HOST, FLASK_PORT)
        app.run(host=FLASK_HOST, port=FLASK_PORT)
    except Exception:
        logging.exception("web service failed to start")
        raise
