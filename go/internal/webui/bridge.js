// Stands in for the Wails bridge when the page runs in a browser: window.go.app.API.<Method>(...)
// becomes POST /api/<Method>. Also tells when the data changed behind the page's back.
(function () {
  var de = /^de/i.test(navigator.language || '');
  var known = null;
  var banner = null;

  function note(fp) {
    if (known === null || fp === null) { known = fp; return; }
    if (fp !== known) showBanner();
  }

  function showBanner() {
    if (banner || !document.body) return;
    banner = document.createElement('div');
    banner.setAttribute('role', 'status');
    banner.style.cssText = 'position:fixed;left:50%;bottom:16px;transform:translateX(-50%);z-index:99999;display:flex;gap:12px;align-items:center;padding:8px 14px;border-radius:8px;font:14px system-ui,sans-serif;background:#3b4cca;color:#fff;box-shadow:0 2px 12px rgba(0,0,0,.3)';
    var span = document.createElement('span');
    span.textContent = de ? 'Die Daten wurden im Fenster oder von außen geändert.' : 'The data was changed in the window or from outside.';
    var btn = document.createElement('button');
    btn.textContent = de ? 'Neu laden' : 'Reload';
    btn.style.cssText = 'font:inherit;padding:2px 10px;border-radius:6px;border:1px solid #fff;background:transparent;color:#fff;cursor:pointer';
    btn.onclick = function () { location.reload(); };
    banner.appendChild(span);
    banner.appendChild(btn);
    document.body.appendChild(banner);
  }

  function call(name, args) {
    return fetch('/api/' + name, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(args),
    }).then(function (res) {
      if (!res.ok) throw new Error(res.status + ' ' + res.statusText);
      var fp = res.headers.get('X-Fingerprint');
      return res.json().then(function (a) {
        if (a.error) throw a.error;
        // Own calls move the baseline, so only the changes of the other side show the banner.
        if (fp) known = fp;
        return a.result === undefined ? null : a.result;
      });
    });
  }

  var api = new Proxy({}, {
    get: function (_, name) {
      if (typeof name !== 'string' || name === 'then') return undefined;
      return function () { return call(name, Array.prototype.slice.call(arguments)); };
    },
  });
  window.go = { app: { API: api } };
  window.foresprintWeb = true;

  function poll() {
    fetch('/__changes').then(function (r) { return r.ok ? r.json() : null; }).then(function (j) {
      if (j) note(j.fingerprint);
    }).catch(function () {});
  }
  setInterval(poll, 5000);
  poll();
})();
