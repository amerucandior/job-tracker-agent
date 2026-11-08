from datetime import datetime, timezone
import pytest
from job_tracker_agent.engine.filter import HeuristicPreFilter
from job_tracker_agent.engine.extractor import LLMExtractor
from job_tracker_agent.models import EmailMessage, IngestionProvider, ApplicationStage


def test_heuristic_pre_filter():
    screener = HeuristicPreFilter()

    # 1. ATS domain email
    ats_msg = EmailMessage(
        account_id="test@test.com",
        message_id="1",
        thread_id="t1",
        provider=IngestionProvider.GMAIL,
        sender_email="no-reply@greenhouse.io",
        subject="Your application to Acme Corp",
        received_at=datetime.now(timezone.utc),
        body_text="Thank you for applying to Acme Corp.",
    )
    assert screener.is_candidate_email(ats_msg) is True

    # 2. Recruiter keyword email from custom domain
    recruiter_msg = EmailMessage(
        account_id="test@test.com",
        message_id="2",
        thread_id="t2",
        provider=IngestionProvider.OUTLOOK,
        sender_email="sarah.connor@cyberdyne.systems",
        subject="Invitation to interview for Senior Systems Architect",
        received_at=datetime.now(timezone.utc),
        body_text="Hi, we would love to schedule a phone screen next week.",
    )
    assert screener.is_candidate_email(recruiter_msg) is True

    # 3. Non-recruiting newsletter
    newsletter_msg = EmailMessage(
        account_id="test@test.com",
        message_id="3",
        thread_id="t3",
        provider=IngestionProvider.GMAIL,
        sender_email="news@techweekly.com",
        subject="Top 10 gadgets of 2026",
        received_at=datetime.now(timezone.utc),
        body_text="Check out these new devices launching this month.",
    )
    assert screener.is_candidate_email(newsletter_msg) is False

    # 4. Ignored system sender (GitHub issue notification mentioning application)
    github_msg = EmailMessage(
        account_id="test@test.com",
        message_id="4",
        thread_id="t4",
        provider=IngestionProvider.OUTLOOK,
        sender_email="notifications@github.com",
        subject="Re: Facilitate external configuration (multiple application.yaml)",
        received_at=datetime.now(timezone.utc),
        body_text="Issue #51933 has been updated.",
    )
    assert screener.is_candidate_email(github_msg) is False


def test_llm_extractor_json_parsing():
    extractor = LLMExtractor()
    msg = EmailMessage(
        account_id="test@test.com",
        message_id="1",
        thread_id="t1",
        provider=IngestionProvider.GMAIL,
        sender_email="no-reply@greenhouse.io",
        subject="Interview with Stripe",
        received_at=datetime.now(timezone.utc),
        body_text="We would like to invite you to an interview.",
    )

    mock_json = """
    ```json
    {
      "is_job_application": true,
      "company": "Stripe",
      "role": "Backend Engineer",
      "stage": "Interview",
      "confidence": 0.95,
      "review_flag": false,
      "summary": "Stripe reached out to schedule a technical interview.",
      "action_items": ["Click Calendly link to pick a slot"],
      "interview_date": "2026-11-15T14:00:00Z"
    }
    ```
    """
    extracted = extractor._parse_json_to_model(mock_json, msg)
    assert extracted.is_job_application is True
    assert extracted.company == "Stripe"
    assert extracted.role == "Backend Engineer"
    assert extracted.stage == ApplicationStage.INTERVIEW
    assert extracted.confidence == 0.95
    assert extracted.review_flag is False
    assert len(extracted.action_items) == 1
