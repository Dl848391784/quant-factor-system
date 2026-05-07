/**
 * 认证前端模块
 * 作者: 云舟
 * 功能: 处理登录状态检查、token 管理、登出等
 */

// ========== Token 管理 ==========

/**
 * 获取 token（Cookie 方式）
 * 
 * 注意：token 存储在 Cookie 中，前端无法直接读取（HttpOnly）
 * 此函数仅用于兼容性，返回 null
 */
function getToken() {
    // Cookie 是 HttpOnly，JS 无法读取
    // 返回 null，依赖后端 Cookie 自动发送
    return null;
}

/**
 * 设置 token（已废弃）
 * 
 * 注意：token 由后端通过 Set-Cookie header 设置
 * 此函数不再使用，保留仅为向后兼容
 */
function setToken(token) {
    // 已废弃：Cookie 方式下前端不设置 token
    console.warn('setToken is deprecated: token is managed by server Cookie');
}

/**
 * 清除 token（调用登出 API）
 * 
 * 注意：清除 Cookie 需调用后端登出 API
 * 前端无法直接清除 HttpOnly Cookie
 */
async function clearToken() {
    // 清除本地用户信息
    localStorage.removeItem('username');
    localStorage.removeItem('user_id');
    
    // 调用登出 API 清除 Cookie
    try {
        await fetch('/api/auth/logout', {
            method: 'POST',
            credentials: 'include'  // 发送 Cookie
        });
    } catch (error) {
        console.error('Logout API failed:', error);
    }
}

/**
 * 获取存储的用户名
 */
function getUsername() {
    return localStorage.getItem('username');
}

/**
 * 获取存储的用户 ID
 */
function getUserId() {
    return localStorage.getItem('user_id');
}

// ========== 认证状态检查 ==========

/**
 * 检查是否已登录
 */
function isLoggedIn() {
    return getToken() !== null;
}

/**
 * 验证 token 是否有效
 * @returns {Promise<boolean>} token 是否有效
 */
async function verifyToken() {
    // Cookie 方式：通过 API 验证 Cookie 是否有效
    try {
        const response = await fetch('/api/auth/verify', {
            credentials: 'include'  // 发送 Cookie
        });
        
        const data = await response.json();
        return data.success;
    } catch (error) {
        console.error('Token verification failed:', error);
        return false;
    }
}

/**
 * 检查登录状态并重定向
 * 用于页面加载时的认证检查
 */
async function checkAuthAndRedirect() {
    // Cookie 方式：无需检查 localStorage token
    // 直接验证 Cookie 是否有效
    
    // 验证 Cookie token（通过 API）
    const isValid = await verifyToken();
    
    if (!isValid) {
        // Cookie 无效，清除本地信息并重定向
        localStorage.removeItem('username');
        localStorage.removeItem('user_id');
        redirectToLogin();
        return false;
    }
    
    return true;
}

/**
 * 重定向到登录页
 * 改进版：保存完整 URL（包含查询参数），使用 replaceState 防止后退
 */
function redirectToLogin() {
    const currentPath = window.location.pathname;
    const currentQuery = window.location.search;
    const fullUrl = currentPath + currentQuery;
    
    // 保存完整 URL（包含查询参数）
    sessionStorage.setItem('redirect_after_login', fullUrl);
    
    // 使用 replaceState 防止后退按钮回到保护页面
    history.replaceState(null, '', '/login?need_login=1');
    window.location.href = '/login?need_login=1';
}

// ========== API 请求辅助 ==========

/**
 * 发送带认证的 API 请求
 * @param {string} url API URL
 * @param {object} options fetch options
 * @returns {Promise<Response>} fetch response
 */
async function authFetch(url, options = {}) {
    // Cookie 方式：无需手动添加 Authorization header
    // Cookie 自动发送（credentials: 'include')
    
    // 确保 credentials: 'include' 以发送 Cookie
    options.credentials = 'include';
    
    try {
        const response = await fetch(url, options);
        
        // 检查是否认证失败
        if (response.status === 401) {
            // Cookie 无效，清除本地信息并重定向
            localStorage.removeItem('username');
            localStorage.removeItem('user_id');
            redirectToLogin();
            return null;
        }
        
        return response;
    } catch (error) {
        console.error('Auth fetch failed:', error);
        return null;
    }
}

// ========== 登出 ==========

/**
 * 用户登出
 */
async function logout() {
    // Cookie 方式：调用登出 API 清除 Cookie
    try {
        // 调用登出 API（清除 Cookie 和将 token 加入黑名单）
        await fetch('/api/auth/logout', {
            method: 'POST',
            credentials: 'include'  // 发送 Cookie
        });
    } catch (error) {
        console.error('Logout API failed:', error);
    }
    
    // 清除本地用户信息
    localStorage.removeItem('username');
    localStorage.removeItem('user_id');
    
    // 重定向到登录页
    window.location.href = '/login';
}

// ========== 用户信息显示 ==========

/**
 * 更新页面上的用户信息显示
 */
function updateUserInfoDisplay() {
    const username = getUsername();
    const userElements = document.querySelectorAll('.user-name');
    
    userElements.forEach(el => {
        el.textContent = username || '未登录';
    });
}

// ========== 页面初始化 ==========

/**
 * 页面加载时的认证初始化
 */
async function initAuth() {
    // 检查是否在登录页（登录页不需要认证检查）
    if (window.location.pathname === '/login') {
        return;
    }
    
    // 验证 token
    const isValid = await verifyToken();
    
    if (!isValid && isLoggedIn()) {
        // Token 无效但本地有存储，清除
        clearToken();
    }
    
    // 更新用户信息显示
    updateUserInfoDisplay();
}

// 页面加载时初始化
window.addEventListener('load', initAuth);

// ========== 导出函数（供其他脚本使用） ==========

window.AuthModule = {
    getToken,
    setToken,
    clearToken,
    getUsername,
    getUserId,
    isLoggedIn,
    verifyToken,
    checkAuthAndRedirect,
    redirectToLogin,
    authFetch,
    logout,
    updateUserInfoDisplay,
    initAuth
};