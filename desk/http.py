import argparse
from contextlib import closing
from dataclasses import asdict
from http.server import ThreadingHTTPServer
import json
from pathlib import Path
import sqlite3

from delivery.inspection import inspect_batch
from delivery.pickup import pickup_batch
from delivery.release import init_issued_batches
from desk.batches import DeskConflict, create_batch, get_batch, init_batches
from desk.dispatch import dispatch_batch
from desk.press_client import HttpPressClient, PressClient, PressResponseError, PressTransportError
from desk.progress import read_progress
from desk.receipts import init_dispatch_receipts
from editions.drafts import parse_draft
from editions.paper import require_fields
from editions.proofs import ProofTemplate
from editions.releases import freeze_revision, get_revision, init_revisions
from press.http import JsonRequestHandler, require_identifier


def initialize_desk(db_path):
    with closing(sqlite3.connect(db_path)) as db, db:
        db.execute('BEGIN IMMEDIATE')
        init_revisions(db)
        init_batches(db)
        init_dispatch_receipts(db)
        init_issued_batches(db)


class DeskRequestHandler(JsonRequestHandler):
    def do_GET(self):
        self._serve(lambda path: self._with_db(self._get, path))

    def do_POST(self):
        self._serve(lambda path, data: self._with_db(self._post, path, data), post=True)

    def _with_db(self, handler, *args):
        try:
            with closing(sqlite3.connect(self.server.db_path)) as db:
                return handler(db, *args)
        except DeskConflict as exc:
            return 409, {'error': str(exc)}
        except PressTransportError:
            return 503, {'error': 'press_unavailable'}
        except PressResponseError as exc:
            return exc.status, {'error': str(exc)}

    def _get(self, db, path):
        if len(path) == 2:
            if path[0] == 'editions':
                return 200, get_revision(db, path[1]).to_record()
            if path[0] == 'batches':
                return 200, get_batch(db, path[1]).to_record()
        if len(path) == 3 and path[0] == 'batches':
            batch_id, action = path[1:]
            if action == 'progress':
                return 200, asdict(read_progress(db, self.server.client, batch_id))
            if action == 'delivery':
                return 200, asdict(pickup_batch(db, self.server.client, batch_id))
        raise KeyError('unknown_route')

    def _template(self):
        try:
            with self.server.template_path.open(encoding='utf-8') as stream:
                config = json.load(stream)
            return ProofTemplate.from_record(config['template'])
        except (OSError, ValueError, KeyError, TypeError) as exc:
            raise PressTransportError('template_unavailable') from exc

    def _post(self, db, path, body):
        if path == ('editions',):
            draft = parse_draft(body)
            try:
                template = self._template()
            except PressTransportError as exc:
                return 503, {'error': str(exc)}
            return 201, freeze_revision(db, draft, template).to_record()
        if path == ('batches',):
            require_fields(body, 'revision_id', 'start', 'count')
            return 201, create_batch(db, body['revision_id'], body['start'], body['count']).to_record()
        if len(path) == 3 and path[0] == 'batches':
            batch_id, action = path[1:]
            if action == 'dispatch':
                require_fields(body, 'press_id', 'request_id')
                press_id = require_identifier(body['press_id'], 'invalid_press_id')
                request_id = require_identifier(body['request_id'], 'invalid_request_id')
                return 200, dispatch_batch(db, self.server.client, batch_id, press_id, request_id)
            if action == 'inspection':
                require_fields(body, 'measurements')
                return 200, asdict(inspect_batch(db, self.server.client, batch_id, body['measurements']))
        raise KeyError('unknown_route')


def serve_desk(db_path, template_path, client: PressClient, *, host='127.0.0.1', port=0):
    initialize_desk(db_path)
    server = ThreadingHTTPServer((host, port), DeskRequestHandler)
    server.db_path = db_path
    server.template_path = Path(template_path)
    server.client = client
    return server


def main():
    parser = argparse.ArgumentParser(description='Run the local print workshop desk')
    parser.add_argument('--db', required=True)
    parser.add_argument('--template', required=True)
    parser.add_argument('--port', required=True, type=int)
    parser.add_argument('--press', required=True, nargs=2, action='append', metavar=('ID', 'URL'))
    args = parser.parse_args()
    addresses = {require_identifier(press_id, 'invalid_press_id'): url for press_id, url in args.press}
    if len(addresses) != len(args.press):
        parser.error('press identifiers must be unique')
    with serve_desk(args.db, args.template, HttpPressClient(addresses), port=args.port) as server:
        server.serve_forever()


if __name__ == '__main__':
    main()
