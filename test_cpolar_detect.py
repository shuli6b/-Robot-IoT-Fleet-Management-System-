import paramiko

hostname = "20.tcp.cpolar.top"
port = 14987
username = "qtz"
password = "qtz666"

client = paramiko.SSHClient()
client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
client.connect(hostname, port=port, username=username, password=password)

# Check cpolar API endpoints or process info
test_script = """
import urllib.request
import json
import subprocess

# 1. Try local ports
for p in [9200, 4040, 4041, 4042]:
    for path in ['/api/tunnels', '/api/v1/tunnels', '/api/status', '/status', '/api/online_tunnels']:
        url = f'http://127.0.0.1:{p}{path}'
        try:
            req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
            res = urllib.request.urlopen(req, timeout=1)
            data = res.read().decode('utf-8')
            print(f"SUCCESS {url}: {data[:200]}")
        except Exception as e:
            # print(f"FAIL {url}: {e}")
            pass

# 2. Check journalctl logs for cpolar public addresses
try:
    p = subprocess.Popen(['journalctl', '-u', 'cpolar', '-n', '100', '--no-pager'], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    out, _ = p.communicate()
    for line in out.decode('utf-8', errors='ignore').split('\\n'):
        if 'tcp://' in line or 'http://' in line or 'https://' in line or 'r20.cpolar' in line or 'tcp.cpolar' in line:
            print("LOG LINE:", line.strip())
except Exception as e:
    print("Journalctl error:", e)
"""

sftp = client.open_sftp()
with sftp.open('/home/qtz/test_cpolar_api.py', 'w') as f:
    f.write(test_script)
sftp.close()

stdin, stdout, stderr = client.exec_command("echo qtz666 | sudo -S python3 /home/qtz/test_cpolar_api.py")
print(stdout.read().decode('utf-8'))
print(stderr.read().decode('utf-8'))

client.close()
