# A-IMS Railway POC
# 베이스: Debian bookworm (12) — PGDG가 확실히 지원하는 안정 코드네임.
# 목적: 컨테이너 안에 PostgreSQL 18 클라이언트(pg_dump 포함)를 정확히 설치.
#   주의: Debian 기본 repo의 메타패키지(postgresql-client)는 18이 아닐 수 있으므로,
#         반드시 PGDG apt repo를 추가하고 버전 고정 패키지(postgresql-client-18)를 설치한다.
FROM python:3.12-slim-bookworm

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

# --- PostgreSQL 18 클라이언트 설치 (PGDG repo) ---
# 코드네임은 베이스 이미지 OS(bookworm)와 반드시 일치시킨다: "bookworm-pgdg".
RUN set -eux; \
    apt-get update; \
    apt-get install -y --no-install-recommends \
        ca-certificates curl gnupg lsb-release; \
    install -d /usr/share/postgresql-common/pgdg; \
    curl -fsSL https://www.postgresql.org/media/keys/ACCC4CF8.asc \
        -o /usr/share/postgresql-common/pgdg/apt.postgresql.org.asc; \
    echo "deb [signed-by=/usr/share/postgresql-common/pgdg/apt.postgresql.org.asc] \
https://apt.postgresql.org/pub/repos/apt bookworm-pgdg main" \
        > /etc/apt/sources.list.d/pgdg.list; \
    apt-get update; \
    apt-get install -y --no-install-recommends postgresql-client-18; \
    rm -rf /var/lib/apt/lists/*; \
    pg_dump --version

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY main.py .

# Railway는 $PORT 를 주입한다. 기본값 8000.
ENV PORT=8000
CMD ["sh", "-c", "uvicorn main:app --host 0.0.0.0 --port ${PORT}"]
