import sqlite3, json
conn = sqlite3.connect('robot.db')
c = conn.cursor()
c.execute("SELECT config_value FROM system_config WHERE config_key='llm_api_config'")
row = c.fetchone()
if row:
    print(json.loads(row[0]))
else:
    print("NO CONFIG")
