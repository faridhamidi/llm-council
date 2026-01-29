/**
 * API client for the LLM Council backend.
 */

const API_BASE = 'http://localhost:8001';

export const api = {
  /**
   * List all conversations.
   */
  async listConversations() {
    const response = await fetch(`${API_BASE}/api/conversations`);
    if (!response.ok) {
      throw new Error('Failed to list conversations');
    }
    return response.json();
  },

  /**
   * Create a new conversation.
   */
  async createConversation() {
    const response = await fetch(`${API_BASE}/api/conversations`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
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
    const response = await fetch(
      `${API_BASE}/api/conversations/${conversationId}`
    );
    if (!response.ok) {
      throw new Error('Failed to get conversation');
    }
    return response.json();
  },

  /**
   * Delete a conversation (soft-delete).
   */
  async deleteConversation(conversationId) {
    const response = await fetch(
      `${API_BASE}/api/conversations/${conversationId}`,
      {
        method: 'DELETE',
      }
    );
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
    const response = await fetch(
      `${API_BASE}/api/conversations/${conversationId}/restore`,
      {
        method: 'POST',
      }
    );
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
    const response = await fetch(
      `${API_BASE}/api/conversations/${conversationId}/message`,
      {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({ content }),
      }
    );
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
    const response = await fetch(
      `${API_BASE}/api/conversations/${conversationId}/message/stream`,
      {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        signal,
        body: JSON.stringify({ content }),
      }
    );

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
    const response = await fetch(`${API_BASE}/api/settings/bedrock-token`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
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
    const response = await fetch(`${API_BASE}/api/settings/bedrock-region`);
    if (!response.ok) {
      throw new Error('Failed to load Bedrock region');
    }
    return response.json();
  },

  /**
   * List Bedrock region options.
   */
  async listBedrockRegions() {
    const response = await fetch(`${API_BASE}/api/settings/bedrock-region/options`);
    if (!response.ok) {
      throw new Error('Failed to load Bedrock region options');
    }
    return response.json();
  },

  /**
   * Update the Bedrock region at runtime.
   */
  async updateBedrockRegion(region) {
    const response = await fetch(`${API_BASE}/api/settings/bedrock-region`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
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
    const response = await fetch(`${API_BASE}/api/settings/council`);
    if (!response.ok) {
      throw new Error('Failed to load council settings');
    }
    return response.json();
  },

  /**
   * Update council settings.
   */
  async updateCouncilSettings(settings) {
    const response = await fetch(`${API_BASE}/api/settings/council`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
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
    const response = await fetch(`${API_BASE}/api/settings/council/presets`);
    if (!response.ok) {
      throw new Error('Failed to load council presets');
    }
    return response.json();
  },

  /**
   * Save a council preset.
   */
  async saveCouncilPreset(name, settings) {
    const response = await fetch(`${API_BASE}/api/settings/council/presets`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
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
    const response = await fetch(`${API_BASE}/api/settings/council/presets/apply`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({ preset_id: presetId }),
    });
    if (!response.ok) {
      const errorText = await response.text();
      throw new Error(errorText || 'Failed to apply council preset');
    }
    return response.json();
  },

  /**
   * Delete a council preset.
   */
  async deleteCouncilPreset(presetId) {
    const response = await fetch(`${API_BASE}/api/settings/council/presets/${presetId}`, {
      method: 'DELETE',
    });
    if (!response.ok) {
      const errorText = await response.text();
      throw new Error(errorText || 'Failed to delete council preset');
    }
    return response.json();
  },

  /**
   * List Bedrock Converse-capable models for the current region.
   */
  async listBedrockModels() {
    const response = await fetch(`${API_BASE}/api/settings/bedrock-models`);
    if (!response.ok) {
      throw new Error('Failed to load Bedrock models');
    }
    return response.json();
  },

  /**
   * Cancel an active streaming message for a conversation.
   */
  async cancelMessageStream(conversationId) {
    const response = await fetch(
      `${API_BASE}/api/conversations/${conversationId}/message/cancel`,
      {
        method: 'POST',
      }
    );
    if (!response.ok) {
      const errorText = await response.text();
      throw new Error(errorText || 'Failed to cancel stream');
    }
    return response.json();
  },
};
