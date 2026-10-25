// Stands in for the Wails bridge when the page runs in a browser: window.go.app.API.<Method>(...)
// becomes POST /api/<Method>. Also passes the changes of the data folder on to the page.
(function () {
  // The window and this page show the same data folder. The server tells every change of it
  // (server-sent events); the page decides whether it was its own and reloads its view if not.
  function listen() {
    var es = new EventSource('/__events');
    es.onmessage = function (e) {
      // The first message is the state when the page opened; the page may not listen yet.
      if (window.foresprintFingerprint === undefined) window.foresprintFingerprint = e.data;
      window.dispatchEvent(new CustomEvent('foresprint:data', { detail: e.data }));
    };
  }

  function call(name, args) {
    return fetch('/api/' + name, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(args),
    }).then(function (res) {
      if (!res.ok) throw new Error(res.status + ' ' + res.statusText);
      return res.json().then(function (a) {
        if (a.error) throw a.error;
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

  listen();
})();
