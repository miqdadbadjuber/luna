import os

# TestClient sends Host: testserver, which the host allowlist would reject.
os.environ.setdefault("LUNA_ALLOWED_HOSTS", "testserver")


def page_source(client):
    """The main page plus the CSS and JS files it loads, for string checks on the UI."""
    import re

    html = client.get("/").text
    parts = [html]
    for path in re.findall(r'"(/assets/ui/[^"?]+)', html):
        res = client.get(path)
        assert res.status_code == 200, path
        parts.append(res.text)
    return "\n".join(parts)
