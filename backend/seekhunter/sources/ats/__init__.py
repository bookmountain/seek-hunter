"""Company Radar ATS clients (see base.py for the shared interface)."""

from seekhunter.http import PoliteClient
from seekhunter.sources.ats.ashby import AshbyClient
from seekhunter.sources.ats.base import ATSClient, ATSError, is_australian
from seekhunter.sources.ats.greenhouse import GreenhouseClient
from seekhunter.sources.ats.lever import LeverClient
from seekhunter.sources.ats.smartrecruiters import SmartRecruitersClient
from seekhunter.sources.ats.workable import WorkableClient
from seekhunter.sources.ats.workday import WorkdayClient

# ATS kinds the radar polls itself; "pageup" / "other" careers pages are left to changedetection.io.
POLLED_ATS = ("greenhouse", "lever", "ashby", "workable", "smartrecruiters", "workday")
ATS_KINDS = (*POLLED_ATS, "pageup", "other")


def radar_http_client() -> PoliteClient:
    """1-2 s between requests (these are small public JSON APIs); a short single backoff so one
    rate-limited board doesn't stall the whole 30-minute poll."""
    return PoliteClient(min_delay=1.0, max_delay=2.0, backoffs=(10.0,))


def build_ats_clients(client=None) -> dict[str, ATSClient]:  # noqa: ANN001
    client = client or radar_http_client()
    return {
        "greenhouse": GreenhouseClient(client),
        "lever": LeverClient(client),
        "ashby": AshbyClient(client),
        "workable": WorkableClient(client),
        "smartrecruiters": SmartRecruitersClient(client),
        "workday": WorkdayClient(client),
    }


__all__ = ["ATS_KINDS", "ATSClient", "ATSError", "POLLED_ATS", "build_ats_clients", "is_australian",
           "radar_http_client"]
