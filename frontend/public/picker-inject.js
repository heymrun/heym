/**
 * Heym Selector Picker - Injected by bookmarklet.
 * Runs in target page context. Generates CSS selector on element click.
 */
(function () {
  "use strict";

  var scriptUrl = (document.currentScript && document.currentScript.src) || "";
  var baseUrl = scriptUrl.replace(/\/picker-inject\.js.*$/, "") || window.location.origin;

  function escapeCssIdentifier(str) {
    if (!str || typeof str !== "string") return "";
    return str.replace(/([^a-zA-Z0-9_-])/g, "\\$1");
  }

  function getSelector(el) {
    if (!el || !el.tagName) return "";
    var tag = el.tagName.toLowerCase();
    if (tag === "html") return "html";
    if (tag === "body") return "body";

    if (el.id && /^[a-zA-Z][a-zA-Z0-9_-]*$/.test(el.id)) {
      var idSel = "#" + escapeCssIdentifier(el.id);
      try {
        if (document.querySelectorAll(idSel).length === 1) return idSel;
      } catch (e) {
        void e;
      }
    }

    var path = [];
    var current = el;
    while (current && current !== document.body) {
      var part = current.tagName.toLowerCase();
      if (current.id && /^[a-zA-Z][a-zA-Z0-9_-]*$/.test(current.id)) {
        part = "#" + escapeCssIdentifier(current.id);
        path.unshift(part);
        break;
      }
      var classes = (current.className && typeof current.className === "string")
        ? current.className.trim().split(/\s+/).filter(Boolean)
        : [];
      if (classes.length > 0) {
        var classPart = classes.slice(0, 2).map(function (c) {
          return "." + escapeCssIdentifier(c);
        }).join("");
        part += classPart;
      }
      var siblings = current.parentNode ? Array.prototype.filter.call(current.parentNode.children, function (n) {
        return n.tagName === current.tagName;
      }) : [];
      if (siblings.length > 1) {
        var idx = siblings.indexOf(current) + 1;
        part += ":nth-of-type(" + idx + ")";
      }
      path.unshift(part);
      current = current.parentNode;
    }
    return path.join(" > ");
  }

  function onPick(e) {
    e.preventDefault();
    e.stopPropagation();
    var sel = getSelector(e.target);
    if (!sel) return;
    var url = baseUrl + "/picker-callback?selector=" + encodeURIComponent(sel);
    window.open(url, "heym-picker-cb", "width=100,height=100");
    document.body.removeEventListener("click", onPick, true);
    if (overlay) overlay.remove();
    document.body.style.cursor = "";
  }

  var overlay = document.createElement("div");
  overlay.id = "heym-picker-overlay";
  overlay.style.cssText = "position:fixed;top:0;left:0;right:0;bottom:0;z-index:2147483647;pointer-events:none;background:rgba(0,150,255,0.05);border:2px dashed #0096ff;";
  overlay.innerHTML = '<div style="position:fixed;top:10px;left:50%;transform:translateX(-50%);background:#0096ff;color:#fff;padding:8px 16px;border-radius:6px;font-family:sans-serif;font-size:14px;pointer-events:auto;">Click an element to pick its selector</div>';
  document.body.appendChild(overlay);
  document.body.style.cursor = "crosshair";
  document.body.addEventListener("click", onPick, true);
})();
