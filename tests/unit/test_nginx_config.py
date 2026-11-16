from pathlib import Path


NGINX_CONFIG = Path(__file__).parents[2] / ".docker" / "app" / "nginx.conf"


def _location_block(config: str, path: str) -> str:
    start = config.index(f"location {path} {{")
    end = config.index("\n    }", start)
    return config[start:end]


_PUBLIC_PATHS = ("/feeds/", "/iptv/", "/webdav/")


def test_public_feed_routes_are_proxied_to_backend():
    config = NGINX_CONFIG.read_text()

    for path in _PUBLIC_PATHS:
        block = _location_block(config, path)
        assert "proxy_pass http://127.0.0.1:5001;" in block
        assert "try_files" not in block


def test_public_feed_location_is_not_left_to_spa_fallback():
    config = NGINX_CONFIG.read_text()

    for path in _PUBLIC_PATHS:
        assert config.index(f"location {path} {{") < config.index("location / {")



def test_proxy_preserves_outer_forwarded_https_scheme():
    config = NGINX_CONFIG.read_text()

    assert "map $http_x_forwarded_proto $vodloft_forwarded_proto {" in config
    assert '"" $scheme;' in config

    for path in ("/api/", *_PUBLIC_PATHS):
        block = _location_block(config, path)
        assert (
            "proxy_set_header X-Forwarded-Proto "
            "$vodloft_forwarded_proto;"
        ) in block
