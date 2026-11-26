from contextlib import ExitStack, closing
import json
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
import unittest
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from desk.http import serve_desk
from desk.press_client import HttpPressClient
from press.http import DropReply, running_server, serve_press
from press.simulator import DevicePaused, SimulatedPress


SAMPLE = Path(__file__).resolve().parents[1] / 'samples' / 'festival.json'


class DeviceControls:
    def __init__(self):
        self.hold_before_arrival = set()
        self.hold_before_effect = set()
        self.drop_after_effect = set()
        self.drop_after_reply = set()
        self.arrived = {}

    def before_arrival(self, action):
        if action.request_id in self.hold_before_arrival:
            raise DevicePaused

    def before_effect(self, action):
        self.arrived[action.request_id] = action
        if action.request_id in self.hold_before_effect:
            raise DevicePaused

    def after_effect(self, action, result):
        if action.request_id in self.drop_after_effect:
            self.drop_after_effect.remove(action.request_id)
            raise DropReply

    def on_reply(self, path, result):
        key = 'queue' if path == ('queue',) else result.get('request_id')
        if key in self.drop_after_reply:
            self.drop_after_reply.remove(key)
            raise DropReply


class Workshop:
    def __enter__(self):
        self.resources = ExitStack()
        try:
            self.root = Path(self.resources.enter_context(TemporaryDirectory(prefix='print-regression-')))
            self.sample = json.loads(SAMPLE.read_text(encoding='utf-8'))
            self.template_path = self.root / 'festival.json'
            self.template_path.write_text(json.dumps(self.sample), encoding='utf-8')
            self.addresses = {}
            self.controls = {}
            self.devices = {}
            self.press_stack = {}
            self.desk_stack = self.resources.enter_context(ExitStack())
            for press_id in ('A', 'B'):
                self.press_stack[press_id] = self.resources.enter_context(ExitStack())
                self.reopen_press(press_id)
            self.reopen_desk()
        except BaseException:
            self.resources.close()
            raise
        return self

    def __exit__(self, *exc):
        return self.resources.__exit__(*exc)

    def reopen_press(self, press_id):
        self.press_stack[press_id].close()
        controls = DeviceControls()
        device = SimulatedPress(self.root / f'{press_id}-device.sqlite', press_id,
                                before_arrival=controls.before_arrival, before_effect=controls.before_effect,
                                after_effect=controls.after_effect)
        server = serve_press(self.root / f'{press_id}-runs.sqlite', device, on_reply=controls.on_reply)
        self.addresses[press_id] = self.press_stack[press_id].enter_context(running_server(server))
        self.controls[press_id] = controls
        self.devices[press_id] = device

    def stop_press(self, press_id):
        # Keep the former address configured so an attempted live query would fail.
        self.press_stack[press_id].close()

    def reopen_desk(self):
        self.desk_stack.close()
        server = serve_desk(self.root / 'desk.sqlite', self.template_path, HttpPressClient(self.addresses))
        self.desk_address = self.desk_stack.enter_context(running_server(server))

    def run_count(self, press_id):
        with closing(sqlite3.connect(self.root / f'{press_id}-runs.sqlite')) as db:
            return db.execute('SELECT COUNT(*) FROM queued_runs').fetchone()[0]

    def saved_advance(self, press_id, request_id):
        with closing(sqlite3.connect(self.root / f'{press_id}-runs.sqlite')) as db:
            row = db.execute('SELECT result FROM advance_requests WHERE request_id = ?', (request_id,)).fetchone()
        if row is None:
            raise AssertionError('expected a reserved advance request')
        return None if row[0] is None else json.loads(row[0])

    @staticmethod
    def http(address, path, body=None):
        data = None if body is None else json.dumps(body).encode('utf-8')
        request = Request(address + path, data, {'Content-Type': 'application/json'})
        try:
            with urlopen(request, timeout=5) as stream:
                return stream.status, json.load(stream)
        except HTTPError as exc:
            with exc:
                return exc.code, json.load(exc)

    def desk(self, path, body=None):
        return self.http(self.desk_address, path, body)

    def press(self, press_id, path, body=None):
        return self.http(self.addresses[press_id], path, body)


class WorkshopTest(unittest.TestCase):
    def setUp(self):
        self.rig = self.enterContext(Workshop())

    def freeze(self, draft=None):
        status, result = self.rig.desk('/editions', self.rig.sample['draft'] if draft is None else draft)
        self.assertEqual(status, 201, result)
        return result

    def batch(self, revision=None, *, start=41, count=3):
        if revision is None:
            revision = self.freeze()
        status, batch = self.rig.desk('/batches', {'revision_id': revision['revision_id'],
                                                  'start': start, 'count': count})
        self.assertEqual(status, 201, batch)
        return batch

    @staticmethod
    def batch_path(batch, action=''):
        return '/batches/' + batch['batch_id'] + (f'/{action}' if action else '')

    def dispatch(self, batch, *, press_id='A', request_id='dispatch-1'):
        status, result = self.rig.desk(self.batch_path(batch, 'dispatch'),
                                       {'press_id': press_id, 'request_id': request_id})
        self.assertEqual(status, 200, result)
        return result

    @staticmethod
    def advance_path(ref):
        return f"/runs/{ref['run_id']}/advance"

    def advance(self, ref, request_id):
        status, result = self.rig.press(ref['press_id'], self.advance_path(ref), {'request_id': request_id})
        self.assertEqual(status, 200, result)
        return result

    def progress(self, batch):
        status, result = self.rig.desk(self.batch_path(batch, 'progress'))
        self.assertEqual(status, 200, result)
        return result

    def whole_run(self, *, steps=9):
        batch = self.batch()
        ref = self.dispatch(batch)
        for step in range(steps):
            self.advance(ref, f'advance-{step + 1}')
        return batch, ref

    def inspect(self, batch, measurements):
        return self.rig.desk(self.batch_path(batch, 'inspection'), {'measurements': measurements})

    def pickup(self, batch):
        return self.rig.desk(self.batch_path(batch, 'delivery'))


def scenario(case_id, inputs, expected, actual, downstream_expected, downstream_actual, paths, oracle):
    print('POINTWISE_SCENARIO ' + json.dumps({
        'case_id': case_id, 'input': inputs, 'expected': expected, 'actual': actual,
        'downstream_expected': downstream_expected, 'downstream_actual': downstream_actual,
        'code_paths': paths, 'oracle': oracle,
    }, ensure_ascii=False, sort_keys=True))
