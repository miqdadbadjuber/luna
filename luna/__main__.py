import uvicorn

# Deliberately does not import luna.app: the reloader parent must not load .env into its
# environment, or workers inherit stale values and an edited .env never takes effect.
uvicorn.run("luna.app:app", host="localhost", port=8000, reload=True, reload_dirs=["luna"])
