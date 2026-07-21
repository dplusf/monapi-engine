from __future__ import annotations

import random
import smtplib
import string
from dataclasses import dataclass

from app.core.config import Settings
from app.services.socks_smtp import SocksSMTP


@dataclass
class SmtpResult:
    attempted: bool
    code: int | None
    message: str | None


def random_user(length: int = 10) -> str:
    letters = string.ascii_lowercase
    return "".join(random.choice(letters) for _ in range(length))


def smtp_rcpt_probe(settings: Settings, mx_host: str, rcpt: str) -> SmtpResult:
    if not settings.smtp_enabled:
        return SmtpResult(attempted=False, code=None, message=None)

    smtp_cls = SocksSMTP if settings.smtp_socks_enabled else smtplib.SMTP

    try:
        with smtp_cls(timeout=settings.smtp_timeout_seconds) as server:
            if settings.smtp_socks_enabled and isinstance(server, SocksSMTP):
                server.set_proxy(settings.smtp_proxy_addr, settings.smtp_proxy_port)

            server.connect(mx_host, 25)
            server.helo(settings.smtp_helo_host)
            server.mail(settings.smtp_mail_from)
            code, msg = server.rcpt(rcpt)
            try:
                message = msg.decode("utf-8", errors="ignore") if isinstance(msg, (bytes, bytearray)) else str(msg)
            except Exception:
                message = str(msg)
            return SmtpResult(attempted=True, code=int(code) if code is not None else None, message=message)
    except Exception as e:
        return SmtpResult(attempted=True, code=None, message=str(e))
