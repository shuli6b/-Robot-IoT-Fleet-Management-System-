import paramiko
client=paramiko.SSHClient()
client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
client.connect('20.tcp.cpolar.top', 14987, 'qtz', 'qtz666')
client.exec_command("echo qtz666 | sudo -S sqlite3 /home/qtz/robot-iot-standalone/robot.db \"DELETE FROM devices WHERE device_id LIKE '%诗歌%';\"")
client.close()
