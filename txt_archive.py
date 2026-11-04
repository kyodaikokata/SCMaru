"""Read SCMaru TXT exports into isolated, restorable history entries."""
from datetime import datetime
from decimal import Decimal
import hashlib
import re
import time


HEADER = re.compile(r'Room: ([\w-]+) \| Source: ([\w-]+)')
START = re.compile(r'Start: (\S+) \((broadcast|capture start; broadcast start unknown)\)')
ENTRY = re.compile(
    r'^\[(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d)\] '
    r'(○|△|□|未处理 / 未確認)(.*?) \| (.+) \| (\d+(?:\.\d{1,2})?) 电池 / 電池\n'
    r'ID: (.+?) \| User: (.+)\n', re.MULTILINE
)
MARKS = {'○': 'circle', '△': 'triangle', '□': 'square', '未处理 / 未確認': ''}
MAX_BYTES = 8 * 1024 * 1024


def import_file(ledger, path):
    with path.open('rb') as stream:
        data = stream.read(MAX_BYTES + 1)
    if len(data) > MAX_BYTES:
        return False
    text = data.decode('utf-8-sig').replace('\r\n', '\n')
    lines = text.split('\n', 4)
    if len(lines) < 5 or lines[0] != 'SCMaru / SC archive' or not lines[3].startswith('Timezone: '):
        return False
    header, start = HEADER.fullmatch(lines[1]), START.fullmatch(lines[2])
    if not header or not start:
        return False
    room, source = header.groups()
    if source.startswith('txt-'):
        return False
    date, origin = start.groups()
    for session in ledger.db.execute('SELECT id FROM sessions WHERE room=? AND source=?', (room, source)):
        if path.name == f"{date}_{room}_{source}_{session['id'][:6]}_SC.txt":
            return False
    body = lines[4].lstrip('\n')
    entries = list(ENTRY.finditer(body))
    if not entries or entries[0].start():
        return False
    session_id = hashlib.sha256(text.encode('utf-8')).hexdigest()
    if ledger.db.execute('SELECT 1 FROM sessions WHERE id=?', (session_id,)).fetchone():
        return False
    started = int(datetime.strptime(date, '%Y-%m-%d_%H-%M-%S').timestamp())
    archive_id = session_id + '-archive'
    now = int(time.time())
    events = []
    for index, entry in enumerate(entries):
        stamp, mark, flags, name, amount, external_id, user = entry.groups()
        next_entry = entries[index + 1] if index + 1 < len(entries) else None
        end = next_entry.start() if next_entry else len(body)
        message = body[entry.end():end].removesuffix('\n\n' if next_entry else '\n')
        events.append((
            f'{session_id}:{index}', external_id, session_id, room, 'txt-' + source, 'sc',
            user, name, int(datetime.strptime(stamp, '%Y-%m-%d %H:%M:%S').timestamp()),
            int(Decimal(amount) * 100), message,
            '', MARKS[mark], int('[AUTO]' in flags), int('[REMOVED BY PLATFORM]' in flags), archive_id,
        ))
    with ledger.db:
        result = ledger.db.execute('INSERT OR IGNORE INTO sessions VALUES (?,?,?,?,?,?)',
                                   (session_id, room, 'txt-' + source, started, int(origin == 'broadcast'), now))
        if not result.rowcount:
            return False
        ledger.db.execute('INSERT INTO archives VALUES (?,?,?,?,0)',
                          (archive_id, session_id, now, 'TXT · ' + path.name))
        ledger.db.executemany(
            '''INSERT INTO events (id,external_id,session,room,source,kind,user,name,ts,amount,text,
                                   note,mark,automatic,deleted,batch)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''', events
        )
    return True
