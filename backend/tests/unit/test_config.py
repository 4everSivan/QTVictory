"""T01-2：配置项默认值、环境变量覆盖与非法值校验（02 §6.10 全表）。"""

import pytest
from pydantic import ValidationError

from app.config import Settings


def test_defaults_match_design():
    s = Settings()
    assert s.qtv_port == 8787
    assert s.qtv_db == "data/qtvictory.db"
    assert s.qtv_poll_sec == 3
    assert s.qtv_api_key == ""
    assert s.qtv_public_read is False
    assert s.qtv_rate_limit == 20
    assert s.qtv_volume_participation == 0.25
    assert s.qtv_dividend_tax == 0.10
    assert s.qtv_max_traders == 64
    assert s.qtv_cors == "http://localhost:4312"


def test_env_override():
    s = Settings(qtv_port=9000, qtv_api_key="secret", qtv_rate_limit=5)
    assert s.qtv_port == 9000
    assert s.qtv_api_key == "secret"
    assert s.qtv_rate_limit == 5


def test_invalid_values_rejected():
    with pytest.raises(ValidationError):
        Settings(qtv_port=0)
    with pytest.raises(ValidationError):
        Settings(qtv_port=70000)
    with pytest.raises(ValidationError):
        Settings(qtv_volume_participation=1.5)
    with pytest.raises(ValidationError):
        Settings(qtv_rate_limit=0)
