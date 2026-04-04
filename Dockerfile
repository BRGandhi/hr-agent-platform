FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

RUN python - <<'PY'
import pathlib
import sqlite3
import sys

db_path = pathlib.Path("/app/hr_data.db")
if not db_path.exists():
    sys.exit("hr_data.db is missing from the image build context. Commit the bundled database or rebuild it before deploying.")

conn = sqlite3.connect(str(db_path))
try:
    row = conn.execute("SELECT COUNT(*) FROM employees").fetchone()
    if not row or int(row[0]) <= 0:
        sys.exit("hr_data.db exists but the employees table is missing or empty.")
finally:
    conn.close()

print("Validated bundled HR database.")
PY

EXPOSE 8000

HEALTHCHECK CMD python -c "import os, urllib.request; urllib.request.urlopen('http://127.0.0.1:%s/healthz' % os.getenv('PORT', '8000'))"

CMD ["sh", "-c", "python -m uvicorn server:app --host 0.0.0.0 --port ${PORT:-8000}"]
