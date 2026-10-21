from functools import lru_cache

from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.config import DATABASE_URL


@lru_cache
def session_factory():
    if not DATABASE_URL:
        raise HTTPException(503, "서버 DB 설정이 필요해요.")
    engine = create_engine(DATABASE_URL, pool_pre_ping=True, connect_args={"connect_timeout": 5})
    return sessionmaker(bind=engine, expire_on_commit=False)


def get_db():
    # 테이블 생성은 Flyway만 담당합니다.
    with session_factory()() as db:
        try:
            yield db
        except Exception:
            db.rollback()
            raise
