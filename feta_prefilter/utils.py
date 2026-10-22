import logging
import ssl
import warnings
from pathlib import Path

import urllib3
from pymisp import PyMISP

logger = logging.getLogger(__name__)


def password_loader(path: Path):
    def loader():
        with open(path) as f:
            return f.read().strip()

    return loader


def make_ssl_context(ssl_config: dict[str, str]) -> ssl.SSLContext | None:
    """Creates an SSL context with the specified configuration."""
    logger.info("Loading SSL configuration")

    ssl_context = ssl.create_default_context(ssl.Purpose.SERVER_AUTH)
    ssl_context.options |= ssl.OP_NO_SSLv2
    ssl_context.options |= ssl.OP_NO_SSLv3

    ssl_context.check_hostname = False
    ssl_context.verify_mode = ssl.CERT_REQUIRED

    cacert_path = Path(ssl_config["ca_cert_file"])
    if cacert_path.exists():
        logger.debug(f"Loading CA certificate {cacert_path}")
        ssl_context.load_verify_locations(cacert_path)
    else:
        logger.debug("Loading system CA certificates")
        if ssl_context.verify_mode == ssl.CERT_NONE:
            ssl_context.verify_mode = ssl.CERT_OPTIONAL
        ssl_context.load_default_certs()

    logger.info(
        "Check hostname: %s, server verify mode: %s",
        ssl_context.check_hostname,
        ssl_context.verify_mode,
    )

    logger.debug("Loading client certificate and key")
    ssl_context.load_cert_chain(
        certfile=Path(ssl_config["cert_file"]),
        keyfile=Path(ssl_config["private_key_file"]),
        password=password_loader(Path(ssl_config["private_key_password_file"])),
    )

    return ssl_context


def misp_client(
    misp_url: str,
    misp_key: str,
    misp_ssl: bool | str = True,
    timeout: float | None = None,
) -> PyMISP:
    """Creates a PyMISP client that verifies the instance certificate by default.

    misp_ssl is passed straight to PyMISP: True = verify against the system CA store,
    a string = path to a CA bundle, False = no verification. requests installs an
    "always" filter for urllib3.SecurityWarning, so an unverified request logs a
    two-line warning on every call (that was ~100 % of the loader log); an explicit
    opt-out is therefore announced once and the warning is suppressed after that.
    """
    if misp_ssl is False:
        logger.warning(
            "TLS certificate verification disabled for MISP instance %s (misp_ssl=False),"
            " suppressing urllib3 InsecureRequestWarning",
            misp_url,
        )
        warnings.filterwarnings(
            "ignore", category=urllib3.exceptions.InsecureRequestWarning
        )

    return PyMISP(misp_url, misp_key, ssl=misp_ssl, timeout=timeout)


def filter_credentials(config_section):
    if isinstance(config_section, dict):
        ret = {}
        for key, value in config_section.items():
            if "pass" in key or "token" in key or "secret" in key or "key" in key:
                ret[key] = "*********"
            else:
                ret[key] = filter_credentials(value)
        return ret
    elif isinstance(config_section, list):
        return [filter_credentials(item) for item in config_section]
    else:
        return config_section
