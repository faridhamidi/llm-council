/**
 * API client for the LLM Council backend.
 */

const isBrowser = typeof window !== 'undefined';
const hostname = isBrowser ? window.location.hostname : '';
const isLocalHost = hostname === 'localhost' || hostname === '127.0.0.1';

const rawEnvBase = import.meta.env.VITE_API_BASE || '';
const normalizeBase = (value) => (value || '').replace(/\/$/, '');

const CANDIDATE_BASES = [];
if (rawEnvBase) CANDIDATE_BASES.push(normalizeBase(rawEnvBase));
if (isLocalHost) CANDIDATE_BASES.push('http://localhost:8001');
CANDIDATE_BASES.push('');

const STATUS_PATH = '/api/auth/status';
let resolvedBase = null;
let resolving = null;

const withTimeout = (promise, ms) =>
  new Promise((resolve, reject) => {
    const timer = setTimeout(() => reject(new Error('timeout')), ms);
    promise
      .then((value) => {
        clearTimeout(timer);
        resolve(value);
      })
      .catch((err) => {
        clearTimeout(timer);
        reject(err);
      });
  });

const isReachable = async (base) => {
  try {
    const response = await withTimeout(
      fetch(`${base}${STATUS_PATH}`, {
        method: 'GET',
        credentials: 'include',
      }),
      2500
    );
    return response.status === 200 || response.status === 401 || response.status === 403;
  } catch (error) {
    return false;
  }
};

const resolveApiBase = async () => {
  if (resolvedBase !== null) return resolvedBase;
  if (resolving) return resolving;

  resolving = (async () => {
    for (const base of CANDIDATE_BASES) {
      if (await isReachable(base)) {
        resolvedBase = base;
        resolving = null;
        return base;
      }
    }
    resolvedBase = CANDIDATE_BASES[0] || '';
    resolving = null;
    return resolvedBase;
  })();

  return resolving;
};

const getAccessKey = () => accessKey || '';
let accessKey = '';

export const setAccessKey = (value) => {
  const trimmed = (value || '').trim();
  if (trimmed) {
    accessKey = trimmed;
  }
};

export const clearAccessKey = () => {
  accessKey = '';
};

const withAuth = (headers = {}) => {
  const key = getAccessKey();
  return {
    ...headers,
    ...(key ? { 'x-llm-council-pin': key } : {}),
  };
};

const apiFetch = async (path, options = {}) => {
  const base = await resolveApiBase();
  return fetch(`${base}${path}`, {
    ...options,
    credentials: 'include',
  });
};

export const api = {
  /**
   * Auth status.
   */
  async getAuthStatus() {
    const response = await apiFetch(STATUS_PATH);
    if (!response.ok) {
      throw new Error('Failed to load auth status');
    }
    return response.json();
  },

  /**
   * Set PIN (first-time setup).
   */
  async setupAuthPin(pin) {
    const response = await apiFetch('/api/auth/setup', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({ pin }),
    });
    if (!response.ok) {
      const errorText = await response.text();
      throw new Error(errorText || 'Failed to set PIN');
    }
    return response.json();
  },

  /**
   * List all conversations.
   */
  async listConversations() {
    const response = await apiFetch('/api/conversations', {
      headers: withAuth(),
    });
    if (response.status === 401) {
      throw new Error('Unauthorized');
    }
    if (!response.ok) {
      throw new Error('Failed to list conversations');
    }
    return response.json();
  },

  /**
   * Create a new conversation.
   */
  async createConversation() {
    const response = await apiFetch('/api/conversations', {
      method: 'POST',
      headers: withAuth({
        'Content-Type': 'application/json',
      }),
      body: JSON.stringify({}),
    });
    if (!response.ok) {
      throw new Error('Failed to create conversation');
    }
    return response.json();
  },

  /**
   * Get a specific conversation.
   */
  async getConversation(conversationId) {
    const response = await apiFetch(`/api/conversations/${conversationId}`, {
      headers: withAuth(),
    });
    if (!response.ok) {
      throw new Error('Failed to get conversation');
    }
    return response.json();
  },

  /**
   * Delete a conversation (soft-delete).
   */
  async deleteConversation(conversationId) {
    const response = await apiFetch(`/api/conversations/${conversationId}`, {
      method: 'DELETE',
      headers: withAuth(),
    });
    if (!response.ok) {
      const errorText = await response.text();
      throw new Error(errorText || 'Failed to delete conversation');
    }
    return response.json();
  },

  /**
   * Restore a deleted conversation.
   */
  async restoreConversation(conversationId) {
    const response = await apiFetch(`/api/conversations/${conversationId}/restore`, {
      method: 'POST',
      headers: withAuth(),
    });
    if (!response.ok) {
      const errorText = await response.text();
      throw new Error(errorText || 'Failed to restore conversation');
    }
    return response.json();
  },

  /**
   * Send a message in a conversation.
   */
  async sendMessage(conversationId, content) {
    const response = await apiFetch(`/api/conversations/${conversationId}/message`, {
      method: 'POST',
      headers: withAuth({
        'Content-Type': 'application/json',
      }),
      body: JSON.stringify({ content }),
    });
    if (!response.ok) {
      throw new Error('Failed to send message');
    }
    return response.json();
  },

  /**
   * Send a message and receive streaming updates.
   * @param {string} conversationId - The conversation ID
   * @param {string} content - The message content
   * @param {function} onEvent - Callback function for each event: (eventType, data) => void
   * @returns {Promise<void>}
   */
  async sendMessageStream(conversationId, content, onEvent, options = {}) {
    const { signal } = options;
    const response = await apiFetch(`/api/conversations/${conversationId}/message/stream`, {
      method: 'POST',
      headers: withAuth({
        'Content-Type': 'application/json',
      }),
      signal,
      body: JSON.stringify({ content }),
    });

    if (!response.ok) {
      throw new Error('Failed to send message');
    }

    const reader = response.body.getReader();
    const decoder = new TextDecoder();

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;

      const chunk = decoder.decode(value);
      const lines = chunk.split('\n');

      for (const line of lines) {
        if (line.startsWith('data: ')) {
          const data = line.slice(6);
          try {
            const event = JSON.parse(data);
            onEvent(event.type, event);
          } catch (e) {
            console.error('Failed to parse SSE event:', e);
          }
        }
      }
    }
  },

  /**
   * Update the Bedrock API token at runtime.
   */
  async updateBedrockToken(token) {
    const response = await apiFetch('/api/settings/bedrock-token', {
      method: 'POST',
      headers: withAuth({
        'Content-Type': 'application/json',
      }),
      body: JSON.stringify({ token }),
    });
    if (!response.ok) {
      const errorText = await response.text();
      throw new Error(errorText || 'Failed to update Bedrock token');
    }
    return response.json();
  },

  /**
   * Get current Bedrock region.
   */
  async getBedrockRegion() {
    const response = await apiFetch('/api/settings/bedrock-region', {
      headers: withAuth(),
    });
    if (!response.ok) {
      throw new Error('Failed to load Bedrock region');
    }
    return response.json();
  },

  /**
   * List Bedrock region options.
   */
  async listBedrockRegions() {
    const response = await apiFetch('/api/settings/bedrock-region/options', {
      headers: withAuth(),
    });
    if (!response.ok) {
      throw new Error('Failed to load Bedrock region options');
    }
    return response.json();
  },

  /**
   * Update the Bedrock region at runtime.
   */
  async updateBedrockRegion(region) {
    const response = await apiFetch('/api/settings/bedrock-region', {
      method: 'POST',
      headers: withAuth({
        'Content-Type': 'application/json',
      }),
      body: JSON.stringify({ region }),
    });
    if (!response.ok) {
      const errorText = await response.text();
      throw new Error(errorText || 'Failed to update Bedrock region');
    }
    return response.json();
  },

  /**
   * Get council settings.
   */
  async getCouncilSettings() {
    const response = await apiFetch('/api/settings/council', {
      headers: withAuth(),
    });
    if (!response.ok) {
      throw new Error('Failed to load council settings');
    }
    return response.json();
  },

  /**
   * Update council settings.
   */
  async updateCouncilSettings(settings) {
    const response = await apiFetch('/api/settings/council', {
      method: 'POST',
      headers: withAuth({
        'Content-Type': 'application/json',
      }),
      body: JSON.stringify(settings),
    });
    if (!response.ok) {
      const errorText = await response.text();
      throw new Error(errorText || 'Failed to update council settings');
    }
    return response.json();
  },

  /**
   * List council presets.
   */
  async listCouncilPresets() {
    const response = await apiFetch('/api/settings/council/presets', {
      headers: withAuth(),
    });
    if (!response.ok) {
      throw new Error('Failed to load council presets');
    }
    return response.json();
  },

  /**
   * Save a council preset.
   */
  async saveCouncilPreset(name, settings) {
    const response = await apiFetch('/api/settings/council/presets', {
      method: 'POST',
      headers: withAuth({
        'Content-Type': 'application/json',
      }),
      body: JSON.stringify({ name, settings }),
    });
    if (!response.ok) {
      const errorText = await response.text();
      throw new Error(errorText || 'Failed to save council preset');
    }
    return response.json();
  },

  /**
   * Apply a council preset.
   */
  async applyCouncilPreset(presetId) {
    const response = await apiFetch('/api/settings/council/presets/apply', {
      method: 'POST',
      headers: withAuth({
        'Content-Type': 'application/json',
      }),
      body: JSON.stringify({ preset_id: presetId }),
    });
    if (!response.ok) {
      const errorText = await response.text();
      throw new Error(errorText || 'Failed to apply preset');
    }
    return response.json();
  },

  /**
   * Delete a council preset.
   */
  async deleteCouncilPreset(presetId) {
    const response = await apiFetch(`/api/settings/council/presets/${presetId}`, {
      method: 'DELETE',
      headers: withAuth(),
    });
    if (!response.ok) {
      const errorText = await response.text();
      throw new Error(errorText || 'Failed to delete preset');
    }
    return response.json();
  },

  /**
   * List Bedrock Converse-capable models for the current region.
   */
  async listBedrockModels() {
    const response = await apiFetch('/api/settings/bedrock-models', {
      headers: withAuth(),
    });
    if (!response.ok) {
      throw new Error('Failed to load Bedrock models');
    }
    return response.json();
  },

  /**
   * Cancel an active streaming message for a conversation.
   */
  async cancelMessageStream(conversationId) {
    const response = await apiFetch(`/api/conversations/${conversationId}/message/cancel`, {
      method: 'POST',
      headers: withAuth(),
    });
    if (!response.ok) {
      const errorText = await response.text();
      throw new Error(errorText || 'Failed to cancel stream');
    }
    return response.json();
  },
};
