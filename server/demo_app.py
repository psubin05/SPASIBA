"""Local-only full-flow demo; production map app remains server.app:app."""
import os
from pathlib import Path

from server.legacy_app import create_app

app = create_app(demo_db=os.environ.get('SPASIBA_DEMO_DB', str(Path(__file__).resolve().parents[1] / '.local/demo.sqlite3')))
