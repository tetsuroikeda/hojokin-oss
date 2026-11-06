// video.html を 30fps で1コマずつ撮り、ffmpeg に流して音のない mp4 にする。
// 使い方：node render.mjs <video.html> <出力.mp4> <全体の秒数> [始めの秒] [終わりの秒]
// この Mac の Google Chrome を使う（Chromium を落とさない）。puppeteer-core は docs/video/ で npm install する。
import { spawn } from 'node:child_process';
import { pathToFileURL } from 'node:url';
import puppeteer from 'puppeteer-core';

const [, , html, out, totalArg, fromArg, toArg] = process.argv;
const FPS = 30;
const total = Number(totalArg);
const from = Number(fromArg || 0);
const to = Number(toArg || total);
const CHROME = '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome';

const browser = await puppeteer.launch({
  executablePath: CHROME,
  headless: 'new',
  args: ['--allow-file-access-from-files', '--hide-scrollbars', '--force-device-scale-factor=1', '--font-render-hinting=none'],
  defaultViewport: { width: 1920, height: 1080, deviceScaleFactor: 1 },
});
const page = await browser.newPage();
page.on('pageerror', e => { console.error('ページの誤り:', e.message); process.exit(1); });
await page.goto(pathToFileURL(html).href, { waitUntil: 'load' });
await page.evaluate(() => document.fonts.ready);

const ff = spawn('ffmpeg', ['-y', '-loglevel', 'error', '-f', 'image2pipe', '-framerate', String(FPS), '-c:v', 'mjpeg', '-i', '-',
  '-c:v', 'libx264', '-preset', 'medium', '-crf', '18', '-pix_fmt', 'yuv420p', '-r', String(FPS), out], { stdio: ['pipe', 'inherit', 'inherit'] });

const frames = Math.round((to - from) * FPS);
const started = Date.now();
for (let i = 0; i < frames; i++) {
  const t = from + i / FPS;
  await page.evaluate(t => window.seek(t), t);
  const buf = await page.screenshot({ type: 'jpeg', quality: 92, optimizeForSpeed: true });
  if (!ff.stdin.write(buf)) await new Promise(r => ff.stdin.once('drain', r));
  if (i % 300 === 0) console.log(`${i}/${frames} コマ（${Math.round((Date.now() - started) / 1000)} 秒）`);
}
ff.stdin.end();
await new Promise(r => ff.on('close', r));
await browser.close();
console.log('撮り終えました:', out);
