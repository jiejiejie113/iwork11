const fs = require("fs");
const path = require("path");
const vm = require("vm");

let timerCallback = null;
let clearedTimer = null;
const elements = {
  app: { hidden: false },
  "iwork-runtime-error": { hidden: true },
};
const window = {
  __iworkVueMounted: false,
  setTimeout(callback, delay) {
    if (delay !== 5000) throw new Error(`unexpected timeout: ${delay}`);
    timerCallback = callback;
    return 7;
  },
  clearTimeout(timerId) {
    clearedTimer = timerId;
  },
};
const context = {
  window,
  document: {
    getElementById(id) {
      return elements[id] || null;
    },
  },
};

const scriptPath = path.resolve(__dirname, "../../static/iwork/runtime_guard.js");
vm.runInNewContext(fs.readFileSync(scriptPath, "utf8"), context, {
  filename: "runtime_guard.js",
});

timerCallback();
const failed = {
  app_hidden: elements.app.hidden,
  error_hidden: elements["iwork-runtime-error"].hidden,
};

window.iworkMarkVueMounted();
const recovered = {
  app_hidden: elements.app.hidden,
  error_hidden: elements["iwork-runtime-error"].hidden,
};

if (clearedTimer !== 7) throw new Error("runtime guard timer was not cleared");
process.stdout.write(JSON.stringify({ failed, recovered }));
