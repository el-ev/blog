(() => {
  const rawCopyNode = document.getElementById('copy-data');
  if (!rawCopyNode) {
    return;
  }

  let rawCopyTexts = {};
  let toast = null;
  let toastTimer = 0;
  let announcer = null;

  const ensureToast = () => {
    if (toast) {
      return toast;
    }
    const nextToast = document.createElement('div');
    nextToast.id = 'copy-toast';
    nextToast.setAttribute('aria-hidden', 'true');
    document.body.appendChild(nextToast);
    toast = nextToast;
    return nextToast;
  };

  const ensureAnnouncer = () => {
    if (announcer) {
      return announcer;
    }
    const nextAnnouncer = document.createElement('div');
    nextAnnouncer.id = 'copy-announcer';
    nextAnnouncer.className = 'sr-only';
    nextAnnouncer.setAttribute('role', 'status');
    nextAnnouncer.setAttribute('aria-live', 'polite');
    nextAnnouncer.setAttribute('aria-atomic', 'true');
    document.body.appendChild(nextAnnouncer);
    announcer = nextAnnouncer;
    return nextAnnouncer;
  };

  const announce = (message) => {
    const announcerElement = ensureAnnouncer();
    announcerElement.textContent = '';
    window.requestAnimationFrame(() => {
      announcerElement.textContent = message;
    });
  };

  const showToast = (message) => {
    const toastElement = ensureToast();
    toastElement.textContent = message;
    toastElement.style.opacity = '1';
    announce(message);

    window.clearTimeout(toastTimer);
    toastTimer = window.setTimeout(() => {
      toastElement.style.opacity = '0';
    }, 1200);
  };

  const copyText = async (text) => {
    try {
      await navigator.clipboard?.writeText(text);
      return true;
    } catch {
      return false;
    }
  };

  window.copyCode = async (uid) => {
    const text = rawCopyTexts[uid];
    if (typeof text !== 'string' || !text.length) {
      return;
    }
    const copied = text.length > 0 && await copyText(text);
    showToast(copied ? 'Copied' : 'Copy failed');
  };

  const parseRawCopyPayload = (payload) => {
    try {
      const data = JSON.parse(payload);
      if (!data || typeof data !== 'object' || Array.isArray(data)) {
        return {};
      }
      const normalized = {};
      for (const [key, value] of Object.entries(data)) {
        if (typeof value === 'string') {
          normalized[key] = value;
        }
      }
      return normalized;
    } catch {
      return {};
    }
  };

  const inlinePayload = rawCopyNode.textContent?.trim() || '';
  if (inlinePayload) {
    rawCopyTexts = parseRawCopyPayload(inlinePayload);
    if (Object.keys(rawCopyTexts).length) {
      return;
    }
  }

  const rawCopySrc = rawCopyNode.getAttribute('data-src');
  if (!rawCopySrc) {
    return;
  }

  const hydrateRawCopyData = async () => {
    try {
      const response = await fetch(rawCopySrc, {cache: 'force-cache'});
      if (!response.ok) {
        return;
      }
      rawCopyTexts = parseRawCopyPayload(await response.text());
    } catch {
      // Keep the no-op copy handler when payload fetch fails.
    }
  };

  void hydrateRawCopyData();
})();
