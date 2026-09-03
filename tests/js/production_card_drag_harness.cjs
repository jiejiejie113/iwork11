'use strict';

const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const templatePath = path.resolve(
    __dirname,
    '..',
    '..',
    'iwork',
    'templates',
    'iwork',
    'production_detail.html',
);
const template = fs.readFileSync(templatePath, 'utf8');
const pointerStart = template.indexOf('// ---- Pointer 拖拽排序');
const pointerEnd = template.indexOf('// ---- localStorage 持久化');
assert(pointerStart >= 0, '未找到卡片 Pointer 拖拽代码');
assert(pointerEnd > pointerStart, '未找到卡片拖拽代码结束位置');

function createWindow() {
    const listeners = new Map();
    const timers = new Map();
    let nextTimerId = 1;

    return {
        addEventListener(type, listener) {
            const callbacks = listeners.get(type) || [];
            callbacks.push(listener);
            listeners.set(type, callbacks);
        },
        removeEventListener(type, listener) {
            const callbacks = listeners.get(type) || [];
            listeners.set(type, callbacks.filter((callback) => callback !== listener));
        },
        setTimeout(callback) {
            const timerId = nextTimerId;
            nextTimerId += 1;
            timers.set(timerId, callback);
            return timerId;
        },
        clearTimeout(timerId) {
            timers.delete(timerId);
        },
        dispatch(type, event) {
            for (const listener of [...(listeners.get(type) || [])]) {
                listener(event);
            }
        },
        runTimers() {
            const callbacks = [...timers.values()];
            timers.clear();
            for (const callback of callbacks) callback();
        },
    };
}

function createCard() {
    return {
        isConnected: true,
        capturedPointerId: null,
        releasedPointerId: null,
        style: {
            touchAction: '',
            removeProperty(property) {
                if (property === 'touch-action') this.touchAction = '';
            },
        },
        getBoundingClientRect() {
            return { left: 10, top: 20, width: 160, height: 90 };
        },
        setPointerCapture(pointerId) {
            this.capturedPointerId = pointerId;
        },
        releasePointerCapture(pointerId) {
            this.releasedPointerId = pointerId;
        },
    };
}

function createHarness() {
    const window = createWindow();
    const activeDrag = { value: false };
    const dragIndex = { value: -1 };
    const dragStyle = {};
    const orderedEmployees = {
        value: [
            { reg_per_sys_id: 'employee-a' },
            { reg_per_sys_id: 'employee-b' },
        ],
    };
    const cardOrder = { value: [] };
    const savedOrders = [];
    const targetWrapper = {
        closest() {
            return this;
        },
    };
    const document = {
        querySelector() {
            return null;
        },
        elementFromPoint() {
            return targetWrapper;
        },
        querySelectorAll() {
            return [{}, targetWrapper];
        },
    };
    const runCardCode = new Function(
        'activeDrag',
        'dragIndex',
        'dragStyle',
        'orderedEmployees',
        'cardOrder',
        'saveCardOrder',
        'window',
        'document',
        `const CARD_LONG_PRESS_DELAY = 500;
         const CARD_DRAG_MOVE_THRESHOLD = 8;
         ${template.slice(pointerStart, pointerEnd)}
         return { onPointerDown, onPointerUp, onPointerMove };`,
    );
    const handlers = runCardCode(
        activeDrag,
        dragIndex,
        dragStyle,
        orderedEmployees,
        cardOrder,
        (order) => savedOrders.push([...order]),
        window,
        document,
    );
    return {
        ...handlers,
        window,
        activeDrag,
        dragIndex,
        cardOrder,
        savedOrders,
    };
}

function touchEvent(card, pointerId, clientX, clientY) {
    return {
        button: 0,
        isPrimary: true,
        pointerType: 'touch',
        pointerId,
        clientX,
        clientY,
        currentTarget: card,
    };
}

const harness = createHarness();
const card = createCard();
harness.onPointerDown(touchEvent(card, 7, 100, 100), 0);
assert.equal(harness.activeDrag.value, false, '按下时不应立即进入拖拽');

let preventedBeforeLongPress = false;
harness.window.dispatch('pointermove', {
    pointerId: 7,
    clientX: 112,
    clientY: 101,
    cancelable: true,
    preventDefault() {
        preventedBeforeLongPress = true;
    },
});
assert.equal(harness.activeDrag.value, false, '长按前应继续等待');
assert.equal(preventedBeforeLongPress, false, '长按前不得阻止浏览器默认滚动');

harness.window.runTimers();
assert.equal(harness.activeDrag.value, true, '长按到时应进入卡片交换');
assert.equal(card.capturedPointerId, 7, '长按激活后才捕获指针');

let preventedDuringDrag = false;
harness.window.dispatch('pointermove', {
    pointerId: 7,
    clientX: 220,
    clientY: 100,
    cancelable: true,
    preventDefault() {
        preventedDuringDrag = true;
    },
});
assert.equal(preventedDuringDrag, true, '交换期间应接管可取消的指针移动');
assert.deepEqual(
    harness.cardOrder.value,
    ['employee-b', 'employee-a'],
    '交换期间应更新卡片顺序',
);

harness.onPointerUp({ pointerId: 7 });
assert.equal(harness.activeDrag.value, false, '抬起后应结束交换');
assert.deepEqual(harness.savedOrders, [['employee-b', 'employee-a']]);

const tapHarness = createHarness();
const tapCard = createCard();
tapHarness.onPointerDown(touchEvent(tapCard, 9, 100, 100), 0);
tapHarness.window.dispatch('pointerup', { pointerId: 9 });
tapHarness.window.runTimers();
assert.equal(tapHarness.activeDrag.value, false, '普通点击不得进入交换');
assert.equal(tapCard.capturedPointerId, null, '普通点击不得捕获指针');
assert.deepEqual(tapHarness.savedOrders, []);

const cancelledHarness = createHarness();
const cancelledCard = createCard();
cancelledHarness.onPointerDown(touchEvent(cancelledCard, 8, 100, 100), 0);
cancelledHarness.window.dispatch('pointercancel', { pointerId: 8 });
cancelledHarness.window.runTimers();
assert.equal(cancelledHarness.activeDrag.value, false, '滚动触发 pointercancel 后不得进入交换');
assert.equal(cancelledCard.capturedPointerId, null, 'pointercancel 后不得捕获指针');

process.stdout.write(JSON.stringify({
    long_press_after_move: true,
    pending_scroll_not_prevented: true,
    tap_does_not_activate: true,
    pointercancel_cleans_pending: true,
}));
