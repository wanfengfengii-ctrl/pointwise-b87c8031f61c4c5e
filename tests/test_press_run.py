from tests.workshop import WorkshopTest, scenario


class TestPressRun(WorkshopTest):
    def test_dispatch_conflict(self):
        batch = self.batch()
        ref = self.dispatch(batch)
        path = self.batch_path(batch, 'dispatch')
        self.assertEqual(self.rig.desk(path, {'press_id': 'B', 'request_id': 'other-machine'}),
                         (409, {'error': 'batch_press_conflict'}))
        self.assertEqual((self.rig.run_count('A'), self.rig.run_count('B')), (1, 0))
        self.assertEqual(self.progress(batch)['run_id'], ref['run_id'])
        self.assertEqual(self.advance(ref, 'move-original')['number'], 41)

    def test_dispatch_replay(self):
        batch = self.batch()
        path = self.batch_path(batch, 'dispatch')
        body = {'press_id': 'A', 'request_id': 'lost-enqueue'}
        self.rig.controls['A'].drop_after_reply.add('queue')
        self.assertEqual(self.rig.desk(path, body), (503, {'error': 'press_unavailable'}))
        pending = self.progress(batch)
        self.assertEqual((pending['press_id'], pending['run_id'], pending['missing']), ('A', None, [41, 42, 43]))
        self.assertEqual(self.rig.run_count('A'), 1)
        self.rig.reopen_desk()
        self.rig.reopen_press('A')
        ref = self.dispatch(batch, request_id='lost-enqueue')
        self.assertEqual(ref['run_id'], 'A-R1')
        self.assertEqual(self.rig.desk(path, body), (200, ref))
        self.assertEqual(self.rig.run_count('A'), 1)
        self.assertEqual(self.rig.desk(path, {'press_id': 'B', 'request_id': 'try-b'})[0], 409)
        self.assertEqual(self.rig.run_count('B'), 0)

    def test_dispatch_contract(self):
        batch = self.batch()
        path = self.batch_path(batch, 'dispatch')
        self.assertEqual(self.rig.desk('/batches/B404/dispatch', {'press_id': 'A', 'request_id': 'unknown'}),
                         (404, {'error': 'unknown_batch'}))
        self.assertEqual(self.rig.desk(path, {'press_id': 'X', 'request_id': 'unknown'}),
                         (404, {'error': 'unknown_press'}))
        self.assertIsNone(self.rig.desk(self.batch_path(batch))[1]['press_id'])
        self.assertEqual((self.rig.run_count('A'), self.rig.run_count('B')), (0, 0))
        self.dispatch(batch)
        self.assertEqual(self.rig.desk(path, {'press_id': 'B', 'request_id': 'dispatch-1'}),
                         (409, {'error': 'dispatch_request_conflict'}))
        later = self.batch()
        self.assertEqual(self.rig.desk(self.batch_path(later, 'dispatch'),
                                       {'press_id': 'A', 'request_id': 'dispatch-1'}),
                         (409, {'error': 'dispatch_request_conflict'}))
        self.assertIsNone(self.rig.desk(self.batch_path(later))[1]['press_id'])
        self.assertEqual(self.rig.run_count('A'), 1)

    def test_replay_receipt(self):
        batch = self.batch(count=2)
        ref = self.dispatch(batch)
        self.advance(ref, 'front-41')
        self.advance(ref, 'back-41')
        self.rig.controls['A'].drop_after_reply.add('eject-41')
        status, _ = self.rig.press('A', self.advance_path(ref), {'request_id': 'eject-41'}) if False else (None, None)
        from http.client import RemoteDisconnected
        with self.assertRaises(RemoteDisconnected):
            self.rig.press('A', self.advance_path(ref), {'request_id': 'eject-41'})
        first = self.rig.saved_advance('A', 'eject-41')
        self.assertEqual([event['number'] for event in first['actual']], [41])
        self.rig.reopen_press('A')
        self.assertEqual(self.advance(ref, 'eject-41'), first)
        self.assertEqual(self.rig.devices['A'].count_ejections(ref['run_id']), 1)
        for step in ['front', 'back', 'eject']:
            self.advance(ref, f'{step}-42')
        self.assertEqual(self.advance(ref, 'eject-41'), first)
        self.assertEqual(self.rig.devices['A'].count_ejections(ref['run_id']), 2)

    def test_device_commit_recovery(self):
        from http.client import RemoteDisconnected
        batch = self.batch(count=1)
        ref = self.dispatch(batch)
        self.advance(ref, 'front')
        self.advance(ref, 'back')
        self.rig.controls['A'].drop_after_effect.add('post-device-commit')
        with self.assertRaises(RemoteDisconnected):
            self.rig.press('A', self.advance_path(ref), {'request_id': 'post-device-commit'})
        events = self.rig.devices['A'].ejection_events()
        self.assertEqual(len(events), 1)
        self.assertIsNone(self.rig.saved_advance('A', 'post-device-commit'))
        self.assertEqual(self.progress(batch)['actual'], events)
        self.rig.reopen_press('A')
        result = self.advance(ref, 'post-device-commit')
        self.assertEqual(result['actual'], events)
        self.assertEqual(result['ejection_id'], events[0]['ejection_id'])
        self.assertEqual(result['action_id'], events[0]['action_id'])
        self.assertEqual(self.rig.devices['A'].ejection_events(), events)
        self.assertEqual(self.rig.saved_advance('A', 'post-device-commit'), result)

    def test_gapped_progress(self):
        batch = self.batch()
        ref = self.dispatch(batch)
        for stage in ('front', 'back', 'eject'):
            self.advance(ref, f'{stage}-41')
        self.rig.controls['A'].hold_before_arrival.add('delayed-42')
        self.assertEqual(self.rig.press('A', self.advance_path(ref), {'request_id': 'delayed-42'}),
                         (503, {'error': 'device_waiting'}))
        self.assertNotIn('delayed-42', self.rig.controls['A'].arrived)
        for stage in ('front', 'back', 'eject'):
            self.assertEqual(self.advance(ref, f'{stage}-43')['number'], 43)
        events = self.rig.devices['A'].ejection_events()
        expected = [41, 43]
        self.assertEqual([event['number'] for event in events], expected)
        progress = self.progress(batch)
        self.assertEqual(progress['actual'], events)
        self.assertEqual(progress['missing'], [42])
        self.assertEqual(self.progress(batch), progress)
        self.assertEqual(self.rig.devices['A'].ejection_events(), events)
        scenario('v5.gapped_progress', {'plan': [41, 42, 43], 'held_before_arrival': 42},
                 expected, [event['number'] for event in events], [42], progress['missing'],
                 ['press/queue.py', 'press/simulator.py', 'desk/progress.py'],
                 'Compare independent device events with the manually enumerated three-sheet plan.')
        self.rig.controls['A'].hold_before_arrival.remove('delayed-42')
        self.assertEqual(self.advance(ref, 'delayed-42')['number'], 42)
        self.advance(ref, 'back-42')
        self.advance(ref, 'eject-42')
        self.assertEqual([event['number'] for event in self.progress(batch)['actual']], [41, 42, 43])

    def test_advance_contract(self):
        first = self.dispatch(self.batch(count=1))
        second = self.dispatch(self.batch(count=1), request_id='dispatch-2')
        self.assertEqual(self.rig.press('A', '/runs/A-R404/advance', {'request_id': 'unbound'}),
                         (404, {'error': 'unknown_run'}))
        front = self.advance(first, 'unbound')
        self.assertEqual((front['stage'], front['ejection_id']), ('front', None))
        self.assertEqual(self.rig.press('A', self.advance_path(second), {'request_id': 'unbound'}),
                         (409, {'error': 'advance_request_conflict'}))
        back = self.advance(first, 'first-back')
        self.assertEqual((back['stage'], back['ejection_id']), ('back', None))
        self.assertEqual(self.rig.devices['A'].count_ejections(), 0)
        self.advance(first, 'first-eject')
        self.assertEqual(self.rig.press('A', self.advance_path(first), {'request_id': 'new-after-complete'}),
                         (409, {'error': 'run_complete'}))
        self.assertEqual(self.rig.devices['A'].count_ejections(first['run_id']), 1)
        self.assertEqual(self.rig.devices['A'].count_ejections(second['run_id']), 0)
