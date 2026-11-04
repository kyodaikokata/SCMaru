"""Local bilingual tutorial styled with the app's selected KotobaLive palette."""
import tkinter as tk
from tkinter import ttk
import webbrowser

GUIDE = {
 'zh': ('如何获取主播身份码', [
  ('1 · 使用主播账号', '在 B 站网页或直播姬登录拥有该直播间的主播账号。SCDesk 本身不读取你的登录状态。'),
  ('2 · 打开幻星互动', '打开 B 站「幻星互动」网页。也可从直播姬的直播工具／更多进入「互动玩法」。不同版本的入口名称可能略有变化。'),
  ('3 · 找到「身份码」', '在互动玩法页面寻找「身份码」或「获取身份码」。网页端可能位于页面右下角或应用下载详情中；直播姬可能在互动玩法面板上方。'),
  ('4 · 复制到 SCDesk', '复制身份码，在 SCDesk 设置中选择「身份码直连（官方）」，粘贴到「主播身份码」。身份码不是直播间号、UID，也不是推流码。'),
  ('5 · 完成应用配置后连接', '本工具独立调用官方接口，因此还需要自己的应用 ID、Access Key ID、Access Key Secret。首次在高级设置配置，之后无需运行 blivechat。若没有应用凭据，可使用免登录的直播间号模式。'),
  ('6 · 更新与保存', '需要记住身份码时勾选「记住本机身份码」，程序用 Windows 本机用户加密保存。刷新身份码会使旧码失效，刷新后需要在 SCDesk 更新。'),
 ], '打开幻星互动', '开发者入驻与文档', '关闭'),
 'ja': ('配信者認証コードの取得方法', [
  ('1 · 配信者アカウント', '対象ルームを所有する配信者アカウントで Bilibili のWebサイトまたは配信姫にログインします。SCDesk はログイン状態を読み取りません。'),
  ('2 · 幻星互动を開く', 'Bilibili の「幻星互动」を開きます。配信姫のライブツール／その他から「互动玩法」を開く方法もあります。バージョンにより表示が異なります。'),
  ('3 · 「身份码」を探す', '「身份码」または「获取身份码」を探します。Webでは右下やアプリのダウンロード詳細、配信姫では互动玩法パネル上部に表示される場合があります。'),
  ('4 · SCDesk に貼り付ける', 'コードをコピーし、SCDesk の設定で「認証コード直接接続（公式）」を選び、「配信者認証コード」に貼り付けます。ルームID・UID・配信キーとは別です。'),
  ('5 · アプリ設定と接続', '公式APIへの直接接続には、ご自身のアプリID・Access Key ID・Access Key Secretも必要です。詳細設定で初回設定すると、blivechatなしで動作します。アプリ情報がなければログイン不要のルームIDモードが使えます。'),
  ('6 · 保存と更新', 'コードを保存する場合は「このPCで認証コードを記憶」を有効にします。Windowsの現在のユーザーで暗号化保存します。コードを再発行すると旧コードは無効になるため、SCDesk側も更新してください。'),
 ], '幻星互动を開く', '開発者登録・ドキュメント', '閉じる'),
}


def show_guide(parent, lang, palette):
    title, steps, open_label, docs_label, close = GUIDE[lang]
    window = tk.Toplevel(parent)
    window.title(title)
    window.geometry('760x720')
    window.configure(bg=palette['bg'])
    outer = ttk.Frame(window, padding=24)
    outer.pack(fill='both', expand=True)
    ttk.Label(outer, text=title, style='Title.TLabel').pack(anchor='w', pady=(0, 18))
    for heading, body in steps:
        ttk.Label(outer, text=heading, font=('Microsoft YaHei UI', 11, 'bold')).pack(anchor='w', pady=(8, 4))
        ttk.Label(outer, text=body, wraplength=700).pack(anchor='w')
    actions = ttk.Frame(outer)
    actions.pack(fill='x', side='bottom', pady=12)
    ttk.Button(actions, text=open_label, command=lambda: webbrowser.open('https://play-live.bilibili.com/')).pack(side='left')
    ttk.Button(actions, text=docs_label, command=lambda: webbrowser.open('https://open-live.bilibili.com/')).pack(side='left', padx=10)
    ttk.Button(actions, text=close, command=window.destroy).pack(side='right')
    return window
