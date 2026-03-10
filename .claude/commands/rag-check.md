아래 Python 코드를 실행해서 RAG 파이프라인 현재 상태를 점검해줘.

```python
import psycopg2, os, sys
sys.stdout.reconfigure(encoding='utf-8')
from dotenv import load_dotenv
load_dotenv('RAG/config/.env')
conn = psycopg2.connect(
    host=os.getenv('DB_HOST','localhost'),
    port=os.getenv('DB_PORT',5432),
    dbname=os.getenv('DB_NAME','vod_recommendation'),
    user=os.getenv('DB_USER','postgres'),
    password=os.getenv('DB_PASSWORD')
)
cur = conn.cursor()

cur.execute('SELECT COUNT(*) FROM vod WHERE rag_processed = TRUE')
done = cur.fetchone()[0]
cur.execute('SELECT COUNT(*) FROM vod WHERE rag_processed IS NULL OR rag_processed = FALSE')
remaining = cur.fetchone()[0]
total = done + remaining

cur.execute('SELECT rag_source, COUNT(*) FROM vod WHERE rag_processed = TRUE GROUP BY rag_source ORDER BY COUNT(*) DESC')
sources = cur.fetchall()

cols = ['director','cast_lead','cast_guest','rating','release_date','smry','genre','asset_prod','series_nm']

print(f'=== RAG 진행률 ===')
print(f'완료: {done:,} / {total:,} ({done/total*100:.1f}%)')
print(f'남은것: {remaining:,}개')
print(f'\n=== 소스별 결과 ===')
for r in sources:
    print(f'  {r[0]}: {r[1]:,}')
print(f'\n=== 현재 결측치 ===')
for col in cols:
    cur.execute(f'SELECT COUNT(*) FROM vod WHERE {col} IS NULL')
    print(f'  {col}: {cur.fetchone()[0]:,}개')
conn.close()
```

결과를 표 형태로 정리해서 보여줘.
