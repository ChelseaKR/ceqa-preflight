"""The opt-in AI layer described in ADR 0002.

Nothing in this package is imported by the default ``check`` path. The model client is
imported lazily inside the ``ai`` commands so that the default path gains no dependency.
Every module here treats model output as untrusted: values must quote the document and
claims must quote the committed corpus, and both are verified before display.
"""
