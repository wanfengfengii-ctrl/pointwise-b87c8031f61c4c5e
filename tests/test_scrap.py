import json

from tests.scrap_transport import RelayedWorkshop
from tests.workshop import WorkshopTest, scenario


def measurement(event, deviation):
    return {'ejection_id': event['ejection_id'], 'deviation_mm': deviation}


class TestScrap(WorkshopTest):
    def scrap(self, batch, **body):
        return self.rig.desk(self.batch_path(batch, 'scrap'), body)

    def reprint(self, ref, number, *, prefix):
        results = []
        for stage in ('front', 'back', 'eject'):
            results.append(self.advance(ref, f'{prefix}-{stage}'))
        self.assertEqual(results[-1]['stage'], 'ejected')
        self.assertEqual([result['number'] for result in results], [number] * 3)
        return results[-1]

    def test_return_and_reprint(self):
        batch, ref = self.whole_run()
        events = self.rig.devices['A'].ejection_events(ref['run_id'])
        self.assertEqual([event['ejection_id'] for event in events], ['A-P1', 'A-P2', 'A-P3'])

        status, receipt = self.scrap(batch, request_id='scrap-041', ejection_id='A-P1', deviation_mm=3)
        self.assertEqual(status, 200, receipt)
        self.assertEqual(receipt['request_id'], 'scrap-041')
        self.assertEqual((receipt['number'], receipt['ejection_id']), (41, 'A-P1'))
        self.assertEqual(receipt['run_id'], ref['run_id'])

        progress = self.progress(batch)
        self.assertEqual(progress['missing'], [41])
        self.assertEqual(progress['retired'], ['A-P1'])
        self.assertEqual([event['ejection_id'] for event in progress['history']],
                         ['A-P1', 'A-P2', 'A-P3'])
        self.assertEqual([event['ejection_id'] for event in progress['actual']], ['A-P2', 'A-P3'])

        remote = self.rig.press('A', f"/runs/{ref['run_id']}")[1]
        self.assertEqual([event['ejection_id'] for event in remote['actual']],
                         ['A-P1', 'A-P2', 'A-P3'])
        self.assertEqual(remote['retired'], ['A-P1'])

        # A reprint is the same run; its partial duplex still leaves 041 missing.
        self.advance(ref, 'reprint-front')
        self.assertEqual(self.progress(batch)['missing'], [41])
        self.advance(ref, 'reprint-back')
        self.assertEqual(self.progress(batch)['missing'], [41])
        ejected = self.advance(ref, 'reprint-eject')
        self.assertEqual(ejected['ejection_id'], 'A-P4')
        self.assertEqual(self.progress(batch)['missing'], [])

        # Old ejection id no longer covers the sheet; only the new paper counts.
        old = [measurement(event, 0) for event in events]
        self.assertEqual(self.inspect(batch, old), (409, {'error': 'measurement_coverage'}))
        new_events = self.rig.devices['A'].ejection_events(ref['run_id'])
        current = [measurement(event, 0) for event in new_events if event['ejection_id'] != 'A-P1']
        status, issued = self.inspect(batch, current)
        self.assertEqual(status, 200, issued)
        self.assertEqual([(row['print_number'], row['ejection_id']) for row in issued['sheets']],
                         [('041', 'A-P4'), ('042', 'A-P2'), ('043', 'A-P3')])
        self.assertEqual(self.pickup(batch), (200, issued))
        scenario('v8.return_reprint', {'return': {'ejection_id': 'A-P1', 'deviation_mm': 3,
                                                  'tolerance_mm': batch['plan']['tolerance_mm']}},
                 ['A-P1', 'A-P2', 'A-P3', 'A-P4'], [event['ejection_id'] for event in new_events],
                 [['041', 'A-P4'], ['042', 'A-P2'], ['043', 'A-P3']],
                 [[row['print_number'], row['ejection_id']] for row in issued['sheets']],
                 ['press/retirement.py', 'press/runs.py', 'desk/scrap.py', 'desk/progress.py',
                  'delivery/coverage.py', 'delivery/release.py'],
                 'Device keeps all four physical ejections in order; delivery keeps the reprint id '
                 'under the original number ordering.')

    def test_scrap_contract(self):
        batch = self.batch()
        ref = self.dispatch(batch)
        path = self.batch_path(batch, 'scrap')
        self.assertEqual(self.rig.desk('/batches/B404/scrap',
                                       {'request_id': 'x', 'ejection_id': 'A-P1', 'deviation_mm': 3}),
                         (404, {'error': 'unknown_batch'}))
        self.assertEqual(self.scrap(batch, request_id='small', ejection_id='A-P1', deviation_mm=2),
                         (422, {'error': 'scrap_deviation_out_of_tolerance'}))
        self.assertEqual(self.scrap(batch, request_id='small', ejection_id='A-P1', deviation_mm=-2),
                         (422, {'error': 'scrap_deviation_out_of_tolerance'}))
        self.assertEqual(self.scrap(batch, request_id='small', ejection_id='A-P1', deviation_mm=True),
                         (422, {'error': 'scrap_deviation_out_of_tolerance'}))
        self.assertEqual(self.scrap(batch, request_id='small', ejection_id='A-P1', deviation_mm=3.0),
                         (422, {'error': 'scrap_deviation_out_of_tolerance'}))
        self.assertEqual(self.rig.desk(path, {'request_id': 'missing', 'deviation_mm': 3}),
                         (422, {'error': 'invalid_fields'}))
        # Nothing ejected yet, so no physical paper can be returned.
        self.assertEqual(self.scrap(batch, request_id='early', ejection_id='A-P1', deviation_mm=3)[0], 409)
        self.assertEqual(self.save_retire_state(ref, 'A-P1'), [])

        for step in range(3):
            self.advance(ref, f'first-{step}')
        self.assertEqual(self.scrap(batch, request_id='foreign', ejection_id='A-P9', deviation_mm=3),
                         (409, {'error': 'sheet_not_in_batch'}))
        status, first = self.scrap(batch, request_id='scrap-041', ejection_id='A-P1', deviation_mm=3)
        self.assertEqual(status, 200, first)
        # Exact replay returns the first receipt; changed parameters are rejected.
        self.assertEqual(self.scrap(batch, request_id='scrap-041', ejection_id='A-P1', deviation_mm=3),
                         (200, first))
        self.assertEqual(self.scrap(batch, request_id='scrap-041', ejection_id='A-P1', deviation_mm=4),
                         (409, {'error': 'scrap_request_conflict'}))
        # A second return of the same original paper is refused.
        self.assertEqual(self.scrap(batch, request_id='again', ejection_id='A-P1', deviation_mm=3),
                         (409, {'error': 'sheet_already_retired'}))

    def save_retire_state(self, ref, ejection_id):
        remote = self.rig.press('A', f"/runs/{ref['run_id']}")[1]
        return [item for item in remote.get('retired', []) if item == ejection_id]

    def test_signed_out_sheet_cannot_be_scrapped(self):
        batch, ref = self.whole_run()
        events = self.rig.devices['A'].ejection_events(ref['run_id'])
        status, issued = self.inspect(batch, [measurement(event, 0) for event in events])
        self.assertEqual(status, 200, issued)
        self.assertEqual(self.scrap(batch, request_id='late', ejection_id='A-P1', deviation_mm=3),
                         (409, {'error': 'sheet_already_issued'}))
        self.assertEqual(self.rig.devices['A'].count_ejections(ref['run_id']), 3)
        self.assertEqual(self.rig.press('A', f"/runs/{ref['run_id']}")[1].get('retired'), None)
        self.assertEqual(self.pickup(batch), (200, issued))

    def test_reprint_cannot_be_scrapped_or_signed_under_old_id(self):
        batch, ref = self.whole_run()
        self.assertEqual(self.scrap(batch, request_id='scrap-041', ejection_id='A-P1', deviation_mm=3)[0], 200)
        self.reprint(ref, 41, prefix='reprint')
        self.assertEqual(self.scrap(batch, request_id='scrap-new', ejection_id='A-P4', deviation_mm=3),
                         (409, {'error': 'sheet_already_retired'}))

    def test_lost_ejection_reply_still_belongs_to_original(self):
        from http.client import RemoteDisconnected

        batch = self.batch(count=1)
        ref = self.dispatch(batch)
        self.advance(ref, 'front')
        self.advance(ref, 'back')
        self.rig.controls['A'].drop_after_effect.add('eject-41')
        with self.assertRaises(RemoteDisconnected):
            self.rig.press('A', self.advance_path(ref), {'request_id': 'eject-41'})
        # The device ejected A-P1 but the press never saved the advance receipt.
        self.assertEqual([event['ejection_id'] for event in
                          self.rig.devices['A'].ejection_events(ref['run_id'])], ['A-P1'])
        # The return is processed off the physical event, not the lost receipt.
        status, returned = self.scrap(batch, request_id='scrap-041', ejection_id='A-P1', deviation_mm=3)
        self.assertEqual(status, 200, returned)

        # The old eject request still names the very same original paper.
        replay = self.advance(ref, 'eject-41')
        self.assertEqual((replay['number'], replay['ejection_id']), (41, 'A-P1'))
        self.assertEqual([event['ejection_id'] for event in
                          self.rig.devices['A'].ejection_events(ref['run_id'])], ['A-P1'])
        self.assertEqual(self.rig.devices['A'].count_ejections(ref['run_id']), 1)

        # 041 stays missing until the reprint really ejects.
        self.assertEqual(self.progress(batch)['missing'], [41])
        self.reprint(ref, 41, prefix='reprint')
        self.assertEqual([event['ejection_id'] for event in
                          self.rig.devices['A'].ejection_events(ref['run_id'])], ['A-P1', 'A-P2'])
        self.assertEqual(self.progress(batch)['missing'], [])

    def test_partial_reprint_reports_missing(self):
        batch, ref = self.whole_run()
        self.assertEqual(self.scrap(batch, request_id='scrap-041', ejection_id='A-P1', deviation_mm=3)[0], 200)
        self.advance(ref, 'reprint-front')
        progress = self.progress(batch)
        self.assertEqual(progress['missing'], [41])
        self.assertEqual([event['ejection_id'] for event in progress['actual']], ['A-P2', 'A-P3'])
        self.assertEqual(self.pickup(batch), (409, {'error': 'incomplete'}))
        self.advance(ref, 'reprint-back')
        self.assertEqual(self.progress(batch)['missing'], [41])
        self.assertEqual(self.pickup(batch), (409, {'error': 'incomplete'}))
        self.advance(ref, 'reprint-eject')
        self.assertEqual(self.progress(batch)['missing'], [])
        self.assertEqual(self.pickup(batch), (409, {'error': 'not_inspected'}))


class TestScrapOrdering(WorkshopTest):
    def setUp(self):
        self.rig = self.enterContext(RelayedWorkshop())

    def scrap(self, batch, **body):
        return self.rig.desk(self.batch_path(batch, 'scrap'), body)

    def test_hidden_retire_reply_blocks_old_table(self):
        from concurrent.futures import ThreadPoolExecutor

        batch, ref = self.whole_run()
        events = self.rig.devices['A'].ejection_events(ref['run_id'])
        original_table = [measurement(event, 0) for event in events]
        retire_path = f"/runs/{ref['run_id']}/retire"
        relay = self.rig.relay
        with ThreadPoolExecutor(max_workers=1) as pool:
            with relay.next_reply(lambda x: x.method == 'POST' and x.path == retire_path and x.status == 200,
                                  drop=True) as held:
                pending = pool.submit(self.scrap, batch, request_id='scrap-041',
                                      ejection_id='A-P1', deviation_mm=3)
                receipt = json.loads(held.wait().response)
                self.assertEqual(receipt['ejection_id'], 'A-P1')
                # The press has committed the retirement even though the desk is blind to its reply.
                self.assertEqual(self.rig.press('A', f"/runs/{ref['run_id']}")[1]['retired'], ['A-P1'])
                self.assertEqual(pending.result(timeout=5), (503, {'error': 'press_unavailable'}))

        # The old, previously acceptable table can no longer be signed out.
        self.assertEqual(self.inspect(batch, original_table), (409, {'error': 'incomplete'}))
        self.assertEqual(self.pickup(batch), (409, {'error': 'incomplete'}))

        # Reopening and replaying the same return resumes it with a single reprint.
        self.rig.reopen_desk()
        status, receipt = self.scrap(batch, request_id='scrap-041', ejection_id='A-P1', deviation_mm=3)
        self.assertEqual(status, 200, receipt)
        self.assertEqual(receipt['ejection_id'], 'A-P1')
        self.assertEqual(self.rig.devices['A'].count_ejections(ref['run_id']), 3)
        self.assertEqual(self.rig.press('A', f"/runs/{ref['run_id']}")[1]['retired'], ['A-P1'])
        for stage in ('front', 'back', 'eject'):
            self.advance(ref, f'reprint-{stage}')
        self.assertEqual(self.rig.devices['A'].count_ejections(ref['run_id']), 4)
        self.assertEqual(self.rig.press('A', f"/runs/{ref['run_id']}")[1]['retired'], ['A-P1'])
        scenario('v9.return_wins', {'hidden_retire_reply': True, 'replay_request': 'scrap-041'},
                 {'old_table_signable': False, 'ejections': 4},
                 {'old_table_signable': self.inspect(batch, original_table)[0] == 200,
                  'ejections': self.rig.devices['A'].count_ejections(ref['run_id'])},
                 {'missing': []}, {'missing': self.progress(batch)['missing']},
                 ['press/retirement.py', 'desk/scrap.py', 'desk/receipts.py',
                  'desk/progress.py', 'delivery/coverage.py'],
                 'Retirement committed downstream while its reply is hidden: the old table is '
                 'refused and replay produces exactly one reprint.')

    def test_signed_out_before_return(self):
        batch, ref = self.whole_run()
        events = self.rig.devices['A'].ejection_events(ref['run_id'])
        status, issued = self.inspect(batch, [measurement(event, 0) for event in events])
        self.assertEqual(status, 200, issued)
        self.assertEqual(self.scrap(batch, request_id='scrap-041', ejection_id='A-P1', deviation_mm=3),
                         (409, {'error': 'sheet_already_issued'}))
        self.assertEqual(self.rig.press('A', f"/runs/{ref['run_id']}")[1].get('retired'), None)
        self.assertEqual(self.rig.devices['A'].count_ejections(ref['run_id']), 3)
        # The signed-out batch issues no reprint: the run is complete and refuses
        # to reserve another sheet.
        self.assertEqual(self.rig.press('A', self.advance_path(ref), {'request_id': 'late-reprint'}),
                         (409, {'error': 'run_complete'}))
        self.assertEqual(self.pickup(batch), (200, issued))
        scenario('v9.signout_wins', {'signed_before_return': True, 'return_deviation_mm': 3},
                 {'return_status': 409, 'ejections': 3, 'pickup_ok': True},
                 {'return_status': 409, 'ejections': self.rig.devices['A'].count_ejections(ref['run_id']),
                  'pickup_ok': self.pickup(batch)[0] == 200},
                 {'retired': None}, {'retired': self.rig.press('A', f"/runs/{ref['run_id']}")[1].get('retired')},
                 ['delivery/release.py', 'delivery/pickup.py', 'desk/scrap.py'],
                 'The sheet was signed out first: the return is refused and the run admits no reprint.')

    def test_both_orders_are_exclusive(self):
        # Order 1: sign out first, then a return is refused and no reprint occurs.
        signed = self.batch(count=1)
        signed_ref = self.dispatch(signed, request_id='sign-out-first')
        for stage in ('front', 'back', 'eject'):
            self.advance(signed_ref, f'signed-{stage}')
        signed_events = self.rig.devices['A'].ejection_events(signed_ref['run_id'])
        self.assertEqual(self.inspect(signed, [measurement(signed_events[0], 0)])[0], 200)
        self.assertEqual(self.rig.desk(self.batch_path(signed, 'scrap'),
                                       {'request_id': 'lost-return', 'ejection_id': signed_events[0]['ejection_id'],
                                        'deviation_mm': 3}), (409, {'error': 'sheet_already_issued'}))

        # Order 2: return first, then a sign-out of the old table is refused.
        returned = self.batch(count=1)
        returned_ref = self.dispatch(returned, request_id='return-first')
        for stage in ('front', 'back', 'eject'):
            self.advance(returned_ref, f'returned-{stage}')
        returned_event = self.rig.devices['A'].ejection_events(returned_ref['run_id'])[0]
        self.assertEqual(self.rig.desk(self.batch_path(returned, 'scrap'),
                                       {'request_id': 'good-return',
                                        'ejection_id': returned_event['ejection_id'],
                                        'deviation_mm': 3})[0], 200)
        self.assertEqual(self.inspect(returned, [measurement(returned_event, 0)]),
                         (409, {'error': 'incomplete'}))
