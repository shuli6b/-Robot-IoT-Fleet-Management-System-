import paramiko

hostname = "20.tcp.cpolar.top"
port = 14987
username = "qtz"
password = "qtz666"

client = paramiko.SSHClient()
client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
client.connect(hostname, port=port, username=username, password=password)

script = """
import urllib.request, re

try:
    req = urllib.request.Request('http://127.0.0.1:9200/', headers={'User-Agent': 'Mozilla/5.0'})
    res = urllib.request.urlopen(req, timeout=2)
    html = res.read().decode('utf-8', errors='ignore')
    print("Web HTML snippet:", html[:300])
except Exception as e:
    print("Web error:", e)

# Check all listening ports of cpolar
import subprocess
p = subprocess.Popen(['sudo', 'ss', '-tlpn'], stdout=subprocess.PIPE)
out, _ = p.communicate()
for l in out.decode('utf-8').split('\\n'):
    if 'cpolar' in l:
        print("SS:", l.strip())
"""

sftp = client.open_sftp()
with sftp.open('/home/qtz/test_web.py', 'w') as f:
    f.write(script)
sftp.close()

stdin, stdout, stderr = client.exec_command("echo qtz666 | sudo -S python3 /home/qtz/test_web.py")
print(stdout.read().decode('utf-8'))
print(stderr.read().decode('utf-8'))

client.close()
