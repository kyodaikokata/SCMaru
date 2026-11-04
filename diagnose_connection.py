"""Read-only room connectivity check; never print or persist viewer messages."""
import argparse
import logging
import queue
import time
from connections import Collector

parser = argparse.ArgumentParser()
parser.add_argument('room')
args = parser.parse_args()
logging.getLogger('blivedm').setLevel(logging.CRITICAL)
out = queue.Queue()
collector = Collector(out)
collector.start('room', room=args.room)
end = time.monotonic() + 25
success = False
while time.monotonic() < end:
    try: kind, data = out.get(timeout=.3)
    except queue.Empty: continue
    if kind in ('room', 'reconnecting', 'error', 'stopped', 'warning'): print(kind, data if kind != 'room' else data['room'], flush=True)
    if kind == 'heartbeat':
        print('Server heartbeat received: connection authenticated.', flush=True)
        success = True
        break
collector.stop()
if collector.thread: collector.thread.join(timeout=12)
print('Result:', 'connected' if success else 'not authenticated within 25 seconds')
