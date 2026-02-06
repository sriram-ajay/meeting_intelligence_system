import shutil
import os
from pathlib import Path
import sys

# Ensure project root is on sys.path
# Looking for pyproject.toml to find root
current_dir = Path(__file__).resolve().parent
project_root = current_dir.parent

if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

try:
    from shared_utils.config_loader import get_settings
    from shared_utils.constants import DatabaseConfig
except ImportError:
    print("Error: Could not import project modules. Run this from the project root.")
    sys.exit(1)

def resync_db():
    """
    Nuclear Reset: Deletes the LanceDB directory to fix schema mismatches.
    """
    settings = get_settings()
    db_uri = settings.database_uri
    
    # Handle both absolute and relative paths
    if db_uri.startswith("./"):
        db_path = project_root / db_uri[2:]
    else:
        db_path = Path(db_uri)

    print(f"Targeting database at: {db_path}")

    if db_path.exists():
        try:
            print(f"Removing existing database directory: {db_path}...")
            # We use rmtree but being careful to check it's actually a directory
            if db_path.is_dir():
                shutil.rmtree(db_path)
                print("Successfully deleted database.")
            else:
                os.remove(db_path)
                print("Successfully removed database file.")
            
            # Recreate the parent directory
            db_path.parent.mkdir(parents=True, exist_ok=True)
            print("Ready for fresh indexing with new schema.")
        except Exception as e:
            print(f"Error during deletion: {e}")
            print("Tip: Make sure no other processes (like Docker containers) are holding a lock on the database files.")
    else:
        print(f"Database directory {db_path} does not exist. Nothing to resync.")

if __name__ == "__main__":
    resync_db()
