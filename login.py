"""Optional Bilibili QR login; only the user scans and confirms on their phone."""
import asyncio
import queue
import threading
import time
from urllib.parse import urlsplit

import aiohttp
import qrcode
import tkinter as tk
from tkinter import ttk

PASSPORT = 'https://passport.bilibili.com'
LOGIN_HOSTS = {'passport.bilibili.com', 'account.bilibili.com'}


def official_login_url(url):
    try:
        parsed = urlsplit(url)
        return parsed.scheme == 'https' and parsed.hostname in LOGIN_HOSTS and not parsed.username and not parsed.password and parsed.port in (None, 443)
    except (ValueError, TypeError):
        return False


def qr_status(body):
    if not isinstance(body, dict) or body.get('code') != 0: return 'qr_failed'
    data = body.get('data')
    if not isinstance(data, dict): return 'qr_failed'
    return {86101: 'qr_waiting', 86090: 'qr_scanned', 86038: 'qr_expired', 0: 'qr_success'}.get(data.get('code'), 'qr_failed')


def qr_matrix(url):
    qr = qrcode.QRCode(error_correction=qrcode.constants.ERROR_CORRECT_M, border=4)
    qr.add_data(url)
    qr.make(fit=True)
    return qr.get_matrix()


def matrix_photo(master, matrix, target=280):
    """Render integer-sized modules directly in Tk, without PNG/Pillow decoders."""
    import tkinter as tk
    size = len(matrix)
    if not 21 <= size <= 185 or any(len(row) != size for row in matrix): raise ValueError('Invalid QR matrix')
    bitmap = tk.PhotoImage(master=master, width=size, height=size)
    rows = ['{' + ' '.join('#000000' if pixel else '#ffffff' for pixel in row) + '}' for row in matrix]
    bitmap.put(' '.join(rows))
    scale = max(1, target // size)
    return bitmap.zoom(scale, scale)


class LoginFailure(Exception):
    def __init__(self, reason, code=None):
        super().__init__(reason)
        self.reason, self.code = reason, code


class QRLogin:
    def __init__(self, output, base=PASSPORT, interval=2):
        self.output, self.base, self.interval = output, base, interval
        self.stopping = threading.Event()
        self.loop = self.task = self.thread = None

    def start(self):
        self.thread = threading.Thread(target=lambda: asyncio.run(self.run()), daemon=True)
        self.thread.start()

    def stop(self):
        self.stopping.set()
        if self.loop and self.task and not self.loop.is_closed():
            try: self.loop.call_soon_threadsafe(self.task.cancel)
            except RuntimeError: pass

    async def request(self, session, path, **kwargs):
        async with session.get(self.base + path, allow_redirects=False, **kwargs) as response:
            if response.status != 200: raise LoginFailure('qr_http_error', response.status)
            try: body = await response.json(content_type=None)
            except ValueError: raise LoginFailure('qr_response_error') from None
            if not isinstance(body, dict): raise LoginFailure('qr_response_error')
            if body.get('code') != 0:
                code = body.get('code')
                raise LoginFailure('qr_api_error', code if isinstance(code, int) else None)
            return body, response.cookies.get('SESSDATA')

    async def run(self):
        self.loop, self.task = asyncio.get_running_loop(), asyncio.current_task()
        if self.stopping.is_set(): return
        stage = 'qr_stage_generate'
        try:
            async with aiohttp.ClientSession(
                headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36',
                         'Referer': 'https://www.bilibili.com/', 'Accept': 'application/json'},
                trust_env=True, timeout=aiohttp.ClientTimeout(total=12)) as session:
                body, _ = await self.request(session, '/x/passport-login/web/qrcode/generate')
                data = body.get('data')
                if not isinstance(data, dict): raise LoginFailure('qr_response_error')
                url, key = data.get('url'), data.get('qrcode_key')
                if not isinstance(url, str) or not official_login_url(url): raise LoginFailure('qr_destination_error')
                if not isinstance(key, str) or not key: raise LoginFailure('qr_response_error')
                stage = 'qr_stage_render'
                self.output.put(('matrix', qr_matrix(url)))
                self.output.put(('status', 'qr_waiting'))
                stage = 'qr_stage_poll'
                expires, failures = time.monotonic() + 180, 0
                while not self.stopping.is_set() and time.monotonic() < expires:
                    try:
                        body, cookie = await self.request(session, '/x/passport-login/web/qrcode/poll', params={'qrcode_key': key})
                        failures = 0
                    except (aiohttp.ClientError, asyncio.TimeoutError):
                        failures += 1
                        if failures >= 3: raise
                        self.output.put(('status', 'qr_poll_retry'))
                        await asyncio.sleep(self.interval)
                        continue
                    status = qr_status(body)
                    if status == 'qr_failed': raise LoginFailure('qr_response_error')
                    if status == 'qr_success':
                        if not cookie or not cookie.value: raise LoginFailure('qr_cookie_missing')
                        self.output.put(('status', status))
                        self.output.put(('success', cookie.value))
                        return
                    self.output.put(('status', status))
                    if status == 'qr_expired': return
                    await asyncio.sleep(self.interval)
                if not self.stopping.is_set(): self.output.put(('status', 'qr_expired'))
        except asyncio.CancelledError:
            pass
        except Exception as exc:
            if isinstance(exc, LoginFailure): reason, code = exc.reason, exc.code
            elif isinstance(exc, aiohttp.ClientSSLError): reason, code = 'qr_tls_error', None
            elif isinstance(exc, (aiohttp.ClientError, asyncio.TimeoutError)): reason, code = 'qr_network_error', None
            else: reason, code = ('qr_render_failed' if stage == 'qr_stage_render' else 'qr_response_error'), None
            # Never include request URLs, QR keys or cookies in errors/logs.
            self.output.put(('failure', dict(stage=stage, reason=reason, code=code)))


class QRPanel(ttk.Frame):
    """Reusable QR display for the welcome page and optional re-login window."""
    def __init__(self, parent, translate, palette, on_success):
        super().__init__(parent)
        self.t, self.success = translate, on_success
        self.worker = self.timer = self.success_timer = self.photo = None
        self.window = self
        self.closed = False
        ttk.Label(self, text=translate('qr_hint'), wraplength=620, justify='center').pack(pady=(6, 8))
        holder = tk.Frame(self, width=296, height=296, bg='#ffffff')
        holder.pack(pady=4)
        holder.pack_propagate(False)
        self.image = tk.Label(holder, bg='#ffffff', text=translate('qr_loading'), wraplength=260, fg='#503847')
        self.image.pack(fill='both', expand=True)
        self.status = tk.StringVar(value=translate('qr_loading'))
        ttk.Label(self, textvariable=self.status, wraplength=620, justify='center').pack(pady=6)
        ttk.Button(self, text=translate('qr_refresh'), command=self.refresh).pack(pady=4)
        self.worker = self.timer = self.success_timer = self.photo = None
        self.complete = False
        self.refresh()

    def refresh(self):
        if self.worker: self.worker.stop()
        for timer in (self.timer, self.success_timer):
            if timer: self.window.after_cancel(timer)
        self.timer = self.success_timer = None
        self.complete, self.photo = False, None
        self.status.set(self.t('qr_loading'))
        self.image.configure(image='', text=self.t('qr_loading'))
        self.queue = queue.Queue()
        self.worker = QRLogin(self.queue)
        self.worker.start()
        self.poll()

    def poll(self):
        self.timer = None
        if not self.window.winfo_exists(): return
        while not self.queue.empty():
            kind, value = self.queue.get_nowait()
            if kind == 'matrix':
                try:
                    self.photo = matrix_photo(self.window, value)
                    self.image.configure(image=self.photo, text='')
                except Exception:
                    self.worker.stop()
                    self.status.set(self.t('qr_render_failed'))
                    self.image.configure(image='', text=self.t('qr_render_failed'))
                    return
            elif kind == 'status': self.status.set(self.t(value))
            elif kind == 'failure':
                suffix = f" ({value['code']})" if value.get('code') is not None else ''
                self.status.set(self.t(value['stage']) + '：' + self.t(value['reason']) + suffix)
                if self.photo is None: self.image.configure(text=self.t('qr_refresh_hint'))
            elif kind == 'success' and not self.complete:
                self.complete = True
                try: self.success(value)
                except Exception:
                    self.status.set(self.t('qr_save_failed'))
                    return
                return
        self.timer = self.window.after(200, self.poll)

    def stop(self):
        if self.worker: self.worker.stop()
        for timer in (self.timer, self.success_timer):
            if timer:
                try: self.window.after_cancel(timer)
                except tk.TclError: pass
        self.timer = self.success_timer = None

    def destroy(self):
        self.closed = True
        self.stop()
        super().destroy()

    def close(self):
        if self.winfo_exists(): self.destroy()


class LoginDialog:
    def __init__(self, parent, translate, palette, on_success, notice=None):
        from version import VERSION
        self.window = tk.Toplevel(parent)
        self.window.title(translate('qr_login') + ' · SCMaru ' + VERSION)
        self.window.geometry('680x600' if notice else '680x550')
        self.window.configure(bg=palette['bg'])
        self.window.protocol('WM_DELETE_WINDOW', self.close)
        self.success, self.success_timer = on_success, None
        if notice:
            ttk.Label(self.window, text=notice, wraplength=620, justify='center').pack(padx=20,pady=12)
        self.panel = QRPanel(self.window, translate, palette, self._success)
        self.panel.pack(fill='both', expand=True, padx=16, pady=8)
        ttk.Button(self.window, text=translate('qr_skip'), command=self.close).pack(pady=(4,16))

    def __getattr__(self, name):
        return getattr(self.panel, name)

    def _success(self, value):
        self.success(value)
        self.success_timer = self.window.after(900, self.close)

    def refresh(self):
        if self.success_timer: self.window.after_cancel(self.success_timer)
        self.success_timer = None
        self.panel.refresh()

    def close(self):
        self.panel.stop()
        if self.success_timer:
            try: self.window.after_cancel(self.success_timer)
            except tk.TclError: pass
            self.success_timer = None
        if self.window.winfo_exists(): self.window.destroy()


async def session_valid(cookie, endpoint='https://api.bilibili.com/x/web-interface/nav'):
    """Only explicit platform logout is expiry; network/HTTP failures are unknown."""
    from connections import install_web_session
    try:
        async with aiohttp.ClientSession(trust_env=True, timeout=aiohttp.ClientTimeout(total=10), headers={'User-Agent':'Mozilla/5.0','Referer':'https://www.bilibili.com/'}) as session:
            install_web_session(session, cookie)
            async with session.get(endpoint, allow_redirects=False) as response:
                if response.status != 200: return None
                body = await response.json(content_type=None)
            return session_validity(body)
    except (aiohttp.ClientError, asyncio.TimeoutError, ValueError, TypeError):
        return None


def session_validity(body):
    if not isinstance(body, dict): return None
    if body.get('code') == -101: return False
    data = body.get('data')
    if body.get('code') == 0 and isinstance(data, dict) and isinstance(data.get('isLogin'), bool):
        return data['isLogin']
    return None


def check_saved_session(output, cookie, generation):
    def run():
        try: valid = asyncio.run(session_valid(cookie))
        except Exception: valid = None
        output.put(('login_checked', dict(valid=valid, generation=generation)))
    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    return thread
