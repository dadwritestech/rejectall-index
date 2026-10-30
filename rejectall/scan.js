// Runs inside one frame. Collects visible clickable elements and toggles,
// walking open shadow roots. Tags each element with data-rai-id so Python can
// click it later with a CSS locator (Playwright CSS pierces open shadow DOM).
// Classification happens in Python; this only gathers facts.
(args) => {
  const { cookieRe, cmpRe, liRe, scanTag } = args;
  const COOKIE = new RegExp(cookieRe, "i");
  const CMP = new RegExp(cmpRe, "i");
  const LI = new RegExp(liRe, "i");
  const CLICKABLE = 'button, a, [role="button"], [role="link"], input[type="button"], input[type="submit"], [onclick], [tabindex]';
  const TOGGLE = 'input[type="checkbox"], [role="switch"], [role="checkbox"]';

  function* walk(root) {
    const stack = [root];
    while (stack.length) {
      const node = stack.pop();
      if (node.nodeType === 1) {
        yield node;
        if (node.shadowRoot) stack.push(node.shadowRoot);
      }
      const kids = node.children || [];
      for (let i = kids.length - 1; i >= 0; i--) stack.push(kids[i]);
    }
  }
  function parentOf(el) {
    if (el.parentElement) return el.parentElement;
    const r = el.getRootNode && el.getRootNode();
    return r && r.host ? r.host : null;
  }
  function visible(el) {
    const r = el.getBoundingClientRect();
    if (r.width < 2 || r.height < 2) return false;
    const s = getComputedStyle(el);
    if (s.visibility === "hidden" || s.display === "none" || parseFloat(s.opacity) < 0.05) return false;
    // Banners often fade out on an ancestor (opacity 0) before leaving the DOM.
    if (el.checkVisibility && !el.checkVisibility({ opacityProperty: true, visibilityProperty: true })) return false;
    return true;
  }
  function label(el) {
    let t = (el.innerText || el.value || "").trim();
    if (!t) t = (el.getAttribute("aria-label") || el.getAttribute("title") || "").trim();
    return t.replace(/\s+/g, " ").slice(0, 120);
  }
  function inContext(el) {
    let cur = el, depth = 0, textChecked = 0;
    while (cur && depth < 12) {
      const idc = (cur.id || "") + " " + (typeof cur.className === "string" ? cur.className : "") + " " + (cur.getAttribute && (cur.getAttribute("aria-label") || ""));
      if (CMP.test(idc)) return true;
      if (cur.getAttribute && /dialog|alertdialog/.test(cur.getAttribute("role") || "")) {
        if (COOKIE.test((cur.innerText || "").slice(0, 4000))) return true;
      }
      if (textChecked < 6) {
        const txt = (cur.innerText || "");
        if (txt.length > 0 && txt.length < 6000 && COOKIE.test(txt)) {
          const s = getComputedStyle(cur);
          // Footer links also sit near "privacy" text; demand an overlay-like ancestor
          // or a short local block for the text match to count.
          if (s.position === "fixed" || s.position === "sticky" || txt.length < 1500) return true;
        }
        textChecked++;
      }
      cur = parentOf(cur);
      depth++;
    }
    return false;
  }
  // Innermost fixed/sticky/dialog ancestor: the "overlay root" a banner lives in.
  // Buttons sharing a root form one group (one banner). html/body are skipped:
  // scroll-lock scripts often make body position:fixed while a banner is open.
  let grpN = 0;  // groups is declared below, before first use
  function overlayRoot(el) {
    let cur = el, root = null;
    while (cur && cur !== document.body && cur !== document.documentElement) {
      const s = getComputedStyle(cur);
      if (s.position === "fixed" || s.position === "sticky" || (cur.getAttribute && /dialog/.test(cur.getAttribute("role") || ""))) { root = cur; break; }
      cur = parentOf(cur);
    }
    if (!root) return null;
    if (!root.getAttribute("data-rai-grp") || !root.getAttribute("data-rai-grp").startsWith(scanTag + "-")) {
      const gid = `${scanTag}-g${grpN++}`;
      root.setAttribute("data-rai-grp", gid);
      const r = root.getBoundingClientRect();
      const vw = innerWidth, vh = innerHeight;
      const w = Math.max(0, Math.min(r.right, vw) - Math.max(r.left, 0)), h = Math.max(0, Math.min(r.bottom, vh) - Math.max(r.top, 0));
      groups[gid] = { area: Math.round(w * h), text: (root.innerText || "").replace(/\s+/g, " ").slice(0, 3000) };
    }
    return root.getAttribute("data-rai-grp");
  }

  const buttons = [];
  const toggles = [];
  const groups = {};
  let n = 0;
  for (const el of walk(document)) {
    if (el.matches && el.matches(CLICKABLE)) {
      if (el.matches("[tabindex]") && !el.matches('button, a, [role="button"], [onclick]')) {
        if (getComputedStyle(el).cursor !== "pointer") continue;
      }
      if (!visible(el)) continue;
      const text = label(el);
      if (!text) continue;
      const id = `${scanTag}-${n++}`;
      el.setAttribute("data-rai-id", id);
      const r = el.getBoundingClientRect();
      buttons.push({ id, text, tag: el.tagName.toLowerCase(), context: inContext(el), group: overlayRoot(el),
        box: [Math.round(r.x), Math.round(r.y), Math.round(r.width), Math.round(r.height)] });
    } else if (el.matches && el.matches(TOGGLE)) {
      if (!inContext(el)) continue;
      const checked = el.matches("input") ? el.checked : el.getAttribute("aria-checked") === "true";
      const disabled = el.disabled || el.getAttribute("aria-disabled") === "true";
      // Custom switches hide the real input; judge visibility on the nearest visible ancestor.
      let host = el, hops = 0;
      while (host && !visible(host) && hops < 4) { host = parentOf(host); hops++; }
      let ctx = "", cur = el;
      for (let i = 0; i < 4 && cur; i++) { ctx = (cur.innerText || "").trim(); if (ctx.length > 3) break; cur = parentOf(cur); }
      const lbl = (el.labels && el.labels[0] && el.labels[0].innerText) || el.getAttribute("aria-label") || ctx.slice(0, 160);
      let liCtx = "", c2 = el;
      const attrs = (el.id || "") + " " + (el.getAttribute("name") || "") + " " + (el.getAttribute("aria-label") || "");
      if (/leg[-_ ]?(?:it|int)|legitimate/i.test(attrs)) liCtx = "legitimate interest";
      for (let i = 0; i < 3 && c2 && !liCtx; i++) { liCtx = (c2.innerText || "") + " " + (c2.id || "") + " " + (c2.getAttribute ? c2.getAttribute("aria-label") || "" : ""); if (LI.test(liCtx)) break; liCtx = ""; c2 = parentOf(c2); }
      const id = `${scanTag}-t${n++}`;
      el.setAttribute("data-rai-id", id);
      toggles.push({ id, label: (lbl || "").replace(/\s+/g, " ").trim().slice(0, 160), checked: !!checked,
        disabled: !!disabled, visible: !!(host && visible(host)), legit_interest: LI.test(liCtx) });
    }
  }
  const bodyText = (document.body && document.body.innerText || "").slice(0, 20000);
  return { buttons, toggles, groups, title: document.title || "", bodyText, url: location.href };
}
