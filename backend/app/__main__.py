"""``python -m app`` — запуск для режима single (служба Windows, #30) и для разработки.

Читает HOST/PORT/API_WORKERS из Settings. В single всегда один процесс (валидатор Settings).
"""

from __future__ import annotations

import uvicorn

from app.core.config import ConfigError, get_settings

# Заголовки X-Forwarded-* принимаются только от прокси на той же машине
# (single: cloudflared; scaled: Caddy проксирует в контейнер через свою сеть, см. #36).
TRUSTED_PROXY_IPS = "127.0.0.1,::1"


def main() -> None:
    """``uvicorn.run("app.main:create_app", factory=True, host=settings.host, port=settings.port,
    workers=settings.api_workers, log_config=None, proxy_headers=True)``.
    ``forwarded_allow_ips`` — только loopback (single: cloudflared на той же машине)."""
    try:
        settings = get_settings()
    except ConfigError as exc:
        # SystemExit со строкой: текст в stderr, код возврата 1, без трассировки.
        raise SystemExit(str(exc)) from None

    uvicorn.run(
        "app.main:create_app",
        factory=True,
        host=settings.host,
        port=settings.port,
        workers=settings.api_workers,
        log_config=None,
        proxy_headers=True,
        forwarded_allow_ips=TRUSTED_PROXY_IPS,
    )


if __name__ == "__main__":
    main()
