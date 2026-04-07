        (() => {
            const rawCopyTexts = JSON.parse(
                document.getElementById("raw-copy-data")?.textContent || "{}"
            );
            if (!Object.keys(rawCopyTexts).length) {
                return;
            }

            const toast = document.createElement("div");
            toast.id = "raw-copy-toast";
            document.body.appendChild(toast);

            let toastTimer = 0;
            const showToast = (message) => {
                toast.textContent = message;
                toast.style.opacity = "1";

                window.clearTimeout(toastTimer);
                toastTimer = window.setTimeout(() => {
                    toast.style.opacity = "0";
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
                if (typeof text !== "string" || !text.length) {
                    return;
                }
                const copied = text.length > 0 && await copyText(text);
                showToast(copied ? "Copied" : "Copy failed");
            };
        })();