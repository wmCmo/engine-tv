// Installed-app support for both apps' pages: registers the shared service worker (/sw.js) and, when the
// browser says the site can be installed, adds an "Install app" button to the page's top bar.
(function () {
  // registration only works over HTTPS (tailscale serve) or on localhost
  if ("serviceWorker" in navigator && window.isSecureContext) navigator.serviceWorker.register("/sw.js").catch(() => {});
  window.addEventListener("beforeinstallprompt", e => {
    e.preventDefault();            // our button instead of the browser's mini banner
    const bar = document.querySelector(".topbar") || document.querySelector("header");
    if (!bar || document.getElementById("installApp")) return;
    const b = document.createElement("button");
    b.id = "installApp";
    b.textContent = "Install app";
    b.title = "Add this app to your home screen";
    b.style.cssText = "background:var(--accent,#81b64c);color:#1f1d1b;border:0;border-radius:5px;padding:6px 12px;"
      + "font:inherit;font-size:13px;font-weight:700;cursor:pointer;width:auto;margin:0";
    b.onclick = async () => { e.prompt(); await e.userChoice; b.remove(); };
    bar.appendChild(b);
  });
  window.addEventListener("appinstalled", () => document.getElementById("installApp")?.remove());
})();
