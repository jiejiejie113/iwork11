const fs = require("fs");
const path = require("path");
const vm = require("vm");

class Node {
    constructor(tag = "div", attributes = {}) {
        this.tagName = tag.toUpperCase();
        this.children = [];
        this.listeners = {};
        this.hidden = false;
        this.dataset = {};
        this.textContent = "";
        this.className = "";
        this.type = "";
        for (const [key, value] of Object.entries(attributes)) {
            if (!key.startsWith("data-")) continue;
            const datasetKey = key.slice(5).replace(/-([a-z])/g, (_, character) => character.toUpperCase());
            this.dataset[datasetKey] = value;
        }
    }

    append(...items) {
        for (const item of items) {
            if (!item || typeof item !== "object") continue;
            item.parentNode = this;
            this.children.push(item);
        }
    }

    appendChild(item) {
        this.append(item);
        return item;
    }

    replaceChildren(...items) {
        this.children = [];
        this.append(...items);
    }

    addEventListener(type, callback) {
        (this.listeners[type] ||= []).push(callback);
    }

    matches(selector) {
        if (!selector.startsWith("[data-") || !selector.endsWith("]")) return false;
        const key = selector.slice(6, -1).replace(/-([a-z])/g, (_, character) => character.toUpperCase());
        return Object.hasOwn(this.dataset, key);
    }

    querySelector(selector) {
        if (this.matches(selector)) return this;
        for (const child of this.children) {
            const found = child.querySelector?.(selector);
            if (found) return found;
        }
        return null;
    }

    contains(target) {
        return this === target || this.children.some((child) => child.contains?.(target));
    }

    closest(selector) {
        return this.matches(selector) ? this : null;
    }
}

async function main() {
    const root = new Node("div", {"data-iwork-notification-center": ""});
    const selectors = [
        "toggle", "count", "drawer", "list", "subscriptions", "settings", "read-all",
        "modal", "modal-title", "modal-body", "modal-close", "modal-panel",
    ];
    for (const selector of selectors) {
        root.append(new Node("div", {[`data-notification-${selector}`]: ""}));
    }
    const modal = root.querySelector("[data-notification-modal]");
    modal.hidden = true;

    global.document = {
        cookie: "csrftoken=test",
        createElement: (tag) => new Node(tag),
        createTextNode: (value) => Object.assign(new Node("#text"), {textContent: value}),
        querySelectorAll: (selector) => selector === "[data-iwork-notification-center]" ? [root] : [],
        addEventListener() {},
    };
    global.window = {location: {pathname: "/iwork/"}};
    global.EventSource = class {
        addEventListener() {}
    };

    const requests = [];
    let warning = "";
    console.warn = (...items) => {
        warning = items.map(String).join(" ");
    };
    global.fetch = async (url, options = {}) => {
        const method = options.method || "GET";
        requests.push([url, method]);
        if (method === "POST") {
            return {ok: false, status: 403, json: async () => ({message: "CSRF失败"})};
        }
        return {
            ok: true,
            status: 200,
            json: async () => ({
                unread_count: 1,
                notifications: [{
                    id: 7,
                    title: "每日责任摘要",
                    message: "有未填目标",
                    updated_at: "2026-08-27T00:00:00Z",
                    is_read: false,
                    payload: {type: "daily_summary", status_counts: {overdue: 1}, flows: []},
                }],
            }),
        };
    };

    const scriptPath = path.resolve(__dirname, "../../static/iwork/notifications.js");
    vm.runInThisContext(fs.readFileSync(scriptPath, "utf8"), {filename: "notifications.js"});
    await new Promise((resolve) => setTimeout(resolve, 0));
    const card = root.querySelector("[data-notification-list]").children[0];
    await card.listeners.click[0]();

    process.stdout.write(JSON.stringify({
        modal_hidden: modal.hidden,
        warning,
        requests,
    }));
    if (modal.hidden) process.exitCode = 1;
}

main().catch((error) => {
    process.stderr.write(String(error.stack || error));
    process.exitCode = 1;
});
