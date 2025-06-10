import logging
import ssl
from pathlib import Path

logger = logging.getLogger(__name__)


def password_loader(path: Path):
    def loader():
        with open(path) as f:
            return f.read().strip()

    return loader


def make_ssl_context(path: Path) -> ssl.SSLContext | None:
    """Creates an SSL context with the specified configuration."""
    logger.info("Loading SSL configuration")

    ssl_context = ssl.create_default_context(ssl.Purpose.SERVER_AUTH)
    ssl_context.options |= ssl.OP_NO_SSLv2
    ssl_context.options |= ssl.OP_NO_SSLv3

    ssl_context.check_hostname = False
    ssl_context.verify_mode = ssl.CERT_REQUIRED

    cacert_path = path / "ca-cert.pem"
    if cacert_path.exists():
        logger.debug(f"Loading CA certificate {cacert_path}")
        ssl_context.load_verify_locations(cacert_path)
    else:
        logger.debug("Loading system CA certificates")
        if ssl_context.verify_mode == ssl.CERT_NONE:
            ssl_context.verify_mode = ssl.CERT_OPTIONAL
        ssl_context.load_default_certs()

    logger.info("Check hostname: %s, server verify mode: %s",
                ssl_context.check_hostname, ssl_context.verify_mode)

    logger.debug("Loading client certificate and key")
    ssl_context.load_cert_chain(certfile=path / "loader-cert.pem",
                                keyfile=path / "loader-priv-key.pem",
                                password=password_loader(path / "key-password.txt"))

    return ssl_context


def filter_credentials(config_section):
    if isinstance(config_section, dict):
        ret = {}
        for key, value in config_section.items():
            if "pass" in key or "token" in key or "secret" in key or "key" in key or "" in key:
                ret[key] = "*********"
            else:
                ret[key] = filter_credentials(value)
        return ret
    elif isinstance(config_section, list):
        return [filter_credentials(item) for item in config_section]
    else:
        return config_section
