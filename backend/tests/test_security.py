from seekhunter.security import client_allowed

CIDRS = ["127.0.0.1/32", "192.168.4.0/24", "100.64.0.0/10"]
PUBLIC = ["180.150.112.113"]


def test_lan_and_tailscale_allowed_without_cf_header():
    assert client_allowed("192.168.4.20", None, CIDRS, PUBLIC)
    assert client_allowed("100.101.1.2", None, CIDRS, PUBLIC)
    assert not client_allowed("8.8.8.8", None, CIDRS, PUBLIC)


def test_tunnel_requests_judged_by_cf_ip():
    # cloudflared on .106 connects from the LAN, so the CF header must take precedence
    assert client_allowed("192.168.4.106", "180.150.112.113", CIDRS, PUBLIC)
    assert not client_allowed("192.168.4.106", "1.1.1.1", CIDRS, PUBLIC)
    assert client_allowed("192.168.4.106", "100.80.0.5", CIDRS, PUBLIC)
