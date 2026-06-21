"""
A-IMS Railway POC — minimal FastAPI app.

POC 검증 목적 전용. A-IMS 본체 아님.
세 가지 게이트를 찍는다:
  GET /            - 안내
  GET /health      - 서버 생존 확인
  GET /db-check    - Railway Postgres 연결 + 서버 버전 확인 (18.x 기대)
  GET /pg-dump-test - 컨테이너 내부에서 실제로 pg_dump 실행 (제일 중요한 게이트)

환경변수:
  DATABASE_URL  - Railway가 Postgres 서비스 연결 시 자동 주입.
                  (서비스 Variables에서 reference로 연결)
"""

import os
import subprocess
import datetime

from fastapi import FastAPI
from fastapi.responses import JSONResponse

app = FastAPI(title="A-IMS Railway POC")


def _database_url() -> str | None:
    # Railway는 보통 DATABASE_URL 을 주입한다.
    # 일부 템플릿은 DATABASE_PUBLIC_URL 만 주기도 하므로 둘 다 본다.
    return os.environ.get("DATABASE_URL") or os.environ.get("DATABASE_PUBLIC_URL")


@app.get("/")
def root():
    return {
        "service": "aims-railway-poc",
        "endpoints": ["/health", "/db-check", "/pg-dump-test"],
        "note": "POC only. Not A-IMS production.",
    }


@app.get("/health")
def health():
    return {"status": "ok", "time": datetime.datetime.utcnow().isoformat() + "Z"}


@app.get("/db-check")
def db_check():
    """psycopg3로 Railway Postgres에 붙어 서버 버전을 읽는다."""
    dsn = _database_url()
    if not dsn:
        return JSONResponse(
            status_code=500,
            content={"ok": False, "error": "DATABASE_URL not set"},
        )
    try:
        import psycopg

        with psycopg.connect(dsn, connect_timeout=10) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT version();")
                row = cur.fetchone()
        return {"ok": True, "server_version": row[0] if row else None}
    except Exception as e:  # noqa: BLE001 — POC: 어떤 실패든 그대로 노출
        return JSONResponse(
            status_code=500,
            content={"ok": False, "error": f"{type(e).__name__}: {e}"},
        )


@app.get("/pg-dump-test")
def pg_dump_test():
    """
    컨테이너 내부 pg_dump 게이트.
    1) pg_dump --version 을 찍어 클라이언트 메이저가 18인지 확인.
    2) 실제 Railway DB를 향해 schema-only dump를 떠서 성공/바이트수를 본다.
       (데이터 없는 빈 DB라 schema-only 로도 충분히 '붙어서 떠진다'를 증명)
    """
    dsn = _database_url()
    result: dict = {}

    # 1) 클라이언트 버전
    try:
        ver = subprocess.run(
            ["pg_dump", "--version"],
            capture_output=True, text=True, timeout=30,
        )
        result["pg_dump_version"] = ver.stdout.strip() or ver.stderr.strip()
        result["pg_dump_found"] = ver.returncode == 0
    except FileNotFoundError:
        return JSONResponse(
            status_code=500,
            content={"ok": False, "error": "pg_dump binary not found in container"},
        )
    except Exception as e:  # noqa: BLE001
        return JSONResponse(
            status_code=500,
            content={"ok": False, "error": f"version check failed: {type(e).__name__}: {e}"},
        )

    # 2) 실제 dump 시도
    if not dsn:
        result["ok"] = False
        result["error"] = "DATABASE_URL not set; skipped real dump"
        return JSONResponse(status_code=500, content=result)

    try:
        dump = subprocess.run(
            ["pg_dump", "--schema-only", "--no-owner", "--no-privileges", dsn],
            capture_output=True, text=True, timeout=120,
        )
        if dump.returncode == 0:
            result["ok"] = True
            result["dump_bytes"] = len(dump.stdout.encode("utf-8"))
            # 너무 길면 앞부분만
            result["dump_head"] = dump.stdout[:500]
        else:
            result["ok"] = False
            result["error"] = dump.stderr.strip()[:1000]
        return JSONResponse(
            status_code=200 if result.get("ok") else 500,
            content=result,
        )
    except Exception as e:  # noqa: BLE001
        result["ok"] = False
        result["error"] = f"dump failed: {type(e).__name__}: {e}"
        return JSONResponse(status_code=500, content=result)
