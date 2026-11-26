from contextlib import ExitStack
import json
from pathlib import Path
from tempfile import TemporaryDirectory

from desk.http import serve_desk
from desk.press_client import HttpPressClient, request_json
from press.http import running_server, serve_press
from press.simulator import SimulatedPress


def main():
    sample_path = Path(__file__).with_name('festival.json')
    sample = json.loads(sample_path.read_text(encoding='utf-8'))
    with TemporaryDirectory(prefix='print-festival-') as directory, ExitStack() as stack:
        root = Path(directory)
        devices = {name: SimulatedPress(root / f'{name}-device.sqlite', name) for name in ('A', 'B')}
        addresses = {
            name: stack.enter_context(running_server(serve_press(root / f'{name}-runs.sqlite', device)))
            for name, device in devices.items()
        }
        desk = stack.enter_context(running_server(serve_desk(root / 'desk.sqlite', sample_path,
                                                           HttpPressClient(addresses))))
        revision = request_json(desk, '/editions', sample['draft'])
        batch = request_json(desk, '/batches', {'revision_id': revision['revision_id'], **sample['batch']})
        prefix = '/batches/' + batch['batch_id']
        ref = request_json(desk, prefix + '/dispatch', {'press_id': 'A', 'request_id': 'festival-print'})
        for step in range(3 * sample['batch']['count']):
            request_json(addresses['A'], f"/runs/{ref['run_id']}/advance", {'request_id': f'print-{step + 1}'})
        actual = devices['A'].ejection_events(ref['run_id'])
        progress = request_json(desk, prefix + '/progress')
        assert len(actual) == 3 and devices['B'].count_ejections() == 0
        assert progress['actual'] == actual and progress['missing'] == []
        deviations = sample['deviations_mm']
        measurements = [{'ejection_id': event['ejection_id'], 'deviation_mm': deviations[str(event['number'])]}
                        for event in reversed(actual)]

        # The first 041 on the fresh press is A-P1.  With 3 mm it is out of the
        # frozen 2 mm tolerance, so the quality inspector returns it.
        returned = request_json(desk, prefix + '/scrap',
                                {'request_id': 'scrap-041', 'ejection_id': 'A-P1', 'deviation_mm': 3})
        assert (returned['number'], returned['ejection_id']) == (41, 'A-P1')
        after_return = request_json(desk, prefix + '/progress')
        assert after_return['missing'] == [41]
        assert after_return['retired'] == ['A-P1']
        assert [event['ejection_id'] for event in after_return['history']] == ['A-P1', 'A-P2', 'A-P3']
        assert [event['ejection_id'] for event in after_return['actual']] == ['A-P2', 'A-P3']

        # Reprint on the same run: still missing after front, then A-P4 on real ejection.
        request_json(addresses['A'], f"/runs/{ref['run_id']}/advance", {'request_id': 'reprint-front'})
        partial = request_json(desk, prefix + '/progress')
        assert partial['missing'] == [41], partial
        for stage in ('back', 'eject'):
            request_json(addresses['A'], f"/runs/{ref['run_id']}/advance",
                         {'request_id': f'reprint-{stage}'})
        completed = request_json(desk, prefix + '/progress')
        assert completed['missing'] == []
        assert [event['ejection_id'] for event in completed['actual']] == ['A-P4', 'A-P2', 'A-P3']
        run_read = request_json(addresses['A'], f"/runs/{ref['run_id']}")
        assert [event['ejection_id'] for event in run_read['actual']] == [
            'A-P1', 'A-P4', 'A-P2', 'A-P3']
        assert run_read['retired'] == ['A-P1']

        # The reprint's own measurement is the one accepted.
        final_measurements = [{'ejection_id': event['ejection_id'],
                               'deviation_mm': deviations[str(event['number'])]}
                              for event in completed['actual']]
        issued = request_json(desk, prefix + '/inspection', {'measurements': final_measurements})
        delivery = request_json(desk, prefix + '/delivery')
        assert issued == delivery
        rows = delivery['sheets']
        assert [row['print_number'] for row in rows] == ['041', '042', '043']
        assert [row['deviation_mm'] for row in rows] == [0, -2, 2]
        assert [row['ejection_id'] for row in rows] == ['A-P4', 'A-P2', 'A-P3']

        print(json.dumps({
            'sample': sample['draft']['draft_id'],
            'back_proof': revision['back_print'],
            'progress': progress,
            'returned': returned,
            'return_progress': after_return,
            'reprint_partial_progress': partial,
            'reprint_progress': completed,
            'reprint_run': run_read,
            'delivery': delivery,
        }, ensure_ascii=False, sort_keys=True))


if __name__ == '__main__':
    main()
