import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from app import app as flask_app
from database.db import init_db, seed_db


@pytest.fixture(scope="session")
def app():
    flask_app.config["TESTING"] = True
    flask_app.config["SECRET_KEY"] = "test-secret"
    with flask_app.app_context():
        init_db()
        seed_db()
    yield flask_app


@pytest.fixture
def client(app):
    return app.test_client()
