(() => {
  const storageKey = 'blog-color-theme';
  let theme = 'light';

  try {
    const savedTheme = window.localStorage?.getItem(storageKey);
    if (savedTheme === 'light' || savedTheme === 'dark') {
      theme = savedTheme;
    } else if (window.matchMedia?.('(prefers-color-scheme: dark)')?.matches) {
      theme = 'dark';
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
})();
