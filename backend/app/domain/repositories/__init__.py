"""Abstract repository interfaces (Module 02).

Methods are named for intent (`list_public_feed`, `find_by_project_code`), not
for SQL. Concrete implementations live in `infrastructure/repositories/`, and
tests inject fakes that satisfy the same interface.
"""
