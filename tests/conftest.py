from pathlib import Path

import pytest

from server import game_ws
from server.db import Database


@pytest.fixture(autouse=True)
def isolated_game_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Database:
    """Point the websocket layer at a throwaway db for every test, so test
    runs never read or write the real poker.db on disk."""
    test_db = Database(tmp_path / "game.db")
    monkeypatch.setattr(game_ws, "db", test_db)
    return test_db
