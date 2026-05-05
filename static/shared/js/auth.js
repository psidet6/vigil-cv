const AUTH_STORAGE_USERS = 'vigil_cv_users_v1';
const AUTH_STORAGE_SESSION = 'vigil_cv_session_v1';

function getDefaultAuthUsers() {
  return [
    {
      username: 'demo',
      password: '123456',
      name: '管理员',
      unit: '示例机构视觉分析团队'
    }
  ];
}

function loadAuthUsers() {
  try {
    const raw = localStorage.getItem(AUTH_STORAGE_USERS);
    const parsed = raw ? JSON.parse(raw) : [];
    if (Array.isArray(parsed) && parsed.length) {
      return parsed;
    }
  } catch (e) {}
  const defaults = getDefaultAuthUsers();
  try {
    localStorage.setItem(AUTH_STORAGE_USERS, JSON.stringify(defaults));
  } catch (e) {}
  return defaults;
}

function saveAuthUsers(users) {
  try {
    localStorage.setItem(AUTH_STORAGE_USERS, JSON.stringify(users));
  } catch (e) {}
}

function getAuthSession() {
  try {
    const raw = localStorage.getItem(AUTH_STORAGE_SESSION);
    return raw ? JSON.parse(raw) : null;
  } catch (e) {
    return null;
  }
}

function saveAuthSession(session) {
  try {
    localStorage.setItem(AUTH_STORAGE_SESSION, JSON.stringify(session));
  } catch (e) {}
}

function clearAuthSession() {
  try {
    localStorage.removeItem(AUTH_STORAGE_SESSION);
  } catch (e) {}
}

function getAuthOwnerUsername() {
  var session = getAuthSession();
  return session && session.username ? String(session.username).trim() : '';
}

function installAuthFetchBridge() {
  if (window.__multiRiderAuthFetchInstalled || typeof window.fetch !== 'function') {
    return;
  }
  var nativeFetch = window.fetch.bind(window);
  window.fetch = function (input, init) {
    var options = init ? Object.assign({}, init) : {};
    var requestUrl = typeof input === 'string' ? input : (input && input.url ? input.url : '');
    var sameOrigin = true;
    try {
      if (requestUrl) {
        sameOrigin = new URL(requestUrl, window.location.href).origin === window.location.origin;
      }
    } catch (e) {
      sameOrigin = true;
    }
    if (sameOrigin) {
      var username = getAuthOwnerUsername();
      if (username) {
        var headers = new Headers(options.headers || (input && input.headers ? input.headers : undefined));
        if (!headers.has('X-Vigil-CV-User')) {
          headers.set('X-Vigil-CV-User', username);
        }
        options.headers = headers;
      }
    }
    return nativeFetch(input, options);
  };
  window.__multiRiderAuthFetchInstalled = true;
}

installAuthFetchBridge();

function switchAuthPanel(name) {
  ['login', 'register'].forEach(function (panelName) {
    var button = document.getElementById('authTab' + panelName.charAt(0).toUpperCase() + panelName.slice(1));
    var panel = document.getElementById('authPanel' + panelName.charAt(0).toUpperCase() + panelName.slice(1));
    if (button) button.classList.toggle('active', panelName === name);
    if (panel) panel.classList.toggle('hidden', panelName !== name);
  });
}

function showAppShell(session) {
  var authShell = document.getElementById('authShell');
  var appShell = document.getElementById('appShell');
  var userName = document.getElementById('currentUserName');
  var userUnit = document.getElementById('currentUserUnit');
  if (authShell) authShell.classList.add('hidden');
  if (appShell) appShell.classList.remove('hidden');
  if (userName) userName.textContent = session && session.name ? session.name : '值班员';
  if (userUnit) userUnit.textContent = session && session.unit ? session.unit : '基层业务人员';
}

function showAuthShell() {
  var authShell = document.getElementById('authShell');
  var appShell = document.getElementById('appShell');
  if (appShell) appShell.classList.add('hidden');
  if (authShell) authShell.classList.remove('hidden');
}

function handleLogin(event) {
  if (event) event.preventDefault();
  var usernameInput = document.getElementById('authLoginUsername');
  var passwordInput = document.getElementById('authLoginPassword');
  var feedback = document.getElementById('authLoginFeedback');
  var username = usernameInput ? usernameInput.value.trim() : '';
  var password = passwordInput ? passwordInput.value.trim() : '';
  if (!username || !password) {
    if (feedback) feedback.textContent = '请输入工号和密码。';
    return false;
  }
  var user = loadAuthUsers().find(function (item) {
    return item.username === username && item.password === password;
  });
  if (!user) {
    if (feedback) feedback.textContent = '账号或密码不正确。';
    return false;
  }
  if (feedback) feedback.textContent = '';
  saveAuthSession(user);
  showAppShell(user);
  return false;
}

function handleRegister(event) {
  if (event) event.preventDefault();
  var usernameInput = document.getElementById('authRegisterUsername');
  var nameInput = document.getElementById('authRegisterName');
  var unitInput = document.getElementById('authRegisterUnit');
  var phoneInput = document.getElementById('authRegisterPhone');
  var passwordInput = document.getElementById('authRegisterPassword');
  var username = usernameInput ? usernameInput.value.trim() : '';
  var name = nameInput ? nameInput.value.trim() : '';
  var unit = unitInput ? unitInput.value.trim() : '';
  var phone = phoneInput ? phoneInput.value.trim() : '';
  var password = passwordInput ? passwordInput.value.trim() : '';
  var feedback = document.getElementById('authRegisterFeedback');
  if (!username || !name || !unit || !phone || !password) {
    if (feedback) feedback.textContent = '请填写完整注册信息。';
    return false;
  }
  var users = loadAuthUsers();
  if (users.some(function (item) { return item.username === username; })) {
    if (feedback) feedback.textContent = '该工号已存在，请直接登录。';
    return false;
  }
  users.push({ username: username, password: password, name: name, unit: unit, phone: phone });
  saveAuthUsers(users);
  if (feedback) feedback.textContent = '注册申请已保存，可直接使用该账号登录。';
  switchAuthPanel('login');
  var loginUser = document.getElementById('authLoginUsername');
  var loginPassword = document.getElementById('authLoginPassword');
  if (loginUser) loginUser.value = username;
  if (loginPassword) loginPassword.value = password;
  return false;
}

function logoutApp() {
  clearAuthSession();
  showAuthShell();
  switchAuthPanel('login');
}

function quickEnterApp() {
  var user = getDefaultAuthUsers()[0];
  saveAuthSession(user);
  showAppShell(user);
}

function initAppAuth() {
  loadAuthUsers();
  switchAuthPanel('login');
  var session = getAuthSession();
  if (session) {
    showAppShell(session);
  } else {
    showAuthShell();
  }
}

window.switchAuthPanel = switchAuthPanel;
window.handleLogin = handleLogin;
window.handleRegister = handleRegister;
window.logoutApp = logoutApp;
window.quickEnterApp = quickEnterApp;
window.initAppAuth = initAppAuth;
