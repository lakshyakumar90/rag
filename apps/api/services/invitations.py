"""Workspace invitation email delivery via Resend API or SMTP."""

from __future__ import annotations

import logging
import smtplib
from email.message import EmailMessage

import httpx

from core.config import get_settings

logger = logging.getLogger(__name__)


class InvitationEmailService:
    """Delivers workspace invitation links via Resend or SMTP."""

    def __init__(self, http_client: httpx.AsyncClient | None = None) -> None:
        self._client = http_client

    async def send_invite(
        self,
        *,
        to_email: str,
        workspace_name: str,
        inviter_email: str,
        accept_url: str,
    ) -> bool:
        settings = get_settings()
        subject = f"You're invited to join {workspace_name} on RAG Workspace"
        html_body = (
            f"<p>{inviter_email} invited you to join <strong>{workspace_name}</strong> "
            f"on RAG Workspace.</p>"
            f'<p><a href="{accept_url}">Accept Invitation</a></p>'
            f"<p>If the button doesn't work, copy this link: {accept_url}</p>"
        )
        text_body = (
            f"{inviter_email} invited you to {workspace_name} on RAG Workspace.\n\n"
            f"Accept your invitation: {accept_url}\n"
        )

        if settings.resend_api_key:
            return await self._send_via_resend(
                api_key=settings.resend_api_key,
                from_addr=settings.email_from,
                to_email=to_email,
                subject=subject,
                html_body=html_body,
                text_body=text_body,
            )

        if settings.smtp_host:
            return self._send_via_smtp(
                host=settings.smtp_host,
                port=settings.smtp_port,
                username=settings.smtp_username,
                password=settings.smtp_password,
                from_addr=settings.email_from,
                to_email=to_email,
                subject=subject,
                text_body=text_body,
            )

        logger.info(
            "Email delivery not configured; invite link for %s: %s",
            to_email,
            accept_url,
        )
        return False

    async def _send_via_resend(
        self,
        *,
        api_key: str,
        from_addr: str,
        to_email: str,
        subject: str,
        html_body: str,
        text_body: str,
    ) -> bool:
        payload = {
            "from": from_addr,
            "to": [to_email],
            "subject": subject,
            "html": html_body,
            "text": text_body,
        }
        headers = {"Authorization": f"Bearer {api_key}"}
        owns = self._client is None
        client = self._client or httpx.AsyncClient(timeout=15.0)
        try:
            resp = await client.post(
                "https://api.resend.com/emails", json=payload, headers=headers
            )
            resp.raise_for_status()
            return True
        except Exception as exc:
            logger.warning("Resend email delivery failed for %s: %s", to_email, exc)
            return False
        finally:
            if owns:
                await client.aclose()

    @staticmethod
    def _send_via_smtp(
        *,
        host: str,
        port: int,
        username: str | None,
        password: str | None,
        from_addr: str,
        to_email: str,
        subject: str,
        text_body: str,
    ) -> bool:
        msg = EmailMessage()
        msg["From"] = from_addr
        msg["To"] = to_email
        msg["Subject"] = subject
        msg.set_content(text_body)
        try:
            with smtplib.SMTP(host, port, timeout=15) as server:
                if username and password:
                    server.starttls()
                    server.login(username, password)
                server.send_message(msg)
            return True
        except Exception as exc:
            logger.warning("SMTP email delivery failed for %s: %s", to_email, exc)
            return False
