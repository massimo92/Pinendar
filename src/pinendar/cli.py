import argparse
from pathlib import Path

import uvicorn

from pinendar.config import Settings
from pinendar.infrastructure.auth_store import AuthStore
from pinendar.infrastructure.migrations import migrate


def main() -> None:
    parser = argparse.ArgumentParser(prog="pinendar")
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("migrate")
    subparsers.add_parser("serve")
    account_parser = subparsers.add_parser("account")
    account_subparsers = account_parser.add_subparsers(dest="account_command", required=True)
    create_parser = account_subparsers.add_parser("create")
    create_parser.add_argument("--username", required=True)
    create_parser.add_argument("--password", required=True)
    create_parser.add_argument("--environment", type=Path, required=True)
    reset_parser = account_subparsers.add_parser("reset-password")
    reset_parser.add_argument("--username", required=True)
    reset_parser.add_argument("--password", required=True)
    args = parser.parse_args()
    settings = Settings()
    if args.command == "migrate":
        migrate(settings.database_path)
    elif args.command == "serve":
        uvicorn.run("pinendar.main:app", host="0.0.0.0", port=settings.port, workers=1)
    else:
        auth_store = AuthStore(settings.auth_database_path)
        auth_store.create_schema()
        try:
            if args.account_command == "create":
                migrate(args.environment)
                account, recovery_code = auth_store.create_account(
                    args.username, args.password, args.environment
                )
                print(f"Usuari creat: {account.username}")
                print(f"Clau de recuperació (desa-la ara): {recovery_code}")
            else:
                account = auth_store.reset_password(args.username, args.password)
                print(f"Contrasenya actualitzada: {account.username}")
        finally:
            auth_store.engine.dispose()
