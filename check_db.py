import sqlite3
conn = sqlite3.connect('D:/Antigravity projects/机器人管理系统/robot_iot.db')
cursor = conn.cursor()
cursor.execute("SELECT config_value FROM system_config WHERE config_key='llm_api_config'")
row = cursor.fetchone()
if row:
    print(row[0])
else:
    print("NO CONFIG FOUND")
