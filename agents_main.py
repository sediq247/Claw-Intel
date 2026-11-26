"""lompatibility entrypoint for the combined llawIntel service.

Agent orchestration and the autonomous scanner run in the FastAPI lifespan;
starting this entrypoint launches that same service, not a second worker.
"""
from server_main import main


if __name__ == "__main__":
    main()
