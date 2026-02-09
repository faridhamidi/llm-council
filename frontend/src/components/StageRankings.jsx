import { memo, useCallback, useMemo, useState } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import './StageRankings.css';

const MARKDOWN_PLUGINS = [remarkGfm];

function deAnonymizeText(text, labelToModel) {
  if (!labelToModel) return text;

  let result = text;
  // Replace each "Response X" with the actual model name
  Object.entries(labelToModel).forEach(([label, model]) => {
    result = result.replace(new RegExp(label, 'g'), `**${model}**`);
  });
  return result;
}

function StageRankings({
  rankings,
  labelToModel,
  aggregateRankings,
  stageName = 'Peer Rankings',
  stagePrompt = '',
}) {
  const [activeTab, setActiveTab] = useState(0);
  const [copied, setCopied] = useState(false);

  if (!rankings || rankings.length === 0) {
    return null;
  }

  const activeRanking = useMemo(
    () => rankings[activeTab] || rankings[0] || null,
    [rankings, activeTab]
  );

  const rankingText = useMemo(
    () => deAnonymizeText(activeRanking?.ranking || '', labelToModel),
    [activeRanking, labelToModel]
  );

  const copyText = useMemo(() => {
    if (!activeRanking) return '';
    let text = `Evaluator: ${activeRanking.model}\n\n${rankingText}`;
    if (activeRanking.parsed_ranking && activeRanking.parsed_ranking.length > 0) {
      const parsed = activeRanking.parsed_ranking.map((label, i) => {
        const name = labelToModel && labelToModel[label] ? labelToModel[label] : label;
        return `${i + 1}. ${name}`;
      }).join('\n');
      text += `\n\nExtracted Ranking:\n${parsed}`;
    }
    return text;
  }, [activeRanking, rankingText, labelToModel]);

  const handleCopy = useCallback(async () => {
    const text = copyText;
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
      console.error('Failed to copy Stage 2 output:', error);
    }
  }, [copyText]);

  if (!activeRanking) {
    return null;
  }

  return (
    <div className="stage stage-rankings">
      <h3 className="stage-title">{stageName}</h3>
      {stagePrompt && <div className="stage-prompt-text">{stagePrompt}</div>}

      <h4>Raw Evaluations</h4>
      <p className="stage-description">
        Each model evaluated all responses using anonymized labels and provided rankings.
        Below, member aliases are shown in <strong>bold</strong> for readability, but the original evaluation used anonymous labels.
      </p>

      <div className="tabs">
        {rankings.map((rank, index) => (
          <button
            key={index}
            className={`tab ${activeTab === index ? 'active' : ''}`}
            onClick={() => {
              setActiveTab(index);
              setCopied(false);
            }}
          >
            {rank.model}
          </button>
        ))}
      </div>

      <div className="tab-content">
        <div className="ranking-header">
          <div className="ranking-model">
            {activeRanking.model}
          </div>
          <button className="copy-stage-btn" onClick={handleCopy}>
            {copied ? 'Copied' : 'Copy'}
          </button>
        </div>
        <div className="ranking-content markdown-content">
          <ReactMarkdown remarkPlugins={MARKDOWN_PLUGINS}>
            {rankingText}
          </ReactMarkdown>
        </div>

        {activeRanking.parsed_ranking &&
         activeRanking.parsed_ranking.length > 0 && (
          <div className="parsed-ranking">
            <strong>Extracted Ranking:</strong>
            <ol>
              {activeRanking.parsed_ranking.map((label, i) => (
                <li key={i}>
                  {labelToModel && labelToModel[label]
                    ? labelToModel[label]
                    : label}
                </li>
              ))}
            </ol>
          </div>
        )}
      </div>

      {aggregateRankings && aggregateRankings.length > 0 && (
        <div className="aggregate-rankings">
          <h4>Aggregate Rankings (Street Cred)</h4>
          <p className="stage-description">
            Combined results across all peer evaluations (lower score is better):
          </p>
          <div className="aggregate-list">
            {aggregateRankings.map((agg, index) => (
              <div key={index} className="aggregate-item">
                <span className="rank-position">#{index + 1}</span>
                <span className="rank-model">
                  {agg.model}
                </span>
                <span className="rank-score">
                  Avg: {agg.average_rank.toFixed(2)}
                </span>
                <span className="rank-count">
                  ({agg.rankings_count} votes)
                </span>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

function arePropsEqual(prevProps, nextProps) {
  return (
    prevProps.rankings === nextProps.rankings &&
    prevProps.labelToModel === nextProps.labelToModel &&
    prevProps.aggregateRankings === nextProps.aggregateRankings &&
    prevProps.stageName === nextProps.stageName &&
    prevProps.stagePrompt === nextProps.stagePrompt
  );
}

export default memo(StageRankings, arePropsEqual);
