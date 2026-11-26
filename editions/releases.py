from dataclasses import asdict, dataclass
import hashlib
import json
import sqlite3

from editions.drafts import EditionDraft
from editions.proofs import DuplexProof, ProofTemplate, build_proof


@dataclass(frozen=True)
class EditionRevision:
    revision_id: str
    draft_id: str
    fingerprint: str
    proof: DuplexProof

    def to_record(self):
        record = asdict(self)
        record['back_print'] = {name: asdict(rect)
                                for name, rect in self.proof.back_rectangles().items()}
        return record


def init_revisions(db: sqlite3.Connection):
    db.execute('''CREATE TABLE IF NOT EXISTS edition_revisions (
        seq INTEGER PRIMARY KEY, draft_id TEXT NOT NULL,
        fingerprint TEXT NOT NULL, proof TEXT NOT NULL
    )''')


def freeze_revision(db: sqlite3.Connection, draft: EditionDraft,
                    template: ProofTemplate) -> EditionRevision:
    proof = build_proof(draft, template)
    body = json.dumps(asdict(proof), sort_keys=True, separators=(',', ':'))
    fingerprint = hashlib.sha256(body.encode('utf-8')).hexdigest()
    with db:
        cursor = db.execute('INSERT INTO edition_revisions(draft_id, fingerprint, proof) VALUES (?, ?, ?)',
                            (draft.draft_id, fingerprint, body))
    return EditionRevision(f'E{cursor.lastrowid}', draft.draft_id, fingerprint, proof)


def get_revision(db: sqlite3.Connection, revision_id: str) -> EditionRevision:
    row = db.execute("SELECT draft_id, fingerprint, proof FROM edition_revisions WHERE 'E' || seq = ?",
                     (revision_id,)).fetchone()
    if row is None:
        raise KeyError('unknown_revision')
    draft_id, fingerprint, proof = row
    return EditionRevision(revision_id, draft_id, fingerprint, DuplexProof.from_record(json.loads(proof)))
