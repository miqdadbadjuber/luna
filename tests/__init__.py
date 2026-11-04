import os

# TestClient sends Host: testserver, which the host allowlist would reject.
os.environ.setdefault("LUNA_ALLOWED_HOSTS", "testserver")
