"""Shared admission contract, independent of the server CLI module identity."""

THRESHOLDS = [0, 1000000, 10000000, 100000000, 1000000000, 10000000000, 100000000000]


class QueueBusy(ValueError):
    """An accepted physical transaction cannot be replaced by another caller."""
