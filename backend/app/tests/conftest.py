"""测试夹具：所有用例使用独立的临时 SQLite 库。

必须在导入 app.db 之前设置 DATA_DIR（DB_PATH 在导入时定型）。
"""
import os
import tempfile

_TMP_DATA_DIR = tempfile.mkdtemp(prefix="ladderbill-pytest-")
os.environ.setdefault("DATA_DIR", _TMP_DATA_DIR)

import pytest  # noqa: E402

from app import seed  # noqa: E402
from app.db import DB_PATH  # noqa: E402


def _reset_db():
    for suffix in ("", "-wal", "-shm"):
        path = str(DB_PATH) + suffix
        if os.path.exists(path):
            os.remove(path)
    seed.init_db()


@pytest.fixture()
def fresh_db():
    """每个用例重建一份带种子数据的库。"""
    _reset_db()
    yield DB_PATH

