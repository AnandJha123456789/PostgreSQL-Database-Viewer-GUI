from dataclasses import dataclass
import os
from dotenv import load_dotenv, find_dotenv

@dataclass
class DatabaseConfig:
    host: str
    port: int
    database: str
    user: str
    password: str

    @classmethod
    def _load_env(cls):
        """Load variables from .env file, overriding existing environment variables."""
        dotenv_path = find_dotenv(usecwd=True)
        if dotenv_path:
            load_dotenv(dotenv_path=dotenv_path, override=True)

    @classmethod
    def from_env_file(cls):
        """Load configuration, prioritizing .env file, then OS environment variables, then defaults."""
        cls._load_env()
        
        return cls(
            host=os.getenv("DB_HOST", "localhost"),
            port=int(os.getenv("DB_PORT", 5432)),
            database=os.getenv("DB_NAME", ""),
            user=os.getenv("DB_USER", ""),
            password=os.getenv("DB_PASS", ""),
        )

    @classmethod
    def get_demo_config(cls):
        """European Bioinformatics Institute (EBI) PSQL Database Credentials for a Demo Mode."""
        return cls(
            host="hh-pgsql-public.ebi.ac.uk",
            port=5432,
            database="pfmegrnargs",
            user="reader",
            password="NWDMCE5xdipIjRrp",
        )