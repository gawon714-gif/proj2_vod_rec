아래 Python 코드를 실행해서 vod 테이블 데이터 품질을 종합 점검해줘.

```python
import psycopg2, os, sys, json
sys.stdout.reconfigure(encoding='utf-8')
from dotenv import load_dotenv
load_dotenv('RAG/config/.env')

conn = psycopg2.connect(
    host=os.getenv('DB_HOST', 'localhost'),
    port=os.getenv('DB_PORT', 5432),
    dbname=os.getenv('DB_NAME', 'vod_recommendation'),
    user=os.getenv('DB_USER', 'postgres'),
    password=os.getenv('DB_PASSWORD')
)
cur = conn.cursor()

cur.execute('SELECT COUNT(*) FROM vod')
total = cur.fetchone()[0]

print(f'=== 전체 VOD: {total:,}건 ===\n')

# 1. 결측치 현황
cols = ['director','cast_lead','cast_guest','rating','release_date','smry','genre','asset_prod','series_nm','ct_cl']
print('=== 결측치 현황 ===')
for col in cols:
    cur.execute(f'SELECT COUNT(*) FROM vod WHERE {col} IS NULL')
    null_cnt = cur.fetchone()[0]
    filled = total - null_cnt
    pct = filled / total * 100
    bar = '█' * int(pct / 5)
    print(f'  {col:15s}: 채움 {filled:,} ({pct:5.1f}%) {bar}')

# 2. rating 분포
print('\n=== rating 분포 (상위 10개) ===')
cur.execute('SELECT rating, COUNT(*) FROM vod GROUP BY rating ORDER BY COUNT(*) DESC LIMIT 10')
for r in cur.fetchall():
    print(f'  {str(r[0]):15s}: {r[1]:,}')

# 3. genre 분포
print('\n=== genre 분포 (상위 10개) ===')
cur.execute('SELECT genre, COUNT(*) FROM vod GROUP BY genre ORDER BY COUNT(*) DESC LIMIT 10')
for r in cur.fetchall():
    print(f'  {str(r[0]):20s}: {r[1]:,}')

# 4. ct_cl 분포
print('\n=== ct_cl 분포 ===')
cur.execute('SELECT ct_cl, COUNT(*) FROM vod GROUP BY ct_cl ORDER BY COUNT(*) DESC')
for r in cur.fetchall():
    print(f'  {str(r[0]):20s}: {r[1]:,}')

# 5. rag_source 분포
print('\n=== rag_source 분포 ===')
cur.execute('SELECT rag_source, COUNT(*) FROM vod GROUP BY rag_source ORDER BY COUNT(*) DESC')
for r in cur.fetchall():
    print(f'  {str(r[0]):15s}: {r[1]:,}')

# 6. smry 이상치
print('\n=== smry 이상치 점검 ===')
cur.execute("SELECT COUNT(*) FROM vod WHERE smry IS NOT NULL AND LENGTH(smry) < 10")
short = cur.fetchone()[0]
cur.execute("SELECT COUNT(*) FROM vod WHERE smry IS NOT NULL AND smry ~ '^[A-Za-z]'")
english = cur.fetchone()[0]
print(f'  10자 미만: {short:,}건')
print(f'  영문 시작: {english:,}건')

conn.close()
```

결과를 항목별로 표 형태로 정리해서 보여줘. 이상치가 발견되면 원인과 처리 방법도 함께 제안해줘.
