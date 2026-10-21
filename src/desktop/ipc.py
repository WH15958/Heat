"""Authenticated, bounded JSON messages over Windows named pipes (no pickle)."""
import hmac
import json
import secrets
from multiprocessing.connection import Client, Listener
import threading

from src.desktop.common import ipc_token, pipe_address


MAX_MESSAGE = 65536


def _encode(value):
    return json.dumps(value, ensure_ascii=False).encode("utf-8")


def _receive(connection, timeout):
    if not connection.poll(timeout):
        raise TimeoutError("Heat 后台响应超时；不会自动重复控制请求。")
    message = json.loads(connection.recv_bytes(MAX_MESSAGE))
    if not isinstance(message, dict):
        raise ValueError("无效的桌面响应。")
    return message


def _proof(token, role, client_nonce, server_nonce, command="", instance_id=""):
    payload = _encode([role, client_nonce, server_nonce, command, instance_id])
    return hmac.new(bytes.fromhex(token), payload, "sha256").hexdigest()


def request(home, role, command, timeout=3.0, *, instance_id=""):
    # Pipe Client fails immediately when no server exists; all responses are bounded.
    with Client(pipe_address(home, role), family="AF_PIPE") as connection:
        token, nonce = ipc_token(home), secrets.token_hex(32)
        connection.send_bytes(_encode({"nonce": nonce}))
        challenge = _receive(connection, timeout)
        server_nonce, proof = challenge.get("nonce", ""), challenge.get("proof", "")
        if (not isinstance(server_nonce, str) or len(server_nonce) != 64
                or not isinstance(proof, str) or not hmac.compare_digest(
                    proof, _proof(token, "server", nonce, server_nonce))):
            raise RuntimeError("无法确认 Heat 后台身份。")
        connection.send_bytes(_encode({"command": command, "instance_id": instance_id,
            "proof": _proof(token, "client", nonce, server_nonce, command, instance_id)}))
        result = _receive(connection, timeout)
        if result.get("error"):
            raise RuntimeError(result["error"])
        return result["result"]


class PipeServer:
    def __init__(self, home, role, handler):
        self.home, self.role, self.handler = home, role, handler
        self.token = ipc_token(home)
        self.listener = Listener(pipe_address(home, role), family="AF_PIPE")
        self.closed = threading.Event()
        self.thread = threading.Thread(target=self._serve, daemon=True)

    def start(self):
        self.thread.start()

    def _serve(self):
        while not self.closed.is_set():
            try:
                connection = self.listener.accept()
            except (OSError, EOFError):
                return
            if self.closed.is_set():
                connection.close()
                break
            threading.Thread(target=self._handle, args=(connection,), daemon=True).start()

    def _handle(self, connection):
        with connection:
            try:
                hello = _receive(connection, 3)
                nonce = hello.get("nonce")
                if not isinstance(nonce, str) or len(nonce) != 64:
                    return
                server_nonce = secrets.token_hex(32)
                connection.send_bytes(_encode({"nonce": server_nonce, "proof":
                    _proof(self.token, "server", nonce, server_nonce)}))
                message = _receive(connection, 3)
                command, instance_id = message.get("command"), message.get("instance_id", "")
                if not isinstance(command, str) or not isinstance(instance_id, str):
                    raise ValueError("无效的桌面命令。")
                proof = message.get("proof", "")
                if not isinstance(proof, str) or not hmac.compare_digest(proof,
                        _proof(self.token, "client", nonce, server_nonce, command, instance_id)):
                    return
                try:
                    result = self.handler(command, instance_id) if self.role == "backend" else self.handler(command)
                    response = {"authenticated": True, "result": result}
                except Exception as exc:
                    response = {"authenticated": True, "error": str(exc)}
                connection.send_bytes(_encode(response))
            except (OSError, EOFError, ValueError, TypeError):
                return

    def close(self):
        self.closed.set()
        if self.thread.ident is None:
            self.listener.close()
            return
        try:
            with Client(pipe_address(self.home, self.role), family="AF_PIPE"):
                pass
        except OSError:
            pass
        self.thread.join(timeout=2)
        self.listener.close()
