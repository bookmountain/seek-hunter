from seekhunter.security import client_allowed

CIDRS = ["127.0.0.1/32", "192.168.4.0/24", "100.64.0.0/10"]
PUBLIC = ["180.150.112.113"]
TUNNEL = ["192.168.4.106"]


def test_lan_and_tailscale_allowed_without_cf_header():
    assert client_allowed("192.168.4.20", None, CIDRS, PUBLIC, TUNNEL)
    assert client_allowed("100.101.1.2", None, CIDRS, PUBLIC, TUNNEL)
    assert not client_allowed("8.8.8.8", None, CIDRS, PUBLIC, TUNNEL)


def test_tunnel_requests_judged_by_cf_ip():
    # cloudflared on .106 connects from the LAN, so the CF header must take precedence
    assert client_allowed("192.168.4.106", "180.150.112.113", CIDRS, PUBLIC, TUNNEL)
    assert not client_allowed("192.168.4.106", "1.1.1.1", CIDRS, PUBLIC, TUNNEL)
    assert client_allowed("192.168.4.106", "100.80.0.5", CIDRS, PUBLIC, TUNNEL)


def test_tunnel_proxy_without_cf_header_is_denied():
    # cloudflared's own LAN IP must never be treated as if it were the real client.
    assert not client_allowed("192.168.4.106", None, CIDRS, PUBLIC, TUNNEL)


def test_tunnel_proxy_with_empty_cf_header_is_denied():
    assert not client_allowed("192.168.4.106", "   ", CIDRS, PUBLIC, TUNNEL)


def test_tunnel_proxy_with_allowed_public_ip_is_allowed():
    assert client_allowed("192.168.4.106", "180.150.112.113", CIDRS, PUBLIC, TUNNEL)


def test_public_ips_support_ipv6_networks():
    public = ["180.150.112.113", "2001:db8:1234::/48"]
    assert client_allowed("8.8.8.8", "2001:db8:1234:5678::1", CIDRS, public, TUNNEL)


def test_invalid_cf_ip_is_denied():
    assert not client_allowed("8.8.8.8", "not-an-ip", CIDRS, PUBLIC, TUNNEL)
