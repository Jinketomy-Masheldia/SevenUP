"""Native transfer progress, streamed diagnostics, and safe operation labels."""

import io
import sys
import subprocess
import unittest

from iphone7_port.core import command_display
from iphone7_port.process import live_run


class ProcessTests(unittest.TestCase):
    def test_terminal_child_is_foreground_for_the_native_progress_meter(self):
        output = io.StringIO()
        code = 'import os;print(os.isatty(2),os.tcgetpgrp(2)==os.getpgrp())'
        result = live_run([sys.executable, '-c', code], timeout=5, stream=output, terminal=True)
        self.assertEqual(result.returncode, 0)
        self.assertIn('True True', output.getvalue())

    def test_large_script_input_does_not_deadlock_live_output(self):
        output = io.StringIO()
        code = 'import sys;print("start",flush=True);s=sys.stdin.read();print(len(s));sys.exit(7)'
        result = live_run([sys.executable, '-c', code], input='x' * 200000, timeout=5, stream=output, terminal=True)
        self.assertEqual(result.returncode, 7)
        self.assertIn('start', output.getvalue())
        self.assertIn('200000', result.stdout)

    def test_redirected_output_is_streamed_and_timeout_stops_the_child(self):
        output = io.StringIO()
        result = live_run([sys.executable, '-c', 'import sys;print("out");print("error",file=sys.stderr)'], timeout=5,
                          stream=output, terminal=False)
        self.assertEqual(result.returncode, 0)
        self.assertIn('out', output.getvalue())
        self.assertIn('error', output.getvalue())
        with self.assertRaises(subprocess.TimeoutExpired):
            live_run([sys.executable, '-c', 'import time;time.sleep(5)'], timeout=0.1, stream=output, terminal=True)

    def test_labels_show_operations_without_password_or_device_identifier(self):
        ssh = ['/bundle/sshpass', '-e', 'ssh', '-F', '/dev/null', 'root@127.0.0.1', '/sbin/newfs_apfs -A /dev/disk0s1']
        self.assertIn('newfs_apfs', command_display(ssh, True))
        self.assertEqual(command_display(['scp', '-O', 'root.dmg', 'root@127.0.0.1:/mnt8/root.dmg'], True),
                         'scp root.dmg -> root@127.0.0.1:/mnt8/root.dmg')
        display = command_display(['/bundle/irecovery', '-i', '0x123456789', '-c', 'bootx'], True)
        self.assertIn('bootx', display)
        self.assertNotIn('0x123456789', display)


if __name__ == '__main__':
    unittest.main()
