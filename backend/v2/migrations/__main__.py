"""``python -m backend.v2.migrations`` entry point; logic lives in ``cli.py``."""

import sys

from backend.v2.migrations.cli import main

sys.exit(main())
