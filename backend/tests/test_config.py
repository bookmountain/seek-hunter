from seekhunter.config import Env


def test_env_defaults_and_list_parsing(monkeypatch):
    monkeypatch.setenv("ALLOWED_PUBLIC_IPS", "1.2.3.4, 5.6.7.8")
    env = Env()
    assert env.telegram_target == "1635495359"
    assert env.allowed_public_ip_list == ["1.2.3.4", "5.6.7.8"]
    assert "192.168.4.0/24" in env.allowed_cidr_list
    assert env.openclaw_agent == "seekhunter-scorer"
