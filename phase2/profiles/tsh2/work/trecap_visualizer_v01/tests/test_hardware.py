"""Hardware lifecycle guards using only injected receipts; no board access.

Every test blocks subprocess and socket entry points. Mock receipts are marked
test-only and never written into the visualizer's physical evidence directory.
"""
import hashlib
import json
import struct
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import hardware


BOOT = '11111111-2222-3333-4444-555555555555'
OTHER_BOOT = 'aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee'
PCM = bytes(1536000)
PCM_SHA = hashlib.sha256(PCM).hexdigest()


def receipt(*bodies):
    return {'status': 'PASS', 'closed': True, 'test_only': True,
            'records': [{'response_body': text} for text in bodies]}


def preflight(boot=BOOT, idle='  sl local_address rem_address st\n'):
    return receipt(boot + '\nrootfs / rootfs rw 0 0\n', idle)


def admitted(source=hardware.SOURCE, epoch=48):
    return receipt('mock hashes verified',
                   json.dumps({'status': 'PASS_HPS_SYSTEM_STATE_ONLY',
                               'bridge_reset': 5, 'manager_mode': 4}),
                   json.dumps({'status': 'PASS_TSH2_READ_ONLY_IDLE',
                               'source_id': source, 'epoch': epoch,
                               'writes_performed': False,
                               'fifo_pop_performed': False}))


class HardwareGuards(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.manifest = self.root / 'manifest.json'
        self.meta = {'source_id': hardware.SOURCE, 'sof_sha256': hardware.SOF,
                     'service_sha256': hardware.SERVICE_SHA,
                     'fpga_probe_sha256': hardware.FPGA_PROBE_SHA,
                     'boot_id': BOOT, 'target': '/tmp/trecap-visualizer-1234abcd'}
        self.write_manifest()
        self.hw = hardware.Hardware(self.manifest)
        self.subprocess_guard = patch.object(hardware.subprocess, 'run',
                                             side_effect=AssertionError('Real process launch forbidden in test'))
        self.socket_guard = patch.object(hardware.socket, 'create_connection',
                                         side_effect=AssertionError('Real network forbidden in test'))
        self.subprocess = self.subprocess_guard.start()
        self.socket = self.socket_guard.start()
        self.uart_guard = patch.object(hardware, 'uart',
                                       side_effect=AssertionError('A test must supply its own fake UART receipt'))
        self.uart = self.uart_guard.start()

    def tearDown(self):
        self.uart_guard.stop()
        self.socket_guard.stop()
        self.subprocess_guard.stop()
        self.tmp.cleanup()

    def write_manifest(self):
        self.manifest.write_text(json.dumps(self.meta), encoding='utf-8')

    def assert_no_real_io(self):
        self.subprocess.assert_not_called()
        self.socket.assert_not_called()

    def test_wrong_boot_stops_before_aperture_plan(self):
        self.uart.return_value = preflight(OTHER_BOOT)
        self.uart.side_effect = None
        with self.assertRaisesRegex(RuntimeError, 'Board rebooted'):
            self.hw._verify(self.root / 'verify')
        self.assertEqual(self.uart.call_count, 1)
        self.assertEqual(self.uart.call_args.args[1], 'admission_preflight')
        commands = ' '.join(x['command'] for x in self.uart.call_args.args[2])
        self.assertNotIn('tsh2_probe.arm', commands)
        self.assertNotIn('system_probe.arm', commands)
        self.assert_no_real_io()

    def test_ambiguous_boot_stops_before_aperture_plan(self):
        self.uart.side_effect = None
        self.uart.return_value = preflight(BOOT + '\n' + OTHER_BOOT)
        with self.assertRaisesRegex(RuntimeError, 'Exactly one observed boot'):
            self.hw._verify(self.root / 'verify')
        self.assertEqual(self.uart.call_count, 1)
        self.assert_no_real_io()

    def test_active_listener_stops_before_aperture_plan(self):
        self.uart.side_effect = None
        self.uart.return_value = preflight(idle='0: 80C4FEA9:46A2 00000000:0000 0A 00000000:00000000\n')
        with self.assertRaisesRegex(RuntimeError, 'TCP listener'):
            self.hw._verify(self.root / 'verify')
        self.assertEqual(self.uart.call_count, 1)
        self.assert_no_real_io()

    def test_active_controller_stops_before_aperture_plan(self):
        self.uart.side_effect = None
        self.uart.return_value = preflight(idle='/proc/99 service.arm\n/tmp/other/service.arm\x00--execute-hardware\n')
        with self.assertRaisesRegex(RuntimeError, 'board capture'):
            self.hw._verify(self.root / 'verify')
        self.assertEqual(self.uart.call_count, 1)
        self.assert_no_real_io()

    def test_valid_inventory_precedes_system_and_fpga_probe(self):
        self.uart.side_effect = [preflight(), admitted()]
        _, value = self.hw._verify(self.root / 'verify')
        calls = self.uart.call_args_list
        self.assertEqual([c.args[1] for c in calls], ['admission_preflight', 'admission'])
        commands = [s['command'] for s in calls[1].args[2]]
        self.assertIn('sha256sum -c', commands[0])
        self.assertIn('system_probe.arm --require-lw-only', commands[1])
        self.assertIn('timeout -s KILL 10', commands[2])
        self.assertIn('tsh2_probe.arm --read-only --source ' + hardware.SOURCE, commands[2])
        self.assertTrue(self.hw.available)
        self.assertEqual(value['epoch'], 48)
        self.assert_no_real_io()

    def test_connect_source_mismatch_latches_unavailable_and_releases_lock(self):
        self.hw.available = True
        self.uart.side_effect = [preflight(), admitted(source='0' * 64)]
        with self.assertRaisesRegex(RuntimeError, 'FPGA identity'):
            self.hw.connect()
        self.assertFalse(self.hw.available)
        self.assertFalse(self.hw.lock.locked())
        self.assertEqual(self.uart.call_count, 2)
        self.assert_no_real_io()

    def test_failed_preflight_does_not_launch_or_retry_service(self):
        self.hw.available = True
        self.uart.side_effect = None
        self.uart.return_value = preflight(OTHER_BOOT)
        folder = self.root / 'capture'
        with self.assertRaisesRegex(RuntimeError, 'Board rebooted'):
            self.hw.capture(PCM, 10000000, PCM_SHA, folder)
        self.assertEqual(self.uart.call_count, 1)
        self.assertFalse(self.hw.available)
        self.assertFalse(self.hw.lock.locked())
        failure = json.loads((folder / 'failure.json').read_text())
        self.assertEqual(failure['status'], 'FAIL_NO_AUTOMATIC_MMIO_RECOVERY')
        self.assert_no_real_io()

    def test_existing_capture_directory_releases_lock_without_board_access(self):
        folder = self.root / 'already_exists'
        folder.mkdir()
        sentinel = folder / 'prior.bin'
        sentinel.write_bytes(b'Preserve existing evidence')
        self.hw.available = True
        with self.assertRaises(FileExistsError):
            self.hw.capture(PCM, 10000000, PCM_SHA, folder)
        self.assertFalse(self.hw.lock.locked())
        self.assertFalse(self.hw.available)
        self.assertEqual(sentinel.read_bytes(), b'Preserve existing evidence')
        self.uart.assert_not_called()
        self.assert_no_real_io()

    def test_mkdir_permission_failure_releases_lock_without_board_access(self):
        folder = self.root / 'inaccessible'
        with patch.object(Path, 'mkdir', side_effect=PermissionError('Injected mkdir denial')):
            with self.assertRaisesRegex(PermissionError, 'Injected mkdir denial'):
                self.hw.capture(PCM, 10000000, PCM_SHA, folder)
        self.assertFalse(self.hw.lock.locked())
        self.assertFalse(self.hw.available)
        self.uart.assert_not_called()
        self.assert_no_real_io()

    def test_concurrent_capture_rejected_without_releasing_other_owners_lock(self):
        self.hw.lock.acquire()
        try:
            with self.assertRaisesRegex(RuntimeError, 'Concurrent board access'):
                self.hw.capture(PCM, 10000000, PCM_SHA, self.root / 'other')
            self.assertTrue(self.hw.lock.locked())
            self.uart.assert_not_called()
            self.assert_no_real_io()
        finally:
            self.hw.lock.release()

    def test_manifest_identity_fields_fail_closed_before_hardware(self):
        cases = [('source_id', '0' * 64), ('sof_sha256', '0' * 64),
                 ('service_sha256', '0' * 64), ('fpga_probe_sha256', '0' * 64),
                 ('fpga_probe_sha256', 'x; unsafe shell text'),
                 ('boot_id', BOOT + '; unsafe shell text'),
                 ('boot_id', 'not-a-uuid'), ('target', '/tmp/arbitrary'),
                 ('target', '/tmp/trecap-visualizer-1234abcd; unsafe shell text')]
        original = dict(self.meta)
        for field, value in cases:
            with self.subTest(field=field, value=value):
                self.meta = {**original, field: value}
                self.write_manifest()
                with self.assertRaises(RuntimeError):
                    hardware.Hardware(self.manifest)
        self.uart.assert_not_called()
        self.assert_no_real_io()

    def test_input_hash_and_threshold_rejected_before_hardware(self):
        for threshold, digest in ((True, PCM_SHA), (-1, PCM_SHA), (1 << 56, PCM_SHA), (10000000, '0' * 64)):
            with self.subTest(threshold=threshold, digest=digest):
                with self.assertRaises(RuntimeError):
                    self.hw.capture(PCM, threshold, digest, self.root / 'never_created')
        self.assertFalse(self.hw.lock.locked())
        self.uart.assert_not_called()
        self.assert_no_real_io()

    def test_capture_progress_follows_real_socket_boundaries_and_measured_bytes(self):
        threshold, epoch, wall, cpu = 10000000, 49, 500000000, 490000000
        y, wire = bytes(1538048), bytes(64)
        header = struct.pack('<IIIIQQQ', 0x31535254, 0, len(y), len(wire), epoch, wall, cpu)
        events = []

        class SocketFixture:
            def __init__(self):
                self.payload = header + y + wire
                self.position = 0
                self.sent = None

            def __enter__(self): return self
            def __exit__(self, *args): pass
            def settimeout(self, seconds): pass
            def shutdown(self, how): pass

            def sendall(self, raw):
                assert events[-1]['phase'] == 'sending'
                assert events[-1]['completed_bytes'] == 0
                self.sent = raw

            def recv(self, count):
                if self.position < 40:
                    assert events[-1]['phase'] == 'processing'
                else:
                    assert events[-1]['phase'] == 'receiving'
                result = self.payload[self.position:self.position + min(count, 65536)]
                self.position += len(result)
                return result

        fixture = SocketFixture()
        self.socket.side_effect = None
        self.socket.return_value = fixture
        finish = receipt('\n'.join(json.dumps(value) for value in [
            {'status': 'LISTENING_FINITE', 'requests': 1, 'boot_id': BOOT, 'source_id': hardware.SOURCE},
            {'sequence': 0, 'success': True, 'reply_sent': True, 'epoch': epoch,
             'threshold': threshold, 'board_wall_ns': wall, 'board_thread_ns': cpu},
            {'status': 'COMPLETED_FINITE_SERVICE'}]))

        def uart_fixture(folder, name, steps):
            phase = events[-1]['phase']
            if name == 'admission_preflight':
                self.assertEqual(phase, 'admission')
                return preflight()
            if name == 'admission': return admitted()
            if name == 'start':
                self.assertEqual(phase, 'starting')
                return receipt('fake started')
            self.assertEqual(phase, 'verifying')
            if name == 'finish': return finish
            if name == 'final_preflight': return preflight()
            if name == 'final': return admitted(epoch=epoch)
            raise AssertionError('Unexpected fake UART stage ' + name)

        self.uart.side_effect = uart_fixture
        result = self.hw.capture(PCM, threshold, PCM_SHA, self.root / 'progress-capture', events.append)
        self.assertEqual(fixture.sent, struct.pack('<IQI', 0x31515254, threshold, len(PCM)) + PCM)
        self.assertEqual(result['y_bytes'], y)
        self.assertEqual(result['wire_bytes'], wire)
        transitions = []
        for event in events:
            if not transitions or event['phase'] != transitions[-1]: transitions.append(event['phase'])
        self.assertEqual(transitions, ['admission', 'starting', 'sending', 'processing', 'receiving', 'verifying'])
        received = [event for event in events if event['phase'] == 'receiving']
        self.assertEqual(received[0]['completed_bytes'], 0)
        self.assertEqual(received[-1]['completed_bytes'], len(y) + len(wire))
        self.assertTrue(all(event['total_bytes'] == len(y) + len(wire) for event in received))
        self.assertEqual([event['completed_bytes'] for event in received],
                         sorted(set(event['completed_bytes'] for event in received)))
        self.assertEqual(self.socket.call_count, 1)
        self.subprocess.assert_not_called()

    def test_invalid_header_never_reports_receiving_or_completed_processing(self):
        events = []

        class BadReply:
            def __enter__(self): return self
            def __exit__(self, *args): pass
            def settimeout(self, seconds): pass
            def shutdown(self, how): pass
            def sendall(self, raw): pass
            def recv(self, count): return bytes(count)

        self.uart.side_effect = [preflight(), admitted(), receipt('fake started')]
        self.socket.side_effect = None
        self.socket.return_value = BadReply()
        with self.assertRaisesRegex(RuntimeError, 'reply status/geometry'):
            self.hw.capture(PCM, 10000000, PCM_SHA, self.root / 'bad-reply', events.append)
        self.assertEqual(events[-1]['phase'], 'processing')
        self.assertNotIn('receiving', [event['phase'] for event in events])
        self.assertFalse(self.hw.available)
        self.assertEqual(self.uart.call_count, 3)
        self.subprocess.assert_not_called()


if __name__ == '__main__':
    unittest.main()
