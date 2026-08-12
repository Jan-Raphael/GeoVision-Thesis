"""Cross-cutting primitives: settings, logging, exceptions, security.

`core` is treated like the standard library - any layer may import it. It is
deliberately excluded from the Clean Architecture layer contract in
`backend/.importlinter` for that reason.
"""
