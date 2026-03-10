import psycopg2, os, sys
sys.stdout.reconfigure(encoding='utf-8')
from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(__file__), '../config/.env'))

conn = psycopg2.connect(
    host=os.getenv('DB_HOST', 'localhost'),
    port=os.getenv('DB_PORT', 5432),
    dbname=os.getenv('DB_NAME', 'vod_recommendation'),
    user=os.getenv('DB_USER', 'postgres'),
    password=os.getenv('DB_PASSWORD')
)
cur = conn.cursor()
cur.execute("""
    SELECT asset_nm, ct_cl, rag_source
    FROM vod
    WHERE smry IS NULL
      AND rag_processed = TRUE
      AND rag_source <> 'not_found'
    ORDER BY ct_cl, asset_nm
""")
rows = cur.fetchall()
print(f'총 {len(rows)}건\n')
for r in rows:
    print(f'  {str(r[2]):10s} | {str(r[1]):15s} | {r[0]}')
conn.close()
