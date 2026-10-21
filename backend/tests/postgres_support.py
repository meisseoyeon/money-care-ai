"""실제 마이그레이션을 적용하는 독립 테스트 스키마."""

import os
import unittest
from pathlib import Path
from uuid import uuid4

from sqlalchemy import create_engine, event
from sqlalchemy.schema import CreateSchema, DropSchema


class PostgresSchemaTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.base_engine = create_engine(os.environ["DEMO_TEST_DATABASE_URL"])
        cls.schema = "budget_test_" + uuid4().hex
        with cls.base_engine.begin() as conn:
            conn.execute(CreateSchema(cls.schema))
        cls.addClassCleanup(cls.drop_schema)
        with cls.base_engine.begin() as conn:
            conn.exec_driver_sql("CREATE EXTENSION IF NOT EXISTS vector WITH SCHEMA public")
            conn.exec_driver_sql(f'SET LOCAL search_path = "{cls.schema}", public, pg_catalog')
            migrations = sorted((Path(__file__).resolve().parents[2] / "database/migrations").glob("V*__*.sql"),
                                key=lambda path: tuple(map(int, path.name.split("__")[0][1:].split("."))))
            for path in migrations:
                script = path.read_text(encoding="utf-8").replace(
                    "SET LOCAL search_path = public, pg_catalog;",
                    f'SET LOCAL search_path = "{cls.schema}", public, pg_catalog;')
                with conn.connection.driver_connection.cursor() as cursor:
                    cursor.execute(script, prepare=False)

        @event.listens_for(cls.base_engine, "checkout")
        def set_search_path(connection, record, proxy):
            previous = connection.autocommit
            connection.autocommit = True
            try:
                with connection.cursor() as cursor:
                    cursor.execute(f'SET search_path = "{cls.schema}", public, pg_catalog')
            finally:
                connection.autocommit = previous

        cls.engine = cls.base_engine.execution_options(schema_translate_map={None: cls.schema})

    @classmethod
    def drop_schema(cls):
        assert cls.schema.startswith("budget_test_") and len(cls.schema) == 44
        try:
            with cls.base_engine.begin() as conn:
                conn.execute(DropSchema(cls.schema, cascade=True))
        finally:
            cls.base_engine.dispose()
