from __future__ import annotations

import json
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import ClassVar

import pytest

from verigym.runtimes.docker.control_plane_environment import (
    ControlPlaneEnvironmentError,
    build_trusted_host_app_server_environment,
)

BROKER_URL = "ws://127.0.0.1:32123/verigym-test"


def _source(**updates: str) -> dict[str, str]:
    values = {
        "HOME": "/safe-home",
        "PATH": "/usr/local/bin:/usr/bin:/bin",
    }
    values.update(updates)
    return values


@pytest.mark.parametrize(
    ("source", "forwarded_names", "expected_forwarded", "preserved_bypass"),
    [
        (_source(), (), (), ()),
        (_source(HTTP_PROXY="http://proxy.invalid:8080"), ("HTTP_PROXY",), ("HTTP_PROXY",), ()),
        (
            _source(HTTPS_PROXY="http://proxy.invalid:8443"),
            ("HTTPS_PROXY",),
            ("HTTPS_PROXY",),
            (),
        ),
        (
            _source(
                HTTP_PROXY="http://proxy.invalid:8080",
                HTTPS_PROXY="http://proxy.invalid:8443",
            ),
            ("HTTP_PROXY", "HTTPS_PROXY"),
            ("HTTP_PROXY", "HTTPS_PROXY"),
            (),
        ),
        (
            _source(
                HTTP_PROXY="http://proxy.invalid:8080",
                NO_PROXY="corp.invalid,localhost",
            ),
            ("HTTP_PROXY",),
            ("HTTP_PROXY",),
            ("corp.invalid",),
        ),
        (
            _source(
                HTTP_PROXY="http://proxy.invalid:8080",
                NO_PROXY="corp.invalid,localhost,127.0.0.1,::1",
            ),
            ("HTTP_PROXY",),
            ("HTTP_PROXY",),
            ("corp.invalid",),
        ),
        (
            _source(
                HTTP_PROXY="http://proxy.invalid:8080",
                http_proxy="http://ignored-lower.invalid:9000",
                https_proxy="http://ignored-lower.invalid:9443",
                no_proxy="ignored.lower.invalid",
                ALL_PROXY="http://ignored-all.invalid:1080",
                all_proxy="http://ignored-all-lower.invalid:1080",
            ),
            ("HTTP_PROXY",),
            ("HTTP_PROXY",),
            (),
        ),
    ],
)
def test_proxy_matrix_synthesizes_mandatory_loopback_bypass(
    source: dict[str, str],
    forwarded_names: tuple[str, ...],
    expected_forwarded: tuple[str, ...],
    preserved_bypass: tuple[str, ...],
) -> None:
    result = build_trusted_host_app_server_environment(
        allow_proxy_environment=True,
        forwarded_proxy_environment_names=forwarded_names,
        broker_url=BROKER_URL,
        source=source,
    )

    assert result.forwarded_proxy_environment_names == expected_forwarded
    assert result.synthesized_control_plane_environment_names == (
        "NO_PROXY",
        "no_proxy",
    )
    assert result.mandatory_loopback_bypass_present
    assert result.values["NO_PROXY"] == result.values["no_proxy"]
    bypass = {entry.casefold() for entry in result.values["NO_PROXY"].split(",")}
    assert {"localhost", "127.0.0.1", "::1"} <= bypass
    assert set(preserved_bypass) <= bypass
    assert {
        "http_proxy",
        "https_proxy",
        "ALL_PROXY",
        "all_proxy",
    }.isdisjoint(result.values)


def test_disabled_proxy_forwarding_has_no_proxy_environment_names() -> None:
    result = build_trusted_host_app_server_environment(
        allow_proxy_environment=False,
        forwarded_proxy_environment_names=(),
        broker_url=BROKER_URL,
        source=_source(
            HTTP_PROXY="http://ignored.invalid:8080",
            HTTPS_PROXY="http://ignored.invalid:8443",
            NO_PROXY="corp.invalid",
            http_proxy="http://ignored-lower.invalid:8080",
            ALL_PROXY="http://ignored-all.invalid:1080",
        ),
    )

    assert result.forwarded_proxy_environment_names == ()
    assert result.synthesized_control_plane_environment_names == ()
    assert result.mandatory_loopback_bypass_present
    assert {
        "HTTP_PROXY",
        "HTTPS_PROXY",
        "NO_PROXY",
        "http_proxy",
        "https_proxy",
        "no_proxy",
        "ALL_PROXY",
        "all_proxy",
    }.isdisjoint(result.values)


def test_credential_bearing_proxy_values_are_absent_from_safe_identity() -> None:
    proxy = "http://proxy-user:proxy-password@proxy.invalid:8080"
    host_bypass = "private.invalid,localhost"
    result = build_trusted_host_app_server_environment(
        allow_proxy_environment=True,
        forwarded_proxy_environment_names=("HTTP_PROXY",),
        broker_url=BROKER_URL,
        source=_source(HTTP_PROXY=proxy, NO_PROXY=host_bypass),
    )

    serialized = json.dumps(result.safe_identity(), sort_keys=True)
    assert proxy not in serialized
    assert "proxy-password" not in serialized
    assert host_bypass not in serialized
    assert result.safe_identity()["proxy_values_persisted_or_hashed"] is False


@pytest.mark.parametrize(
    ("broker_url", "reason"),
    [
        ("ws://localhost:32123/test", "control_plane_broker_identity_invalid"),
        ("ws://127.0.0.1/test", "control_plane_broker_identity_invalid"),
        ("wss://127.0.0.1:32123/test", "control_plane_broker_identity_invalid"),
        (
            "ws://user:password@127.0.0.1:32123/test",
            "control_plane_broker_identity_invalid",
        ),
    ],
)
def test_broker_identity_fails_closed_before_process_launch(
    broker_url: str,
    reason: str,
) -> None:
    with pytest.raises(ControlPlaneEnvironmentError) as observed:
        build_trusted_host_app_server_environment(
            allow_proxy_environment=True,
            forwarded_proxy_environment_names=(),
            broker_url=broker_url,
            source=_source(),
        )
    assert observed.value.reason == reason
    assert "password" not in str(observed.value)


def test_malformed_host_no_proxy_fails_without_exposing_its_value() -> None:
    unsafe = "private.invalid\ncredential-marker"
    with pytest.raises(ControlPlaneEnvironmentError) as observed:
        build_trusted_host_app_server_environment(
            allow_proxy_environment=True,
            forwarded_proxy_environment_names=("HTTP_PROXY",),
            broker_url=BROKER_URL,
            source=_source(HTTP_PROXY="http://proxy.invalid:8080", NO_PROXY=unsafe),
        )
    assert observed.value.reason == "control_plane_loopback_bypass_unavailable"
    assert unsafe not in str(observed.value)


class _DirectHandler(BaseHTTPRequestHandler):
    def log_message(self, _format: str, *_args: object) -> None:
        return

    def do_GET(self) -> None:  # noqa: N802
        body = b"direct"
        self.send_response(200)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


class _ProxyHandler(BaseHTTPRequestHandler):
    requests: ClassVar[list[str]] = []

    def log_message(self, _format: str, *_args: object) -> None:
        return

    def do_GET(self) -> None:  # noqa: N802
        self.requests.append(self.path)
        body = b"proxied"
        self.send_response(200)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def test_non_loopback_http_proxy_behavior_remains_intact() -> None:
    direct = ThreadingHTTPServer(("127.0.0.1", 0), _DirectHandler)
    proxy = ThreadingHTTPServer(("127.0.0.1", 0), _ProxyHandler)
    threads = [
        threading.Thread(target=direct.serve_forever, daemon=True),
        threading.Thread(target=proxy.serve_forever, daemon=True),
    ]
    for thread in threads:
        thread.start()
    _ProxyHandler.requests = []
    proxy_url = f"http://127.0.0.1:{proxy.server_address[1]}"
    result = build_trusted_host_app_server_environment(
        allow_proxy_environment=True,
        forwarded_proxy_environment_names=("HTTP_PROXY",),
        broker_url=BROKER_URL,
        source=_source(HTTP_PROXY=proxy_url),
    )
    script = (
        "import sys, urllib.request; "
        "sys.stdout.buffer.write(urllib.request.urlopen(sys.argv[1], timeout=3).read())"
    )
    try:
        direct_url = f"http://127.0.0.1:{direct.server_address[1]}/direct"
        direct_result = subprocess.run(
            [sys.executable, "-c", script, direct_url],
            env=result.values,
            check=True,
            capture_output=True,
            timeout=10,
        )
        non_loopback_result = subprocess.run(
            [sys.executable, "-c", script, "http://provider.invalid/v1"],
            env=result.values,
            check=True,
            capture_output=True,
            timeout=10,
        )
    finally:
        direct.shutdown()
        direct.server_close()
        proxy.shutdown()
        proxy.server_close()
    assert direct_result.stdout == b"direct"
    assert non_loopback_result.stdout == b"proxied"
    assert _ProxyHandler.requests == ["http://provider.invalid/v1"]
