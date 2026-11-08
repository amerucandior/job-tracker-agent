import json
from unittest.mock import MagicMock
from job_tracker_agent.ingestion.base import clean_html_to_text
from job_tracker_agent.ingestion.outlook import OutlookProvider


def test_clean_html_to_text():
    html = """
    <html>
        <head><style>body { color: red; }</style></head>
        <body>
            <h1>Thank you for applying to Stripe!</h1>
            <p>Dear Candidate,<br/>We have received your application for <strong>Senior Software Engineer</strong>.</p>
            <p>Next steps: please check our candidate portal.</p>
            <script>console.log("analytics");</script>
        </body>
    </html>
    """
    cleaned = clean_html_to_text(html)
    assert "body { color: red; }" not in cleaned
    assert "console.log" not in cleaned
    assert "Thank you for applying to Stripe!" in cleaned
    assert "Senior Software Engineer" in cleaned
    assert "Next steps: please check our candidate portal." in cleaned


def test_outlook_redeem_url(tmp_path, monkeypatch):
    monkeypatch.setattr("job_tracker_agent.ingestion.outlook.get_config_dir", lambda: tmp_path)
    monkeypatch.setattr("job_tracker_agent.ingestion.outlook.load_tokens", lambda: {})
    saved_tokens = {}
    monkeypatch.setattr("job_tracker_agent.ingestion.outlook.save_tokens", lambda t: saved_tokens.update(t))

    flow_path = tmp_path / "ms_flow.json"
    dummy_flow = {"state": "test_state_123", "code_verifier": "dummy_verifier"}
    flow_path.write_text(json.dumps(dummy_flow))

    mock_app = MagicMock()
    mock_app.acquire_token_by_auth_code_flow.return_value = {
        "access_token": "mock_token_xyz",
    }
    monkeypatch.setattr("msal.PublicClientApplication", lambda *args, **kwargs: mock_app)

    provider = OutlookProvider(client_id="dummy-client-id")
    provider._fetch_profile = MagicMock()

    redirect_url = "https://login.live.com/oauth20_desktop.srf?code=mock_code_abc&state=test_state_123"
    success = provider.redeem_url(redirect_url)

    assert success is True
    mock_app.acquire_token_by_auth_code_flow.assert_called_once()
    call_args = mock_app.acquire_token_by_auth_code_flow.call_args[0]
    assert call_args[0] == dummy_flow
    assert call_args[1]["code"] == "mock_code_abc"
    # Verify flow file was cleaned up on success
    assert not flow_path.exists()


