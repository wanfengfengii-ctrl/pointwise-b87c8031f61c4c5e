from http.client import RemoteDisconnected

from tests.workshop import WorkshopTest


class TestHttp(WorkshopTest):
    def test_late_device_action_after_lost_reply(self):
        batch = self.batch()
        ref = self.dispatch(batch)
        device = self.rig.devices['A']
        controls = self.rig.controls['A']
        path = self.advance_path(ref)
        self.advance(ref, 'one-front')
        self.advance(ref, 'one-back')
        controls.drop_after_effect.add('one-eject')
        with self.assertRaises(RemoteDisconnected):
            self.rig.press('A', path, {'request_id': 'one-eject'})
        first_event = device.ejection_events()[0]
        self.assertEqual(first_event['number'], 41)
        self.assertIsNone(self.rig.saved_advance('A', 'one-eject'))

        controls.hold_before_arrival.add('two-front')
        self.assertEqual(self.rig.press('A', path, {'request_id': 'two-front'})[0], 503)
        self.assertNotIn('two-front', controls.arrived)
        self.assertEqual(self.advance(ref, 'three-front')['number'], 43)
        self.assertEqual(self.advance(ref, 'three-back')['number'], 43)
        controls.hold_before_effect.add('three-eject')
        self.assertEqual(self.rig.press('A', path, {'request_id': 'three-eject'})[0], 503)
        in_device = controls.arrived['three-eject']
        self.assertEqual((in_device.batch_id, in_device.number, in_device.stage), (batch['batch_id'], 43, 'ejected'))
        self.assertEqual(device.count_ejections(), 1)
        self.assertEqual(self.progress(batch)['missing'], [42, 43])
        self.assertEqual(self.pickup(batch), (409, {'error': 'incomplete'}))

        controls.hold_before_arrival.remove('two-front')
        delayed = self.advance(ref, 'two-front')
        self.assertEqual((delayed['number'], delayed['stage']), (42, 'front'))
        self.assertEqual(self.advance(ref, 'two-front'), delayed)
        self.advance(ref, 'two-back')
        self.assertEqual(self.advance(ref, 'two-eject')['number'], 42)
        self.assertEqual([event['number'] for event in device.ejection_events()], [41, 42])
        self.assertEqual(self.progress(batch)['missing'], [43])
        self.assertEqual(self.rig.devices['B'].count_ejections(), 0)

        self.rig.reopen_press('A')
        self.rig.reopen_desk()
        self.assertEqual(self.advance(ref, 'one-eject')['ejection_id'], first_event['ejection_id'])
        self.assertEqual(self.advance(ref, 'three-eject')['action_id'], in_device.action_id)
        events = self.rig.devices['A'].ejection_events()
        self.assertEqual([event['number'] for event in events], [41, 42, 43])
        self.assertEqual(self.progress(batch)['actual'], events)

    def test_progress_and_pickup_for_unstarted_batches(self):
        batch = self.batch()
        self.assertEqual(self.progress(batch), {'batch_id': batch['batch_id'], 'press_id': None, 'run_id': None,
                                                'actual': [], 'missing': [41, 42, 43]})
        self.assertEqual(self.pickup(batch), (409, {'error': 'incomplete'}))
        self.assertEqual(self.rig.desk('/batches/B404/progress'), (404, {'error': 'unknown_batch'}))
        self.assertEqual(self.rig.desk('/batches/B404/delivery'), (404, {'error': 'unknown_batch'}))
