"""Non-sensitive QR generation diagnostics. Never display tokens or account data."""
import asyncio
from urllib.parse import urlsplit
import aiohttp
import io
from login import official_login_url


async def check():
    try:
        async with aiohttp.ClientSession(headers={'User-Agent': 'Mozilla/5.0', 'Referer': 'https://www.bilibili.com/'},
                                         timeout=aiohttp.ClientTimeout(total=12)) as session:
            async with session.get('https://passport.bilibili.com/x/passport-login/web/qrcode/generate') as response:
                print('HTTP:', response.status, 'Type:', response.content_type, flush=True)
                body = await response.json()
            print('Code:', body.get('code'), 'Data fields:', list((body.get('data') or {}).keys()), flush=True)
            data = body.get('data') or {}
            print('QR host:', urlsplit(data.get('url', '')).hostname, flush=True)
            print('Login URL accepted:', official_login_url(data.get('url', '')), flush=True)
            if data.get('url'):
                import qrcode
                from PIL import Image
                image = qrcode.make(data['url']).get_image().resize((260, 260), Image.Resampling.NEAREST)
                png = io.BytesIO()
                image.save(png, format='PNG')
                print('QR PNG generated:', png.getvalue().startswith(b'\x89PNG'), flush=True)
    except Exception as exc:
        print('Failure type:', type(exc).__name__, flush=True)


if __name__ == '__main__': asyncio.run(check())
