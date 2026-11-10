import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.config import settings
from app.database import Base
from app.main import app


class DemoWorkspaceTest(unittest.TestCase):
    def test_new_guests_receive_separate_persistent_samples(self):
        with tempfile.TemporaryDirectory() as directory:
            engine = create_engine(f"sqlite:///{(Path(directory) / 'demo.db').as_posix()}", connect_args={"check_same_thread": False})
            Base.metadata.create_all(engine)
            sessions = sessionmaker(bind=engine, autoflush=False, autocommit=False)
            with patch.object(settings, "seed_demo_workspace", True), patch.object(settings, "obligo_env", "development"), patch("app.auth.SessionLocal", sessions), patch("app.services.SessionLocal", sessions):
                a, b = TestClient(app), TestClient(app)
                try:
                    self.assertEqual(a.post('/api/session/guest', json={}).status_code, 200)
                    self.assertEqual(b.post('/api/session/guest', json={}).status_code, 200)
                    contracts_a, contracts_b = a.get('/api/contracts').json(), b.get('/api/contracts').json()
                    obligations_a, obligations_b = a.get('/api/obligations').json(), b.get('/api/obligations').json()
                    self.assertEqual((len(contracts_a), len(obligations_a)), (8, 24))
                    self.assertEqual((len(contracts_b), len(obligations_b)), (8, 24))
                    self.assertTrue(all(item['title'].startswith('[Sample]') for item in contracts_a + obligations_a))
                    self.assertEqual({item['status'] for item in obligations_a}, {'pending_review', 'overdue', 'due_today', 'due_soon', 'upcoming', 'completed', 'unscheduled'})
                    self.assertTrue(set(c['id'] for c in contracts_a).isdisjoint(c['id'] for c in contracts_b))
                    self.assertEqual(b.get(f"/api/contracts/{contracts_a[0]['id']}").status_code, 404)
                    self.assertEqual(a.get('/api/dashboard/summary').json()['total_obligations'], 24)
                    self.assertEqual(a.get('/api/contracts').json(), contracts_a)
                finally:
                    a.close()
                    b.close()
            engine.dispose()


if __name__ == '__main__':
    unittest.main()
