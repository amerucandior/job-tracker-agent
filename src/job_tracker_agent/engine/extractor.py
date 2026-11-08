"""LLM Extractor for parsing job application emails into structured Pydantic models.

Supports cloud APIs (Gemini, OpenAI format) and local Ollama instances.
"""

import json
import logging
import os
import re
from typing import Optional
import requests
from pydantic import ValidationError

from job_tracker_agent.config import LLMConfig
from job_tracker_agent.models import ApplicationStage, EmailMessage, ExtractedApplication

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are an expert AI recruiting assistant analyzing incoming emails.
Your task is to extract structured hiring information from email correspondence.

CRITICAL INSTRUCTIONS:
1. Identify the ACTUAL hiring company or employer name, NOT the ATS vendor (e.g. if the email is from 'no-reply@greenhouse.io' or 'jobs@lever.co' regarding a position at 'Stripe', the company is 'Stripe').
2. Identify the specific job title or role.
3. Determine the hiring stage strictly from one of: Applied, Screening, Interview, Offer, Rejected, Archived.
   - Applied: Application confirmation / receipt acknowledged.
   - Screening: Initial recruiter screen, questionnaire, or introductory call invitation.
   - Interview: Technical interview, coding challenge, take-home test, or onsite.
   - Offer: Formal offer letter or offer conversation.
   - Rejected: Candidate not moving forward, rejection notice.
   - Archived: Ghosted, withdrawn, or expired.
4. Set 'is_job_application' to false if this email is a newsletter, job alert digest, promotional email, or not a direct interaction about a specific application.
5. Provide a clear, concise 1-2 sentence summary of what this specific email conveys.
6. List any immediate action items requested from the candidate (e.g. 'Select interview slot via Calendly link', 'Submit coding test by Friday').
7. Flag 'review_flag' as true if the email is ambiguous, unclear, or if you have low confidence in the company/stage.

Return ONLY valid JSON matching this schema:
{
  "is_job_application": bool,
  "company": str,
  "role": str,
  "stage": "Applied" | "Screening" | "Interview" | "Offer" | "Rejected" | "Archived",
  "confidence": float (0.0 to 1.0),
  "review_flag": bool,
  "summary": str,
  "action_items": [str],
  "interview_date": str or null
}
"""


class LLMExtractor:
    """Extracts structured job application updates from email content."""

    def __init__(self, config: Optional[LLMConfig] = None) -> None:
        self.config = config or LLMConfig()

    def extract(self, message: EmailMessage) -> Optional[ExtractedApplication]:
        """Invoke the configured LLM to extract hiring data from an EmailMessage."""
        prompt_text = (
            f"Sender: {message.sender_name or ''} <{message.sender_email}>\n"
            f"Subject: {message.subject}\n"
            f"Date: {message.received_at.isoformat()}\n\n"
            f"Body:\n{message.body_text[:4000]}"
        )

        provider = (self.config.provider or "gemini").lower()
        try:
            if provider == "ollama":
                raw_json = self._call_ollama(prompt_text)
            elif provider in ("openai", "claude"):
                raw_json = self._call_openai_compatible(prompt_text)
            else:
                # Default to Gemini API
                raw_json = self._call_gemini(prompt_text)

            if not raw_json:
                return self._fallback_error_extraction(message, "Empty response from LLM")

            return self._parse_json_to_model(raw_json, message)

        except Exception as e:
            logger.error(f"Error during LLM extraction: {e}")
            return self._fallback_error_extraction(message, str(e))

    def _call_gemini(self, content: str) -> Optional[str]:
        """Call Google Gemini API using REST endpoint."""
        api_key = self.config.api_key or os.environ.get("GEMINI_API_KEY")
        if not api_key:
            logger.warning("GEMINI_API_KEY not found in config or environment. Trying local Ollama fallback.")
            return self._call_ollama(content)

        model = self.config.model_name or "gemini-2.5-flash"
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"

        payload = {
            "contents": [
                {
                    "parts": [
                        {"text": SYSTEM_PROMPT},
                        {"text": content},
                    ]
                }
            ],
            "generationConfig": {
                "response_mime_type": "application/json",
                "temperature": 0.1,
            },
        }

        res = requests.post(url, json=payload, timeout=20)
        if res.status_code != 200:
            logger.error(f"Gemini API returned {res.status_code}: {res.text}")
            return None

        data = res.json()
        candidates = data.get("candidates", [])
        if candidates:
            parts = candidates[0].get("content", {}).get("parts", [])
            if parts:
                return parts[0].get("text")
        return None

    def _call_ollama(self, content: str) -> Optional[str]:
        """Call local Ollama server running on localhost:11434."""
        base_url = self.config.api_base or "http://localhost:11434"
        model = self.config.model_name or "llama3.1"
        url = f"{base_url}/api/chat"

        payload = {
            "model": model,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": content},
            ],
            "format": "json",
            "stream": False,
            "options": {"temperature": 0.1},
        }

        try:
            res = requests.post(url, json=payload, timeout=30)
            if res.status_code == 200:
                data = res.json()
                return data.get("message", {}).get("content")
            logger.error(f"Ollama server returned {res.status_code}: {res.text}")
        except Exception as e:
            logger.error(f"Could not connect to Ollama at {url}: {e}")
        return None

    def _call_openai_compatible(self, content: str) -> Optional[str]:
        """Call an OpenAI-compatible /v1/chat/completions endpoint."""
        api_key = self.config.api_key or os.environ.get("OPENAI_API_KEY", "")
        base_url = self.config.api_base or "https://api.openai.com/v1"
        model = self.config.model_name or "gpt-4o-mini"

        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": model,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": content},
            ],
            "response_format": {"type": "json_object"},
            "temperature": 0.1,
        }

        res = requests.post(f"{base_url}/chat/completions", headers=headers, json=payload, timeout=20)
        if res.status_code == 200:
            data = res.json()
            return data["choices"][0]["message"]["content"]
        return None

    def _parse_json_to_model(
        self, raw_json: str, message: EmailMessage
    ) -> ExtractedApplication:
        """Sanitize and parse JSON string into ExtractedApplication model."""
        # Strip code block markdown if model wrapped response in ```json ... ```
        cleaned = re.sub(r"^```(?:json)?\s*", "", raw_json.strip(), flags=re.MULTILINE)
        cleaned = re.sub(r"```$", "", cleaned.strip(), flags=re.MULTILINE)

        data = json.loads(cleaned)
        return ExtractedApplication.model_validate(data)

    def _fallback_error_extraction(
        self, message: EmailMessage, reason: str
    ) -> ExtractedApplication:
        """Create a safe fallback application flagged for review when LLM extraction fails."""
        company_guess = message.sender_email.split("@")[-1].split(".")[0].capitalize()
        return ExtractedApplication(
            is_job_application=True,
            company=company_guess,
            role="Unknown Role",
            stage=ApplicationStage.APPLIED,
            confidence=0.3,
            review_flag=True,
            summary=f"Automated parse failed ({reason}). Subject: {message.subject}",
            action_items=["Review email manually in inbox."],
            interview_date=None,
        )
