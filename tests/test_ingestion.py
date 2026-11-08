from job_tracker_agent.ingestion.base import clean_html_to_text


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
