"""数据库会话与初始化。"""
from __future__ import annotations

from collections.abc import Generator

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from .config import settings
from .models import Base

engine = create_engine(
    settings.database_url,
    connect_args={"check_same_thread": False, "timeout": 30},
    future=True,
)


@event.listens_for(Engine, "connect")
def _set_sqlite_pragma(dbapi_connection, connection_record) -> None:  # noqa: ANN001
    """打开外键约束、WAL 与忙等待。

    SQLite 默认不校验外键，不打开的话「删课程留下孤儿选课记录」这类脏数据查不出来。
    `busy_timeout` 让并发写事务排队等待而不是立刻抛 database is locked。
    """
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA busy_timeout=30000")
    cursor.close()


SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def _migrate_sqlite() -> None:
    """SQLite 轻量迁移：create_all 不会给已有表补列。"""
    with engine.begin() as conn:
        course_cols = {
            row[1] for row in conn.exec_driver_sql("PRAGMA table_info(courses)")
        }
        if "enrolled_count" not in course_cols:
            conn.exec_driver_sql(
                "ALTER TABLE courses ADD COLUMN enrolled_count INTEGER NOT NULL DEFAULT 0"
            )
            # 老库按既有选课记录回填，避免所有课程一上线就显示满员/空余错误。
            conn.exec_driver_sql(
                """
                UPDATE courses SET enrolled_count = (
                    SELECT COUNT(*) FROM enrollments
                    WHERE enrollments.course_id = courses.id
                      AND enrollments.status = 'enrolled'
                )
                """
            )

        pending_cols = {
            row[1] for row in conn.exec_driver_sql("PRAGMA table_info(pending_actions)")
        }
        for column, ddl in (
            ("result", "ALTER TABLE pending_actions ADD COLUMN result VARCHAR(16)"),
            ("error", "ALTER TABLE pending_actions ADD COLUMN error TEXT"),
            (
                "executed_at",
                "ALTER TABLE pending_actions ADD COLUMN executed_at DATETIME",
            ),
        ):
            if column not in pending_cols:
                conn.exec_driver_sql(ddl)


def init_db() -> None:
    Base.metadata.create_all(bind=engine)
    _migrate_sqlite()


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
