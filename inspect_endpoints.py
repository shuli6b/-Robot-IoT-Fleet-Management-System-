import paramiko

hostname = "20.tcp.cpolar.top"
port = 14987
username = "qtz"
password = "qtz666"

client = paramiko.SSHClient()
client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
client.connect(hostname, port=port, username=username, password=password)

script = """
import urllib.request, json

# Query /api/tunnels on 4040
for p in [4040, 4042, 6060]:
    for path in ['/api/tunnels', '/api/v1/tunnels', '/status', '/tunnels']:
        try:
            req = urllib.request.Request(f'http://127.0.0.1:{p}{path}', headers={'Accept': 'application/json'})
            res = urllib.request.urlopen(req, timeout=1)
            raw = res.read().decode('utf-8')
            print(f"FOUND {p}{path}:", raw[:300])
        except Exception as e:
            pass
"""

sftp = client.open_sftp()
with sftp.open('/home/qtz/test_ep.py', 'w') as f:
    f.write(script)
sftp.close()

stdin, stdout, stderr = client.exec_command("python3 /home/qtz/test_ep.py")
print(stdout.read().decode('utf-8'))
print(stderr.read().decode('utf-8'))

client.close()
