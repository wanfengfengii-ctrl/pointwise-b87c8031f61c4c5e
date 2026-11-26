from http.client import HTTPException
import json
from typing import Mapping, Protocol
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen


class PressTransportError(RuntimeError):
    pass


class PressResponseError(RuntimeError):
    def __init__(self, status: int, error: str):
        super().__init__(error)
        self.status = status


class PressClient(Protocol):
    def knows_press(self, press_id: str) -> bool: ...
    def enqueue(self, press_id: str, batch_id: str, plan: dict) -> dict: ...
    def read_run(self, press_id: str, run_id: str) -> dict: ...
    def retire(self, press_id: str, run_id: str, request_id: str, ejection_id: str) -> dict: ...


def request_json(address: str, path: str, body: dict | None = None) -> dict:
    data = None if body is None else json.dumps(body).encode('utf-8')
    request = Request(address.rstrip('/') + path, data=data, headers={'Content-Type': 'application/json'})
    try:
        with urlopen(request, timeout=5) as stream:
            result = json.load(stream)
    except HTTPError as exc:
        with exc:
            try:
                problem = json.load(exc)
                error = problem.get('error') if isinstance(problem, dict) else None
            except ValueError:
                error = None
        raise PressResponseError(exc.code, error if isinstance(error, str) else 'http_error') from exc
    except (URLError, HTTPException, OSError, ValueError) as exc:
        raise PressTransportError('transport_unavailable') from exc
    if not isinstance(result, dict):
        raise PressTransportError('invalid_http_reply')
    return result


class HttpPressClient:
    def __init__(self, addresses: Mapping[str, str]):
        self.addresses = addresses

    def knows_press(self, press_id: str) -> bool:
        return press_id in self.addresses

    def _address(self, press_id: str) -> str:
        try:
            return self.addresses[press_id]
        except KeyError as exc:
            raise KeyError('unknown_press') from exc

    def enqueue(self, press_id: str, batch_id: str, plan: dict) -> dict:
        return request_json(self._address(press_id), '/queue',
                            {'press_id': press_id, 'batch_id': batch_id, 'plan': plan})

    def read_run(self, press_id: str, run_id: str) -> dict:
        return request_json(self._address(press_id), '/runs/' + quote(run_id, safe=''))

    def retire(self, press_id: str, run_id: str, request_id: str, ejection_id: str) -> dict:
        return request_json(self._address(press_id), '/runs/' + quote(run_id, safe='') + '/retire',
                            {'request_id': request_id, 'ejection_id': ejection_id})
