import paramiko

hostname = "20.tcp.cpolar.top"
port = 14987
username = "qtz"
password = "qtz666"

client = paramiko.SSHClient()
client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
client.connect(hostname, port=port, username=username, password=password)

stdin, stdout, stderr = client.exec_command(f"echo {password} | sudo -S grep 'Allocated' /var/log/syslog")
print(stdout.read().decode('utf-8', errors='replace'))

client.close()
