/* Browser test for the local build (app/test.html). Runs against a throw-away copy of the data
   (tests/test_local.py starts the server with --test and a temp folder) and posts PASS/FAIL lines
   to /api/test-result. */
(() => {
  const R = [];
  const ok = (cond, msg) => R.push((cond ? 'PASS ' : 'FAIL ') + msg);
  const wait = ms => new Promise(r => setTimeout(r, ms));
  const saved = async () => (await (await fetch('/api/data', { cache: 'no-store' })).json()).collections;
  const until = async (fn, ms = 4000) => { const t = Date.now(); while (Date.now() - t < ms) { if (await fn()) return true; await wait(100); } return false; };

  async function run() {
    await until(() => document.querySelectorAll('.fair').length > 0);
    setLang('zh', false);  // the checks below read the Chinese UI; the English one is checked further down
    const n = +(document.querySelector('#rcount').textContent.match(/\/ (\d+)/) || [])[1];
    ok(n > 100, `catalogue loaded (${n} fairs)`);
    ok(/目录更新于 \d{4}-\d\d-\d\d/.test(document.querySelector('#upd').textContent), 'catalogue date shown');
    ok(!document.querySelector('#exports').hidden, 'export buttons visible in the local version');
    ok(!document.querySelector('link[href*="fonts.googleapis"]'), 'no web fonts (works offline)');

    // status + priority + note are saved to the local file
    document.querySelector('.fair[data-id="ade-2026"]').click();
    document.querySelector('#st [data-st="going"]').click();
    document.querySelector('#pr [data-pr="high"]').click();
    const t = document.querySelector('#notes');
    t.value = '想见 Spotify 的数据团队'; t.dispatchEvent(new Event('input'));
    document.querySelector('#x').click();
    ok(await until(async () => { const p = (await saved()).plans || {}; return p['ade-2026'] && p['ade-2026'].status === 'going' && p['ade-2026'].notes === '想见 Spotify 的数据团队' && p['ade-2026'].priority === 'high'; }), 'status, priority and note saved');
    ok(document.querySelector('#stats').textContent.replace(/\s/g, '').includes('1要去'), 'going counter updated');

    // Highlight choice is saved
    document.querySelector('[data-dd="hl"]').click();
    document.querySelector('.opt[data-hl="media"]').click();
    ok(await until(async () => ((((await saved()).settings || {}).prefs || {}).highlight || []).includes('media')), 'Highlight saved');
    document.body.click();

    // calendar export: the day after ADE's last day across the 25 Oct clock change is 26 Oct, not 25
    const ade = fairs.find(f => f.id === 'ade-2026');
    const ics = buildIcs([ade]);
    ok(ics.includes('DTSTART;VALUE=DATE:20261021') && ics.includes('DTEND;VALUE=DATE:20261026'), 'ics dates (clock change safe)');
    ok(ics.startsWith('BEGIN:VCALENDAR') && ics.includes('END:VEVENT') && ics.trim().endsWith('END:VCALENDAR'), 'ics structure');
    const enc = new TextEncoder();
    ok(ics.split('\r\n').every(l => enc.encode(l).length <= 75), 'ics lines folded to 75 bytes');
    ok(calLinks(ade).includes('20261021/20261026'), 'Google calendar link end date');
    ok(!calLinks(ade).includes('outlook'), 'no Outlook links');

    // filters: range, mine, stale saved values
    document.querySelector('[data-r="all"]').click();
    const all = +document.querySelector('#rcount').textContent.match(/显示 (\d+)/)[1];
    document.querySelector('[data-r="3"]').click();
    const three = +document.querySelector('#rcount').textContent.match(/显示 (\d+)/)[1];
    ok(all > three && three > 0, `time range filters (3 个月 ${three} < 全部 ${all})`);
    document.querySelector('[data-q="mine"]').click();
    ok(document.querySelector('#rcount').textContent.startsWith('显示 1 '), 'only my fairs');
    document.querySelector('[data-q="mine"]').click();

    // a second save of the same document while the first is still on its way
    document.querySelector('.fair[data-id="ade-2026"]').click();
    document.querySelector('#st [data-st="registered"]').click();
    document.querySelector('#st [data-st="interested"]').click();
    document.querySelector('#x').click();
    ok(await until(async () => (((await saved()).plans || {})['ade-2026'] || {}).status === 'interested'), 'last click wins');

    // ---- English UI: no Chinese character may be left anywhere on screen (user notes excepted) ----
    const CJK = /[　-鿿＀-￯]/;
    const cjkIn = el => (el.innerText.match(/[^\n]*[　-鿿＀-￯][^\n]*/g) || []).slice(0, 3).join(' | ');
    document.querySelector('[data-r="all"]').click();
    document.querySelector('[data-q="past"]').click();
    document.querySelector('#lang').click();
    ok(document.documentElement.lang === 'en' && document.querySelector('#lang').textContent === '中文', 'switched to English');
    ok(await until(async () => ((((await saved()).settings || {}).prefs || {}).lang === 'en')), 'language choice saved');
    ok(document.querySelector('#rcount').textContent.startsWith('Showing') && document.querySelector('#upd').textContent.startsWith('Catalogue updated'), 'header and counter in English');
    // the "中文" switch button is meant to stay in Chinese, so Chinese readers can find it
    const wrapText = el => el.innerText.replace(document.querySelector('#lang').innerText, '');
    ok(!CJK.test(wrapText(document.querySelector('.wrap'))), 'list view has no Chinese (except the 中文 button): ' + cjkIn(document.querySelector('main')));
    for (const dd of ['countries', 'months', 'inds', 'types', 'scales', 'hl']) {
      document.querySelector(`[data-dd="${dd}"]`).click();
      const panel = document.querySelector('.ddpanel');
      ok(panel && !CJK.test(panel.innerText), `filter "${dd}" has no Chinese: ` + (panel ? cjkIn(panel) : 'no panel'));
      document.querySelector(`[data-dd="${dd}"]`).click();
    }
    document.querySelector('[data-dd="countries"]').click();
    document.querySelector('.opt[data-v="DE"]').click();
    document.body.click();
    ok(!CJK.test(document.querySelector('#active').innerText), 'active filter pills in English');
    document.querySelector('#clear').click();
    document.querySelector('#v-tl').click();
    ok(!CJK.test(document.querySelector('#out').innerText), 'timeline has no Chinese: ' + cjkIn(document.querySelector('#out')));
    document.querySelector('#v-list').click();
    // every fair's detail panel, in English (ade-2026 has a Chinese note written above, so it is skipped)
    const leaks = [];
    for (const f of fairs) {
      if (f.id === 'ade-2026') continue;
      openDetail(f.id);
      const text = document.querySelector('#drawer').innerText;
      if (CJK.test(text)) leaks.push(f.id + ': ' + cjkIn(document.querySelector('#drawer')));
      closeDetail();
    }
    ok(!leaks.length, `all ${fairs.length - 1} detail panels in English` + (leaks.length ? ' — ' + leaks.slice(0, 3).join(' || ') : ''));
    openDetail('formnext-2026');
    ok(document.querySelector('#drawer').innerText.includes('early-bird rate ends'), 'deadline label in English');
    closeDetail();
    ok(buildIcs([fairs.find(f => f.id === 'ecr-2027')]).includes('SUMMARY:ECR 2027 – European Congress of Radiology'), 'calendar export uses English names');
    // search finds fairs by Chinese and by English words in either language
    const search = s => { const i = document.querySelector('#q'); i.value = s; i.dispatchEvent(new Event('input')); return +document.querySelector('#rcount').textContent.match(/Showing (\d+)/)[1]; };
    ok(search('radiology') === 1 && search('放射学') === 1, 'search works with English and Chinese words');
    search('');
    // and back to Chinese
    document.querySelector('#lang').click();
    ok(document.documentElement.lang === 'zh-CN' && document.querySelector('#rcount').textContent.startsWith('显示'), 'switched back to Chinese');
    ok(document.querySelector('.fair[data-id="ecr-2027"] .name').textContent === 'ECR 2027 欧洲放射学大会', 'Chinese names back');
  }

  window.addEventListener('load', () => {
    run().catch(e => R.push('FAIL exception: ' + (e && e.message || e))).finally(() =>
      fetch('/api/test-result', { method: 'POST', body: R.join('\n') }));
  });
})();
