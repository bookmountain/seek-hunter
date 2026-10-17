from seekhunter.contacts import Contacts, extract_contacts, find_linkedin_profile, linkedin_search_urls


def test_extracts_name_and_phone_after_call_verb():
    text = (
        "To apply please click apply or call Brayden Mackay on 08 8216 3534 for a confidential "
        "discussion."
    )
    c = extract_contacts(text)
    assert c.name == "Brayden Mackay"
    assert c.phone == "08 8216 3534"
    assert c.email is None


def test_extracts_name_phone_and_email_with_title_after_contact_verb():
    text = (
        "If interested, please contact Sarah O'Neil, Senior Consultant, on 0412 345 678 or "
        "sarah.oneil@agency.com.au"
    )
    c = extract_contacts(text)
    assert c.name == "Sarah O'Neil"
    assert c.phone == "0412 345 678"
    assert c.email == "sarah.oneil@agency.com.au"


def test_team_phone_only_no_name():
    c = extract_contacts("Call our team on 1300 123 456 to discuss.")
    assert c.phone == "1300 123 456"
    assert c.name is None


def test_contact_talent_acquisition_has_no_name():
    c = extract_contacts("Contact Talent Acquisition for more information.")
    assert c.name is None


def test_mobile_plus61_is_normalised():
    c = extract_contacts("Please call Jane Smith on +61 412 345 678 today.")
    assert c.phone == "+61 412 345 678"
    assert c.name == "Jane Smith"


def test_landline_plus61_is_normalised():
    c = extract_contacts("Phone +61 8 8216 3534 for details.")
    assert c.phone == "+61 8 8216 3534"


def test_no_contacts_in_plain_text():
    c = extract_contacts("We are a great place to work with lots of benefits.")
    assert c == Contacts(name=None, phone=None, email=None)


def test_noreply_email_is_ignored():
    c = extract_contacts("Questions? Email noreply@bigcorp.com or call Mary Jones on 0412 345 678")
    assert c.email is None
    assert c.phone == "0412 345 678"


def test_reach_out_to_verb():
    c = extract_contacts("Please reach out to Tom Baker for a chat about the role.")
    assert c.name == "Tom Baker"


def test_speak_to_verb():
    c = extract_contacts("Speak to Alex Turner about this exciting opportunity.")
    assert c.name == "Alex Turner"


def test_linkedin_search_urls_with_name():
    urls = linkedin_search_urls("Brayden Mackay", "Acme Pty Ltd")
    assert "Brayden+Mackay" in urls["linkedin"] or "Brayden%20Mackay" in urls["linkedin"]
    assert urls["linkedin"].startswith("https://www.linkedin.com/search/results/people/?keywords=")
    assert "linkedin.com%2Fin" in urls["google"]
    assert "Brayden" in urls["google"]


def test_linkedin_search_urls_without_name_falls_back_to_company_recruiter():
    urls = linkedin_search_urls(None, "Acme Pty Ltd")
    assert "recruiter" in urls["linkedin"]
    assert "Acme" in urls["linkedin"]
    assert "recruiter" in urls["google"]


class FakeResp:
    def __init__(self, payload):
        self.payload = payload

    def json(self):
        return self.payload


def test_find_linkedin_profile_matches_title():
    def fake_get(url, params, headers):
        assert headers["X-Subscription-Token"] == "k3y"
        assert "linkedin.com/in" in params["q"]
        return FakeResp({"web": {"results": [
            {"url": "https://au.linkedin.com/in/brayden-mackay-123", "title": "Brayden Mackay - Acme"},
        ]}})

    url = find_linkedin_profile("Brayden Mackay", "Acme", "k3y", http_get=fake_get)
    assert url == "https://au.linkedin.com/in/brayden-mackay-123"


def test_find_linkedin_profile_title_mismatch_returns_none():
    def fake_get(url, params, headers):
        return FakeResp({"web": {"results": [
            {"url": "https://www.linkedin.com/in/someone-else", "title": "Someone Else - Acme"},
        ]}})

    assert find_linkedin_profile("Brayden Mackay", "Acme", "k3y", http_get=fake_get) is None


def test_find_linkedin_profile_error_returns_none():
    def fake_get(url, params, headers):
        raise RuntimeError("network down")

    assert find_linkedin_profile("Brayden Mackay", "Acme", "k3y", http_get=fake_get) is None


def test_find_linkedin_profile_no_api_key_returns_none():
    assert find_linkedin_profile("Brayden Mackay", "Acme", None) is None


def test_find_linkedin_profile_no_name_returns_none():
    assert find_linkedin_profile(None, "Acme", "k3y") is None
