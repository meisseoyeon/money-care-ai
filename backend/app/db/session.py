from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import DATABASE_URL

# engine: DB와의 연결 통로. 서버 전체에서 하나만 만들어 같이 씀.
engine = create_engine(DATABASE_URL, pool_pre_ping=True)

# SessionLocal: 요청 하나마다 새 "작업 공간(세션)"을 만드는 공장.
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def get_db():
    """API 함수에 DB 세션을 빌려주고, 요청이 끝나면 반드시 닫음."""
    db: Session = SessionLocal()
    try:
        yield db
    finally:
        db.close()