import uvicorn


def main():
    """启动Heat Web服务器"""
    uvicorn.run("src.web.app:app", host="0.0.0.0", port=8000, log_level="info")


if __name__ == "__main__":
    uvicorn.run("src.web.app:app", host="0.0.0.0", port=8000, reload=True)
