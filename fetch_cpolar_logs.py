import paramiko
import re

hostname = "20.tcp.cpolar.top"
port = 14987
username = "qtz"
password = "qtz666"

client = paramiko.SSHClient()
client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
client.connect(hostname, port=port, username=username, password=password)

# Check journalctl for cpolar allocated tunnels
stdin, stdout, stderr = client.exec_command("sudo -S journalctl -u cpolar --no-pager -n 500")
stdin.write(password + '\n')
stdin.flush()
logs = stdout.read().decode('utf-8', errors='replace')

for line in logs.split('\n'):
    if "tcp://" in line or "Allocated" in line or "Tunnel" in line or "started" in line:
        print(line.strip())

# Or look at cpolar config to find the tunnel id, then query the web API if possible
stdin, stdout, stderr = client.exec_command("curl -s http://127.0.0.1:4040/api/tunnels")
print("API 4040:", stdout.read().decode('utf-8'))

client.close()
