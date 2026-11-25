"""Exceptions shared by every data source."""


class SourceUnavailable(Exception):
    """A source couldn't be reached or returned something unusable right now."""


class NotFound(Exception):
    """The source has no page for this stock."""
