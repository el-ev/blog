(() => {
  const ACTIVE_INPUTS = new Map();
  const SR_INPUTS = new Map();
  const SR_CHECKBOXES = new Map();
  const SR_RADIOS = new Map();
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
    const cb = SR_CHECKBOXES.get(id);
    if (cb) return cb.checked ? 'true' : '';
    const radios = SR_RADIOS.get(id);
    if (radios) {
      for (const r of radios) {
        if (r.checked) return r.value;
      }
      return '';
    }
    const entry = ACTIVE_INPUTS.get(id);
    return entry ? entry.element.value : '';
  };

  f.set = (id, value) => {
    const str = String(value);
    const cb = SR_CHECKBOXES.get(id);
    if (cb) {
      cb.checked = str === 'true';
      document.dispatchEvent(new CustomEvent('svg-input', {detail: {id, value: str}}));
      return;
    }
    const radios = SR_RADIOS.get(id);
    if (radios) {
      for (const r of radios) {
        r.checked = r.value === str;
      }
      document.dispatchEvent(new CustomEvent('svg-input', {detail: {id, value: str}}));
      return;
    }
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

  document.querySelectorAll('.sr-only-checkbox').forEach((cb) => {
    const id = cb.dataset.checkboxId;
    if (!id) return;
    SR_CHECKBOXES.set(id, cb);
    f._conds['checkbox:' + id] = () => cb.checked;
    cb.addEventListener('change', () => {
      fireInput(id, cb.checked ? 'true' : '');
    });
  });

  document.querySelectorAll('.sr-only-radio').forEach((radio) => {
    const group = radio.dataset.radioGroup;
    if (!group) return;
    if (!SR_RADIOS.has(group)) SR_RADIOS.set(group, []);
    SR_RADIOS.get(group).push(radio);
    f._conds['radio:' + group + ':' + radio.value] = () => radio.checked;
    radio.addEventListener('change', () => {
      fireInput(group, radio.value);
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

  const spawnInputOverlay = (id, anchorNode, pageObject, initialKey) => {
    const existing = ACTIVE_INPUTS.get(id);
    if (existing) {
      existing.element.focus();
      if (initialKey) {
        existing.element.value += initialKey;
        fireInput(id, existing.element.value);
      }
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
        anchorNode.focus();
        return;
      }
      if (e.key === 'Tab') {
        e.preventDefault();
        input.blur();
        const svgDoc = pageObject.contentDocument;
        if (svgDoc) {
          const focusable = [...svgDoc.querySelectorAll('a[aria-label]')];
          const idx = focusable.indexOf(anchorNode);
          const next = focusable[e.shiftKey ? idx - 1 : idx + 1];
          if (next) next.focus();
          else anchorNode.focus();
        }
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

    if (initialKey) {
      input.value += initialKey;
      fireInput(id, input.value);
    }
  };

  window.spawnFormInput = spawnInputOverlay;

  window.execFormAction = (id) => {
    const fn = f._actions[id];
    if (typeof fn === 'function') {
      fn();
    }
  };

  window.toggleCheckbox = (id) => {
    const cb = SR_CHECKBOXES.get(id);
    if (cb) {
      cb.checked = !cb.checked;
      fireInput(id, cb.checked ? 'true' : '');
    }
  };

  window.selectRadio = (group, value) => {
    const radios = SR_RADIOS.get(group);
    if (!radios) return;
    for (const r of radios) {
      r.checked = r.value === value;
    }
    fireInput(group, value);
  };
})();
