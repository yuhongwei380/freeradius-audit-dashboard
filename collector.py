import sqlite3
import requests
import schedule
import time
import re
import json

# 配置参数
EXPORTER_URL = "http://<你的Radius服务器IP>:9090/api/logs"
API_TOKEN = "super-secret-audit-key-2026"
DB_FILE = "audit_logs.db"

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
    print(f"开始拉取数据，当前游标 start_line={last_line}")
    
    headers = {"Authorization": f"Bearer {API_TOKEN}"}
    params = {"start_line": last_line}
    
    try:
        response = requests.get(EXPORTER_URL, headers=headers, params=params, timeout=10)
        if response.status_code != 200:
            print(f"API 请求失败: {response.status_code}")
            return
            
        result = response.json()
        end_line = result.get("end_line", last_line)
        data = result.get("data", [])
        
        if not data:
            print("没有新数据。")
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
                print(f"解析失败跳过: {raw_log}")
                
        conn.commit()
        conn.close()
        
        # 成功落库后，更新游标
        update_last_line(end_line)
        print(f"成功入库 {parsed_count} 条记录，更新游标为 {end_line}")
        
    except Exception as e:
        print(f"执行任务时发生错误: {e}")

if __name__ == "__main__":
    init_db()
    # 立即执行一次
    fetch_and_store_logs()
    
    # 设定定时任务，每分钟执行一次
    schedule.every(1).minutes.do(fetch_and_store_logs)
    print("采集器已启动，按 Ctrl+C 停止...")
    
    while True:
        schedule.run_pending()
        time.sleep(1)
