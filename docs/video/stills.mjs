// 確かめ用：指定した秒の静止画を撮る。node stills.mjs <video.html> <出力フォルダ> <秒> [<秒> ...]
import { pathToFileURL } from 'node:url';
import puppeteer from 'puppeteer-core';

const [, , html, dir, ...times] = process.argv;
const browser = await puppeteer.launch({
  executablePath: '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
  headless: 'new',
  args: ['--allow-file-access-from-files', '--hide-scrollbars'],
  defaultViewport: { width: 1920, height: 1080, deviceScaleFactor: 1 },
});
const page = await browser.newPage();
page.on('pageerror', e => console.error('ページの誤り:', e.message));
await page.goto(pathToFileURL(html).href, { waitUntil: 'load' });
await page.evaluate(() => document.fonts.ready);
for (const t of times) {
  await page.evaluate(t => window.seek(t), Number(t));
  await page.screenshot({ path: `${dir}/t${String(t).padStart(6, '0')}.jpg`, type: 'jpeg', quality: 80 });
}
await browser.close();
