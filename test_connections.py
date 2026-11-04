"""Exercise actual WebSocket decoding against a local mock, never public rooms."""
import asyncio
import dataclasses
import json
import queue
import struct
import time
import unittest
from unittest.mock import patch, AsyncMock

from aiohttp import web, WSMsgType
import blivedm
from blivedm.models import open_live, web as web_models
from blivedm.clients.ws_base import Operation
import blivedm.clients.open_live as official_client

from connections import Collector


def packet(operation, value):
    body = value if isinstance(value, bytes) else json.dumps(value).encode()
    return struct.pack('>IHHII', len(body) + 16, 16, 0 if operation == 5 else 1, operation, 1) + body


class TransportTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.info_patch = patch('connections.room_info', new=AsyncMock(return_value=dict(live=True, timestamp=int(time.time()))))
        self.info_patch.start()
        self.name_patch = patch('connections.room_anchor_name', new=AsyncMock(return_value='Room Streamer'))
        self.name_patch.start()
        self.calls = []
        self.messages = []
        self.out = queue.Queue()
        self.collector = Collector(self.out)
        app = web.Application()
        app.router.add_post('/v2/app/{action}', self.api)
        app.router.add_get('/ws', self.ws)
        self.runner = web.AppRunner(app)
        await self.runner.setup()
        self.site = web.TCPSite(self.runner, '127.0.0.1', 0)
        await self.site.start()
        self.port = self.site._server.sockets[0].getsockname()[1]
        self.base = f'http://127.0.0.1:{self.port}'
        self.endpoint_patches = [patch.object(official_client, name, self.base + '/v2/app/' + action)
                                 for name, action in [('START_URL', 'start'), ('END_URL', 'end'), ('HEARTBEAT_URL', 'heartbeat')]]
        for p in self.endpoint_patches: p.start()

    async def asyncTearDown(self):
        self.collector.stop()
        for _ in range(100):
            if not self.collector.running: break
            await asyncio.sleep(.02)
        await self.runner.cleanup()
        self.info_patch.stop()
        self.name_patch.stop()
        for p in self.endpoint_patches: p.stop()
        self.assertFalse(self.collector.running)

    async def api(self, request):
        action = request.match_info['action']
        body = await request.json()
        self.calls.append((action, body))
        import hashlib, hmac
        signed = {k.lower(): v for k, v in request.headers.items() if k.lower().startswith('x-bili-')}
        expected = hmac.new(b'unit-secret', '\n'.join(f'{k}:{signed[k]}' for k in sorted(signed)).encode(), hashlib.sha256).hexdigest()
        self.assertEqual(request.headers.get('Authorization'), expected)
        if action == 'start':
            data = {'game_info': {'game_id': 'mock-game'},
                    'websocket_info': {'auth_body': '{}', 'wss_link': [self.base.replace('http:', 'ws:') + '/ws']},
                    'anchor_info': {'room_id': 123, 'uid': 1, 'open_id': 'owner', 'uname': 'Official Streamer'}}
        else:
            data = {}
        return web.json_response({'code': 0, 'message': '', 'data': data})

    async def ws(self, request):
        ws = web.WebSocketResponse()
        await ws.prepare(request)
        async for msg in ws:
            if msg.type != WSMsgType.BINARY: continue
            op = struct.unpack('>IHHII', msg.data[:16])[3]
            if op == Operation.AUTH:
                await ws.send_bytes(packet(Operation.AUTH_REPLY, {'code': 0}))
                for cmd in self.messages:
                    await ws.send_bytes(packet(Operation.SEND_MSG_REPLY, cmd))
            elif op == Operation.HEARTBEAT:
                await ws.send_bytes(packet(Operation.HEARTBEAT_REPLY, b'\0\0\0\0'))
        return ws

    async def received(self, expected=1):
        rows = []
        for _ in range(200):
            while not self.out.empty(): rows.append(self.out.get_nowait())
            if sum(kind == 'event' for kind, data in rows) >= expected and any(k == 'heartbeat' for k, d in rows):
                return rows
            await asyncio.sleep(.01)
        self.fail(f'No expected events: {rows}')

    async def test_official_signed_start_raw_events_stop(self):
        now = int(time.time())
        sc = open_live.SuperChatMessage(message_id=99, uname='Alice', open_id='alice', rmb=30,
                                        message='test SC', timestamp=now)
        gift = open_live.GiftMessage(msg_id='gift-1', uname='Alice', open_id='alice', paid=True,
                                    gift_name='Gift', gift_num=2, price=1000, r_price=800, timestamp=now)
        self.messages = [{'cmd': 'LIVE_OPEN_PLATFORM_SUPER_CHAT', 'data': dataclasses.asdict(sc)},
                         {'cmd': 'LIVE_OPEN_PLATFORM_SEND_GIFT', 'data': dataclasses.asdict(gift)}]
        self.collector.start('open', auth='MOCKONLY12345', access_key_id='unit-id', access_key_secret='unit-secret', app_id='123')
        rows = await self.received(2)
        events = [data for kind, data in rows if kind == 'event']
        self.assertEqual(next(data for kind, data in rows if kind == 'room')['anchor_name'], 'Official Streamer')
        self.assertEqual([e['amount'] for e in events], [30000, 1600])
        self.assertEqual(events[0]['user'], 'open:alice')
        self.collector.stop()
        for _ in range(100):
            if not self.collector.running: break
            await asyncio.sleep(.02)
        self.assertEqual([a for a, b in self.calls], ['start', 'end'])
        self.assertEqual(self.calls[1][1]['game_id'], 'mock-game')

    async def test_room_mode_without_auth(self):
        target = self.base.replace('http:', 'ws:') + '/ws'

        class LocalRoom(blivedm.BLiveClient):
            async def init_room(self):
                self._room_id = 123
                return True

            def _get_ws_url(self, retry_count): return target

            async def _send_auth(self):
                await self._websocket.send_bytes(self._make_packet({'roomid': self.room_id}, Operation.AUTH))

        sc = web_models.SuperChatMessage(id=1, uid=42, uname='Alice', price=50, message='web SC', start_time=int(time.time()))
        data = dataclasses.asdict(sc)
        # The web API represents SC user/gift fields as nested objects.
        data.update(user_info=dict(uname=sc.uname, face='', guard_level=0, user_level=0),
                    gift=dict(gift_id=0, gift_name='SC'))
        self.messages = [{'cmd': 'SUPER_CHAT_MESSAGE', 'data': data}]
        with patch.object(blivedm, 'BLiveClient', LocalRoom):
            self.collector.start('room', room='123')
            rows = await self.received()
            event = next(data for kind, data in rows if kind == 'event')
            self.assertEqual(next(data for kind, data in rows if kind == 'room')['anchor_name'], 'Room Streamer')
            self.assertEqual(event['amount'], 50000)
            self.assertEqual(event['user'], 'uid:42')
            self.assertEqual(self.calls, [])
            self.collector.stop()
            for _ in range(100):
                if not self.collector.running: break
                await asyncio.sleep(.02)


if __name__ == '__main__': unittest.main()
