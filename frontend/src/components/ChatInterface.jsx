import { useState, useEffect, useRef } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import Stage1 from './Stage1';
import Stage2 from './Stage2';
import Stage3 from './Stage3';
import './ChatInterface.css';

function CopyButton({ text, label = 'Copy', copiedLabel = 'Copied', className }) {
  const [copied, setCopied] = useState(false);
  const hasText = Boolean(text);

  const handleCopy = async () => {
    if (!hasText) return;
    try {
      if (navigator?.clipboard?.writeText) {
        await navigator.clipboard.writeText(text);
      } else {
        const textarea = document.createElement('textarea');
        textarea.value = text;
        textarea.setAttribute('readonly', '');
        textarea.style.position = 'absolute';
        textarea.style.left = '-9999px';
        document.body.appendChild(textarea);
        textarea.select();
        document.execCommand('copy');
        document.body.removeChild(textarea);
      }
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch (error) {
      console.error('Failed to copy message:', error);
    }
  };

  return (
    <button
      className={className}
      onClick={handleCopy}
      disabled={!hasText}
    >
      {copied ? copiedLabel : label}
    </button>
  );
}

export default function ChatInterface({
  conversation,
  onSendMessage,
  onStop,
  isLoading,
}) {
  const [input, setInput] = useState('');
  const messagesEndRef = useRef(null);

  const buildLabelMap = (message) => {
    if (message?.metadata?.label_to_model) {
      return message.metadata.label_to_model;
    }
    if (!message?.stage1 || !Array.isArray(message.stage1)) return null;

    const successful = message.stage1.filter(
      (result) => result.status !== 'failed' && result.response
    );
    if (!successful.length) return null;

    const labelMap = {};
    successful.forEach((result, index) => {
      const label = `Response ${String.fromCharCode(65 + index)}`;
      labelMap[label] = result.model;
    });
    return labelMap;
  };

  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  };

  useEffect(() => {
    scrollToBottom();
  }, [conversation]);

  const handleSubmit = (e) => {
    e.preventDefault();
    if (input.trim() && !isLoading) {
      onSendMessage(input);
      setInput('');
    }
  };

  const handleKeyDown = (e) => {
    // Submit on Enter (without Shift)
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSubmit(e);
    }
  };

  if (!conversation) {
    return (
      <div className="chat-interface">
        <div className="empty-state">
          <h2>Welcome to LLM Council</h2>
          <p>Create a new conversation to get started</p>
        </div>
      </div>
    );
  }

  return (
    <div className="chat-interface">
      <div className="messages-container">
        {conversation.messages.length === 0 ? (
          <div className="empty-state">
            <h2>Start a conversation</h2>
            <p>Ask a question to consult the LLM Council</p>
          </div>
        ) : (
          conversation.messages.map((msg, index) => (
            <div key={index} className="message-group">
              {msg.role === 'user' ? (
                <div className="user-message">
                  <div className="message-header">
                    <div className="message-label">You</div>
                    <CopyButton text={msg.content} className="copy-message-btn" />
                  </div>
                  <div className="message-content">
                    <div className="markdown-content">
                      <ReactMarkdown remarkPlugins={[remarkGfm]}>
                        {msg.content}
                      </ReactMarkdown>
                    </div>
                  </div>
                </div>
              ) : (
                <div className="assistant-message">
                  <div className="message-label">LLM Council</div>
                  {(() => {
                    const labelToModel = buildLabelMap(msg);
                    return (
                      <>
                        {/* Stage 1 */}
                        {msg.loading?.stage1 && (
                          <div className="stage-loading">
                            <div className="spinner"></div>
                            <span>Running Stage 1: Collecting individual responses...</span>
                          </div>
                        )}
                        {msg.stage1 && <Stage1 responses={msg.stage1} />}

                        {/* Stage 2 */}
                        {msg.loading?.stage2 && (
                          <div className="stage-loading">
                            <div className="spinner"></div>
                            <span>Running Stage 2: Peer rankings...</span>
                          </div>
                        )}
                        {msg.stage2 && (
                          <Stage2
                            rankings={msg.stage2}
                            labelToModel={labelToModel}
                            aggregateRankings={msg.metadata?.aggregate_rankings}
                          />
                        )}

                        {/* Stage 3 */}
                        {msg.loading?.stage3 && (
                          <div className="stage-loading">
                            <div className="spinner"></div>
                            <span>Running Stage 3: Final synthesis...</span>
                          </div>
                        )}
                        {msg.stage3 && (
                          <Stage3
                            finalResponse={msg.stage3}
                            labelToModel={labelToModel}
                          />
                        )}
                      </>
                    );
                  })()}
                </div>
              )}
            </div>
          ))
        )}

        {isLoading && (
          <div className="loading-indicator">
            <div className="spinner"></div>
            <span>Consulting the council...</span>
            {onStop && (
              <button className="stop-button" onClick={onStop}>
                Stop
              </button>
            )}
          </div>
        )}

        <div ref={messagesEndRef} />
      </div>

      {conversation.messages.length === 0 && (
        <form className="input-form" onSubmit={handleSubmit}>
          <textarea
            className="message-input"
            placeholder="Ask your question... (Shift+Enter for new line, Enter to send)"
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={handleKeyDown}
            disabled={isLoading}
            rows={3}
          />
          <button
            type="submit"
            className="send-button"
            disabled={!input.trim() || isLoading}
          >
            Send
          </button>
        </form>
      )}
    </div>
  );
}
