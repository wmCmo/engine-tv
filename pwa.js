// Installed-app support shared by every page: registers the service worker and, when the browser
// says the site can be installed, shows an "Install app" button in the top bar.
(function () {
  if ("serviceWorker" in navigator) navigator.serviceWorker.register("/sw.js").catch(() => {});
  window.addEventListener("beforeinstallprompt", e => {
    e.preventDefault();            // use our button instead of the browser's mini banner
    window.__installPrompt = e;
    const bar = document.querySelector(".topbar");
    if (!bar || document.getElementById("installApp")) return;
    const b = document.createElement("button");
    b.id = "installApp";
    b.textContent = "Install app";
    b.title = "Add Lc0 Live to your home screen";
    b.style.cssText = "background:#81b64c;color:#fff;border:0;border-radius:5px;padding:6px 12px;font-weight:700;cursor:pointer";
    b.onclick = async () => { e.prompt(); await e.userChoice; b.remove(); };
    bar.appendChild(b);
  });
  window.addEventListener("appinstalled", () => document.getElementById("installApp")?.remove());
})();
