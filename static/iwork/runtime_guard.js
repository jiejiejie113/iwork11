(() => {
    const timeoutId = window.setTimeout(() => {
        if (window.__iworkVueMounted) return;

        const app = document.getElementById('app');
        const error = document.getElementById('iwork-runtime-error');
        if (app) app.hidden = true;
        if (error) error.hidden = false;
    }, 5000);

    window.iworkMarkVueMounted = () => {
        window.__iworkVueMounted = true;
        window.clearTimeout(timeoutId);

        const app = document.getElementById('app');
        const error = document.getElementById('iwork-runtime-error');
        if (app) app.hidden = false;
        if (error) error.hidden = true;
    };
})();
