"""Small semantic terminal colors; redirected output and logs remain plain."""

import os
import sys

COLORS = {'info': '36', 'success': '32', 'warning': '33', 'error': '31', 'title': '1;36'}


def paint(message, tone='info', stream=None):
    stream = sys.stdout if stream is None else stream
    if 'NO_COLOR' in os.environ or os.environ.get('TERM') == 'dumb' or not stream.isatty():
        return str(message)
    return f'\033[{COLORS[tone]}m{message}\033[0m'


def say(message, tone='info'):
    print(paint(message, tone), flush=True)
