"""Config condivisa dei test: repo root su sys.path (stesso schema di
`PYTHONPATH=.` usato dagli script in scripts/), così i test girano anche
senza impostare la variabile d'ambiente a mano."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
