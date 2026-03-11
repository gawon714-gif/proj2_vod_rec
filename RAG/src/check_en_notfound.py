import psycopg2, os, sys
sys.stdout.reconfigure(encoding='utf-8')
from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(__file__), '../config/.env'))

conn = psycopg2.connect(
    host=os.getenv('DB_HOST'), port=os.getenv('DB_PORT'),
    dbname=os.getenv('DB_NAME'), user=os.getenv('DB_USER'),
    password=os.getenv('DB_PASSWORD')
)
cur = conn.cursor()
cur.execute("""
    SELECT asset_nm, ct_cl FROM vod
    WHERE rag_source = 'not_found'
      AND asset_nm ~ '^[A-Za-z0-9 !?.,;:()\-]+$'
    ORDER BY ct_cl, asset_nm
""")
rows = cur.fetchall()
print(f'총 {len(rows)}건\n')
for r in rows:
    print(f'  [{r[1]:12s}] {r[0]}')
conn.close()
