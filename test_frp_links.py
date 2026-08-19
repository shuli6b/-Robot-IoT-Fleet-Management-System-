import sys
import paramiko
import urllib.request
import socket
import json

host = "106.55.248.254"

print("==========================================================")
print("TESTING FRP LINKS TO: " + host)
print("==========================================================")

# 1. Test Web Dashboard on port 8000
print("\n[1/3] Testing Web Dashboard HTTP (106.55.248.254:8000)...")
try:
    req = urllib.request.Request(f"http://{host}:8000/api/system/overview", headers={"User-Agent": "Mozilla/5.0"})
    res = urllib.request.urlopen(req, timeout=5)
    data = json.loads(res.read().decode('utf-8'))
    print("SUCCESS: Web Dashboard API connected! Data:")
    print(json.dumps(data, indent=2, ensure_ascii=False))
except Exception as e:
    print(f"FAILED Web Dashboard port 8000: {e}")

# 2. Test MQTT Port 1883
print("\n[2/3] Testing MQTT Port (106.55.248.254:1883)...")
try:
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(4.0)
    res = s.connect_ex((host, 1883))
    s.close()
    if res == 0:
        print("SUCCESS: MQTT 1883 port connected!")
    else:
        print(f"FAILED MQTT port 1883 (code: {res})")
except Exception as e:
    print(f"FAILED MQTT test: {e}")

# 3. Test SSH Tunnel on Port 2222
print("\n[3/3] Testing SSH Tunnel to local machine (106.55.248.254:2222)...")
try:
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(host, port=2222, username="qtz", password="qtz666", timeout=5)
    print("SUCCESS: Connected to local Ubuntu machine via SSH (qtz@local)!")
    
    stdin, stdout, stderr = client.exec_command("hostname && uname -a")
    print("Local host info:", stdout.read().decode('utf-8').strip())
    
    stdin, stdout, stderr = client.exec_command("systemctl status robot-iot --no-pager")
    print("Local service status:\n", stdout.read().decode('utf-8').strip())
    
    client.close()
except Exception as e:
    print(f"FAILED SSH Tunnel 2222: {e}")

print("\n==========================================================")
