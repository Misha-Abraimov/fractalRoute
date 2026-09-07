"""Explicit idempotent development schema upgrade command.

Run with: python -m backend.schema_upgrade
"""

from .app.database import initialize_database


def main() -> None:
    initialize_database()
    print("Database schema is current.")


if __name__ == "__main__":
    main()
