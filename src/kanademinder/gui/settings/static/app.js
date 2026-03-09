// Settings GUI JavaScript
// Handles loading, validating, and saving configuration

// ── State ────────────────────────────────────────────────────────────────────
let isLoading = false;
let isSaving = false;

// ── DOM Elements ─────────────────────────────────────────────────────────────
const form = document.getElementById('settings-form');
const saveBtn = document.getElementById('save-btn');
const cancelBtn = document.getElementById('cancel-btn');
const statusEl = document.getElementById('status-message');

// ── API Helpers ──────────────────────────────────────────────────────────────
async function waitForPyWebViewAPI() {
  let retries = 0;
  const maxRetries = 100;  // 10 seconds total

  while (retries < maxRetries) {
    // Check if pywebview is fully initialized
    if (window.pywebview &&
        window.pywebview.api &&
        typeof window.pywebview.api.get_config === 'function') {
      return true;
    }
    await new Promise(r => setTimeout(r, 100));
    retries++;
  }
  return false;
}

async function callApi(method, ...args) {
  // Wait for pywebview API to be ready
  const apiReady = await waitForPyWebViewAPI();
  if (!apiReady) {
    throw new Error('pywebview API not available after waiting');
  }

  return await window.pywebview.api[method](...args);
}

// ── UI Helpers ───────────────────────────────────────────────────────────────
function showStatus(message, type = 'info') {
  statusEl.textContent = message;
  statusEl.className = 'status ' + type;
  statusEl.style.display = 'block';

  // Auto-hide success messages after 5 seconds
  if (type === 'success') {
    setTimeout(() => {
      statusEl.style.display = 'none';
    }, 5000);
  }
}

function hideStatus() {
  statusEl.style.display = 'none';
}

function setLoading(loading) {
  isLoading = loading;
  saveBtn.disabled = loading || isSaving;
}

function setSaving(saving) {
  isSaving = saving;
  saveBtn.disabled = saving || isLoading;
  saveBtn.textContent = saving ? 'Saving…' : 'Save Settings';
}

// ── Form Handling ────────────────────────────────────────────────────────────
function getFormData() {
  const formData = new FormData(form);

  return {
    llm: {
      provider: formData.get('llm.provider') || '',
      base_url: formData.get('llm.base_url') || '',
      api_key: formData.get('llm.api_key') || '',
      model: formData.get('llm.model') || '',
    },
    schedule: {
      interval_minutes: parseInt(formData.get('schedule.interval_minutes'), 10) || 30,
      start_of_day: formData.get('schedule.start_of_day') || '08:00',
      end_of_day: formData.get('schedule.end_of_day') || '22:00',
    },
    behavior: {
      default_task_type: formData.get('behavior.default_task_type') || 'major',
      notification_mode: formData.get('behavior.notification_mode') || 'banner',
    },
  };
}

function setFormData(config) {
  // LLM settings
  if (config.llm) {
    setInputValue('llm-provider', config.llm.provider || '');
    setInputValue('llm-base-url', config.llm.base_url || '');
    setInputValue('llm-api-key', config.llm.api_key || '');
    setInputValue('llm-model', config.llm.model || '');
  }

  // Schedule settings
  if (config.schedule) {
    setInputValue('schedule-interval', config.schedule.interval_minutes || 30);
    setInputValue('schedule-start', config.schedule.start_of_day || '08:00');
    setInputValue('schedule-end', config.schedule.end_of_day || '22:00');
  }

  // Behavior settings
  if (config.behavior) {
    setInputValue('behavior-default-type', config.behavior.default_task_type || 'major');
    setInputValue('behavior-notif-mode', config.behavior.notification_mode || 'banner');
  }
}

function setInputValue(id, value) {
  const el = document.getElementById(id);
  if (el) {
    el.value = value;
  }
}

// ── Validation ───────────────────────────────────────────────────────────────
function validateTimeFormat(value) {
  return /^([01]?[0-9]|2[0-3]):([0-5][0-9])$/.test(value);
}

function validateForm() {
  const config = getFormData();
  const errors = [];

  // LLM validation
  if (!config.llm.base_url.trim()) {
    errors.push('LLM Base URL is required');
  }
  if (!config.llm.model.trim()) {
    errors.push('LLM Model is required');
  }

  // Schedule validation
  if (config.schedule.interval_minutes < 5) {
    errors.push('Interval must be at least 5 minutes');
  }
  if (!validateTimeFormat(config.schedule.start_of_day)) {
    errors.push('Start of Day must be in HH:MM format');
  }
  if (!validateTimeFormat(config.schedule.end_of_day)) {
    errors.push('End of Day must be in HH:MM format');
  }

  return errors;
}

// ── API Calls ─────────────────────────────────────────────────────────────────
async function loadConfig() {
  setLoading(true);
  hideStatus();

  try {
    const config = await callApi('get_config');
    setFormData(config);
    console.log('Configuration loaded');
  } catch (e) {
    console.error('Failed to load config:', e);
    showStatus('Failed to load configuration: ' + e.message, 'error');
  } finally {
    setLoading(false);
  }
}

async function saveConfig() {
  // Frontend validation
  const errors = validateForm();
  if (errors.length > 0) {
    showStatus('Please fix the following: ' + errors.join('; '), 'error');
    return;
  }

  const config = getFormData();
  setSaving(true);
  hideStatus();

  try {
    const result = await callApi('save_config', config);

    if (result.success) {
      showStatus('Settings saved successfully!', 'success');
    } else {
      showStatus('Failed to save: ' + (result.error || 'Unknown error'), 'error');
    }
  } catch (e) {
    console.error('Failed to save config:', e);
    showStatus('Error saving configuration: ' + e.message, 'error');
  } finally {
    setSaving(false);
  }
}

// ── Event Handlers ────────────────────────────────────────────────────────────
form.addEventListener('submit', (e) => {
  e.preventDefault();
  saveConfig();
});

cancelBtn.addEventListener('click', async () => {
  // Close the window via Python API
  try {
    if (window.pywebview && window.pywebview.api && window.pywebview.api.close_window) {
      await window.pywebview.api.close_window();
    } else {
      console.error('close_window API not available');
      // Fallback: try native window.close()
      window.close();
    }
  } catch (e) {
    console.error('Failed to close window:', e);
    window.close();
  }
});

// Password visibility toggle
document.querySelectorAll('.toggle-password').forEach(btn => {
  btn.addEventListener('click', () => {
    const targetId = btn.dataset.target;
    const input = document.getElementById(targetId);
    if (input) {
      input.type = input.type === 'password' ? 'text' : 'password';
      btn.textContent = input.type === 'password' ? 'Show' : 'Hide';
    }
  });
});

// Real-time validation for time inputs
document.querySelectorAll('input[pattern]').forEach(input => {
  input.addEventListener('blur', () => {
    if (input.value && !input.checkValidity()) {
      input.classList.add('invalid');
    } else {
      input.classList.remove('invalid');
    }
  });

  input.addEventListener('input', () => {
    if (input.classList.contains('invalid')) {
      if (input.checkValidity()) {
        input.classList.remove('invalid');
      }
    }
  });
});

// ── Initialization ───────────────────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', () => {
  loadConfig();
});
