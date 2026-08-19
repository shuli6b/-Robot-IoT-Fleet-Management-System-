import paramiko

hostname = "106.55.248.254"
port = 22
username = "ubuntu"
password = "Shuli666"

client = paramiko.SSHClient()
client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
client.connect(hostname, port=port, username=username, password=password)

toml_content = """bindPort = 7000
auth.token = "RobotIoT_Secure_Token_2026"

webServer.addr = "0.0.0.0"
webServer.port = 7500
webServer.user = "admin"
webServer.password = "Admin_Robot_2026"
"""

sftp = client.open_sftp()
with sftp.open('/tmp/frps.toml', 'w') as f:
    f.write(toml_content)
sftp.close()

stdin, stdout, stderr = client.exec_command(f"echo {password} | sudo -S cp /tmp/frps.toml /usr/local/frp/frps.toml && echo {password} | sudo -S systemctl restart frps")
print(stdout.read().decode('utf-8'))
print(stderr.read().decode('utf-8'))

time_sleep = 1
import time
time.sleep(1)

stdin, stdout, stderr = client.exec_command(f"echo {password} | sudo -S systemctl status frps --no-pager")
print("STATUS:\n", stdout.read().decode('utf-8'))

client.close()
