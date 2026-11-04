# Contributing to Luna

Thanks for taking a look. Bug reports, fixes, and small focused features are all welcome.

## Before you start

- Open an issue for anything larger than a typo or a one-file fix, so we do not build the same thing twice.
- Do not include API keys, cookies, or downloaded media in a commit, an issue, or a screenshot.
- Keep the scope of a pull request to the thing it says it does. Separate refactors from fixes.

## Development

```bash
python -m venv .venv
.venv/bin/pip install -r requirements-dev.txt     # Windows: .venv\Scripts\pip
python -m unittest discover -v
```

The suite must pass before a pull request is reviewed. It has no network tests; anything that needs yt-dlp, ffmpeg, or a provider must be faked or skipped, not called live.

Style follows the surrounding file: type hints where they already exist, no new dependencies without a reason in the pull request, and comments that explain why rather than what.

## Sign-off (DCO)

Every commit needs a `Signed-off-by` line, which certifies you wrote the change or have the right to submit it. Git adds it for you:

```bash
git commit -s -m "Describe the change"
```

That produces:

```
Signed-off-by: Your Name <you@example.com>
```

Use your real name and a reachable address. By signing off you agree to the [Developer Certificate of Origin 1.1](https://developercertificate.org/).

## License of contributions

Luna is licensed under the GNU Affero General Public License, version 3 or later. By submitting a contribution you license it to everyone under those terms.

You also grant the maintainer a perpetual, worldwide, non-exclusive, royalty-free right to relicense your contribution, including under a commercial license. That is what keeps dual licensing possible: without it, one contribution would block a commercial license forever. If you are not comfortable with that, open an issue first and we can talk about it before you write code.

## Reporting a security issue

Do not open a public issue for a vulnerability. Use GitHub's private vulnerability reporting on the repository instead, and include the version, the steps, and what an attacker gains.
