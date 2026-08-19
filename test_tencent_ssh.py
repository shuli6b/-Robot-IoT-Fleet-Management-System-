import paramiko

hostname = "106.55.248.254"
port = 22
username = "ubuntu"
password = "Shuli666"

print(f"Connecting to {username}@{hostname}:{port}...")
client = paramiko.SSHClient()
client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

try:
    client.connect(hostname, port=port, username=username, password=password, timeout=10)
    print("SUCCESS: Connected to Tencent Cloud VPS!")
    
    # Test sudo and get system info
    stdin, stdout, stderr = client.exec_command(f"echo {password} | sudo -S uname -a")
    print("System:", stdout.read().decode('utf-8').strip())
    
    stdin, stdout, stderr = client.exec_command(f"echo {password} | sudo -S lsb_release -a")
    print("Release:\n", stdout.read().decode('utf-8').strip())
    
    stdin, stdout, stderr = client.exec_command(f"echo {password} | sudo -S ufw status")
    print("UFW status:\n", stdout.read().decode('utf-8').strip())
    
except Exception as e:
    print("Failed to connect:", e)
finally:
    client.close()
