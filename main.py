"""
A-IMS Railway POC — minimal FastAPI app.

POC 검증 목적 전용. A-IMS 본체 아님.
"""

import os
import subprocess
import datetime
import uuid
import urllib.request

from fastapi import FastAPI
from fastapi.responses import JSONResponse

app = FastAPI(title="A-IMS Railway POC")


def _database_url():
    return os.environ.get("DATABASE_URL") or os.environ.get("DATABASE_PUBLIC_URL")


@app.get("/")
def root():
    return {
        "service": "aims-railway-poc",
        "endpoints": ["/health", "/db-check", "/pg-dump-test", "/bucket-test"],
        "note": "POC only. Not A-IMS production.",
    }


@app.get("/health")
def health():
    return {"status": "ok", "time": datetime.datetime.utcnow().isoformat() + "Z"}


@app.get("/db-check")
def db_check():
    dsn = _database_url()
    if not dsn:
        return JSONResponse(status_code=500, content={"ok": False, "error": "DATABASE_URL not set"})
    try:
        import psycopg
        with psycopg.connect(dsn, connect_timeout=10) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT version();")
                row = cur.fetchone()
        return {"ok": True, "server_version": row[0] if row else None}
    except Exception as e:
        return JSONResponse(status_code=500, content={"ok": False, "error": f"{type(e).__name__}: {e}"})


@app.get("/pg-dump-test")
def pg_dump_test():
    dsn = _database_url()
    result = {}
    try:
        ver = subprocess.run(["pg_dump", "--version"], capture_output=True, text=True, timeout=30)
        result["pg_dump_version"] = ver.stdout.strip() or ver.stderr.strip()
        result["pg_dump_found"] = ver.returncode == 0
    except FileNotFoundError:
        return JSONResponse(status_code=500, content={"ok": False, "error": "pg_dump binary not found in container"})
    except Exception as e:
        return JSONResponse(status_code=500, content={"ok": False, "error": f"version check failed: {type(e).__name__}: {e}"})
    if not dsn:
        result["ok"] = False
        result["error"] = "DATABASE_URL not set; skipped real dump"
        return JSONResponse(status_code=500, content=result)
    try:
        dump = subprocess.run(["pg_dump", "--schema-only", "--no-owner", "--no-privileges", dsn], capture_output=True, text=True, timeout=120)
        if dump.returncode == 0:
            result["ok"] = True
            result["dump_bytes"] = len(dump.stdout.encode("utf-8"))
            result["dump_head"] = dump.stdout[:500]
        else:
            result["ok"] = False
            result["error"] = dump.stderr.strip()[:1000]
        return JSONResponse(status_code=200 if result.get("ok") else 500, content=result)
    except Exception as e:
        result["ok"] = False
        result["error"] = f"dump failed: {type(e).__name__}: {e}"
        return JSONResponse(status_code=500, content=result)


@app.get("/bucket-test")
def bucket_test():
    endpoint = os.environ.get("AWS_ENDPOINT_URL")
    bucket = os.environ.get("AWS_S3_BUCKET_NAME")
    region = os.environ.get("AWS_DEFAULT_REGION") or "auto"
    akid = os.environ.get("AWS_ACCESS_KEY_ID")
    secret = os.environ.get("AWS_SECRET_ACCESS_KEY")
    missing = [k for k, v in {"AWS_ENDPOINT_URL": endpoint, "AWS_S3_BUCKET_NAME": bucket, "AWS_ACCESS_KEY_ID": akid, "AWS_SECRET_ACCESS_KEY": secret}.items() if not v]
    if missing:
        return JSONResponse(status_code=500, content={"ok": False, "error": f"missing env: {missing}"})
    try:
        import boto3
        from botocore.config import Config
        s3 = boto3.client("s3", endpoint_url=endpoint, region_name=region, aws_access_key_id=akid, aws_secret_access_key=secret, config=Config(s3={"addressing_style": "virtual"}))
        key = f"poc-test/{uuid.uuid4().hex}.txt"
        payload = f"aims-railway-poc bucket test {datetime.datetime.utcnow().isoformat()}Z"
        s3.put_object(Bucket=bucket, Key=key, Body=payload.encode("utf-8"))
        url = s3.generate_presigned_url("get_object", Params={"Bucket": bucket, "Key": key}, ExpiresIn=300)
        with urllib.request.urlopen(url, timeout=30) as resp:
            downloaded = resp.read().decode("utf-8")
        return {"ok": downloaded == payload, "key": key, "uploaded_bytes": len(payload.encode("utf-8")), "downloaded_matches": downloaded == payload, "presigned_url_sample": url.split("?")[0]}
    except Exception as e:
        return JSONResponse(status_code=500, content={"ok": False, "error": f"{type(e).__name__}: {e}"})
