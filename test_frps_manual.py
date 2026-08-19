import paramiko

hostname = "106.55.248.254"
port = 22
username = "ubuntu"
password = "Shuli666"

client = paramiko.SSHClient()
client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
client.connect(hostname, port=port, username=username, password=password)

stdin, stdout, stderr = client.exec_command(f"echo {password} | sudo -S /usr/local/frp/frps -c /usr/local/frp/frps.toml")
print("MANUAL RUN OUT:")
print(stdout.read().decode('utf-8'))
print("MANUAL RUN ERR:")
print(stderr.read().decode('utf-8'))

client.close()
