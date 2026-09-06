"use strict";
(function () {
    const nativeFetch = window.fetch.bind(window);
    window.fetch = async function (input, options = {}) {
        const url = new URL(typeof input === 'string' ? input : input.url, location.href);
        const headers = new Headers(options.headers || (input instanceof Request ? input.headers : undefined));
        if (url.origin === location.origin && url.pathname.startsWith('/api/')) {
            const token = localStorage.getItem('robot_token');
            if (token) headers.set('Authorization', 'Bearer ' + token);
            headers.delete('X-User-Role');
            headers.delete('X-User-Name');
        }
        const response = await nativeFetch(input, {...options, headers});
        if (response.status === 401 && url.origin === location.origin && !url.pathname.startsWith('/api/auth/login') && location.pathname !== '/login') {
            localStorage.removeItem('robot_token');
            localStorage.removeItem('robot_user');
            location.replace('/login');
        }
        return response;
    };
    window.addEventListener('unhandledrejection', event => console.error('Request failed:', event.reason));
    window.verifiedNumber = value => (typeof value === 'number' && Number.isFinite(value)) ? value : '--';
    window.downloadAuthenticated = async function (url) {
        const response = await fetch(url);
        if (!response.ok) {
            const error = await response.json();
            throw new Error(error.message || '下载失败');
        }
        const blob = await response.blob();
        const name = /filename="?([^";]+)"?/.exec(response.headers.get('content-disposition') || '');
        const link = document.createElement('a');
        const objectUrl = URL.createObjectURL(blob);
        link.href = objectUrl;
        link.download = name ? name[1] : 'download';
        document.body.appendChild(link);
        link.click();
        link.remove();
        setTimeout(() => URL.revokeObjectURL(objectUrl), 1000);
    };
    window.forcePasswordChange = function (username) {
        return new Promise(resolve => {
            const dialog = document.createElement('dialog');
            dialog.style.cssText = 'padding:24px;max-width:420px;width:90%;border:1px solid #999;border-radius:6px;';
            dialog.innerHTML = '<form><h2>更新生产环境密码</h2><label>原密码<input type="password" name="old" required autocomplete="current-password"></label><label>新密码（至少12位）<input type="password" name="next" required minlength="12" maxlength="128" autocomplete="new-password"></label><p role="alert"></p><button type="submit">更新密码并重新登录</button></form>';
            for (const label of dialog.querySelectorAll('label')) label.style.cssText = 'display:grid;gap:8px;margin:16px 0;';
            dialog.addEventListener('cancel', event => event.preventDefault());
            dialog.querySelector('form').addEventListener('submit', async event => {
                event.preventDefault();
                const form = event.currentTarget;
                const response = await fetch('/api/auth/password', {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({username,old_password:form.elements.old.value,new_password:form.elements.next.value})});
                const body = await response.json();
                if (response.ok) {
                    localStorage.removeItem('robot_token');
                    localStorage.removeItem('robot_user');
                    resolve(false);
                    location.replace('/login');
                } else dialog.querySelector('[role=alert]').textContent = body.message;
            });
            document.body.appendChild(dialog);
            dialog.showModal();
        });
    };
})();
