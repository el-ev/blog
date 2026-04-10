(() => {
    const STORAGE_KEY = "blog-color-theme";
    const LIGHT_THEME = "light";
    const DARK_THEME = "dark";
    const ACTION_PREFIX = "#action=";
    const COPY_ACTION_PREFIX = "copy:";
    const THEME_ACTION = "theme";
    const BOUND_SVG_DOCUMENTS = new WeakSet();
    const SVG_COLOR_TOKENS = [
        "--svg-paper-bg",
        "--svg-text",
        "--svg-muted-text",
        "--svg-footer-text",
        "--svg-code-bg",
        "--svg-surface-bg",
        "--svg-code-comment",
        "--svg-code-green",
        "--svg-code-dark-green",
        "--svg-code-red",
        "--svg-code-blue",
        "--svg-code-magenta",
        "--svg-muted-stroke",
        "--svg-code-gutter",
    ];

    const resolveTheme = (theme) => (theme === DARK_THEME ? DARK_THEME : LIGHT_THEME);

    const getSavedTheme = () => {
        try {
            const theme = window.localStorage?.getItem(STORAGE_KEY);
            return theme === LIGHT_THEME || theme === DARK_THEME ? theme : null;
        } catch {
            return null;
        }
    };

    const getPreferredTheme = () => {
        const media = window.matchMedia?.("(prefers-color-scheme: dark)");
        return media?.matches ? DARK_THEME : LIGHT_THEME;
    };

    const applyThemeToSvgRoot = (svgRoot, computedStyles) => {
        if (!svgRoot) {
            return;
        }
        for (const token of SVG_COLOR_TOKENS) {
            const value = computedStyles.getPropertyValue(token).trim();
            if (value) {
                svgRoot.style.setProperty(token, value);
            }
        }
    };

    const applyThemeToObject = (pageObject, computedStyles) => {
        const svgRoot = pageObject.contentDocument?.documentElement;
        if (!svgRoot) {
            return;
        }
        applyThemeToSvgRoot(svgRoot, computedStyles);
    };

    const readAnchorHref = (anchorNode) => anchorNode.getAttribute("href") || "";

    const parseActionPayload = (actionPayload) => {
        const segments = actionPayload
            .split("|")
            .map((segment) => segment.trim())
            .filter((segment) => segment.length > 0);
        if (segments.length === 0) {
            return { actionToken: "", metadata: {} };
        }

        const actionToken = segments[0];
        const metadata = {};
        for (const segment of segments.slice(1)) {
            const separatorIndex = segment.indexOf(":");
            if (separatorIndex <= 0) {
                continue;
            }
            const key = segment.slice(0, separatorIndex).trim().toLowerCase();
            const value = segment.slice(separatorIndex + 1).trim();
            if (!key || !value) {
                continue;
            }
            metadata[key] = value;
        }
        return { actionToken, metadata };
    };

    const parseSvgAction = (href) => {
        if (!href.startsWith(ACTION_PREFIX)) {
            return null;
        }
        let actionPayload = href.slice(ACTION_PREFIX.length);
        try {
            actionPayload = decodeURIComponent(actionPayload);
        } catch {
            // Keep the raw payload when decoding fails.
        }

        const { actionToken } = parseActionPayload(actionPayload);
        if (actionToken === THEME_ACTION) {
            return { type: THEME_ACTION };
        }
        if (actionToken.startsWith(COPY_ACTION_PREFIX)) {
            const uid = actionToken.slice(COPY_ACTION_PREFIX.length).trim();
            if (uid) {
                return { type: "copy", uid };
            }
        }
        return null;
    };

    const executeSvgAction = (action) => {
        if (action.type === THEME_ACTION) {
            window.toggleColorTheme?.();
            return;
        }
        if (action.type === "copy") {
            void window.copyCode?.(action.uid);
        }
    };

    const bindSvgActionsToObject = (pageObject) => {
        const svgDocument = pageObject.contentDocument;
        if (!svgDocument || BOUND_SVG_DOCUMENTS.has(svgDocument)) {
            return;
        }
        BOUND_SVG_DOCUMENTS.add(svgDocument);

        svgDocument.addEventListener("click", (event) => {
            const eventTarget = event.target;
            if (!eventTarget || typeof eventTarget.closest !== "function") {
                return;
            }
            const anchorNode = eventTarget.closest("a");
            if (!anchorNode) {
                return;
            }

            const action = parseSvgAction(readAnchorHref(anchorNode));
            if (!action) {
                return;
            }

            event.preventDefault();
            executeSvgAction(action);
        });

        svgDocument.addEventListener("keydown", (event) => {
            if (event.key !== " " && event.key !== "Spacebar") {
                return;
            }
            const eventTarget = event.target;
            if (!eventTarget || typeof eventTarget.closest !== "function") {
                return;
            }
            const anchorNode = eventTarget.closest("a");
            if (!anchorNode) {
                return;
            }
            const action = parseSvgAction(readAnchorHref(anchorNode));
            if (!action) {
                return;
            }
            event.preventDefault();
            executeSvgAction(action);
        });
    };

    const applyTheme = (theme, persist = false) => {
        const resolvedTheme = resolveTheme(theme);
        const root = document.documentElement;
        root.setAttribute("data-theme", resolvedTheme);
        root.classList.toggle("theme-light", resolvedTheme === LIGHT_THEME);
        root.classList.toggle("theme-dark", resolvedTheme === DARK_THEME);

        const computedStyles = window.getComputedStyle(root);
        document
            .querySelectorAll('object.page[type="image/svg+xml"]')
            .forEach((pageObject) => applyThemeToObject(pageObject, computedStyles));

        if (persist) {
            try {
                window.localStorage?.setItem(STORAGE_KEY, resolvedTheme);
            } catch {
                // noop
            }
        }
    };

    const getCurrentTheme = () =>
        resolveTheme(document.documentElement.getAttribute("data-theme"));

    const initializePageObject = (pageObject) => {
        const computedStyles = window.getComputedStyle(document.documentElement);
        applyThemeToObject(pageObject, computedStyles);
        bindSvgActionsToObject(pageObject);
    };

    document
        .querySelectorAll('object.page[type="image/svg+xml"]')
        .forEach((pageObject) => {
            pageObject.addEventListener("load", () => {
                initializePageObject(pageObject);
            });
            initializePageObject(pageObject);
        });

    window.toggleColorTheme = () => {
        const nextTheme = getCurrentTheme() === DARK_THEME ? LIGHT_THEME : DARK_THEME;
        applyTheme(nextTheme, true);
    };

    window.setColorTheme = (theme) => {
        if (theme !== LIGHT_THEME && theme !== DARK_THEME) {
            return;
        }
        applyTheme(theme, true);
    };

    const initialTheme = getSavedTheme() || getPreferredTheme();
    applyTheme(initialTheme);
})();
