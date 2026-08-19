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

for p in [4040, 4042, 9200]:
    url = f'http://127.0.0.1:{p}/api/tunnels'
    try:
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        res = urllib.request.urlopen(req, timeout=1)
        data = json.loads(res.read().decode('utf-8'))
        print(f"=== Port {p} API /api/tunnels ===")
        print(json.dumps(data, indent=2, ensure_ascii=False))
    except Exception as e:
        print(f"Port {p} error: {e}")
"""

stdin, stdout, stderr = client.exec_command(f"python3 -c \"{script.replace(chr(10), ';')}\"")
# Better to pass via sftp
sftp = client.open_sftp()
with sftp.open('/home/qtz/test_json.py', 'w') as f:
    f.write(script)
sftp.close()

stdin, stdout, stderr = client.exec_command("python3 /home/qtz/test_json.py")
print(stdout.read().decode('utf-8'))
print(stderr.read().decode('utf-8'))

client.close()
