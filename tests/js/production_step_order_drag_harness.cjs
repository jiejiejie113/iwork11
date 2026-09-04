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
const codeStart = template.indexOf('// ---- 当前详情的工序顺序与拖拽 ----');
const codeEnd = template.indexOf('// 工序热力图范围');
assert(codeStart >= 0, '未找到工序顺序代码');
assert(codeEnd > codeStart, '未找到工序顺序代码结束位置');

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

function createStorage() {
    const values = new Map();
    return {
        getItem(key) {
            return values.has(key) ? values.get(key) : null;
        },
        setItem(key, value) {
            values.set(key, String(value));
        },
        read(key) {
            return values.get(key);
        },
    };
}

function createRow(stepno, top) {
    return {
        dataset: { stepOrderStepno: String(stepno) },
        getBoundingClientRect() {
            return { top, bottom: top + 40, height: 40 };
        },
        closest() {
            return this;
        },
    };
}

function createHandle() {
    return {
        isConnected: true,
        capturedPointerId: null,
        releasedPointerId: null,
        setPointerCapture(pointerId) {
            this.capturedPointerId = pointerId;
        },
        releasePointerCapture(pointerId) {
            this.releasedPointerId = pointerId;
        },
    };
}

function createHarness({ detailType = 'flow', detailKey = 'SO1', steps = [1, 2, 10], scrollable = false, storage = null, stepOrderDragEnabled = true } = {}) {
    const window = createWindow();
    const localStorage = storage || createStorage();
    const detailTypeRef = { value: detailType };
    const detailKeyRef = { value: detailKey };
    const stepSummary = { value: steps.map((stepno) => ({ stepno })) };
    const stepOrderListRef = { value: null };
    const stepOrderDragEnabledRef = { value: stepOrderDragEnabled };
    const draggingStepOrderNo = { value: null };
    const stepOrderHoverStepNo = { value: null };
    const rows = steps.map((stepno, index) => createRow(stepno, index * 40));
    let targetRow = rows[0];
    const list = {
        scrollTop: scrollable ? 100 : 0,
        scrollHeight: scrollable ? 600 : 120,
        clientHeight: 120,
        getBoundingClientRect() {
            return { top: 0, bottom: 120 };
        },
        contains(node) {
            return rows.includes(node);
        },
    };
    stepOrderListRef.value = list;
    const document = {
        elementFromPoint() {
            return targetRow;
        },
    };
    const ref = (value) => ({ value });
    const computed = (factory) => ({
        get value() {
            return factory();
        },
    });
    const naturalCompare = (left, right) => String(left).localeCompare(
        String(right),
        undefined,
        { numeric: true, sensitivity: 'base' },
    );
    const runCode = new Function(
        'ref',
        'computed',
        'localStorage',
        'window',
        'document',
        'naturalCompare',
        'stepSummary',
        'detailType',
         'detailKey',
         'stepOrderListRef',
         'stepOrderDragEnabled',
         'draggingStepOrderNo',
         'stepOrderHoverStepNo',
         `const stepOrder = ref([]);
          const STEP_ORDER_STORAGE_PREFIX = 'iwork:production-detail:step-order:v1:';
          const STEP_ORDER_DRAG_OPTIONS = { delay: 300, delayOnTouchOnly: true };
          ${template.slice(codeStart, codeEnd)}
         return {
             stepOrder,
             orderStepsByPreference,
             orderedStepSummary,
             loadStepOrder,
             startStepOrderDrag,
             stopStepOrderDrag,
             stepOrderStorageKey,
             draggingStepOrderNo,
             stepOrderHoverStepNo,
             stepOrderDragEnabled,
             onStepOrderDragEnabledChange,
         };`,
    );
    const handlers = runCode(
        ref,
        computed,
        localStorage,
        window,
        document,
        naturalCompare,
        stepSummary,
        detailTypeRef,
        detailKeyRef,
        stepOrderListRef,
        stepOrderDragEnabledRef,
        draggingStepOrderNo,
        stepOrderHoverStepNo,
    );
    return {
        ...handlers,
        window,
        localStorage,
        detailKey: detailKeyRef,
        rows,
        list,
        setTarget(row) {
            targetRow = row;
        },
        key() {
            return handlers.stepOrderStorageKey(detailTypeRef.value, detailKeyRef.value);
        },
    };
}

function pointerEvent(pointerId, clientY, type = undefined, pointerType = 'mouse') {
    return {
        button: 0,
        isPrimary: true,
        pointerType,
        pointerId,
        clientX: 20,
        clientY,
        type,
        cancelable: true,
        preventDefault() {},
        currentTarget: createHandle(),
    };
}

const defaultHarness = createHarness();
assert.deepEqual(
    defaultHarness.orderedStepSummary.value.map((step) => step.stepno),
    [1, 2, 10],
    '没有缓存时应使用数值工序顺序',
);
defaultHarness.localStorage.setItem(
    defaultHarness.key(),
    JSON.stringify(['10', '10', 'invalid', '1']),
);
defaultHarness.loadStepOrder();
assert.deepEqual(defaultHarness.stepOrder.value, ['10', '1'], '缓存应去重并过滤非法值');
assert.deepEqual(
    defaultHarness.orderedStepSummary.value.map((step) => step.stepno),
    [10, 1, 2],
    '有效缓存应优先于默认工序顺序',
);
assert.deepEqual(
    defaultHarness.orderStepsByPreference(
        [{ stepno: 1 }, { stepno: 2 }, { stepno: 10 }],
    ).map((step) => step.stepno),
    [10, 1, 2],
    '卡片和收起摘要应使用同一工序顺序',
);

const isolatedHarness = createHarness({ detailKey: 'SO2', storage: defaultHarness.localStorage });
isolatedHarness.loadStepOrder();
assert.deepEqual(isolatedHarness.stepOrder.value, [], '不同详情不得读取其他详情的顺序');
isolatedHarness.detailKey.value = 'SO1';
isolatedHarness.loadStepOrder();
assert.deepEqual(isolatedHarness.stepOrder.value, ['10', '1'], '切换回原详情时应读取原顺序');

const disabledHarness = createHarness({ stepOrderDragEnabled: false });
const disabledEvent = pointerEvent(6, 20);
disabledHarness.startStepOrderDrag(disabledEvent, 1);
disabledHarness.window.runTimers();
assert.equal(disabledHarness.draggingStepOrderNo.value, null, '关闭开关时不得进入工序拖拽');
assert.equal(disabledHarness.localStorage.read(disabledHarness.key()), undefined, '关闭开关时不得保存工序顺序');

const touchHarness = createHarness({ scrollable: true });
touchHarness.setTarget(touchHarness.rows[2]);
const touchEvent = pointerEvent(11, 20, undefined, 'touch');
touchHarness.startStepOrderDrag(touchEvent, 1);
assert.equal(touchHarness.draggingStepOrderNo.value, null, '触摸按下后应等待长按');
let preventedBeforeTouchLongPress = false;
touchHarness.window.dispatch('pointermove', {
    pointerId: 11,
    clientX: 20,
    clientY: 80,
    cancelable: true,
    preventDefault() {
        preventedBeforeTouchLongPress = true;
    },
});
assert.equal(touchHarness.draggingStepOrderNo.value, null, '长按前移动不得直接进入拖拽');
assert.equal(preventedBeforeTouchLongPress, false, '长按前移动不得阻止列表滚动');
assert.equal(touchHarness.list.scrollTop, 40, '长按前移动应继续滚动工序列表');
touchHarness.window.runTimers();
assert.equal(touchHarness.draggingStepOrderNo.value, '1', '触摸按住300毫秒后应进入工序拖拽');
assert.equal(touchEvent.currentTarget.capturedPointerId, 11, '长按激活后才捕获触摸指针');
let preventedDuringTouchDrag = false;
touchHarness.window.dispatch('pointermove', {
    pointerId: 11,
    clientX: 20,
    clientY: 118,
    cancelable: true,
    preventDefault() {
        preventedDuringTouchDrag = true;
    },
});
assert.equal(preventedDuringTouchDrag, true, '触摸拖拽激活后应接管指针移动');
assert.deepEqual(touchHarness.stepOrder.value, ['2', '10', '1'], '触摸长按后应更新工序顺序');
touchHarness.window.dispatch('pointerup', { pointerId: 11, type: 'pointerup' });

const tapHarness = createHarness();
const tapEvent = pointerEvent(12, 20, undefined, 'touch');
tapHarness.startStepOrderDrag(tapEvent, 1);
tapHarness.window.dispatch('pointerup', { pointerId: 12, type: 'pointerup' });
tapHarness.window.runTimers();
assert.equal(tapHarness.draggingStepOrderNo.value, null, '触摸点击不得进入工序拖拽');
assert.equal(tapEvent.currentTarget.capturedPointerId, null, '触摸点击不得捕获指针');
assert.equal(tapHarness.localStorage.read(tapHarness.key()), undefined, '触摸点击不得保存工序顺序');

const mouseTapHarness = createHarness();
const mouseTapEvent = pointerEvent(15, 20);
mouseTapHarness.startStepOrderDrag(mouseTapEvent, 1);
assert.equal(mouseTapHarness.draggingStepOrderNo.value, '1', '鼠标按下应立即进入拖拽');
mouseTapHarness.window.dispatch('pointerup', { pointerId: 15, type: 'pointerup' });
assert.equal(mouseTapHarness.localStorage.read(mouseTapHarness.key()), undefined, '鼠标点击未交换顺序时不得保存');

const pendingCancelledHarness = createHarness();
const pendingCancelledEvent = pointerEvent(13, 20, undefined, 'touch');
pendingCancelledHarness.startStepOrderDrag(pendingCancelledEvent, 1);
pendingCancelledHarness.window.dispatch('pointercancel', { pointerId: 13, type: 'pointercancel' });
pendingCancelledHarness.window.runTimers();
assert.equal(pendingCancelledHarness.draggingStepOrderNo.value, null, '待长按阶段取消指针后不得进入拖拽');
assert.equal(pendingCancelledEvent.currentTarget.capturedPointerId, null, '待长按阶段取消后不得捕获指针');

const dragHarness = createHarness({ scrollable: false });
const dragHandle = pointerEvent(7, 20);
dragHarness.setTarget(dragHarness.rows[2]);
dragHandle.currentTarget = createHandle();
dragHarness.startStepOrderDrag(dragHandle, 1);
assert.equal(dragHarness.draggingStepOrderNo.value, '1', '手柄按下后应进入工序拖拽');
dragHarness.window.dispatch('pointermove', {
    pointerId: 7,
    clientX: 20,
    clientY: 118,
    cancelable: true,
    preventDefault() {},
});
assert.deepEqual(dragHarness.stepOrder.value, ['2', '10', '1'], '拖拽应移动到目标工序之后');
dragHarness.window.dispatch('pointerup', { pointerId: 7, type: 'pointerup' });
assert.equal(dragHarness.draggingStepOrderNo.value, null, '抬起后应清理拖拽状态');
assert.equal(dragHarness.localStorage.read(dragHarness.key()), '["2","10","1"]');

const filteredHarness = createHarness({ steps: [1, 10] });
filteredHarness.localStorage.setItem(filteredHarness.key(), JSON.stringify([1, 2, 10]));
filteredHarness.loadStepOrder();
filteredHarness.setTarget(filteredHarness.rows[1]);
const filteredEvent = pointerEvent(8, 20);
filteredHarness.startStepOrderDrag(filteredEvent, 1);
filteredHarness.window.dispatch('pointermove', {
    pointerId: 8,
    clientX: 20,
    clientY: 118,
    cancelable: true,
    preventDefault() {},
});
filteredHarness.window.dispatch('pointerup', { pointerId: 8, type: 'pointerup' });
assert.deepEqual(
    filteredHarness.stepOrder.value,
    ['10', '2', '1'],
    '过滤隐藏的工序应保留在已保存顺序中',
);

const cancelledHarness = createHarness({ scrollable: false });
cancelledHarness.loadStepOrder();
cancelledHarness.setTarget(cancelledHarness.rows[2]);
const cancelledEvent = pointerEvent(9, 20);
cancelledHarness.startStepOrderDrag(cancelledEvent, 1);
cancelledHarness.window.dispatch('pointermove', {
    pointerId: 9,
    clientX: 20,
    clientY: 118,
    cancelable: true,
    preventDefault() {},
});
cancelledHarness.window.dispatch('pointercancel', { pointerId: 9, type: 'pointercancel' });
assert.deepEqual(cancelledHarness.stepOrder.value, [], 'pointercancel 应恢复拖拽前状态');
assert.equal(cancelledHarness.localStorage.read(cancelledHarness.key()), undefined, '取消拖拽不得保存顺序');

const autoScrollHarness = createHarness({ scrollable: true });
autoScrollHarness.setTarget(autoScrollHarness.rows[1]);
const autoScrollEvent = pointerEvent(10, 118);
autoScrollHarness.startStepOrderDrag(autoScrollEvent, 1);
const beforeAutoScroll = autoScrollHarness.list.scrollTop;
autoScrollHarness.window.dispatch('pointermove', {
    pointerId: 10,
    clientX: 20,
    clientY: 118,
    cancelable: true,
    preventDefault() {},
});
autoScrollHarness.window.runAnimationFrames();
assert(autoScrollHarness.list.scrollTop > beforeAutoScroll, '触及列表下沿时应自动滚动');
assert.equal(autoScrollHarness.draggingStepOrderNo.value, '1', '自动滚动期间不得清理拖拽状态');
autoScrollHarness.window.dispatch('pointerup', { pointerId: 10, type: 'pointerup' });

const toggleHarness = createHarness({ scrollable: false });
toggleHarness.setTarget(toggleHarness.rows[2]);
const toggleEvent = pointerEvent(14, 20);
toggleHarness.startStepOrderDrag(toggleEvent, 1);
toggleHarness.window.dispatch('pointermove', {
    pointerId: 14,
    clientX: 20,
    clientY: 118,
    cancelable: true,
    preventDefault() {},
});
toggleHarness.stepOrderDragEnabled.value = false;
toggleHarness.onStepOrderDragEnabledChange();
assert.equal(toggleHarness.draggingStepOrderNo.value, null, '关闭开关时应取消正在进行的拖拽');
assert.deepEqual(toggleHarness.stepOrder.value, [], '关闭开关取消拖拽时应恢复原始顺序');
assert.equal(toggleHarness.localStorage.read(toggleHarness.key()), undefined, '取消拖拽时不得保存顺序');

process.stdout.write(JSON.stringify({
    default_numeric_order: true,
    cache_normalization: true,
    detail_isolation: true,
    handle_hidden_when_disabled: true,
    touch_delay_and_pending_scroll: true,
    touch_tap_does_not_activate: true,
    mouse_tap_does_not_save: true,
    pending_pointercancel_cleans_state: true,
    handle_drag_saves_order: true,
    filtered_hidden_steps_preserved: true,
    pointercancel_restores_state: true,
    edge_scroll_preserves_drag: true,
    toggle_cancels_active_drag: true,
}));
