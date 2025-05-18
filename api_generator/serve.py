# serve.py

import uvicorn

if __name__ == "__main__":
    uvicorn.run(
        "api_generator.asgi_ws:application",
        host="127.0.0.1",
        port=8001,
        reload=True,
        # exclude all files…
        reload_excludes=["*"],
        # …but then re-include only migrations under dynamic_apps
        reload_includes=["dynamic_apps/*/migrations/*.py"],
        lifespan="on",
        log_level="info",
        workers=1
    )
