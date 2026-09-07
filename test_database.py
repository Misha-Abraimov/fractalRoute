import unittest

from sqlalchemy import create_engine, inspect, text

from backend.app.database import ensure_current_route_columns


class DatabaseInitializationTests(unittest.TestCase):
    def test_existing_route_table_gets_async_source_column_idempotently(self):
        engine = create_engine("sqlite+pysqlite:///:memory:")
        with engine.begin() as connection:
            connection.execute(
                text("CREATE TABLE routes (id VARCHAR(36) PRIMARY KEY)")
            )

        ensure_current_route_columns(engine)
        ensure_current_route_columns(engine)

        columns = {column["name"] for column in inspect(engine).get_columns("routes")}
        self.assertEqual(
            columns,
            {
                "id",
                "source_object_key",
                "receive_count",
                "queue_wait_ms",
                "analysis_duration_ms",
                "total_duration_ms",
            },
        )
        engine.dispose()


if __name__ == "__main__":
    unittest.main()
