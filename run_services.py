import argparse
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def build_parser():
    parser = argparse.ArgumentParser(description="Start the dashboard web app and collector together.")
    parser.add_argument("--radius-ip", help="Radius 服务器 IP。会生成 RADIUS_SERVER_IP 环境变量。")
    parser.add_argument("--radius-port", default="9090", help="Radius 导出服务端口，默认 9090。")
    parser.add_argument("--exporter-url", help="直接指定导出接口完整地址，优先级高于 radius-ip。")
    parser.add_argument("--api-token", help="采集器 API Token。")
    parser.add_argument("--db-file", default="audit_logs.db", help="SQLite 数据库文件，默认 audit_logs.db。")
    parser.add_argument("--web-host", default="0.0.0.0", help="Flask 监听地址，默认 0.0.0.0。")
    parser.add_argument("--web-port", default="5000", help="Flask 监听端口，默认 5000。")
    return parser


def make_env(args):
    env = os.environ.copy()
    env["AUDIT_DB_FILE"] = args.db_file
    env["FLASK_HOST"] = args.web_host
    env["FLASK_PORT"] = str(args.web_port)

    if args.exporter_url:
        env["RADIUS_EXPORTER_URL"] = args.exporter_url
    elif args.radius_ip:
        env["RADIUS_SERVER_IP"] = args.radius_ip
        env["RADIUS_SERVER_PORT"] = str(args.radius_port)

    if args.api_token:
        env["RADIUS_API_TOKEN"] = args.api_token

    return env


def start_process(name, script_name, env):
    script_path = ROOT / script_name
    print(f"[{name}] 启动: {script_path}")
    return subprocess.Popen([sys.executable, str(script_path)], cwd=str(ROOT), env=env)


def main():
    parser = build_parser()
    args = parser.parse_args()
    env = make_env(args)

    processes = [
        ("web", start_process("web", "app.py", env)),
        ("collector", start_process("collector", "collector.py", env)),
    ]

    try:
        while True:
            for name, process in processes:
                exit_code = process.poll()
                if exit_code is not None:
                    raise SystemExit(f"[{name}] 已退出，退出码 {exit_code}")
            time.sleep(1)
    except KeyboardInterrupt:
        print("\n收到中断信号，正在停止服务...")
    finally:
        for _, process in processes:
            if process.poll() is None:
                process.terminate()
        for _, process in processes:
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()


if __name__ == "__main__":
    main()
