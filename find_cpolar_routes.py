import paramiko

hostname = "20.tcp.cpolar.top"
port = 14987
username = "qtz"
password = "qtz666"

client = paramiko.SSHClient()
client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
client.connect(hostname, port=port, username=username, password=password)

script = """
import urllib.request, re

req = urllib.request.Request('http://127.0.0.1:9200/', headers={'User-Agent': 'Mozilla/5.0'})
res = urllib.request.urlopen(req)
html = res.read().decode('utf-8')
js_files = re.findall(r'src=(/static/js/[^\s>]+)', html)
print("JS Files:", js_files)

for js in js_files:
    url = f'http://127.0.0.1:9200{js}'
    res_js = urllib.request.urlopen(url)
    js_content = res_js.read().decode('utf-8', errors='ignore')
    # Find all API routes in the JS
    apis = re.findall(r'/api/[a-zA-Z0-9_/]+', js_content)
    print(f"APIs in {js}:", set(apis))
"""

sftp = client.open_sftp()
with sftp.open('/home/qtz/find_cpolar_api.py', 'w') as f:
    f.write(script)
sftp.close()

stdin, stdout, stderr = client.exec_command("python3 /home/qtz/find_cpolar_api.py")
print(stdout.read().decode('utf-8'))
print(stderr.read().decode('utf-8'))

client.close()
