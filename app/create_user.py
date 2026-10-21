"""Create a local account using hidden interactive password input."""
import argparse
from getpass import GetPassWarning, getpass
import warnings

from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from .config import ConfigurationError
from .database import create_db_engine
from .database_config import load_database_settings
from .users import MAX_PASSWORD_LENGTH, MIN_PASSWORD_LENGTH, create_user


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--username', required=True)
    args = parser.parse_args(argv)

    try:
        with warnings.catch_warnings():
            # Refuse getpass's fallback to input that might echo a password.
            warnings.simplefilter('error', GetPassWarning)
            password = getpass(f'Password ({MIN_PASSWORD_LENGTH}-{MAX_PASSWORD_LENGTH} characters): ')
            confirmation = getpass('Confirm password: ')
    except (EOFError, GetPassWarning):
        print('Cannot read a hidden password. Run this command in your own PowerShell terminal.')
        return 1
    except KeyboardInterrupt:
        print('\nCancelled. No account was created.')
        return 130

    if password != confirmation:
        print('Passwords do not match. No account was created.')
        return 1

    engine = None
    try:
        engine = create_db_engine(load_database_settings())
        user_id = create_user(engine, username=args.username, password=password)
    except ConfigurationError:
        print('Database configuration is incomplete or invalid.')
        return 1
    except ValueError:
        print(f'Invalid username or password. Use a 3-32 character lowercase username and a {MIN_PASSWORD_LENGTH}-{MAX_PASSWORD_LENGTH} character password.')
        return 1
    except IntegrityError:
        print('Account creation was rejected by a database constraint. Existing accounts were not changed.')
        return 1
    except SQLAlchemyError:
        print('Database operation failed. Check the MySQL service and application account permissions.')
        return 1
    finally:
        if engine is not None:
            engine.dispose()

    print('User created')
    print('Username:', args.username)
    print('User ID:', user_id)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
