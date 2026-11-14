"""Compatibility entrypoint for the FastAPI service.

The autonomous scan worker is owned by the ASGI lifespan so it shares the
database and event publisher with the API process.
"""
import os
import uvicorn


def main():
    uvicorn.run("backend.app.main:app", host="0.0.0.0", port=int(os.getenv("PORT", "8000")))


if __name__ == "__main__":
    main()
