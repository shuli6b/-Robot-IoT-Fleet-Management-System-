import paramiko
import time

hostname = "106.55.248.254"
port = 22
username = "ubuntu"
password = "Shuli666"

client = paramiko.SSHClient()
client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
client.connect(hostname, port=port, username=username, password=password)

commands = [
    # 1. Update and install basic tools
    "sudo apt update -y && sudo apt install -y curl wget tar ufw",
    
    # 2. Download and setup FRP Server (frps)
    "sudo mkdir -p /usr/local/frp",
    "cd /tmp && (curl -L -o frp.tar.gz https://github.com/fatedier/frp/releases/download/v0.58.1/frp_0.58.1_linux_amd64.tar.gz || curl -L -o frp.tar.gz https://ghproxy.net/https://github.com/fatedier/frp/releases/download/v0.58.1/frp_0.58.1_linux_amd64.tar.gz)",
    "cd /tmp && tar -zxvf frp.tar.gz && sudo cp frp_0.58.1_linux_amd64/frps /usr/local/frp/ && sudo cp frp_0.58.1_linux_amd64/frpc /usr/local/frp/",
    
    # 3. Write frps.toml configuration
    """cat << 'EOF' | sudo tee /usr/local/frp/frps.toml
bindPort = 7000
auth.token = "RobotIoT_Secure_Token_2026"

# Dashboard (optional web console for monitoring tunnels)
webServer.addr = "0.0.0.0"
webServer.port = 7500
webServer.user = "admin"
webServer.password = "Admin_Robot_2026"
EOF""",

    # 4. Create systemd service for frps
    """cat << 'EOF' | sudo tee /etc/systemd/system/frps.service
[Unit]
Description=FRP Server Service (IoT Fleet Penetration Hub)
After=network.target syslog.target
Wants=network.target

[Service]
Type=simple
ExecStart=/usr/local/frp/frps -c /usr/local/frp/frps.toml
Restart=always
RestartSec=3s
LimitNOFILE=65535

[Install]
WantedBy=multi-user.target
EOF""",

    # 5. Enable and start frps
    "sudo systemctl daemon-reload",
    "sudo systemctl enable frps",
    "sudo systemctl restart frps",
    "sudo systemctl status frps --no-pager"
]

for cmd in commands:
    print("---------------------------------------------")
    print(f"Running: {cmd[:60]}...")
    stdin, stdout, stderr = client.exec_command(f"echo {password} | sudo -S bash -c \"{cmd}\"")
    out = stdout.read().decode('utf-8', errors='replace')
    err = stderr.read().decode('utf-8', errors='replace')
    if out: print("OUT:\n", out.strip())
    if err: print("ERR:\n", err.strip())

client.close()
print("FRPS setup completed on Tencent Cloud VPS!")
