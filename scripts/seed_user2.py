import os
import oracledb
from dotenv import load_dotenv
from app.security.auth import hash_password

load_dotenv()

conn = oracledb.connect(
    user=os.getenv("DB_USER"),
    password=os.getenv("DB_PASSWORD"),
    dsn=os.getenv("DB_DSN")
)
cursor = conn.cursor()

username = "agent1"
plain_password = "AgentTest123!"
role = "SUPPORT_AGENT"

hashed = hash_password(plain_password)

cursor.execute("""
    INSERT INTO TT_AI_USERS (USERNAME, PASSWORD_HASH, ROLE, IS_ACTIVE)
    VALUES (:username, :password_hash, :role, 1)
""", username=username, password_hash=hashed, role=role)

conn.commit()
print(f"User '{username}' created with role '{role}'.")

cursor.close()
conn.close()
