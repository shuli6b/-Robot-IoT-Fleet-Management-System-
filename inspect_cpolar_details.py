import paramiko

hostname = "20.tcp.cpolar.top"
port = 14987
username = "qtz"
password = "qtz666"

client = paramiko.SSHClient()
client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
client.connect(hostname, port=port, username=username, password=password)

script = """
import subprocess, re, glob, os

print("--- Check Journalctl ---")
try:
    p = subprocess.Popen(['sudo', 'journalctl', '-u', 'cpolar', '-n', '200', '--no-pager'], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    out, err = p.communicate()
    for l in out.decode('utf-8', errors='ignore').split('\\n'):
        if 'tcp://' in l or 'http://' in l or 'https://' in l or 'Tunnel' in l or 'msg=' in l:
            print("LOG:", l.strip())
except Exception as e:
    print("Error:", e)

print("--- Check cpolar process args ---")
p = subprocess.Popen(['ps', 'aux'], stdout=subprocess.PIPE)
out, _ = p.communicate()
for l in out.decode('utf-8').split('\\n'):
    if 'cpolar' in l:
        print("PS:", l.strip())
"""

sftp = client.open_sftp()
with sftp.open('/home/qtz/test_cpolar_log.py', 'w') as f:
    f.write(script)
sftp.close()

stdin, stdout, stderr = client.exec_command("echo qtz666 | sudo -S python3 /home/qtz/test_cpolar_log.py")
print(stdout.read().decode('utf-8'))
print(stderr.read().decode('utf-8'))

client.close()
