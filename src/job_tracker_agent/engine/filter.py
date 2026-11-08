"""Heuristic pre-filter for recruiting and applicant tracking system emails.

Adheres to CONTEXT.md Heuristic Pre-filter definition.
"""

import re
from job_tracker_agent.models import EmailMessage

# Recognized Applicant Tracking System (ATS) domains and subdomains
KNOWN_ATS_DOMAINS = {
    "greenhouse.io",
    "gh.io",
    "lever.co",
    "ashbyhq.com",
    "myworkday.com",
    "workday.com",
    "smartrecruiters.com",
    "icims.com",
    "bamboohr.com",
    "rippling-ats.com",
    "rippling.com",
    "taleo.net",
    "jobvite.com",
    "workable.com",
    "recruitee.com",
    "pinpointhq.com",
    "breezy.hr",
    "jazzhr.com",
    "successfactors.com",
    "hirevue.com",
    "codility.com",
    "hackerrank.net",
    "karat.com",
    "interviewing.io",
}

# Regex patterns matching recruiting email subjects
RECRUITING_SUBJECT_PATTERNS = [
    r"\b(application|applied|candidacy|candidate)\b",
    r"\b(interview|screening|phone screen|chat with|technical screen)\b",
    r"\b(job offer|offer letter|welcome to the team)\b",
    r"\b(coding challenge|take-home|assessment|technical evaluation)\b",
    r"\b(thank you for (applying|your interest)|status of your application)\b",
    r"\b(next steps with|following up on your application)\b",
    r"\b(update regarding your application|update on your candidacy)\b",
    r"\b(moving forward|decision on your application)\b",
]

# Keywords suggesting recruiter sender handles
RECRUITER_HANDLE_PATTERNS = [
    r"\b(talent|recruiting|recruiter|careers|jobs|hiring|people-ops|talentacquisition)\b",
]

# Strong body keywords indicating hiring decisions or next steps
STRONG_BODY_KEYWORDS = [
    r"thank you for taking the time to apply",
    r"we have received your application",
    r"we reviewed your resume and would like to invite you",
    r"invitation to interview",
    r"schedule a (call|phone screen|conversation)",
    r"pleased to offer you the position",
    r"we will not be moving forward with your candidacy",
    r"decided to pursue other candidates",
    r"regret to inform you",
]


class HeuristicPreFilter:
    """Evaluates whether an email is likely related to a job application before invoking an LLM."""

    def __init__(self) -> None:
        self.subject_regex = re.compile("|".join(RECRUITING_SUBJECT_PATTERNS), re.IGNORECASE)
        self.handle_regex = re.compile("|".join(RECRUITER_HANDLE_PATTERNS), re.IGNORECASE)
        self.body_regex = re.compile("|".join(STRONG_BODY_KEYWORDS), re.IGNORECASE)

    def is_candidate_email(self, message: EmailMessage) -> bool:
        """Return True if message passes ATS domain or recruitment heuristic rules."""
        sender_email = message.sender_email.lower()
        domain = sender_email.split("@")[-1] if "@" in sender_email else ""

        # 1. Direct match on recognized ATS provider domain
        for ats_domain in KNOWN_ATS_DOMAINS:
            if domain == ats_domain or domain.endswith("." + ats_domain):
                return True

        # 2. Subject regex match
        if self.subject_regex.search(message.subject):
            return True

        # 3. Recruiter sender handle + body keyword match
        sender_handle = sender_email.split("@")[0] if "@" in sender_email else ""
        if self.handle_regex.search(sender_handle):
            if self.body_regex.search(message.body_text[:1500]):
                return True

        # 4. Strong body phrasing match
        if self.body_regex.search(message.body_text[:1500]):
            return True

        return False
