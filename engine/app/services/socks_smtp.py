from __future__ import annotations

import smtplib
import socks


class SocksSMTP(smtplib.SMTP):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._proxy_addr = None
        self._proxy_port = None

    def set_proxy(self, addr: str, port: int) -> None:
        self._proxy_addr = addr
        self._proxy_port = port

    def _get_socket(self, host, port, timeout):
        if not self._proxy_addr:
            return super()._get_socket(host, port, timeout)
        s = socks.socksocket()
        s.set_proxy(socks.SOCKS5, self._proxy_addr, int(self._proxy_port or 1080))
        s.settimeout(timeout)
        s.connect((host, port))
        return s
