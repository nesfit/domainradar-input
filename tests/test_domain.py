from feta_prefilter.domain import canonical_domain, host_from_url


def test_lowercases_and_strips_a_trailing_dot():
    assert canonical_domain("Example.COM.") == "example.com"


def test_url_with_userinfo_port_and_path_keeps_only_the_host():
    assert canonical_domain("http://user@evil.example:8080/login?x=1") == "evil.example"


def test_bare_host_with_port_and_path():
    assert canonical_domain("evil.example:8080/path") == "evil.example"


def test_idn_is_converted_to_punycode():
    canonical = canonical_domain("Žluťoučký.example")
    assert canonical is not None
    assert canonical.startswith("xn--") and canonical.endswith(".example")


def test_empty_and_malformed_values_return_none():
    assert canonical_domain("") is None
    assert canonical_domain("   ") is None
    assert canonical_domain(None) is None


def test_host_from_url_accepts_scheme_less_values():
    assert host_from_url("evil.example/x") == "evil.example"
    assert host_from_url("http://u:p@evil.example:81/x") == "evil.example"
    assert host_from_url("") is None
