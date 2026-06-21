# aims-railway-poc

A-IMS v2 클라우드 플랫폼 검증용 미니 FastAPI. **A-IMS 본체 아님.**

## 목적
Railway에서 다음 4종을 확인한다.
1. FastAPI 컨테이너가 뜨는가 (`/health`)
2. Railway PostgreSQL에 붙는가 + 서버 버전 (`/db-check`, 18.x 기대)
3. **컨테이너 내부에서 `pg_dump`(18 클라이언트)로 실제 백업이 떠지는가** (`/pg-dump-test`) ← 제일 중요
4. (별도) Bucket 업로드/다운로드

## 핵심 결정
- 베이스 이미지: `python:3.12-slim-bookworm`
- PGDG apt repo 추가 후 `postgresql-client-18` **버전 고정 설치**
  (Debian 기본 메타패키지는 18이 아닐 수 있어 금지)
- Railway PG 서버 = PostgreSQL 18.4 이므로 클라이언트도 18 필수

## 배포 (Railway)
1. 이 레포를 GitHub에 push
2. Railway 프로젝트 `aims-railway-poc`에서 GitHub repo를 서비스로 추가
3. 서비스 Variables에서 `DATABASE_URL`을 Postgres 서비스 reference로 연결
4. 빌드 후 도메인 생성 → 위 엔드포인트 호출

## 통과 기준
- `/db-check` → `server_version`에 `PostgreSQL 18.x`
- `/pg-dump-test` → `pg_dump_version`이 `18.x` AND `ok: true` (실제 dump 성공)
