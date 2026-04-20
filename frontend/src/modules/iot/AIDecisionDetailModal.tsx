// Design Ref §5.4 — 판단 상세 모달.
// Plan SC-4 커버: reason / action JSON / tool_calls 트레이스 / sensor_snapshot / duration_ms.

import { useEffect, useRef, useState } from 'react';
import { MdClose, MdContentCopy, MdCheck, MdWarningAmber } from 'react-icons/md';
import type { AIDecision } from '@/types';

interface Props {
  open: boolean;
  decision: AIDecision | null;
  loading?: boolean;
  error?: string | null;
  onClose: () => void;
}

const CT_LABELS: Record<string, string> = {
  ventilation: '환기',
  irrigation: '관수',
  lighting: '조명',
  shading: '차광/보온',
};

const PR_LABELS: Record<string, { label: string; cls: string }> = {
  emergency: { label: '긴급', cls: 'bg-red-100 text-red-700' },
  high: { label: '높음', cls: 'bg-orange-100 text-orange-700' },
  medium: { label: '중간', cls: 'bg-blue-100 text-blue-700' },
  low: { label: '낮음', cls: 'bg-gray-100 text-gray-600' },
};

const SRC_LABELS: Record<string, { label: string; cls: string }> = {
  rule: { label: '규칙', cls: 'bg-yellow-100 text-yellow-700' },
  llm: { label: 'AI', cls: 'bg-purple-100 text-purple-700' },
  tool: { label: 'AI Tool', cls: 'bg-indigo-100 text-indigo-700' },
  manual: { label: '수동', cls: 'bg-green-100 text-green-700' },
};

function CopyButton({ text, label }: { text: string; label?: string }) {
  const [copied, setCopied] = useState(false);
  const onCopy = async () => {
    try {
      await navigator.clipboard.writeText(text);
      setCopied(true);
      setTimeout(() => setCopied(false), 1200);
    } catch {
      // 무시 (일부 브라우저는 https 요구)
    }
  };
  return (
    <button
      onClick={onCopy}
      className="inline-flex items-center gap-1 text-xs text-gray-500 hover:text-indigo-600 transition-colors"
      aria-label={label ?? 'Copy'}
    >
      {copied ? <MdCheck className="text-green-500" /> : <MdContentCopy />}
      {copied ? '복사됨' : '복사'}
    </button>
  );
}

function Section({
  title,
  children,
  action,
}: {
  title: string;
  children: React.ReactNode;
  action?: React.ReactNode;
}) {
  return (
    <div className="border-t border-gray-100 pt-3 mt-3 first:border-0 first:pt-0 first:mt-0">
      <div className="flex items-center justify-between mb-1.5">
        <h4 className="text-xs font-semibold text-gray-500 uppercase tracking-wide">
          {title}
        </h4>
        {action}
      </div>
      {children}
    </div>
  );
}

export default function AIDecisionDetailModal({
  open,
  decision,
  loading,
  error,
  onClose,
}: Props) {
  const closeBtnRef = useRef<HTMLButtonElement | null>(null);
  const modalRef = useRef<HTMLDivElement | null>(null);

  // Esc 닫기 + focus trap 초기 포커스
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        onClose();
      }
    };
    document.addEventListener('keydown', onKey);
    // 다음 tick 에 focus
    setTimeout(() => closeBtnRef.current?.focus(), 10);
    return () => document.removeEventListener('keydown', onKey);
  }, [open, onClose]);

  if (!open) return null;

  const time = decision?.timestamp
    ? new Date(decision.timestamp).toLocaleString('ko-KR', {
        year: 'numeric',
        month: '2-digit',
        day: '2-digit',
        hour: '2-digit',
        minute: '2-digit',
        second: '2-digit',
      })
    : '';

  const priority = decision ? PR_LABELS[decision.priority] : null;
  const source = decision ? SRC_LABELS[decision.source] : null;

  const actionStr = decision ? JSON.stringify(decision.action ?? {}, null, 2) : '';
  const toolCalls = decision?.tool_calls ?? [];
  const snapshot = decision?.sensor_snapshot;

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4"
      role="dialog"
      aria-modal="true"
      aria-labelledby="ai-decision-detail-title"
      onClick={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <div
        ref={modalRef}
        className="bg-white rounded-2xl shadow-xl w-full max-w-lg max-h-[90vh] overflow-hidden flex flex-col"
      >
        {/* Header */}
        <div className="flex items-center justify-between px-5 py-3 border-b">
          <h3 id="ai-decision-detail-title" className="font-semibold text-gray-800">
            판단 상세
          </h3>
          <button
            ref={closeBtnRef}
            onClick={onClose}
            className="p-1 rounded hover:bg-gray-100 text-gray-500"
            aria-label="닫기"
          >
            <MdClose className="text-xl" />
          </button>
        </div>

        {/* Body */}
        <div className="px-5 py-4 overflow-y-auto flex-1">
          {loading && !decision && (
            <div className="text-sm text-gray-500 py-8 text-center">불러오는 중…</div>
          )}

          {error && (
            <div className="flex items-start gap-2 bg-red-50 text-red-700 rounded-lg p-3 text-sm">
              <MdWarningAmber className="text-xl shrink-0 mt-0.5" />
              <span>{error}</span>
            </div>
          )}

          {decision && (
            <>
              {/* Meta */}
              <div className="flex flex-wrap items-center gap-2 mb-2">
                <span className="text-xs text-gray-500">{time}</span>
                <span className="text-sm font-medium text-gray-800">
                  {CT_LABELS[decision.control_type] ?? decision.control_type}
                </span>
                {priority && (
                  <span className={`text-xs px-2 py-0.5 rounded-full font-medium ${priority.cls}`}>
                    {priority.label}
                  </span>
                )}
                {source && (
                  <span className={`text-xs px-2 py-0.5 rounded-full font-medium ${source.cls}`}>
                    {source.label}
                  </span>
                )}
              </div>

              <Section title="판단 사유">
                <p className="text-sm text-gray-700 leading-relaxed whitespace-pre-wrap">
                  {decision.reason || '내용 없음'}
                </p>
              </Section>

              <Section
                title="Action (제어 변경)"
                action={<CopyButton text={actionStr} label="Copy action JSON" />}
              >
                <pre className="text-xs bg-gray-50 rounded-lg p-2.5 font-mono overflow-x-auto whitespace-pre-wrap break-all">
                  {actionStr || '{}'}
                </pre>
              </Section>

              {snapshot && (
                <Section title="당시 센서 값">
                  <div className="grid grid-cols-2 gap-x-4 gap-y-1 text-sm">
                    {snapshot.temperature != null && (
                      <div className="flex justify-between">
                        <span className="text-gray-500">온도</span>
                        <span className="font-medium text-gray-800">
                          {snapshot.temperature}°C
                        </span>
                      </div>
                    )}
                    {snapshot.humidity != null && (
                      <div className="flex justify-between">
                        <span className="text-gray-500">대기 습도</span>
                        <span className="font-medium text-gray-800">{snapshot.humidity}%</span>
                      </div>
                    )}
                    {snapshot.light_intensity != null && (
                      <div className="flex justify-between">
                        <span className="text-gray-500">조도</span>
                        <span className="font-medium text-gray-800">
                          {snapshot.light_intensity} lx
                        </span>
                      </div>
                    )}
                    {snapshot.soil_moisture != null && (
                      <div className="flex justify-between">
                        <span className="text-gray-500">토양 수분</span>
                        <span className="font-medium text-gray-800">
                          {snapshot.soil_moisture}%
                        </span>
                      </div>
                    )}
                  </div>
                </Section>
              )}

              <Section title={`도구 호출 (${toolCalls.length})`}>
                {toolCalls.length === 0 ? (
                  <p className="text-xs text-gray-400">호출 내역 없음</p>
                ) : (
                  <ol className="space-y-2">
                    {toolCalls.map((tc, i) => {
                      const argStr = JSON.stringify(tc.arguments ?? {}, null, 2);
                      const success =
                        typeof tc.result === 'object' && tc.result
                          ? (tc.result as { success?: boolean }).success
                          : undefined;
                      const errMsg =
                        typeof tc.result === 'object' && tc.result
                          ? (tc.result as { error?: string }).error
                          : undefined;
                      return (
                        <li key={i} className="bg-gray-50 rounded-lg p-2.5">
                          <div className="flex items-center justify-between gap-2 mb-1">
                            <div className="flex items-center gap-1.5 text-sm">
                              <span className="font-mono text-gray-400">{i + 1}.</span>
                              <span className="font-mono text-indigo-600 font-semibold">
                                {tc.tool}
                              </span>
                              {success === true && (
                                <span className="text-[10px] bg-green-100 text-green-700 px-1.5 py-0.5 rounded font-medium">
                                  OK
                                </span>
                              )}
                              {success === false && (
                                <span className="text-[10px] bg-red-100 text-red-700 px-1.5 py-0.5 rounded font-medium">
                                  FAIL
                                </span>
                              )}
                            </div>
                            <CopyButton text={argStr} label={`Copy ${tc.tool} arguments`} />
                          </div>
                          <pre className="text-[11px] font-mono text-gray-600 overflow-x-auto whitespace-pre-wrap break-all">
                            {argStr}
                          </pre>
                          {errMsg && (
                            <p className="text-[11px] text-red-600 mt-1">error: {errMsg}</p>
                          )}
                        </li>
                      );
                    })}
                  </ol>
                )}
              </Section>
            </>
          )}
        </div>

        {/* Footer */}
        {decision && (
          <div className="border-t px-5 py-2.5 text-[11px] text-gray-400 flex items-center justify-between gap-2">
            <div className="flex items-center gap-3 truncate">
              <span>
                duration <span className="font-mono text-gray-600">
                  {decision.duration_ms != null ? `${decision.duration_ms}ms` : '-'}
                </span>
              </span>
              <span className="truncate">
                id{' '}
                <span className="font-mono text-gray-600">
                  {decision.id.slice(0, 8)}…
                </span>
              </span>
            </div>
            <CopyButton text={decision.id} label="Copy decision id" />
          </div>
        )}
      </div>
    </div>
  );
}
