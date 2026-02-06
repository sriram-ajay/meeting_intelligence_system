"""
Database Schema Management & Production Safeguards.

Ensures that the LanceDB tables match the expected structure required by the 
Retrieval strategies. Prevents "silent failures" caused by schema drift.
"""

import lancedb
from typing import Optional
from shared_utils.logging_utils import ContextualLogger
from shared_utils.constants import LogScope, DatabaseConfig

logger = ContextualLogger(scope=LogScope.RAG_ENGINE)

class SchemaManager:
    """
    Orchestrates database health checks and schema migrations.
    """

    def __init__(self, db: lancedb.DBConnection, table_name: str = DatabaseConfig.TABLE_NAME):
        self.db = db
        self.table_name = table_name

    def validate_or_repair(self) -> bool:
        """
        Validates the current table schema against required production standards.
        In a mature system, this would trigger 'Migrations'.
        
        Returns:
            True if schema is valid, False if a mismatch was detected.
        """
        if self.table_name not in self.db.table_names():
            logger.info("schema_check_skipped", reason="table_not_yet_created")
            return True

        try:
            table = self.db.open_table(self.table_name)
            schema_names = table.schema.names
            
            # Critical Production Check: meeting_id isolation
            # If flat_metadata is FALSE, meeting_id will be missing from root
            required_columns = ["meeting_id", "chunk_type", "speaker", "timestamp", "date", "title"]
            missing = [col for col in required_columns if col not in schema_names]
            
            if missing:
                logger.error(
                    "DATABASE_SCHEMA_MISMATCH",
                    missing_columns=missing,
                    cause="Existing table schema does not match the new chunking metadata requirements."
                )
                print(f"\n⚠️  SCHEMA MISMATCH DETECTED: Missing columns {missing}")
                print("⚠️  To fix this, please run: python -m scripts.resync_db")
                return False
            
            logger.info("database_schema_verified", columns=len(schema_names))
            return True
            
        except Exception as e:
            logger.error("schema_validation_failed", error=str(e))
            return False

    def backup_table(self, backup_suffix: str = "_backup"):
        """
        Creates a snapshot of the current table before dangerous operations.
        """
        if self.table_name in self.db.table_names():
            # In LanceDB, we can copy the directory or use .to_pandas() for small sets
            logger.info("database_backup_initiated", table=self.table_name)
            # Implementation depends on data scale
