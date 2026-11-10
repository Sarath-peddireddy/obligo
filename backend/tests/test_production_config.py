import unittest
from unittest.mock import patch

from app.config import settings
from app.database import normalize_database_url
from app.main import validate_production_settings


class ProductionConfigurationTest(unittest.TestCase):
    def test_postgres_url_normalization(self):
        self.assertEqual(normalize_database_url("postgres://db/example"), "postgresql+psycopg://db/example")
        self.assertEqual(normalize_database_url("postgresql://db/example"), "postgresql+psycopg://db/example")
        self.assertEqual(normalize_database_url("sqlite:///test.db"), "sqlite:///test.db")

    def test_fail_closed_configuration(self):
        values = dict(obligo_env="production", mcp_bearer_token="x" * 40,
                      cors_origins="https://frontend.example", mcp_allowed_hosts="backend.example",
                      mcp_allowed_origins="https://frontend.example")
        with patch.multiple(settings, **values):
            validate_production_settings("postgresql")
            with self.assertRaises(RuntimeError):
                validate_production_settings("sqlite")
            for key, value in [("mcp_bearer_token", ""), ("cors_origins", "https://*.example"),
                               ("cors_origins", "https://frontend.example/path"),
                               ("mcp_allowed_hosts", "*"), ("mcp_allowed_origins", "http://evil.example")]:
                with self.subTest(key=key, value=value), patch.object(settings, key, value):
                    with self.assertRaises(RuntimeError):
                        validate_production_settings("postgresql")


if __name__ == "__main__":
    unittest.main()
