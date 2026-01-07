import threading
import logging
from typing import Optional, List, Any, Tuple
from datetime import datetime
import sys
from .config import DatabaseConfig

# --- DEPENDENCY CHECK ---
try:
    import pg8000.native
except ImportError:
    print("CRITICAL ERROR: The required library 'pg8000' is not installed.")
    print("Please install it by running the following command in your terminal:")
    print(f"{sys.executable} -m pip install pg8000")
    sys.exit(1)

class DatabaseConnection:
    def __init__(self, config: DatabaseConfig):
        self.config = config
        self.conn: Optional[pg8000.native.Connection] = None
        self.logger = logging.getLogger(__name__)
        self.lock = threading.Lock()

    def update_config(self, new_config: DatabaseConfig):
        with self.lock:
            self.close()
            self.config = new_config

    def connect(self) -> bool:
        try:
            with self.lock:
                if self.conn and self.conn._sock is not None:
                    return True

                # Check if minimal info is present
                if not self.config.host or not self.config.database:
                    return False

                self.conn = pg8000.native.Connection(
                    host=self.config.host,
                    port=self.config.port,
                    database=self.config.database,
                    user=self.config.user,
                    password=self.config.password,
                )
                self.logger.info(f"Connected to '{self.config.database}'")
                return True
        except Exception as e:
            self.logger.error(f"Connection failed: {e}")
            return False

    def execute_query(self, query: str) -> Optional[List[List[Any]]]:
        with self.lock:
            try:
                if not self.conn or self.conn._sock is None:
                    self.logger.warning(
                        "Connection closed/missing. Attempting to reconnect..."
                    )
                    if not self.connect():
                        raise ConnectionError(
                            "Failed to establish database connection."
                        )

                rows = self.conn.run(query)
                column_names = [col["name"] for col in self.conn.columns]

                formatted_rows = []
                for row in rows:
                    formatted_row = []
                    for val in row:
                        if isinstance(val, datetime):
                            formatted_row.append(val.strftime("%Y-%m-%d %H:%M:%S"))
                        elif val is None:
                            formatted_row.append("NULL")
                        else:
                            formatted_row.append(str(val))
                    formatted_rows.append(formatted_row)

                return [column_names] + formatted_rows

            except Exception as e:
                self.logger.error(f"Query execution failed: {e}")
                return [["Error"], [[str(e)]]]

    def get_schemas(self) -> List[str]:
        query = "SELECT DISTINCT table_schema FROM information_schema.tables ORDER BY table_schema;"
        results = self.execute_query(query)
        if results and len(results) > 1 and results[0][0] != "Error":
            return [row[0] for row in results[1:]]
        return []

    def get_tables(self, schema: str) -> List[str]:
        query = f"""
        SELECT table_name
        FROM information_schema.tables
        WHERE table_schema = '{schema}'
        ORDER BY table_name
        """
        results = self.execute_query(query)
        if results and len(results) > 1 and results[0][0] != "Error":
            return [row[0] for row in results[1:]]
        return []

    def get_all_tables(self) -> List[Tuple[str, str]]:
        query = """
        SELECT table_schema, table_name
        FROM information_schema.tables
        WHERE table_schema NOT IN ('pg_catalog', 'information_schema')
        ORDER BY table_schema, table_name;
        """
        results = self.execute_query(query)
        if results and len(results) > 1 and results[0][0] != "Error":
            return [tuple(row) for row in results[1:]]
        return []

    def close(self):
        with self.lock:
            if self.conn and self.conn._sock is not None:
                try:
                    self.conn.close()
                    self.logger.info("Database connection closed")
                except Exception as e:
                    self.logger.error(f"Error closing connection: {e}")
            self.conn = None
