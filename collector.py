import sqlite3
import requests
import schedule
import time
import re
import json
import os
import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

# 配置参数
def env_or_default(name, default):
    value = os.getenv(name)
    if value is None or value == "":
        return default
    return value


DB_FILE = env_or_default("AUDIT_DB_FILE", "audit_logs.db")
API_TOKEN = env_or_default("RADIUS_API_TOKEN", "super-secret-audit-key-2026")
EXPORTER_URL = env_or_default("RADIUS_EXPORTER_URL", None)
LOG_DIR = Path(env_or_default("AUDIT_LOG_DIR", "/logs"))
LOG_FILE = LOG_DIR / "collector.log"

if not EXPORTER_URL:
    radius_ip = env_or_default("RADIUS_SERVER_IP", "<你的Radius服务器IP>")
    radius_port = env_or_default("RADIUS_SERVER_PORT", "9090")
    EXPORTER_URL = f"http://{radius_ip}:{radius_port}/api/logs"

# 正则表达式解析日志格式
# 格式示例: [2026-04-14 14:18:17] DISCONNECT | User: phoenix.yu@vesoft.com | MAC: a66e-9206-a4e3 | Client_IP: 192.168.10.81 | Duration: 459s
LOG_PATTERN = re.compile(
    r"\[(?P<timestamp>.*?)\]\s+(?P<action>\w+)\s+\|\s+User:\s+(?P<user>\S+)\s+\|\s+MAC:\s+(?P<mac>\S+)\s+\|\s+Client_IP:\s+(?P<client_ip>\S*)\s+\|\s+(?P<details>.*)"
)

def init_db():
    """初始化 SQLite 数据库"""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    
    # 日志表
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
    
    # 状态表（记录游标）
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS sync_state (
            key TEXT PRIMARY KEY,
            value INTEGER
        )
    ''')
    
    # 初始化游标
    cursor.execute("INSERT OR IGNORE INTO sync_state (key, value) VALUES ('last_line', 1)")
    conn.commit()
    conn.close()


def setup_logging():
    LOG_DIR.mkdir(parents=True, exist_ok=True)

    formatter = logging.Formatter(
        "%(asctime)s | %(levelname)s | %(name)s | %(message)s"
    )

    file_handler = RotatingFileHandler(LOG_FILE, maxBytes=1_000_000, backupCount=3)
    file_handler.setFormatter(formatter)

    stream_handler = logging.StreamHandler()
    stream_handler.setFormatter(formatter)

    root_logger = logging.getLogger()
    root_logger.handlers.clear()
    root_logger.setLevel(logging.INFO)
    root_logger.addHandler(file_handler)
    root_logger.addHandler(stream_handler)

    logging.getLogger("urllib3").setLevel(logging.WARNING)

def get_last_line():
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("SELECT value FROM sync_state WHERE key='last_line'")
    line = cursor.fetchone()[0]
    conn.close()
    return line

def update_last_line(line):
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("UPDATE sync_state SET value=? WHERE key='last_line'", (line,))
    conn.commit()
    conn.close()

def fetch_and_store_logs():
    last_line = get_last_line()
    logging.info("fetch cycle started | start_line=%s", last_line)
    
    headers = {"Authorization": f"Bearer {API_TOKEN}"}
    params = {"start_line": last_line}
    
    try:
        response = requests.get(EXPORTER_URL, headers=headers, params=params, timeout=10)
        if response.status_code != 200:
            logging.error("exporter request failed | status=%s | url=%s", response.status_code, EXPORTER_URL)
            return
            
        result = response.json()
        end_line = result.get("end_line", last_line)
        data = result.get("data", [])
        
        if not data:
            logging.info("no new data returned | end_line=%s", end_line)
            return
            
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        
        parsed_count = 0
        for raw_log in data:
            match = LOG_PATTERN.match(raw_log)
            if match:
                log_dict = match.groupdict()
                cursor.execute('''
                    INSERT INTO access_logs (timestamp, action, username, mac_address, client_ip, details, raw_log)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                ''', (log_dict['timestamp'], log_dict['action'], log_dict['user'], 
                      log_dict['mac'], log_dict['client_ip'], log_dict['details'], raw_log))
                parsed_count += 1
            else:
                logging.warning("log parse failed, skipped | raw_log=%s", raw_log)
                
        conn.commit()
        conn.close()
        
        # 成功落库后，更新游标
        update_last_line(end_line)
        logging.info("fetch cycle completed | inserted=%s | end_line=%s", parsed_count, end_line)
        
    except Exception as e:
        logging.exception("fetch cycle failed")

if __name__ == "__main__":
    try:
        setup_logging()
        init_db()
        logging.info("collector starting | db=%s | exporter_url=%s", DB_FILE, EXPORTER_URL)

        # 立即执行一次
        fetch_and_store_logs()
        
        # 设定定时任务，每分钟执行一次
        schedule.every(1).minutes.do(fetch_and_store_logs)
        logging.info("collector running | interval=60s")
        
        while True:
            schedule.run_pending()
            time.sleep(1)
    except Exception:
        logging.exception("collector failed to start")
        raise
