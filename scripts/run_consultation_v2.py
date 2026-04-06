#!/usr/bin/env python3
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from consultation_v2.cli import main


if __name__ == '__main__':
    raise SystemExit(main())
