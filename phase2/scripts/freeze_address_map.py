#!/usr/bin/env python3
"""Print the reviewed-record candidate for the Step-4 address-map freeze.

This stable command name is the human review entry point.  The implementation
and canonicalization definition live in :mod:`address_map_contract` so the
freeze checker and helper cannot silently diverge.
"""

from address_map_contract import main


if __name__ == "__main__":
    raise SystemExit(main())
