"""``python -m passport_to_uml`` → CLI конвейера (без предупреждений runpy)."""

import sys

from .engine import main

if __name__ == '__main__':
    sys.exit(main())
