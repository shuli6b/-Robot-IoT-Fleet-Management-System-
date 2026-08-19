import paramiko

hostname = "106.55.248.254"
port = 22
username = "ubuntu"
password = "Shuli666"

client = paramiko.SSHClient()
client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
client.connect(hostname, port=port, username=username, password=password)

stdin, stdout, stderr = client.exec_command(f"echo {password} | sudo -S journalctl -u frps -n 50 --no-pager")
print("FRPS LOGS:\n", stdout.read().decode('utf-8'))

stdin, stdout, stderr = client.exec_command("sudo ss -tlpn")
print("LISTENING PORTS ON VPS:\n", stdout.read().decode('utf-8'))

client.close()
