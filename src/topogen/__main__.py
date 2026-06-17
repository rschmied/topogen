# File Chain (see DEVELOPER.md):
# Doc Version: v1.0.1
# Date Modified: 2026-02-16
#
# - Called by: Python interpreter when running `python -m topogen`
# - Reads from: None (entry point only)
# - Writes to: None (calls main() and exits with its return code)
# - Calls into: src/topogen/main.main()
"""Allow running the package with python -m topogen (same as the topogen console script)."""
from topogen.main import main
import sys
sys.exit(main())
