from collections import ChainMap
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from dataclasses import dataclass
from http.client import HTTPConnection, HTTPException
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from threading import Event, Lock
import unittest
from urllib.parse import urlsplit

from desk.http import serve_desk
from desk.press_client import HttpPressClient, PressTransportError, request_json
from press.http import running_server
from tests.workshop import Workshop, WorkshopTest


@dataclass(frozen=True)
class Exchange:
    method: str
    path: str
    request: bytes
    status: int
    response: bytes
    content_type: str | None


class ReplyGate:
    def __init__(self, drop):
        self.drop = drop
        self._received = Event()
        self._release = Event()
        self._exchange = None

    def wait(self, timeout=4):
        if not self._received.wait(timeout):
            raise TimeoutError("No matching upstream response")
        return self._exchange

    def release(self):
        self._release.set()

    def intercept(self, exchange):
        self._exchange = exchange
        self._received.set()
        return self.drop or not self._release.wait(5)


class _RelayHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        return

    def do_GET(self):
        self._relay()

    def do_POST(self):
        self._relay()

    def _relay(self):
        data = self.rfile.read(int(self.headers.get("Content-Length", "0")))
        target = urlsplit(self.server.relay.upstream())
        connection = HTTPConnection(target.hostname, target.port, timeout=5)
        try:
            body = data if self.command == "POST" else None
            headers = {"Content-Type": "application/json"} if body is not None else {}
            connection.request(self.command, self.path, body=body, headers=headers)
            with connection.getresponse() as upstream:
                exchange = Exchange(self.command, self.path, data, upstream.status,
                                    upstream.read(), upstream.getheader("Content-Type"))
        except (OSError, HTTPException):
            self.close_connection = True
            return
        finally:
            connection.close()
        if self.server.relay.intercept(exchange):
            self.close_connection = True
            return
        self.send_response(exchange.status)
        if exchange.content_type is not None:
            self.send_header("Content-Type", exchange.content_type)
        self.send_header("Content-Length", str(len(exchange.response)))
        self.end_headers()
        self.wfile.write(exchange.response)


class PressRelay:
    def __init__(self, upstream):
        self.upstream = upstream
        self._lock = Lock()
        self._armed = None

    @contextmanager
    def serve(self):
        server = ThreadingHTTPServer(("127.0.0.1", 0), _RelayHandler)
        server.relay = self
        with running_server(server) as address:
            self.address = address
            yield self

    @contextmanager
    def next_reply(self, predicate, *, drop=False):
        gate = ReplyGate(drop)
        registration = (predicate, gate)
        with self._lock:
            if self._armed is not None:
                raise RuntimeError("An upstream reply is already armed")
            self._armed = registration
        try:
            yield gate
        finally:
            gate.release()
            with self._lock:
                if self._armed is registration:
                    self._armed = None

    def intercept(self, exchange):
        with self._lock:
            if self._armed is None:
                return False
            predicate, gate = self._armed
            if not predicate(exchange):
                return False
            self._armed = None
        return gate.intercept(exchange)


class RelayedWorkshop(Workshop):
    def reopen_desk(self):
        if not hasattr(self, "relay"):
            self.relay = self.resources.enter_context(PressRelay(lambda: self.addresses["A"]).serve())
        self.desk_stack.close()
        addresses = ChainMap({"A": self.relay.address}, self.addresses)
        desk = serve_desk(self.root / "desk.sqlite", self.template_path, HttpPressClient(addresses))
        self.desk_address = self.desk_stack.enter_context(running_server(desk))


class TransportFixtureTest(WorkshopTest):
    def setUp(self):
        self.rig = self.enterContext(RelayedWorkshop())

    def test_hold_read_and_drop_committed_write_reply(self):
        batch, ref = self.whole_run(steps=2)
        advance_path = self.advance_path(ref)
        run_path = advance_path.rsplit("/", 1)[0]
        relay = self.rig.relay
        with ThreadPoolExecutor(max_workers=1) as pool:
            with relay.next_reply(lambda x: x.method == "GET" and x.path == run_path and x.status == 200) as read:
                pending = pool.submit(self.rig.desk, self.batch_path(batch, "progress"))
                self.assertEqual(json.loads(read.wait().response)["actual"], [])
                match_write = lambda x: x.method == "POST" and x.path == advance_path and x.status == 200
                with relay.next_reply(match_write, drop=True) as write:
                    with self.assertRaises(PressTransportError):
                        request_json(relay.address, advance_path, {"request_id": "advance-3"})
                    receipt = json.loads(write.wait().response)
                self.assertEqual(receipt["ejection_id"], "A-P1")
                self.assertEqual(self.rig.devices["A"].count_ejections(ref["run_id"]), 1)
                self.assertFalse(pending.done())
            status, stale = pending.result(timeout=5)
        self.assertEqual(status, 200)
        self.assertEqual(stale["missing"], [41, 42, 43])
        self.rig.reopen_press("A")
        self.rig.reopen_desk()
        self.assertEqual(self.advance(ref, "advance-3"), receipt)
        self.assertEqual(self.progress(batch)["missing"], [42, 43])
        self.assertEqual(self.rig.devices["A"].count_ejections(ref["run_id"]), 1)


if __name__ == "__main__":
    unittest.main()
