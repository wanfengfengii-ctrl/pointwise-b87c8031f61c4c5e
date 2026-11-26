from contextlib import closing
from dataclasses import asdict, dataclass
import json
import sqlite3

from press.duplex import DuplexStage, RunConflict


class DevicePaused(RuntimeError):
    pass


@dataclass(frozen=True)
class DeviceAction:
    action_id: str
    batch_id: str
    run_id: str
    request_id: str
    number: int
    stage: DuplexStage
    placement: dict | None


@dataclass(frozen=True)
class DeviceResult:
    action_id: str
    stage: DuplexStage
    ejection_id: str | None


class SimulatedPress:
    def __init__(self, db_path, press_id: str, *, before_arrival=None, before_effect=None, after_effect=None):
        self.db_path = db_path
        self.press_id = press_id
        self.before_arrival = before_arrival
        self.before_effect = before_effect
        self.after_effect = after_effect

    def initialize_device(self):
        with closing(sqlite3.connect(self.db_path)) as db, db:
            db.execute('BEGIN IMMEDIATE')
            db.execute('''CREATE TABLE IF NOT EXISTS device_identity (
                singleton INTEGER PRIMARY KEY CHECK(singleton = 1), press_id TEXT NOT NULL
            )''')
            db.execute('INSERT OR IGNORE INTO device_identity VALUES (1, ?)', (self.press_id,))
            if db.execute('SELECT press_id FROM device_identity').fetchone() != (self.press_id,):
                raise ValueError('device_identity_mismatch')
            db.execute('''CREATE TABLE IF NOT EXISTS device_actions (
                action_id TEXT PRIMARY KEY, run_id TEXT NOT NULL, number INTEGER NOT NULL,
                stage TEXT NOT NULL, body TEXT NOT NULL, result TEXT
            )''')
            db.execute('''CREATE INDEX IF NOT EXISTS device_sheet_history
                          ON device_actions(run_id, number, stage)''')
            db.execute('''CREATE TABLE IF NOT EXISTS device_ejections (
                seq INTEGER PRIMARY KEY, action_id TEXT NOT NULL UNIQUE,
                batch_id TEXT NOT NULL, run_id TEXT NOT NULL, number INTEGER NOT NULL
            )''')

    @staticmethod
    def _saved_result(action, row):
        if row[0] is None:
            return None
        data = json.loads(row[0])
        return DeviceResult(action.action_id, DuplexStage(data['stage']), data['ejection_id'])

    def _accept(self, action: DeviceAction) -> DeviceResult | None:
        body = json.dumps(asdict(action), sort_keys=True, separators=(',', ':'))
        with closing(sqlite3.connect(self.db_path)) as db, db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT result, body FROM device_actions WHERE action_id = ?',
                             (action.action_id,)).fetchone()
            if row is not None:
                if row[1] != body:
                    raise RunConflict('device_action_conflict')
                return self._saved_result(action, row)
            db.execute('''INSERT INTO device_actions(action_id, run_id, number, stage, body)
                          VALUES (?, ?, ?, ?, ?)''',
                       (action.action_id, action.run_id, action.number, action.stage.value, body))
        return None

    def _validate_effect(self, db, action):
        if action.stage in (DuplexStage.FRONT, DuplexStage.BACK):
            if not isinstance(action.placement, dict):
                raise RunConflict('missing_face_placement')
        if action.stage == DuplexStage.QUEUED:
            raise RunConflict('invalid_device_stage')
        required = {DuplexStage.FRONT: set(), DuplexStage.BACK: {DuplexStage.FRONT.value},
                    DuplexStage.EJECTED: {DuplexStage.FRONT.value, DuplexStage.BACK.value}}[action.stage]
        completed = {row[0] for row in db.execute('''SELECT stage FROM device_actions
                       WHERE run_id = ? AND number = ? AND result IS NOT NULL''',
                                                  (action.run_id, action.number))}
        if not required.issubset(completed):
            raise RunConflict('missing_device_face_result')

    def execute(self, action: DeviceAction) -> DeviceResult:
        if self.before_arrival is not None:
            self.before_arrival(action)
        prior = self._accept(action)
        if prior is not None:
            return prior
        if self.before_effect is not None:
            self.before_effect(action)
        with closing(sqlite3.connect(self.db_path)) as db, db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT result FROM device_actions WHERE action_id = ?',
                             (action.action_id,)).fetchone()
            prior = self._saved_result(action, row)
            if prior is not None:
                return prior
            self._validate_effect(db, action)
            ejection_id = None
            if action.stage == DuplexStage.EJECTED:
                cursor = db.execute('''INSERT INTO device_ejections(action_id, batch_id, run_id, number)
                                       VALUES (?, ?, ?, ?)''',
                                    (action.action_id, action.batch_id, action.run_id, action.number))
                ejection_id = f'{self.press_id}-P{cursor.lastrowid}'
            result = DeviceResult(action.action_id, action.stage, ejection_id)
            db.execute('UPDATE device_actions SET result = ? WHERE action_id = ?',
                       (json.dumps(asdict(result)), action.action_id))
        if self.after_effect is not None:
            self.after_effect(action, result)
        return result

    def ejection_events(self, run_id: str | None = None) -> list[dict]:
        sql = 'SELECT seq, action_id, batch_id, run_id, number FROM device_ejections'
        with closing(sqlite3.connect(self.db_path)) as db:
            if run_id is None:
                rows = db.execute(sql + ' ORDER BY seq').fetchall()
            else:
                rows = db.execute(sql + ' WHERE run_id = ? ORDER BY seq', (run_id,)).fetchall()
        return [{'ejection_id': f'{self.press_id}-P{seq}', 'action_id': action_id,
                 'batch_id': batch_id, 'run_id': run, 'press_id': self.press_id, 'number': number}
                for seq, action_id, batch_id, run, number in rows]

    def count_ejections(self, run_id: str | None = None) -> int:
        with closing(sqlite3.connect(self.db_path)) as db:
            if run_id is None:
                return db.execute('SELECT COUNT(*) FROM device_ejections').fetchone()[0]
            return db.execute('SELECT COUNT(*) FROM device_ejections WHERE run_id = ?', (run_id,)).fetchone()[0]
