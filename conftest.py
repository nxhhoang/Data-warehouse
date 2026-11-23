# Backup for pytest.ini's pythonpath option: explicitly put the repository
# root on sys.path so tests can `import src.*` no matter which pytest version
# or invocation style is used.
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
