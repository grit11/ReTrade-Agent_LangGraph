"""Against a running actual application. Requires playwright + a Chromium browser.
python tests/e2e/browser_smoke.py --url http://127.0.0.1:8000
"""
import argparse
from pathlib import Path
from playwright.sync_api import sync_playwright
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--url',default='http://127.0.0.1:8000')
    p.add_argument('--executable',default=None);p.add_argument('--screenshots',type=Path,default=Path('runtime/screenshots'))
    a=p.parse_args();a.screenshots.mkdir(parents=True,exist_ok=True)
    with sync_playwright() as driver:
        browser=driver.chromium.launch(headless=True,**({'executable_path':a.executable} if a.executable else {}))
        page=browser.new_page(viewport={'width':1460,'height':980});errors=[]
        page.on('pageerror',lambda e:errors.append(str(e)))
        page.goto(a.url,wait_until='networkidle');page.wait_for_selector('#mode-badge')
        page.screenshot(path=str(a.screenshots/'welcome.png'))
        page.locator('#message-input').fill('你好');page.locator('#send-button').click()
        page.wait_for_function("!document.querySelector('#send-button').disabled",timeout=240000)
        assert page.locator('.message.assistant').count()>0
        page.screenshot(path=str(a.screenshots/'conversation.png'))
        assert not errors,errors
        browser.close()
    print('Browser smoke completed; inspect the service mode and replies independently.')
