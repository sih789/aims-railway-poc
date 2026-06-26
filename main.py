"""
A-IMS Railway POC — minimal FastAPI app.

POC 검증 목적 전용. A-IMS 본체 아님.
게이트:
  GET /                - 안내
  GET /health          - 서버 생존 확인
  GET /db-check        - Railway Postgres 연결 + 서버 버전 확인 (18.x 기대)
  GET /pg-dump-test    - 컨테이너 내부에서 실제로 pg_dump 실행
  GET /retention-smoke - Railway Bucket에서 list_objects_v2(paginator) + delete_object 실검증

환경변수:
  DATABASE_URL  - Railway가 Postgres 서비스 연결 시 자동 주입.
  AWS_ENDPOINT_URL / AWS_S3_BUCKET_NAME / AWS_ACCESS_KEY_ID /
  AWS_SECRET_ACCESS_KEY / AWS_DEFAULT_REGION - Bucket 접근용.
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
        "endpoints": ["/health", "/db-check", "/pg-dump-test", "/retention-smoke"],
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


@app.get("/retention-smoke")
def retention_smoke():
    """
    3c retention 핵심 동작(list_objects_v2 paginator + delete_object)을
    Railway 실 Bucket에서 검증한다.

    diagnostic-packages/ prefix에 스모크 전용 더미 zip 3개만 put/delete한다.
    실데이터(있다면)는 건드리지 않는다 — 방금 만든 3개 키만 삭제.
    3c 코드와 동일하게 virtual addressing client를 쓴다.
    """
    import boto3
    from botocore.config import Config

    endpoint = os.environ.get("AWS_ENDPOINT_URL")
    bucket = os.environ.get("AWS_S3_BUCKET_NAME")
    region = os.environ.get("AWS_DEFAULT_REGION") or "auto"
    akid = os.environ.get("AWS_ACCESS_KEY_ID")
    secret = os.environ.get("AWS_SECRET_ACCESS_KEY")

    missing = [
        k for k, v in {
            "AWS_ENDPOINT_URL": endpoint,
            "AWS_S3_BUCKET_NAME": bucket,
            "AWS_ACCESS_KEY_ID": akid,
            "AWS_SECRET_ACCESS_KEY": secret,
        }.items() if not v
    ]
    if missing:
        return JSONResponse(
            status_code=500,
            content={"ok": False, "error": f"missing env: {missing}"},
        )

    prefix = "diagnostic-packages/"
    put_keys = [f"{prefix}20260626_10000{i}.zip" for i in (1, 2, 3)]
    result: dict = {}

    try:
        s3 = boto3.client(
            "s3",
            endpoint_url=endpoint,
            region_name=region,
            aws_access_key_id=akid,
            aws_secret_access_key=secret,
            config=Config(region_name=region, s3={"addressing_style": "virtual"}),
        )

        # 1) put 더미 3개
        for k in put_keys:
            s3.put_object(Bucket=bucket, Key=k, Body=b"smoke", ContentType="application/zip")
        result["put"] = {"ok": True, "keys": put_keys}

        # 2) list_objects_v2 paginator 전 페이지 (PageSize 작게 강제 → 다중 페이지)
        paginator = s3.get_paginator("list_objects_v2")
        listed = []
        page_count = 0
        for page in paginator.paginate(
            Bucket=bucket, Prefix=prefix, PaginationConfig={"PageSize": 2}
        ):
            page_count += 1
            for entry in page.get("Contents", []):
                listed.append(entry["Key"])
        result["list"] = {"ok": True, "page_count": page_count, "found": listed}

        # 3) delete 방금 put한 것만
        deleted = []
        for k in put_keys:
            s3.delete_object(Bucket=bucket, Key=k)
            deleted.append(k)
        result["delete"] = {"ok": True, "keys": deleted}

        # 4) delete 후 재확인
        after = []
        for page in paginator.paginate(Bucket=bucket, Prefix=prefix):
            for entry in page.get("Contents", []):
                after.append(entry["Key"])
        result["after_delete"] = {"ok": True, "remaining": after}
        result["smoke_pass"] = all(k not in after for k in put_keys)

        return JSONResponse(status_code=200, content=result)
    except Exception as e:  # noqa: BLE001
        result["ok"] = False
        result["error"] = f"{type(e).__name__}: {e}"
        return JSONResponse(status_code=500, content=result)
