"""Local MySQL connection settings; loading never opens a database connection."""
import os
from dataclasses import dataclass,field
from pathlib import Path

from dotenv import dotenv_values

from .config import ConfigurationError,DEFAULT_ENV_PATH


@dataclass(frozen=True)
class DatabaseSettings:
    host: str
    port: int
    database: str
    user: str
    password: str=field(repr=False)


def load_database_settings(env_path: Path=DEFAULT_ENV_PATH) -> DatabaseSettings:
    file_values=dotenv_values(env_path,encoding='utf-8',interpolate=False)
    values={}
    for key in ('MYSQL_HOST','MYSQL_PORT','MYSQL_DATABASE','MYSQL_USER','MYSQL_PASSWORD'):
        value=os.environ.get(key,file_values.get(key))
        if value is None or value=='':
            raise ConfigurationError(f'{key} is required.')
        if any(ord(c)<32 or ord(c)==127 for c in value):
            raise ConfigurationError(f'{key} must not contain control characters.')
        # Password spaces and symbols are significant; do not normalize the secret.
        if key!='MYSQL_PASSWORD':
            value=value.strip()
            if not value:
                raise ConfigurationError(f'{key} is required.')
        values[key]=value
    try:
        port=int(values['MYSQL_PORT'])
        if not 1<=port<=65535:raise ValueError
    except ValueError:
        raise ConfigurationError('MYSQL_PORT must be an integer between 1 and 65535.') from None
    return DatabaseSettings(host=values['MYSQL_HOST'],port=port,database=values['MYSQL_DATABASE'],
                            user=values['MYSQL_USER'],password=values['MYSQL_PASSWORD'])
