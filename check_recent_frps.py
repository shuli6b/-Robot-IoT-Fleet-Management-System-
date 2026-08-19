import paramiko

hostname = "106.55.248.254"
port = 22
username = "ubuntu"
password = "Shuli666"

client = paramiko.SSHClient()
client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
client.connect(hostname, port=port, username=username, password=password)

stdin, stdout, stderr = client.exec_command(f"echo {password} | sudo -S journalctl -u frps --since '5 minutes ago' --no-pager")
print("RECENT FRPS LOGS:\n", stdout.read().decode('utf-8'))

client.close()
