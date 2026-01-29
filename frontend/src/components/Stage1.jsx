import { useState } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import './Stage1.css';

export default function Stage1({ responses }) {
  const [activeTab, setActiveTab] = useState(0);

  if (!responses || responses.length === 0) {
    return null;
  }

  return (
    <div className="stage stage1">
      <h3 className="stage-title">Stage 1: Individual Responses</h3>

      <div className="tabs">
        {responses.map((resp, index) => (
          <button
            key={index}
            className={`tab ${activeTab === index ? 'active' : ''} ${resp.status === 'failed' ? 'failed' : ''}`}
            onClick={() => setActiveTab(index)}
          >
            {resp.model}{resp.status === 'failed' ? ' (failed)' : ''}
          </button>
        ))}
      </div>

      <div className="tab-content">
        <div className="model-name">{responses[activeTab].model}</div>
        {responses[activeTab].system_prompt_dropped && (
          <div className="system-prompt-warning">
            System prompt ignored by this model (continued without it).
          </div>
        )}
        {responses[activeTab].status === 'failed' ? (
          <div className="response-text markdown-content">
            <p><strong>Failed to respond.</strong></p>
            {responses[activeTab].error && <p>{responses[activeTab].error}</p>}
          </div>
        ) : (
          <div className="response-text markdown-content">
            <ReactMarkdown remarkPlugins={[remarkGfm]}>
              {responses[activeTab].response}
            </ReactMarkdown>
          </div>
        )}
      </div>
    </div>
  );
}
