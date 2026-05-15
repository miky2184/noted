from pathlib import Path
from platformdirs import user_data_dir, user_config_dir

APP_NAME = "noted"

def data_dir() -> Path:
    """Cartella dati sicura per piattaforma.
    Mac:     ~/Library/Application Support/noted/
    Linux:   ~/.local/share/noted/
    Windows: %APPDATA%\\noted\\
    """
    d = Path(user_data_dir(APP_NAME, APP_NAME))
    d.mkdir(parents=True, exist_ok=True)
    return d

def config_dir() -> Path:
    d = Path(user_config_dir(APP_NAME, APP_NAME))
    d.mkdir(parents=True, exist_ok=True)
    return d

def db_path() -> Path:
    return data_dir() / "notes.db"

def config_path() -> Path:
    return config_dir() / "config.json"

def log_path() -> Path:
    return data_dir() / "noted.log"

def cert_path() -> Path:
    return config_dir() / "noted.local.pem"

def key_path() -> Path:
    return config_dir() / "noted.local-key.pem"
