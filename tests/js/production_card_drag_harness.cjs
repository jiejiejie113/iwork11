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
    const animationFrames = new Map();
    let nextTimerId = 1;
    let nextAnimationFrameId = 1;

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
        requestAnimationFrame(callback) {
            const frameId = nextAnimationFrameId;
            nextAnimationFrameId += 1;
            animationFrames.set(frameId, callback);
            return frameId;
        },
        cancelAnimationFrame(frameId) {
            animationFrames.delete(frameId);
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
        runAnimationFrames() {
            const callbacks = [...animationFrames.values()];
            animationFrames.clear();
            for (const callback of callbacks) callback(16);
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
    const wrappers = [
        { dataset: { employeeId: 'employee-a' } },
        { dataset: { employeeId: 'employee-b' } },
    ];
    for (const wrapper of wrappers) {
        wrapper.closest = () => wrapper;
    }
    const targetWrapper = wrappers[1];
    const cardView = {
        scrollTop: 100,
        scrollHeight: 1000,
        clientHeight: 400,
        getBoundingClientRect() {
            return { top: 0, bottom: 400 };
        },
        contains(node) {
            return wrappers.includes(node);
        },
        querySelectorAll() {
            return wrappers;
        },
    };
    const document = {
        querySelector() {
            return null;
        },
        elementFromPoint() {
            return targetWrapper;
        },
    };
    const cardViewRef = { value: cardView };
    const runCardCode = new Function(
        'activeDrag',
        'dragIndex',
        'dragStyle',
        'orderedEmployees',
        'cardOrder',
        'saveCardOrder',
        'window',
        'document',
        'cardViewRef',
        `const CARD_LONG_PRESS_DELAY = 500;
         const CARD_AUTO_SCROLL_EDGE = 72;
         const CARD_AUTO_SCROLL_MIN_SPEED = 2;
         const CARD_AUTO_SCROLL_MAX_SPEED = 14;
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
        cardViewRef,
    );
    return {
        ...handlers,
        window,
        activeDrag,
        dragIndex,
        cardOrder,
        cardView,
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
    clientY: 140,
    cancelable: true,
    preventDefault() {
        preventedBeforeLongPress = true;
    },
});
assert.equal(harness.activeDrag.value, false, '长按前应继续等待');
assert.equal(preventedBeforeLongPress, false, '长按前不得阻止浏览器默认滚动');
assert.equal(harness.cardView.scrollTop, 60, '长按前移动应由卡片滚动容器承接纵向滚动');

harness.window.runTimers();
assert.equal(harness.activeDrag.value, true, '长按到时应进入卡片交换');
assert.equal(card.capturedPointerId, 7, '长按激活后才捕获指针');

let preventedDuringDrag = false;
harness.window.dispatch('pointermove', {
    pointerId: 7,
    clientX: 220,
    clientY: 380,
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
const scrollTopBeforeEdgeFrame = harness.cardView.scrollTop;
harness.window.runAnimationFrames();
assert.equal(harness.activeDrag.value, true, '边缘滚动期间不得清理交换状态');
assert(harness.cardView.scrollTop > scrollTopBeforeEdgeFrame, '接触下沿时应自动滚动卡片容器');

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
assert.equal(cancelledHarness.activeDrag.value, false, '真实 pointercancel 中断后不得进入交换');
assert.equal(cancelledCard.capturedPointerId, null, 'pointercancel 后不得捕获指针');

const topEdgeHarness = createHarness();
topEdgeHarness.cardView.scrollTop = 200;
const topEdgeCard = createCard();
topEdgeHarness.onPointerDown(touchEvent(topEdgeCard, 10, 100, 100), 0);
topEdgeHarness.window.runTimers();
topEdgeHarness.window.dispatch('pointermove', {
    pointerId: 10,
    clientX: 100,
    clientY: 10,
    cancelable: true,
    preventDefault() {},
});
const scrollTopBeforeTopEdgeFrame = topEdgeHarness.cardView.scrollTop;
topEdgeHarness.window.runAnimationFrames();
assert.equal(topEdgeHarness.activeDrag.value, true, '上沿滚动期间不得清理交换状态');
assert(topEdgeHarness.cardView.scrollTop < scrollTopBeforeTopEdgeFrame, '接触上沿时应自动滚动卡片容器');
topEdgeHarness.onPointerUp({ pointerId: 10 });

process.stdout.write(JSON.stringify({
    long_press_after_move: true,
    pending_scroll_preserves_state: true,
    tap_does_not_activate: true,
    edge_scroll_preserves_drag: true,
    pointercancel_cleans_interrupted_pending: true,
}));
