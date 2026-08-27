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

    const STATUS_META = {
        pending: ["待提交", "bg-amber-500/20 text-amber-300 border-amber-500"],
        overdue: ["已逾期", "bg-red-500/20 text-red-300 border-red-500"],
        fulfilled: ["已完成", "bg-emerald-500/20 text-emerald-300 border-emerald-500"],
        fulfilled_late: ["逾期补交", "bg-orange-500/20 text-orange-300 border-orange-500"],
        waived: ["已豁免", "bg-slate-500/20 text-slate-300 border-slate-500"],
    };

    function formatDeadline(value) {
        if (!value) return "";
        const date = new Date(value);
        if (Number.isNaN(date.getTime())) return "";
        return new Intl.DateTimeFormat("sv-SE", {
            timeZone: "Asia/Bangkok",
            year: "numeric",
            month: "2-digit",
            day: "2-digit",
            hour: "2-digit",
            minute: "2-digit",
        }).format(date).replace("T", " ");
    }

    function statusBadge(status) {
        const [label, className] = STATUS_META[status] || [status, "bg-slate-500/20 text-slate-300 border-slate-500"];
        const badge = createText("span", `inline-block px-2 py-0.5 rounded border text-xs ${className}`, label);
        return badge;
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
        const modal = root.querySelector("[data-notification-modal]");
        const modalTitle = root.querySelector("[data-notification-modal-title]");
        const modalBody = root.querySelector("[data-notification-modal-body]");
        const modalClose = root.querySelector("[data-notification-modal-close]");
        let notifications = [];
        let subscriptionData = {subscriptions: [], available_rules: []};

        function closeModal() {
            modal.hidden = true;
            modalBody.replaceChildren();
        }

        function renderModalDetail(payload) {
            modalBody.replaceChildren();
            const counts = payload.status_counts || {};
            const countRow = document.createElement("div");
            countRow.className = "flex flex-wrap gap-2 mb-3";
            for (const [status, [label]] of Object.entries(STATUS_META)) {
                const pill = document.createElement("span");
                pill.className = "px-2 py-1 rounded border border-slate-600 bg-slate-800 text-xs";
                pill.append(statusBadge(status), document.createTextNode(` ${counts[status] || 0}`));
                countRow.appendChild(pill);
            }
            modalBody.appendChild(countRow);

            const flows = payload.flows || [];
            const table = document.createElement("table");
            table.className = "w-full text-left text-sm border-collapse";
            const head = document.createElement("thead");
            head.innerHTML = "<tr class='text-xs text-slate-400 border-b border-slate-700'>"
                + "<th class='py-2 pr-2'>分组</th><th class='py-2 pr-2'>状态</th>"
                + "<th class='py-2 pr-2'>截止时间（UTC+7）</th><th class='py-2'>负责人</th></tr>";
            const body = document.createElement("tbody");
            if (!flows.length) {
                const row = document.createElement("tr");
                const cell = document.createElement("td");
                cell.colSpan = 4;
                cell.className = "py-6 text-center text-slate-500";
                cell.textContent = "当日无责任明细。";
                row.appendChild(cell);
                body.appendChild(row);
            }
            for (const item of flows) {
                const row = document.createElement("tr");
                row.className = "border-b border-slate-800 align-top";
                const flowCell = document.createElement("td");
                flowCell.className = "py-2 pr-2";
                flowCell.textContent = item.flow;
                const statusCell = document.createElement("td");
                statusCell.className = "py-2 pr-2";
                statusCell.appendChild(statusBadge(item.status));
                const deadlineCell = document.createElement("td");
                deadlineCell.className = "py-2 pr-2 whitespace-nowrap";
                deadlineCell.textContent = formatDeadline(item.deadline_at);
                const leaderCell = document.createElement("td");
                leaderCell.className = "py-2";
                leaderCell.textContent = (item.leaders || []).join("、") || "—";
                row.append(flowCell, statusCell, deadlineCell, leaderCell);
                body.appendChild(row);
            }
            table.append(head, body);
            modalBody.appendChild(table);
        }

        function openModalDetail(notification) {
            if (!notification || !notification.payload || notification.payload.type !== "daily_summary") {
                return;
            }
            modalTitle.textContent = notification.title || "每日责任摘要";
            renderModalDetail(notification.payload);
            modal.hidden = false;
        }

        function hasDetail(notification) {
            return Boolean(notification && notification.payload && notification.payload.type === "daily_summary");
        }

        function createNotificationCard(notification) {
            const card = document.createElement("button");
            card.type = "button";
            card.className = `w-full text-left rounded-md px-3 py-2 mb-1 border transition-colors ${notification.is_read ? "border-slate-800 bg-slate-800/40 text-slate-400" : "border-blue-800 bg-blue-950/40 text-slate-100"}`;
            card.append(createText("strong", "block text-sm", notification.title));
            card.append(createText("span", "block mt-1 text-xs", notification.message));
            card.append(createText("time", "block mt-1 text-[11px] text-slate-500", new Date(notification.updated_at).toLocaleString("zh-CN")));
            if (hasDetail(notification)) {
                card.append(createText("span", "block mt-1 text-[11px] text-blue-400", "查看详情 ›"));
            }
            card.addEventListener("click", async () => {
                if (hasDetail(notification)) openModalDetail(notification);
                if (!notification.is_read) {
                    try {
                        await requestJson(`api/account/notifications/${notification.id}/read/`, {method: "POST", body: "{}"});
                        await loadNotifications();
                    } catch (error) {
                        console.warn("标记通知已读失败:", error);
                    }
                }
            });
            return card;
        }

        let readExpanded = false;

        function renderNotifications(unreadCount = 0) {
            count.hidden = unreadCount <= 0;
            count.textContent = unreadCount > 99 ? "99+" : String(unreadCount);
            readExpanded = false;
            list.replaceChildren();
            if (!notifications.length) {
                list.append(createText("p", "py-8 text-center text-sm text-slate-500", "暂无通知"));
                return;
            }
            notifications.filter((notification) => !notification.is_read)
                .forEach((notification) => list.append(createNotificationCard(notification)));
            const read = notifications.filter((notification) => notification.is_read);
            if (!read.length) return;
            const readToggle = createText("button", "w-full text-left rounded-md px-3 py-2 mb-1 border border-slate-800 bg-slate-800/40 text-slate-400 text-xs", "");
            readToggle.type = "button";
            const refreshReadToggle = () => {
                readToggle.textContent = `已读消息（${read.length} 条）${readExpanded ? " ▾" : " ▸"}`;
            };
            refreshReadToggle();
            readToggle.addEventListener("click", () => {
                readExpanded = !readExpanded;
                refreshReadToggle();
                const readSection = list.querySelector("[data-notification-read-section]");
                if (readExpanded && !readSection) {
                    const section = document.createElement("div");
                    section.dataset.notificationReadSection = "true";
                    read.forEach((notification) => section.append(createNotificationCard(notification)));
                    list.append(section);
                } else if (!readExpanded && readSection) {
                    readSection.remove();
                }
            });
            list.append(readToggle);
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
            const back = createText("button", "mb-2 text-xs text-blue-300 hover:text-blue-100", "← 返回通知");
            back.type = "button";
            back.addEventListener("click", () => {
                subscriptionsPanel.hidden = true;
                list.hidden = false;
            });
            subscriptionsPanel.append(back);
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
                try {
                    subscriptionData = await requestJson("api/account/subscriptions/", {
                        method: "PUT",
                        body: JSON.stringify({subscriptions: payload}),
                    });
                    subscriptionsPanel.hidden = true;
                    list.hidden = false;
                } catch (error) {
                    save.insertAdjacentElement(
                        "beforebegin",
                        createText("p", "mb-2 text-xs text-red-400", `保存失败：${error.message}`),
                    );
                }
            });
            subscriptionsPanel.append(save);
        }

        toggle.addEventListener("click", async () => {
            drawer.hidden = !drawer.hidden;
            if (!drawer.hidden) {
                list.hidden = false;
                subscriptionsPanel.hidden = true;
                await loadNotifications();
            }
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
        modalClose.addEventListener("click", closeModal);
        modal.addEventListener("click", (event) => {
            // 遮罩层是模态容器的直接子元素，点击面板外的任意位置都关闭。
            if (!event.target.closest("[data-notification-modal-panel]")) closeModal();
        });
        document.addEventListener("keydown", (event) => {
            if (event.key === "Escape" && !modal.hidden) closeModal();
        });

        const source = new EventSource(basePath + "api/account/notifications/stream/");
        source.addEventListener("notification_changed", loadNotifications);
        source.onerror = () => {
            // EventSource按服务端retry自动重连；每次重连都会重新经过应用授权。
        };
        loadNotifications();
    });
})();
