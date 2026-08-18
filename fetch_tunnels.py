import paramiko
import json

hostname = "20.tcp.cpolar.top"
port = 14987
username = "qtz"
password = "qtz666"

client = paramiko.SSHClient()
client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
client.connect(hostname, port=port, username=username, password=password)

stdin, stdout, stderr = client.exec_command("curl -s http://localhost:4040/api/tunnels || curl -s http://localhost:9200/api/tunnels")
tunnels = stdout.read().decode('utf-8')

print(tunnels)
client.close()
