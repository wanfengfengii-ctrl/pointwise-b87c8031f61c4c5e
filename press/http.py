import argparse
from contextlib import closing, contextmanager
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import sqlite3
from threading import Thread
from urllib.parse import unquote, urlsplit

from editions.paper import require_fields
from layout.plan import plan_from_record
from press.duplex import RunConflict
from press.queue import enqueue_plan, init_queue
from press.retirement import init_retirement, retire_sheet
from press.runs import advance_run, init_runs, read_run_result
from press.simulator import DevicePaused, SimulatedPress


class DropReply(Exception):
    """A local transport hook requests closing a connection before replying."""


class JsonRequestHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        return

    def _path(self):
        return tuple(unquote(part) for part in urlsplit(self.path).path.split('/')[1:])

    def _read_body(self):
        try:
            size = int(self.headers.get('Content-Length', '0'))
            if not 0 < size <= 2_000_000:
                raise ValueError
            body = json.loads(self.rfile.read(size))
        except (ValueError, UnicodeError) as exc:
            raise ValueError('invalid_json_body') from exc
        if not isinstance(body, dict):
            raise ValueError('invalid_json_body')
        return body

    def _serve(self, route, *, post=False):
        try:
            path = self._path()
            if post:
                status, result = route(path, self._read_body())
            else:
                status, result = route(path)
        except DropReply:
            self.close_connection = True
            return
        except (KeyError, ValueError, sqlite3.Error) as exc:
            if isinstance(exc, KeyError):
                status, result = 404, {'error': exc.args[0]}
            elif isinstance(exc, ValueError):
                status, result = 422, {'error': str(exc)}
            else:
                status, result = 503, {'error': 'database_unavailable'}
        encoded = json.dumps(result, ensure_ascii=False).encode('utf-8')
        try:
            self.send_response(status)
            self.send_header('Content-Type', 'application/json; charset=utf-8')
            self.send_header('Content-Length', str(len(encoded)))
            self.end_headers()
            self.wfile.write(encoded)
        except (BrokenPipeError, ConnectionResetError):
            self.close_connection = True


def require_identifier(value, error='invalid_identifier'):
    if (not isinstance(value, str) or not 0 < len(value) <= 80
            or not all(char.isalnum() or char in '-_.' for char in value)):
        raise ValueError(error)
    return value


class PressRequestHandler(JsonRequestHandler):
    def do_GET(self):
        self._serve(self._get)

    def do_POST(self):
        self._serve(self._post, post=True)

    def _get(self, path):
        if len(path) == 2 and path[0] == 'runs':
            with closing(sqlite3.connect(self.server.db_path)) as db:
                return 200, read_run_result(db, self.server.device, path[1])
        raise KeyError('unknown_route')

    def _post(self, path, body):
        device = self.server.device
        try:
            with closing(sqlite3.connect(self.server.db_path)) as db:
                if path == ('queue',):
                    require_fields(body, 'batch_id', 'press_id', 'plan')
                    if body['press_id'] != device.press_id:
                        raise KeyError('unknown_press')
                    batch_id = require_identifier(body['batch_id'], 'invalid_batch_id')
                    result = enqueue_plan(db, device.press_id, batch_id, plan_from_record(body['plan'])).reference()
                elif len(path) == 3 and path[0] == 'runs' and path[2] == 'advance':
                    require_fields(body, 'request_id')
                    request_id = require_identifier(body['request_id'], 'invalid_request_id')
                    result = advance_run(db, device, path[1], request_id)
                elif len(path) == 3 and path[0] == 'runs' and path[2] == 'retire':
                    require_fields(body, 'request_id', 'ejection_id')
                    request_id = require_identifier(body['request_id'], 'invalid_request_id')
                    ejection_id = require_identifier(body['ejection_id'], 'invalid_ejection_id')
                    result = retire_sheet(db, device, path[1], request_id, ejection_id)
                else:
                    raise KeyError('unknown_route')
        except RunConflict as exc:
            return 409, {'error': str(exc)}
        except DevicePaused:
            return 503, {'error': 'device_waiting'}
        if self.server.on_reply is not None:
            self.server.on_reply(path, result)
        return 200, result


def initialize_press(db_path, device: SimulatedPress):
    require_identifier(device.press_id, 'invalid_press_id')
    with closing(sqlite3.connect(db_path)) as db, db:
        db.execute('BEGIN IMMEDIATE')
        db.execute('''CREATE TABLE IF NOT EXISTS press_identity (
            singleton INTEGER PRIMARY KEY CHECK(singleton = 1), press_id TEXT NOT NULL
        )''')
        db.execute('INSERT OR IGNORE INTO press_identity VALUES (1, ?)', (device.press_id,))
        if db.execute('SELECT press_id FROM press_identity').fetchone() != (device.press_id,):
            raise ValueError('press_identity_mismatch')
        init_queue(db)
        init_runs(db)
        init_retirement(db)
    device.initialize_device()


def serve_press(db_path, device: SimulatedPress, *, host='127.0.0.1', port=0, on_reply=None):
    initialize_press(db_path, device)
    server = ThreadingHTTPServer((host, port), PressRequestHandler)
    server.db_path = db_path
    server.device = device
    server.on_reply = on_reply
    return server


@contextmanager
def running_server(server):
    with server:
        thread = Thread(target=server.serve_forever, kwargs={'poll_interval': 0.02})
        thread.start()
        try:
            yield f'http://127.0.0.1:{server.server_port}'
        finally:
            server.shutdown()
            thread.join()


def main():
    parser = argparse.ArgumentParser(description='Run a local print press service')
    parser.add_argument('--id', required=True)
    parser.add_argument('--db', required=True)
    parser.add_argument('--device', required=True)
    parser.add_argument('--port', required=True, type=int)
    args = parser.parse_args()
    with serve_press(args.db, SimulatedPress(args.device, args.id), port=args.port) as server:
        server.serve_forever()


if __name__ == '__main__':
    main()
