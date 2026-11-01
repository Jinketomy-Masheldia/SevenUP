"""Stream long-running tool output, using a terminal for native SCP progress."""

import codecs
import errno
import fcntl
import os
import pty
import select
import signal
import struct
import subprocess
import sys
import termios
import threading
import time
import shutil


def live_run(command, *, timeout, env=None, cwd=None, input=None, stream=None, terminal=None):
    stream = sys.stdout if stream is None else stream
    terminal = stream.isatty() if terminal is None else terminal
    master = slave = None
    options = {}
    if terminal:
        master, slave = pty.openpty()
        width, height = shutil.get_terminal_size((100, 24))
        fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack('HHHH', height, width, 0, 0))
        options = {'stdout': slave, 'stderr': slave,
                   'preexec_fn': lambda: fcntl.ioctl(1, termios.TIOCSCTTY, 0)}
    else:
        options = {'stdout': subprocess.PIPE, 'stderr': subprocess.STDOUT}
    process = None
    captured = []
    writer = None
    try:
        process = subprocess.Popen(command, stdin=subprocess.PIPE if input is not None else subprocess.DEVNULL,
                                   env=env, cwd=cwd, start_new_session=True, **options)
        if slave is not None:
            os.close(slave)
            slave = None
        if input is not None:
            payload = input.encode() if isinstance(input, str) else input
            def feed():
                try:
                    process.stdin.write(payload)
                    process.stdin.flush()
                except (BrokenPipeError, OSError):
                    pass
                finally:
                    try:
                        process.stdin.close()
                    except (BrokenPipeError, OSError):
                        pass
            writer = threading.Thread(target=feed, daemon=True)
            writer.start()
        descriptor = master if terminal else process.stdout.fileno()
        decoder = codecs.getincrementaldecoder('utf-8')(errors='replace')
        deadline = time.monotonic() + timeout
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise subprocess.TimeoutExpired(command, timeout, output=''.join(captured))
            ready, _, _ = select.select([descriptor], [], [], min(0.1, remaining))
            if ready:
                try:
                    data = os.read(descriptor, 65536)
                except OSError as exc:
                    if terminal and exc.errno == errno.EIO:
                        break
                    raise
                if not data:
                    break
                text = decoder.decode(data)
                captured.append(text)
                stream.write(text)
                stream.flush()
            elif process.poll() is not None:
                break
        tail = decoder.decode(b'', final=True)
        if tail:
            captured.append(tail)
            stream.write(tail)
            stream.flush()
        code = process.wait(timeout=max(0.1, deadline - time.monotonic()))
        if writer is not None:
            writer.join(timeout=1)
        return subprocess.CompletedProcess(command, code, ''.join(captured), '')
    finally:
        if process is not None and process.poll() is None:
            try:
                os.killpg(process.pid, signal.SIGTERM)
                process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL)
                process.wait()
            except ProcessLookupError:
                process.wait()
        if process is not None and process.stdout is not None:
            process.stdout.close()
        for descriptor in (master, slave):
            if descriptor is not None:
                os.close(descriptor)
