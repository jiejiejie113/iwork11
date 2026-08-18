(() => {
    "use strict";

    const basePath = window.location.pathname.includes("/iwork/") ? "/iwork/" : "/";

    function csrfToken() {
        const item = document.cookie.split("; ").find((value) => value.startsWith("csrftoken="));
        return item ? decodeURIComponent(item.split("=").slice(1).join("=")) : "";
    }

    async function requestJson(path, options = {}) {
        const response = await fetch(basePath + path, {
            credentials: "same-origin",
            ...options,
            headers: {
                "Content-Type": "application/json",
                "X-CSRFToken": csrfToken(),
                ...(options.headers || {}),
            },
        });
        if (!response.ok) {
            const payload = await response.json().catch(() => ({}));
            throw new Error(payload.message || payload.error || `请求失败 (${response.status})`);
        }
        return response.json();
    }

    function createText(tag, className, value) {
        const element = document.createElement(tag);
        element.className = className;
        element.textContent = value;
        return element;
    }

    document.querySelectorAll("[data-iwork-notification-center]").forEach((root) => {
        if (root.dataset.initialized === "true") return;
        root.dataset.initialized = "true";
        const toggle = root.querySelector("[data-notification-toggle]");
        const count = root.querySelector("[data-notification-count]");
        const drawer = root.querySelector("[data-notification-drawer]");
        const list = root.querySelector("[data-notification-list]");
        const subscriptionsPanel = root.querySelector("[data-notification-subscriptions]");
        const settingsButton = root.querySelector("[data-notification-settings]");
        const readAllButton = root.querySelector("[data-notification-read-all]");
        let notifications = [];
        let subscriptionData = {subscriptions: [], available_rules: []};

        function renderNotifications(unreadCount = 0) {
            count.hidden = unreadCount <= 0;
            count.textContent = unreadCount > 99 ? "99+" : String(unreadCount);
            list.replaceChildren();
            if (!notifications.length) {
                list.append(createText("p", "py-8 text-center text-sm text-slate-500", "暂无通知"));
                return;
            }
            notifications.forEach((notification) => {
                const card = document.createElement("button");
                card.type = "button";
                card.className = `w-full text-left rounded-md px-3 py-2 mb-1 border transition-colors ${notification.is_read ? "border-slate-800 bg-slate-800/40 text-slate-400" : "border-blue-800 bg-blue-950/40 text-slate-100"}`;
                card.append(createText("strong", "block text-sm", notification.title));
                card.append(createText("span", "block mt-1 text-xs", notification.message));
                card.append(createText("time", "block mt-1 text-[11px] text-slate-500", new Date(notification.updated_at).toLocaleString("zh-CN")));
                if (!notification.is_read) {
                    card.addEventListener("click", async () => {
                        await requestJson(`api/account/notifications/${notification.id}/read/`, {method: "POST", body: "{}"});
                        await loadNotifications();
                    });
                }
                list.append(card);
            });
        }

        async function loadNotifications() {
            try {
                const payload = await requestJson("api/account/notifications/");
                notifications = payload.notifications || [];
                renderNotifications(payload.unread_count || 0);
            } catch (error) {
                if (String(error.message).includes("可信用户身份")) root.hidden = true;
                else console.warn("加载站内通知失败:", error);
            }
        }

        function subscriptionKey(ruleCode, scopeValue) {
            return `${ruleCode}\u0000${scopeValue || ""}`;
        }

        function renderSubscriptions() {
            subscriptionsPanel.replaceChildren();
            const selected = new Set((subscriptionData.subscriptions || []).map((item) => subscriptionKey(item.rule_code, item.scope_value)));
            const editable = [];
            (subscriptionData.available_rules || []).forEach((rule) => {
                const section = document.createElement("section");
                section.className = "mb-3 rounded border border-slate-700 p-2";
                section.append(createText("strong", "block text-sm text-slate-200", rule.name));
                if (rule.mandatory) {
                    section.append(createText("p", "mt-1 text-xs text-amber-300", "管理员强制通知，不能取消"));
                } else if (rule.scope_type === "flow") {
                    (rule.scopes || []).forEach((scope) => {
                        const label = document.createElement("label");
                        label.className = "mt-2 flex items-center gap-2 text-xs text-slate-300";
                        const input = document.createElement("input");
                        input.type = "checkbox";
                        input.checked = selected.has(subscriptionKey(rule.rule_code, scope));
                        input.dataset.ruleCode = rule.rule_code;
                        input.dataset.scopeType = rule.scope_type;
                        input.dataset.scopeValue = scope;
                        editable.push(input);
                        label.append(input, document.createTextNode(scope));
                        section.append(label);
                    });
                }
                subscriptionsPanel.append(section);
            });
            if (!(subscriptionData.available_rules || []).length) {
                subscriptionsPanel.append(createText("p", "py-6 text-center text-sm text-slate-500", "暂无可配置订阅"));
            }
            const save = createText("button", "w-full rounded bg-blue-600 hover:bg-blue-500 px-3 py-2 text-sm", "保存订阅");
            save.type = "button";
            save.addEventListener("click", async () => {
                const payload = editable.filter((input) => input.checked).map((input) => ({
                    rule_code: input.dataset.ruleCode,
                    scope_type: input.dataset.scopeType,
                    scope_value: input.dataset.scopeValue,
                }));
                subscriptionData = await requestJson("api/account/subscriptions/", {
                    method: "PUT",
                    body: JSON.stringify({subscriptions: payload}),
                });
                subscriptionsPanel.hidden = true;
                list.hidden = false;
            });
            subscriptionsPanel.append(save);
        }

        toggle.addEventListener("click", async () => {
            drawer.hidden = !drawer.hidden;
            if (!drawer.hidden) await loadNotifications();
        });
        settingsButton.addEventListener("click", async () => {
            subscriptionData = await requestJson("api/account/subscriptions/");
            renderSubscriptions();
            list.hidden = true;
            subscriptionsPanel.hidden = false;
        });
        readAllButton.addEventListener("click", async () => {
            await requestJson("api/account/notifications/read-all/", {method: "POST", body: "{}"});
            await loadNotifications();
        });
        document.addEventListener("click", (event) => {
            if (!root.contains(event.target)) drawer.hidden = true;
        });

        const source = new EventSource(basePath + "api/account/notifications/stream/");
        source.addEventListener("notification_changed", loadNotifications);
        source.onerror = () => {
            // EventSource按服务端retry自动重连；每次重连都会重新经过应用授权。
        };
        loadNotifications();
    });
})();
