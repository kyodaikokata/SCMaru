import asyncio
import queue
import unittest
from aiohttp import web, ClientSession
from yarl import URL

from login import QRLogin, qr_status, official_login_url, session_valid, session_validity
from connections import install_web_session


class LoginTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.states = [86101, 86090, 0]
        self.generate_http = 200
        self.generate_code = 0
        self.include_cookie = True
        self.nav_body = dict(code=0,data=dict(isLogin=True))
        self.nav_status = 200
        self.qr_url = 'https://passport.bilibili.com/h5-app/passport/login/scan?qrcode_key=unit-only'
        app = web.Application()
        app.router.add_get('/x/passport-login/web/qrcode/generate', self.generate)
        app.router.add_get('/x/passport-login/web/qrcode/poll', self.poll)
        app.router.add_get('/nav',self.nav)
        self.runner = web.AppRunner(app)
        await self.runner.setup()
        site = web.TCPSite(self.runner, '127.0.0.1', 0)
        await site.start()
        self.base = f'http://127.0.0.1:{site._server.sockets[0].getsockname()[1]}'

    async def asyncTearDown(self): await self.runner.cleanup()

    async def nav(self,request): return web.json_response(self.nav_body,status=self.nav_status)

    async def test_session_expiry_vs_network_uncertainty(self):
        self.assertTrue(await session_valid('synthetic',self.base+'/nav'))
        self.nav_body=dict(code=-101,data=dict(isLogin=False))
        self.assertFalse(await session_valid('synthetic',self.base+'/nav'))
        self.nav_status=503
        self.assertIsNone(await session_valid('synthetic',self.base+'/nav'))
        self.assertIsNone(session_validity(dict(code=-412)))

    async def generate(self, request):
        return web.json_response(dict(code=self.generate_code, data=dict(url=self.qr_url, qrcode_key='unit-only')), status=self.generate_http)

    async def poll(self, request):
        self.assertEqual(request.query['qrcode_key'], 'unit-only')
        code = self.states.pop(0)
        response = web.json_response(dict(code=0, data=dict(code=code)))
        if code == 0 and self.include_cookie: response.set_cookie('SESSDATA', 'unit-session-only', httponly=True)
        return response

    async def test_scan_confirm_and_session_cookie(self):
        output = queue.Queue()
        await QRLogin(output, self.base, interval=.001).run()
        rows = list(output.queue)
        self.assertEqual([value for key, value in rows if key == 'status'], ['qr_waiting', 'qr_waiting', 'qr_scanned', 'qr_success'])
        self.assertEqual(next(value for key, value in rows if key == 'success'), 'unit-session-only')
        matrix = next(value for key, value in rows if key == 'matrix')
        self.assertTrue(all(len(row) == len(matrix) for row in matrix))
        self.assertTrue(any(any(row) for row in matrix))

    async def test_expired_does_not_return_login(self):
        self.states = [86038]
        output = queue.Queue()
        await QRLogin(output, self.base, interval=.001).run()
        self.assertIn(('status', 'qr_expired'), list(output.queue))
        self.assertFalse(any(key == 'success' for key, value in output.queue))

    async def test_current_account_domain_login_url(self):
        self.qr_url = 'https://account.bilibili.com/h5-app/passport/login/scan?qrcode_key=unit-only'
        output = queue.Queue()
        await QRLogin(output, self.base, interval=.001).run()
        self.assertIn(('success', 'unit-session-only'), list(output.queue))
        self.assertTrue(official_login_url(self.qr_url))
        self.assertFalse(official_login_url('https://account.bilibili.com.example.com/'))

    async def test_rejects_unexpected_qr_destination(self):
        self.qr_url = 'https://example.com/login'
        output = queue.Queue()
        await QRLogin(output, self.base).run()
        error = next(value for kind, value in output.queue if kind == 'failure')
        self.assertEqual(error['reason'], 'qr_destination_error')
        self.assertFalse(any(kind == 'matrix' for kind, value in output.queue))

    async def test_cookie_reaches_bilibili_api_but_not_other_hosts(self):
        async with ClientSession() as session:
            install_web_session(session, 'unit-session-only')
            self.assertEqual(session.cookie_jar.filter_cookies(URL('https://api.bilibili.com/'))['SESSDATA'].value, 'unit-session-only')
            self.assertEqual(session.cookie_jar.filter_cookies(URL('https://live.bilibili.com/'))['SESSDATA'].value, 'unit-session-only')
            self.assertNotIn('SESSDATA', session.cookie_jar.filter_cookies(URL('https://example.com/')))

    async def test_generation_errors_report_safe_reason_and_stage(self):
        for http, code, expected in [(503, 0, 'qr_http_error'), (200, -412, 'qr_api_error')]:
            self.generate_http, self.generate_code = http, code
            output = queue.Queue()
            await QRLogin(output, self.base).run()
            failure = next(value for kind, value in output.queue if kind == 'failure')
            self.assertEqual(failure['stage'], 'qr_stage_generate')
            self.assertEqual(failure['reason'], expected)
            self.assertNotIn('unit-only', str(failure))
            self.assertFalse(any(kind == 'matrix' for kind, value in output.queue))

    async def test_confirmation_without_cookie_does_not_report_success(self):
        self.states, self.include_cookie = [0], False
        output = queue.Queue()
        await QRLogin(output, self.base).run()
        failure = next(value for kind, value in output.queue if kind == 'failure')
        self.assertEqual(failure['reason'], 'qr_cookie_missing')
        self.assertFalse(any(kind == 'success' or value == 'qr_success' for kind, value in output.queue))

    async def test_stop_before_request_emits_nothing(self):
        output = queue.Queue()
        worker = QRLogin(output, self.base)
        worker.stop()
        await worker.run()
        self.assertTrue(output.empty())


if __name__ == '__main__': unittest.main()
