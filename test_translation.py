import json
import unittest
from unittest.mock import AsyncMock, patch
from aiohttp import web
from translation import translate, translate_api, translate_google, api_endpoint, TranslationError, PROMPT
import aiohttp


class TranslationTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.requests=[]
        self.status=200
        self.google_calls=[]
        self.detected='zh-CN'
        self.answer=dict(source_language='zh',translated_text='お疲れさま __SCMARU_BV_0__')
        app=web.Application()
        app.router.add_post('/v1/chat/completions',self.api)
        app.router.add_get('/google',self.google)
        self.runner=web.AppRunner(app);await self.runner.setup()
        site=web.TCPSite(self.runner,'127.0.0.1',0);await site.start()
        self.base=f'http://127.0.0.1:{site._server.sockets[0].getsockname()[1]}'
        self.config=dict(mode='api_first',url=self.base+'/v1',model='synthetic-model',key='synthetic-key',ja_to_zh=True,zh_to_ja=True)
    async def asyncTearDown(self): await self.runner.cleanup()
    async def api(self,request):
        self.requests.append(await request.json())
        self.assertEqual(request.headers['Authorization'],'Bearer synthetic-key')
        return web.json_response(dict(choices=[dict(message=dict(content=json.dumps(self.answer)))]),status=self.status)
    async def google(self,request):
        self.google_calls.append(dict(request.query))
        return web.json_response([[['Google '+request.query['q'],request.query['q'],None,None]],None,self.detected])

    async def test_api_preserves_bv_and_supplies_automatic_direction_prompt(self):
        result=await translate('辛苦了 BV1xx411c7mD',self.config,self.base+'/google')
        self.assertEqual(result['text'],'お疲れさま BV1xx411c7mD')
        self.assertEqual(result['target'],'ja')
        self.assertFalse(self.google_calls)
        self.assertIn('BV号码不用翻译',self.requests[0]['messages'][0]['content'])
        self.assertIn('不要回答',PROMPT)

    async def test_japanese_api_output_targets_chinese(self):
        self.answer=dict(source_language='ja',translated_text='辛苦了')
        result=await translate('お疲れさま',self.config,self.base+'/google')
        self.assertEqual(result['target'],'zh-CN')

    async def test_fallback_and_only_engine_modes(self):
        self.status=503
        result=await translate('测试 BV1xx411c7mD',self.config,self.base+'/google')
        self.assertEqual(result['engine'],'Google')
        self.config['mode']='api_only'
        with self.assertRaises(TranslationError): await translate('测试',self.config,self.base+'/google')
        before=len(self.requests)
        self.config['mode']='google_only'
        await translate('测试',self.config,self.base+'/google')
        self.assertEqual(len(self.requests),before)

    async def test_google_corrects_direction_for_kanji_only_japanese(self):
        self.detected='ja'
        self.config['mode']='google_only'
        result=await translate('感謝 BV1xx411c7mD',self.config,self.base+'/google')
        self.assertEqual([r['tl'] for r in self.google_calls],['ja','zh-CN'])
        self.assertEqual(result['target'],'zh-CN')
        self.assertIn('BV1xx411c7mD',result['text'])

    async def test_bv_only_never_sends_a_request(self):
        result=await translate('BV1xx411c7mD',self.config,self.base+'/google')
        self.assertEqual(result['text'],'BV1xx411c7mD')
        self.assertFalse(self.requests or self.google_calls)

    async def test_bad_url_is_rejected(self):
        for url in ('http://example.com','https://key@example.com','file:///secret'):
            with self.assertRaises(TranslationError): api_endpoint(url)

    async def test_directions_can_be_disabled_independently(self):
        self.config['ja_to_zh']=False
        result=await translate('お疲れさまでした',self.config,self.base+'/google')
        self.assertTrue(result['skipped'])
        self.assertFalse(self.requests or self.google_calls)
        self.config.update(ja_to_zh=True,zh_to_ja=False)
        result=await translate('今天也辛苦了',self.config,self.base+'/google')
        self.assertTrue(result['skipped'])
        self.assertFalse(self.requests or self.google_calls)
