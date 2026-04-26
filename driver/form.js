(() => {
  const ACTIVE_INPUTS = new Map();
  const SR_INPUTS = new Map();
  const BOUND_COND_DOCS = new WeakSet();
  const SVG_DOCS = new Set();

  const f = window.form = window.form || {_conds: {}, _actions: {}, _on: {}};

  const initCondElements = (svgDoc) => {
    if (BOUND_COND_DOCS.has(svgDoc)) {
      return;
    }
    BOUND_COND_DOCS.add(svgDoc);
    SVG_DOCS.add(svgDoc);

    svgDoc.querySelectorAll('[data-cond-id]').forEach((el) => {
      if (el.getAttribute('data-cond-branch') === '1') {
        el.style.display = 'none';
      }
    });
  };

  const evaluateCond = (condId) => {
    const fn = f._conds[condId];
    return typeof fn === 'function' ? !!fn() : false;
  };

  const refreshCond = (condId) => {
    const result = evaluateCond(condId);
    const selector = '[data-cond-id="' + CSS.escape(condId) + '"]';
    const toggle = (el) => {
      const branch = el.getAttribute('data-cond-branch');
      const show = branch === '1' ? result : !result;
      el.style.display = show ? '' : 'none';
    };
    for (const svgDoc of SVG_DOCS) {
      svgDoc.querySelectorAll(selector).forEach(toggle);
    }
    document.querySelectorAll(selector).forEach(toggle);
  };

  const refreshAllConds = () => {
    const ids = new Set();
    for (const svgDoc of SVG_DOCS) {
      svgDoc.querySelectorAll('[data-cond-id]').forEach((el) => {
        ids.add(el.getAttribute('data-cond-id'));
      });
    }
    document.querySelectorAll('[data-cond-id]').forEach((el) => {
      ids.add(el.getAttribute('data-cond-id'));
    });
    for (const condId of ids) {
      refreshCond(condId);
    }
  };

  const syncValue = (id, value) => {
    const overlay = ACTIVE_INPUTS.get(id);
    if (overlay && overlay.element.value !== value) {
      overlay.element.value = value;
    }
    const srInput = SR_INPUTS.get(id);
    if (srInput && srInput.value !== value) {
      srInput.value = value;
    }
  };

  const fireInput = (id, value) => {
    syncValue(id, value);
    const fns = f._on[id];
    if (fns) fns.forEach((fn) => fn(value));
    document.dispatchEvent(new CustomEvent('svg-input', {
      detail: {id, value},
    }));
  };

  f.get = (id) => {
    const srInput = SR_INPUTS.get(id);
    if (srInput) return srInput.value;
    const entry = ACTIVE_INPUTS.get(id);
    return entry ? entry.element.value : '';
  };

  f.set = (id, value) => {
    const str = String(value);
    syncValue(id, str);
    document.dispatchEvent(new CustomEvent('svg-input', {
      detail: {id, value: str},
    }));
  };

  f.refresh = refreshAllConds;

  const bindPageObject = (pageObject) => {
    const svgDoc = pageObject.contentDocument;
    if (svgDoc) {
      initCondElements(svgDoc);
      refreshAllConds();
    }
  };

  document.querySelectorAll('object.page[type="image/svg+xml"]')
      .forEach((pageObject) => {
        pageObject.addEventListener('load', () => bindPageObject(pageObject));
        bindPageObject(pageObject);
      });

  document.querySelectorAll('.sr-only-input').forEach((input) => {
    const id = input.dataset.inputId;
    if (!id) return;
    SR_INPUTS.set(id, input);
    input.addEventListener('input', () => {
      fireInput(id, input.value);
    });
  });

  document.querySelectorAll('.sr-only-action').forEach((btn) => {
    const id = btn.dataset.actionId;
    if (!id) return;
    btn.addEventListener('click', () => {
      window.execFormAction?.(id);
    });
  });

  document.addEventListener('svg-input', () => {
    refreshAllConds();
  });

  refreshAllConds();

  new MutationObserver(() => {
    for (const [, entry] of ACTIVE_INPUTS) {
      entry.element.remove();
    }
    ACTIVE_INPUTS.clear();
  }).observe(document.documentElement, {
    attributes: true,
    attributeFilter: ['data-layout'],
  });

  const spawnInputOverlay = (id, anchorNode, pageObject) => {
    const existing = ACTIVE_INPUTS.get(id);
    if (existing) {
      existing.element.focus();
      return;
    }

    const input = document.createElement('input');
    input.type = 'text';
    input.className = 'svg-input-overlay';
    input.dataset.inputId = id;
    input.setAttribute('aria-label', 'Input: ' + id);

    const srInput = SR_INPUTS.get(id);
    if (srInput) {
      input.value = srInput.value;
    }

    const reposition = () => {
      const oRect = pageObject.getBoundingClientRect();
      const aRect = anchorNode.getBoundingClientRect();
      input.style.left = (oRect.left + aRect.left + window.scrollX) + 'px';
      input.style.top = (oRect.top + aRect.top + window.scrollY) + 'px';
      input.style.width = aRect.width + 'px';
      input.style.height = aRect.height + 'px';
      input.style.fontSize = Math.round(Math.max(10, aRect.height * 0.5)) + 'px';
    };

    reposition();
    document.body.appendChild(input);
    ACTIVE_INPUTS.set(id, {element: input, reposition});

    input.addEventListener('keydown', (e) => {
      if (e.key === 'Escape') {
        input.blur();
      }
    });

    input.addEventListener('blur', () => {
      if (!input.value) {
        input.remove();
        ACTIVE_INPUTS.delete(id);
      }
    });

    input.addEventListener('input', () => {
      fireInput(id, input.value);
    });

    const trackPosition = () => {
      if (!input.isConnected) return;
      reposition();
      requestAnimationFrame(trackPosition);
    };
    requestAnimationFrame(trackPosition);
    input.focus();
  };

  window.spawnFormInput = spawnInputOverlay;

  window.execFormAction = (id) => {
    const fn = f._actions[id];
    if (typeof fn === 'function') {
      fn();
    }
  };
})();
