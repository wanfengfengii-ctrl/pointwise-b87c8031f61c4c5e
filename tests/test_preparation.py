from copy import deepcopy
import hashlib
import json

from tests.workshop import WorkshopTest, scenario


class TestPreparation(WorkshopTest):
    def test_numbered_plan(self):
        revision = self.freeze()
        batch = self.batch(revision)
        rows = batch['plan']['sheets']
        expected = [[41, '041', 32], [42, '042', 32], [43, '043', 32]]
        actual = [[row['number'], row['print_number'], row['back']['art']['x']] for row in rows]
        self.assertEqual(actual, expected)
        self.assertEqual([row['front']['art']['x'] for row in rows], [10, 10, 10])
        self.assertEqual(self.rig.desk(self.batch_path(batch)), (200, batch))
        ref = self.dispatch(batch)
        front = self.advance(ref, 'read-plan-on-press')
        downstream = self.rig.controls['A'].arrived['read-plan-on-press'].placement
        press_expected = {'print_number': '041', 'mark_id': f"{revision['revision_id']}-041",
                          'art': {'x': 10, 'y': 20, 'w': 60, 'h': 90},
                          'number_box': {'x': 18, 'y': 116, 'w': 24, 'h': 6},
                          'mark_box': {'x': 8, 'y': 12, 'w': 2, 'h': 2}}
        self.assertEqual((front['number'], front['stage']), (41, 'front'))
        self.assertEqual(downstream, press_expected)
        scenario('v1', {'draft': self.rig.sample['draft'], 'range': [41, 3]}, expected, actual,
                 press_expected, downstream,
                 ['editions/proofs.py', 'layout/plan.py', 'layout/back.py', 'press/runs.py'],
                 'Independent fixture geometry and the manual calculation 100 - 12 - 56 = 32.')

    def test_flip_coordinates(self):
        expected = {
            'long': [(32, 24, 56, 80), (58, 116, 24, 6), (90, 12, 2, 2)],
            'short': [(12, 46, 56, 80), (18, 28, 24, 6), (8, 136, 2, 2)],
        }
        front_expected = [(10, 20, 60, 90), (18, 116, 24, 6), (8, 12, 2, 2)]
        keys = ('art', 'number_box', 'mark_box')

        def coordinates(face):
            return [tuple(face[key][field] for field in ('x', 'y', 'w', 'h')) for key in keys]

        for flip in ('long', 'short'):
            with self.subTest(flip=flip):
                draft = deepcopy(self.rig.sample['draft'])
                draft['flip'] = flip
                revision = self.freeze(draft)
                batch = self.batch(revision)
                self.assertEqual(coordinates(revision['back_print']), expected[flip])
                for row in batch['plan']['sheets']:
                    self.assertEqual(coordinates(row['front']), front_expected)
                    self.assertEqual(coordinates(row['back']), expected[flip])
                    for face in ('front', 'back'):
                        self.assertEqual(row[face]['print_number'], row['print_number'])
                        self.assertEqual(row[face]['mark_id'], f"{revision['revision_id']}-{row['print_number']}")

    def test_range_validation(self):
        revision = self.freeze()
        for start, texts in [(99, ['099', '100', '101']), (999, ['999', '1000', '1001'])]:
            rows = self.batch(revision, start=start)['plan']['sheets']
            self.assertEqual([row['number'] for row in rows], list(range(start, start + 3)))
            self.assertEqual([row['print_number'] for row in rows], texts)
        for start, count in [(0, 2), (True, 2), (41.0, 2), (None, 2), (41, 0), (41, False),
                             (41, 501), (999_999, 2)]:
            with self.subTest(start=start, count=count):
                self.assertEqual(self.rig.desk('/batches', {'revision_id': revision['revision_id'],
                                                           'start': start, 'count': count})[0], 422)
        self.assertEqual(self.rig.desk('/batches', {'revision_id': 'E404', 'start': 41, 'count': 3})[0], 404)
        self.assertEqual(self.rig.desk('/batches/B3')[0], 404)
        self.assertEqual(self.batch(revision)['batch_id'], 'B3')

    def test_back_outside_paper(self):
        old = self.freeze()
        draft = deepcopy(self.rig.sample['draft'])
        draft['back_art']['w'] = 99
        self.assertEqual(self.rig.desk('/editions', draft), (422, {'error': 'back_outside_printable_area'}))
        self.assertEqual(self.rig.desk('/editions/E1'), (200, old))
        self.assertEqual(self.rig.desk('/editions/E2')[0], 404)
        self.assertEqual(self.batch(old)['plan']['revision_id'], old['revision_id'])

    def test_back_edge_rectangle(self):
        self.freeze()
        draft = deepcopy(self.rig.sample['draft'])
        draft['back_art']['x'] = 2
        self.assertEqual(self.rig.desk('/editions', draft), (422, {'error': 'back_outside_printable_area'}))
        self.assertEqual(self.rig.desk('/editions/E2')[0], 404)
        draft['back_art']['x'] = 5
        exact_edge = self.freeze(draft)
        self.assertEqual(exact_edge['revision_id'], 'E2')
        self.assertEqual(exact_edge['back_print']['art'], {'x': 39, 'y': 24, 'w': 56, 'h': 80})

    def test_fingerprint_is_content_based(self):
        first = self.freeze()
        second = self.freeze()
        self.assertNotEqual(first['revision_id'], second['revision_id'])
        body = json.dumps(first['proof'], sort_keys=True, separators=(',', ':')).encode('utf-8')
        self.assertEqual(first['fingerprint'], hashlib.sha256(body).hexdigest())
        self.assertEqual(second['fingerprint'], first['fingerprint'])

    def test_fixed_revision(self):
        old = self.freeze()
        original = self.batch(old)
        draft = deepcopy(self.rig.sample['draft'])
        draft['back_art']['x'] = 17
        new = self.freeze(draft)
        current = self.batch(new)
        self.assertNotEqual(old['revision_id'], new['revision_id'])
        self.assertNotEqual(old['fingerprint'], new['fingerprint'])
        self.assertEqual([row['back']['art']['x'] for row in current['plan']['sheets']], [27, 27, 27])
        self.assertEqual([row['back']['art']['x'] for row in original['plan']['sheets']], [32, 32, 32])
        self.assertEqual(self.rig.desk(self.batch_path(original)), (200, original))

    def test_reopen_fixed_snapshot(self):
        old = self.freeze()
        original = self.batch(old)
        sample = deepcopy(self.rig.sample)
        sample['template']['number_box']['x'] = 22
        sample['template']['tolerance_mm'] = 1
        local_text = json.dumps(sample, indent=2)
        self.rig.template_path.write_text(local_text, encoding='utf-8')
        self.rig.reopen_desk()
        self.rig.reopen_desk()
        self.assertEqual(self.rig.template_path.read_text(encoding='utf-8'), local_text)
        current = self.batch(self.freeze())
        self.assertEqual(current['plan']['sheets'][0]['back']['number_box']['x'], 54)
        self.assertEqual(current['plan']['tolerance_mm'], 1)
        self.assertEqual(original['plan']['sheets'][0]['back']['number_box']['x'], 58)
        self.assertEqual(original['plan']['tolerance_mm'], 2)
        self.assertEqual(self.rig.desk('/editions/E1'), (200, old))
        self.assertEqual(self.rig.desk(self.batch_path(original)), (200, original))
        self.assertEqual(self.batch(old)['plan'], original['plan'])
