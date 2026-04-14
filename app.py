from flask import Flask, jsonify, request
import sqlite3

app = Flask(__name__)
DB_FILE = "audit_logs.db"

def get_db_connection():
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    return conn

# ========== 新增：根目录欢迎页，防止 404 ==========
@app.route('/', methods=['GET'])
def index():
    return jsonify({
        "status": "running",
        "message": "Audit Web Service is active.",
        "endpoints": {
            "get_logs": "/api/audit"
        }
    })
# ==================================================

@app.route('/api/audit', methods=['GET'])
def get_audit_logs():
    action_filter = request.args.get('action')
    limit = request.args.get('limit', 100, type=int)
    
    conn = get_db_connection()
    query = "SELECT * FROM access_logs"
    params = []
    
    if action_filter:
        query += " WHERE action = ?"
        params.append(action_filter.upper())
        
    query += " ORDER BY id DESC LIMIT ?"
    params.append(limit)
    
    rows = conn.execute(query, params).fetchall()
    conn.close()
    
    data = [dict(ix) for ix in rows]
    return jsonify({"status": "success", "total_returned": len(data), "data": data})

if __name__ == '__main__':
    print("Web API 启动于 http://0.0.0.0:5000")
    # host='0.0.0.0' 已经确保了它监听所有网卡，允许外部访问
    app.run(host='0.0.0.0', port=5000)
