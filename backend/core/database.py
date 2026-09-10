"""
Database connection and session management.

Architecture:
- SQLAlchemy 2.0 ORM
- MySQL/MariaDB via pymysql
- Session factory with dependency injection
- Connection pooling configured for LWS shared hosting
"""

from sqlalchemy import create_engine, event
from sqlalchemy.orm import declarative_base, sessionmaker, Session
from typing import Generator
import os
from dotenv import load_dotenv

load_dotenv()

# Database URL from environment (dev by default)
DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "mysql+pymysql://unified_dev:dev_password_2026@localhost/unified_ia_dev"
)

# Engine configuration
engine = create_engine(
    DATABASE_URL,
    pool_pre_ping=True,  # Verify connections before using
    pool_size=5,  # Conservative for shared hosting
    max_overflow=10,
    pool_recycle=3600,  # Recycle connections every hour
    echo=False,  # Set True for SQL debugging
)

# Session factory
SessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=engine,
)

# Base class for models (SQLAlchemy 2.0 style)
Base = declarative_base()


def get_db() -> Generator[Session, None, None]:
    """
    FastAPI dependency for database sessions.
    
    Usage:
        @app.get("/items")
        def read_items(db: Session = Depends(get_db)):
            return db.query(Item).all()
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db():
    """
    Initialize database (create tables).
    Only creates new tables, doesn't modify existing ones.
    
    For migrations, use Alembic:
        alembic revision --autogenerate -m "message"
        alembic upgrade head
    """
    Base.metadata.create_all(bind=engine)


def check_connection() -> bool:
    """
    Test database connection.
    
    Returns:
        True if connection successful, False otherwise
    """
    from sqlalchemy import text
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return True
    except Exception as e:
        print(f"❌ Database connection failed: {e}")
        return False


# Event listeners for connection management
@event.listens_for(engine, "connect")
def set_sqlite_pragma(dbapi_conn, connection_record):
    """Set MySQL session variables if needed."""
    pass  # Add MySQL-specific settings here if needed


if __name__ == "__main__":
    """Test database connection when run directly."""
    from sqlalchemy import text
    
    print("🔍 Testing database connection...")
    if check_connection():
        print("✅ Database connection successful")
        
        # Show tables count
        with engine.connect() as conn:
            result = conn.execute(text("SHOW TABLES"))
            tables = [row[0] for row in result.fetchall()]
            print(f"📊 {len(tables)} tables found in database")
            if tables:
                print(f"📋 Sample tables: {', '.join(tables[:5])}")
    else:
        print("❌ Database connection failed")
        print(f"🔗 Connection string: {DATABASE_URL.split('@')[1]}")  # Hide credentials
