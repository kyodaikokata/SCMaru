"""Exclusive anonymous room-number and signed official OpenLive transports."""
from __future__ import annotations

import asyncio
import dataclasses
import queue
import threading
from http.cookies import SimpleCookie
from datetime import datetime, timezone, timedelta

import aiohttp
import blivedm
from yarl import URL

from core import normalize


def install_web_session(session, value):
    if not value: return
    cookie = SimpleCookie()
    cookie['SESSDATA'] = value
    cookie['SESSDATA']['domain'] = '.bilibili.com'
    cookie['SESSDATA']['path'] = '/'
    session.cookie_jar.update_cookies(cookie, response_url=URL('https://live.bilibili.com/'))


async def room_anchor_name(session, room):
    """Public room owner's nickname; never infer it from room title or room ID."""
    try:
        async with session.get('https://api.live.bilibili.com/live_user/v1/UserInfo/get_anchor_in_room',
                               params={'roomid': room}, timeout=aiohttp.ClientTimeout(total=8)) as res:
            body = await res.json()
        name = body.get('data', {}).get('info', {}).get('uname', '') if body.get('code') == 0 else ''
        return name.strip() if isinstance(name, str) else ''
    except (aiohttp.ClientError, asyncio.TimeoutError, AttributeError, ValueError):
        return ''


async def room_info(session, room):
    try:
        async with session.get('https://api.live.bilibili.com/room/v1/Room/get_info', params={'id': room},
                               timeout=aiohttp.ClientTimeout(total=8)) as res:
            body = await res.json()
        if body.get('code') != 0:
            return None
        data = body['data']
        started = data.get('live_time', '')
        timestamp = int(datetime.strptime(started, '%Y-%m-%d %H:%M:%S').replace(tzinfo=timezone(timedelta(hours=8))).timestamp()) if started and not started.startswith('0000') else None
        return dict(live=data['live_status'] == 1, timestamp=timestamp)
    except (aiohttp.ClientError, asyncio.TimeoutError, KeyError, ValueError):
        return None


class Collector:
    def __init__(self, output: queue.Queue):
        self.output = output
        self.thread = None
        self.loop = None
        self.task = None
        self.ready = threading.Event()
        self.stopping = threading.Event()

    @property
    def running(self):
        return bool(self.thread and self.thread.is_alive())

    def start(self, mode, room="", auth="", access_key_id="", access_key_secret="", app_id="", session_cookie=""):
        if self.running:
            raise RuntimeError("Already collecting")
        if mode == "room" and (not room.isdecimal() or int(room) <= 0):
            raise ValueError("Room ID must be a positive integer")
        if mode == "open":
            if not auth.strip():
                raise ValueError("主播身份码 / 配信者認証コード")
            if not access_key_id or not access_key_secret or not str(app_id).isdecimal() or int(app_id) <= 0:
                raise ValueError("请先配置官方应用 ID 和开发者密钥 / アプリID・開発者キーを設定してください")
        self.stopping.clear()
        self.ready.clear()
        self.thread = threading.Thread(target=self._thread_main, args=(mode, room, auth, access_key_id, access_key_secret, app_id, session_cookie), daemon=True)
        self.thread.start()

    def stop(self):
        self.stopping.set()
        if self.loop and self.task and not self.loop.is_closed():
            self.loop.call_soon_threadsafe(self.task.cancel)

    def _thread_main(self, *args):
        try:
            asyncio.run(self._run(*args))
        except Exception as exc:
            # Exceptions can include auth codes in request details; expose only type.
            self.output.put(("error", type(exc).__name__))
        finally:
            self.output.put(("stopped", None))

    async def _run(self, mode, room, auth, access_key_id, access_key_secret, app_id, session_cookie):
        self.loop = asyncio.get_running_loop()
        self.task = asyncio.current_task()
        self.ready.set()
        output = self.output
        anchor_names = {}

        async def describe(client):
            cached_name = getattr(client, 'anchor_name', '') or anchor_names.get(client.room_id, '')
            if cached_name:
                info = await room_info(session, client.room_id)
                name = cached_name
            else:
                info, name = await asyncio.gather(room_info(session, client.room_id), room_anchor_name(session, client.room_id))
            if name: anchor_names[client.room_id] = name
            return dict(room=str(client.room_id), source=mode, info=info, anchor_name=name,
                        logged_in=bool(getattr(client, 'uid', 0)) if mode == 'room' else False)

        class RoomClient(blivedm.BLiveClient):
            async def init_room(self):
                result = await super().init_room()
                if self.room_id:
                    output.put(("room", await describe(self)))
                return result

        class DirectClient(blivedm.OpenLiveClient):
            def _parse_start_game(self, data):
                name = data.get('anchor_info', {}).get('uname', '')
                self.anchor_name = name.strip() if isinstance(name, str) else ''
                return super()._parse_start_game(data)

            async def init_room(self):
                result = await super().init_room()
                if result:
                    output.put(("room", await describe(self)))
                return result

        class Handler(blivedm.BaseHandler):
            def handle(self, client, command):
                cmd = command.get("cmd", "").split(":", 1)[0]
                data = command.get("data", {})
                if cmd in ("LIVE", "LIVE_OPEN_PLATFORM_LIVE_START", "OPEN_LIVEROOM_LIVE_START"):
                    output.put(("live", dict(live=True, timestamp=data.get("timestamp"))))
                elif cmd in ("PREPARING", "LIVE_OPEN_PLATFORM_LIVE_END", "OPEN_LIVEROOM_LIVE_END"):
                    output.put(("live", dict(live=False)))
                try:
                    super().handle(client, command)
                except (KeyError, ValueError, TypeError, AttributeError):
                    output.put(("warning", "schema"))

            def send(self, client, kind, message):
                event = normalize(mode, kind, dataclasses.asdict(message), client.room_id)
                if event:
                    output.put(("event", event))

            def _on_heartbeat(self, client, message):
                output.put(("heartbeat", None))

            def _on_gift(self, c, m): self.send(c, "gift", m)
            def _on_buy_guard(self, c, m): self.send(c, "guard", m)
            def _on_user_toast_v2(self, c, m): self.send(c, "guard", m)
            def _on_super_chat(self, c, m): self.send(c, "sc", m)
            def _on_open_live_gift(self, c, m): self.send(c, "gift", m)
            def _on_open_live_buy_guard(self, c, m): self.send(c, "guard", m)
            def _on_open_live_super_chat(self, c, m): self.send(c, "sc", m)

            def _on_super_chat_delete(self, c, m):
                output.put(("delete", dict(room=str(c.room_id), source=mode, ids=m.ids)))

            def _on_open_live_super_chat_delete(self, c, m):
                output.put(("delete", dict(room=str(c.room_id), source=mode, ids=m.message_ids)))

            def on_client_stopped(self, client, exception):
                if exception:
                    output.put(("error", type(exception).__name__))

        async with aiohttp.ClientSession(headers={"User-Agent": "Mozilla/5.0"},
                                         timeout=aiohttp.ClientTimeout(total=20)) as session:
            if mode == 'room' and session_cookie:
                install_web_session(session, session_cookie)
            client = (RoomClient(int(room), session=session) if mode == "room" else
                      DirectClient(access_key_id, access_key_secret, int(app_id), auth, session=session))
            client.set_handler(Handler())

            def reconnect(retry, total):
                output.put(("reconnecting", None))
                if total > 30:
                    raise ConnectionError("Reconnect limit")
                return min(2 * total + 1, 30)

            client.set_reconnect_policy(reconnect)

            async def poll():
                while True:
                    if client.room_id:
                        info = await room_info(session, client.room_id)
                        if info is None:
                            output.put(("warning", "room_state"))
                        else:
                            if not anchor_names.get(client.room_id):
                                name = await room_anchor_name(session, client.room_id)
                                if name: anchor_names[client.room_id] = name
                            info = dict(info, anchor_name=anchor_names.get(client.room_id, ''))
                            output.put(("room_state", info))
                    await asyncio.sleep(30)

            polling = asyncio.create_task(poll())
            client.start()
            try:
                if self.stopping.is_set():
                    return
                await client.join()
            except asyncio.CancelledError:
                pass
            finally:
                polling.cancel()
                await asyncio.gather(polling, return_exceptions=True)
                await client.stop_and_close()
