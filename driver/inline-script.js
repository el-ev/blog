(() => {
  const themeKey = 'blog-color-theme';
  const layoutKey = 'blog-layout';
  let theme = 'light';
  let layout = 'desktop';

  try {
    const savedTheme = window.localStorage?.getItem(themeKey);
    if (savedTheme === 'light' || savedTheme === 'dark') {
      theme = savedTheme;
    } else if (window.matchMedia?.('(prefers-color-scheme: dark)')?.matches) {
      theme = 'dark';
    }
  } catch {
    // noop
  }

  try {
    const savedLayout = window.localStorage?.getItem(layoutKey);
    if (savedLayout === 'desktop' || savedLayout === 'mobile') {
      layout = savedLayout;
    } else if (window.matchMedia?.('(max-width: 640px)')?.matches) {
      layout = 'mobile';
    }
  } catch {
    // noop
  }

  const root = document.documentElement;
  const isDark = theme === 'dark';
  root.setAttribute('data-theme', theme);
  root.classList.toggle('theme-light', !isDark);
  root.classList.toggle('theme-dark', isDark);
  root.style.colorScheme = isDark ? 'dark' : 'light';
  root.setAttribute('data-layout', layout);

  const activatePages = () => {
    const wrapper = document.querySelector('.pages-' + layout);
    if (!wrapper) return;
    wrapper.querySelectorAll('object.page[data-src]').forEach((obj) => {
      if (!obj.getAttribute('data')) {
        obj.setAttribute('data', obj.getAttribute('data-src'));
      }
    });
  };
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', activatePages);
  } else {
    activatePages();
  }
})();
