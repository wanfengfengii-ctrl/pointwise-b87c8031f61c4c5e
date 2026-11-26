from tests.workshop import WorkshopTest, scenario


def measurement(event, deviation):
    return {'ejection_id': event['ejection_id'], 'deviation_mm': deviation}


class TestDelivery(WorkshopTest):
    def test_partial_duplex(self):
        batch, ref = self.whole_run(steps=7)
        events = self.rig.devices['A'].ejection_events(ref['run_id'])
        self.assertEqual([event['number'] for event in events], [41, 42])
        self.assertEqual(self.progress(batch)['missing'], [43])
        self.assertEqual(self.inspect(batch, [measurement(event, 0) for event in events]),
                         (409, {'error': 'incomplete'}))
        self.assertEqual(self.pickup(batch), (409, {'error': 'incomplete'}))

    def test_before_ejection(self):
        batch, ref = self.whole_run(steps=7)
        events = self.rig.devices['A'].ejection_events(ref['run_id'])
        measurements = [measurement(event, 0) for event in events]
        self.assertEqual([event['number'] for event in events], [41, 42])
        self.assertEqual(self.inspect(batch, measurements), (409, {'error': 'incomplete'}))
        result = self.advance(ref, 'back-last')
        self.assertEqual((result['number'], result['stage'], result['ejection_id']), (43, 'back', None))
        self.assertEqual(self.rig.devices['A'].ejection_events(ref['run_id']), events)
        self.assertEqual(self.inspect(batch, measurements), (409, {'error': 'incomplete'}))
        self.assertEqual(self.pickup(batch), (409, {'error': 'incomplete'}))
        self.advance(ref, 'eject-last')
        self.assertEqual(self.pickup(batch), (409, {'error': 'not_inspected'}))

    def test_pickup_after_restart(self):
        batch, ref = self.whole_run()
        events = self.rig.devices['A'].ejection_events(ref['run_id'])
        self.assertEqual([event['number'] for event in events], [41, 42, 43])
        measurements = [measurement(event, deviation) for event, deviation in zip(events, [0, -2, 2])]
        status, issued = self.inspect(batch, measurements)
        self.assertEqual(status, 200, issued)
        self.rig.reopen_desk()
        self.rig.reopen_press('A')
        status, actual = self.pickup(batch)
        self.assertEqual((status, actual), (200, issued))
        expected_rows = [[label, event['ejection_id'], 'A', deviation]
                         for label, event, deviation in zip(['041', '042', '043'], events, [0, -2, 2])]
        actual_rows = [[row['print_number'], row['ejection_id'], row['press_id'], row['deviation_mm']]
                       for row in actual['sheets']]
        self.assertEqual(actual_rows, expected_rows)
        self.assertEqual(actual['batch_id'], batch['batch_id'])
        scenario('v7', {'measurements': measurements, 'tolerance_mm': 2}, expected_rows, actual_rows,
                 issued, actual, ['delivery/coverage.py', 'delivery/inspection.py', 'delivery/release.py',
                                  'delivery/pickup.py'],
                 'Frozen fixture numbers, physical event IDs, and independently chosen signed edge values.')

    def test_measurement_ids(self):
        batch, ref = self.whole_run()
        other = self.batch(count=1)
        other_ref = self.dispatch(other, request_id='dispatch-other')
        for stage in ('front', 'back', 'eject'):
            self.advance(other_ref, f'other-{stage}')
        foreign = self.rig.devices['A'].ejection_events(other_ref['run_id'])[0]
        original = self.rig.devices['A'].ejection_events(ref['run_id'])
        first, second, third = original
        cases = [
            [measurement(first, -1), measurement(second, 2), measurement(foreign, 1)],
            [measurement(first, -1), measurement(second, 2), measurement(first, 1)],
            [measurement(first, -1), measurement(second, 2)],
            [measurement(first, -1), measurement(second, 2), measurement(third, None)],
            [measurement(first, -1), measurement(second, 2), measurement(third, True)],
            [measurement(first, -1), measurement(second, 2), measurement(third, 1.0)],
        ]
        for invalid in cases:
            with self.subTest(invalid=invalid):
                self.assertEqual(self.inspect(batch, invalid), (409, {'error': 'measurement_coverage'}))
        self.assertEqual(self.pickup(batch), (409, {'error': 'not_inspected'}))
        valid = [measurement(third, 1), measurement(first, -1), measurement(second, 2)]
        status, issued = self.inspect(batch, valid)
        self.assertEqual(status, 200, issued)
        self.assertEqual(issued['delivery_id'], 'D1')
        self.assertEqual([(row['number'], row['ejection_id'], row['deviation_mm']) for row in issued['sheets']],
                         [(41, first['ejection_id'], -1), (42, second['ejection_id'], 2), (43, third['ejection_id'], 1)])
        self.assertEqual(self.inspect(batch, list(reversed(valid))), (200, issued))
        changed = [measurement(third, 0), *valid[1:]]
        self.assertEqual(self.inspect(batch, changed), (409, {'error': 'inspection_already_issued'}))
        self.assertEqual(self.pickup(batch), (200, issued))

    def test_pickup_without_press(self):
        batch, ref = self.whole_run()
        events = self.rig.devices['A'].ejection_events(ref['run_id'])
        status, issued = self.inspect(batch, [measurement(event, 0) for event in events])
        self.assertEqual(status, 200, issued)
        self.rig.stop_press('A')
        self.rig.reopen_desk()
        self.assertEqual(self.rig.desk(self.batch_path(batch, 'progress'))[0], 503)
        self.assertEqual(self.pickup(batch), (200, issued))
        self.assertEqual(self.pickup(batch), (200, issued))

    def test_out_of_tolerance(self):
        batch, ref = self.whole_run()
        events = self.rig.devices['A'].ejection_events(ref['run_id'])
        measurements = [measurement(event, deviation) for event, deviation in zip(events, [0, 2, 3])]
        self.assertEqual(self.inspect(batch, measurements), (422, {'error': 'registration_out_of_tolerance'}))
        self.assertEqual(self.progress(batch)['actual'], events)
        self.assertEqual(self.pickup(batch), (409, {'error': 'not_inspected'}))

    def test_negative_overage(self):
        batch, ref = self.whole_run()
        events = self.rig.devices['A'].ejection_events(ref['run_id'])
        bad = [measurement(event, deviation) for event, deviation in zip(events, [0, -2, -3])]
        self.assertEqual(self.inspect(batch, bad), (422, {'error': 'registration_out_of_tolerance'}))
        self.assertEqual(self.pickup(batch), (409, {'error': 'not_inspected'}))
        self.assertEqual(self.progress(batch)['actual'], events)
        good = [measurement(event, deviation) for event, deviation in zip(events, [0, -2, 2])]
        status, issued = self.inspect(batch, good)
        self.assertEqual(status, 200, issued)
        self.assertEqual(issued['delivery_id'], 'D1')
        self.assertEqual([row['deviation_mm'] for row in issued['sheets']], [0, -2, 2])
