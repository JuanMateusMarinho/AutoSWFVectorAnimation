"""The user's NVIDIA API (build.nvidia.com, OpenAI-compatible) for the AI features (Plan 7, spec §8.11): the key kept by
Windows' credential store (never in a file), the list of models, and a one-token check of the connection. The key
goes only into the Authorization header of requests to BASE_URL; it is never logged or shown in a message."""
import json
import urllib.error
import urllib.request
from dataclasses import dataclass

BASE_URL = "https://integrate.api.nvidia.com/v1"
KEYRING_SERVICE = "AutoSWF"
KEYRING_USER = "nvidia-api-key"
PREFERRED_MODEL = "nemotron-3.5-super-vl"
TIMEOUT_S = 15


def save_key(key: str) -> None:
    import keyring
    keyring.set_password(KEYRING_SERVICE, KEYRING_USER, key.strip())


def load_key() -> str | None:
    import keyring
    return keyring.get_password(KEYRING_SERVICE, KEYRING_USER)


def remove_key() -> None:
    import keyring
    import keyring.errors
    try:
        keyring.delete_password(KEYRING_SERVICE, KEYRING_USER)
    except keyring.errors.PasswordDeleteError:
        pass


def _request(key: str, url: str, body: dict | None = None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method="POST" if body is not None else "GET",
                                 headers={"Authorization": "Bearer " + key, "Accept": "application/json",
                                          **({"Content-Type": "application/json"} if body is not None else {})})
    with urllib.request.urlopen(req, timeout=TIMEOUT_S) as response:
        return json.loads(response.read().decode("utf-8") or "{}")


def list_models(key: str, *, base_url: str = BASE_URL) -> list[str]:
    data = _request(key, base_url.rstrip("/") + "/models")
    return sorted(str(m["id"]) for m in data.get("data", []) if isinstance(m, dict) and "id" in m)


def preferred_model(models: list[str]) -> str | None:
    return next((m for m in models if PREFERRED_MODEL in m), None)


@dataclass(frozen=True)
class ConnectionResult:
    kind: str                       # ok, bad_key, no_access, rate_limit, offline, error
    message: str


def check_connection(key: str, model: str, *, base_url: str = BASE_URL) -> ConnectionResult:
    """One tiny chat request to the model; what happened, in plain words (never with the key)."""
    body = {"model": model, "messages": [{"role": "user", "content": "ping"}], "max_tokens": 1}
    try:
        _request(key, base_url.rstrip("/") + "/chat/completions", body)
    except urllib.error.HTTPError as e:
        if e.code == 401:
            return ConnectionResult("bad_key", "The API key was refused. Check it at build.nvidia.com.")
        if e.code in (403, 404):
            return ConnectionResult("no_access", "This key cannot use %s." % model)
        if e.code == 429:
            return ConnectionResult("rate_limit", "NVIDIA is limiting requests right now; try again in a minute.")
        return ConnectionResult("error", "NVIDIA answered with an error (HTTP %d)." % e.code)
    except (urllib.error.URLError, TimeoutError, OSError):
        return ConnectionResult("offline", "No internet connection to NVIDIA.")
    except ValueError:
        return ConnectionResult("error", "NVIDIA answered with something that is not JSON.")
    return ConnectionResult("ok", "Connected to %s." % model)
