import signal
import uvicorn


def main():
    """启动Heat Web服务器"""
    try:
        signal.signal(signal.SIGINT, signal.default_int_handler)
    except (OSError, ValueError):
        pass
    uvicorn.run("src.web.app:app", host="0.0.0.0", port=8000, reload=False)


if __name__ == "__main__":
    main()
