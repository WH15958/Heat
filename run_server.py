import asyncio

import uvicorn

from src.web.api.ws import data_push_loop


async def main():
    """启动Heat Web服务器"""
    config = uvicorn.Config(
        "src.web.app:app",
        host="0.0.0.0",
        port=8000,
        log_level="info",
        reload=False,
    )
    server = uvicorn.Server(config)

    async def start_push():
        await server.startup()
        if hasattr(server, "app") and hasattr(server.app, "state"):
            asyncio.create_task(data_push_loop(server.app))

    asyncio.create_task(start_push())
    await server.serve()


if __name__ == "__main__":
    uvicorn.run("src.web.app:app", host="0.0.0.0", port=8000, reload=True)
