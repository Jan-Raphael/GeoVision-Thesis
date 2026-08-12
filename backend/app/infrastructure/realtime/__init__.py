"""WebSocket connection hub and Redis pub/sub fan-out (Module 14).

Redis is mandatory rather than optional: with more than one Uvicorn worker, an
in-process registry silently delivers events only to the worker holding the
socket.
"""
