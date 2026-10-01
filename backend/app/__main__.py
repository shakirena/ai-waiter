"""``python -m app`` — запуск для режима single (служба Windows, #30) и для разработки.

Читает HOST/PORT/API_WORKERS из Settings. В single всегда один процесс (валидатор Settings).
"""

from __future__ import annotations


def main() -> None:
    """``uvicorn.run("app.main:create_app", factory=True, host=settings.host, port=settings.port,
    workers=settings.api_workers, log_config=None, proxy_headers=True)``.
    ``forwarded_allow_ips`` — только loopback (single: cloudflared на той же машине)."""
    raise NotImplementedError


if __name__ == "__main__":
    main()
