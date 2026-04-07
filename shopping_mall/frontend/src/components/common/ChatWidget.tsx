import { useState, useRef, useEffect } from 'react';
import { useMutation, useQuery } from '@tanstack/react-query';
import api from '@/lib/api';
import { useUserStore } from '@/stores/userStore';
import { INTENT_LABEL } from '@/admin/constants/chatbot';

interface Message {
  id: string;
  role: 'user' | 'bot';
  text: string;
  intent?: string;
  escalated?: boolean;
}

const STORAGE_KEY = 'chat_session';
const WELCOME: Message = { id: 'welcome', role: 'bot', text: '안녕하세요! FarmOS 마켓 고객지원입니다.\n무엇이든 물어보세요 😊' };

function loadGuestSession(): Message[] {
  try {
    const raw = sessionStorage.getItem(STORAGE_KEY);
    return raw ? JSON.parse(raw) : [WELCOME];
  } catch {
    return [WELCOME];
  }
}

function saveGuestSession(messages: Message[]) {
  try {
    sessionStorage.setItem(STORAGE_KEY, JSON.stringify(messages));
  } catch {}
}

const QUICK_ACTIONS = [
  { label: '📦 배송 조회', intent: 'delivery', text: '배송 현황을 알고 싶어요' },
  { label: '🍎 재고 확인', intent: 'stock', text: '재고 확인해 주세요' },
  { label: '❄️ 보관 방법', intent: 'storage', text: '상품 보관 방법이 궁금해요' },
  { label: '↩️ 교환/환불', intent: 'exchange', text: '교환/환불하고 싶어요' },
  { label: '🌸 제철 상품', intent: 'season', text: '요즘 제철 상품이 뭔가요?' },
];

export default function ChatWidget() {
  const [open, setOpen] = useState(false);
  const [messages, setMessages] = useState<Message[]>([WELCOME]);
  const [initialized, setInitialized] = useState(false);
  const [input, setInput] = useState('');
  const bottomRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const { user } = useUserStore();
  const userId = user?.shop_user_id ?? null;

  // 회원: DB에서 대화 내역 로드
  const { data: dbHistory, isSuccess: historyLoaded } = useQuery({
    queryKey: ['chat-history', userId],
    queryFn: async () => {
      const { data } = await api.get('/api/chatbot/history', { params: { user_id: userId, limit: 20 } });
      return data as Message[];
    },
    enabled: !!userId,
    staleTime: Infinity,
  });

  // 초기 messages 세팅 (회원/비회원 분기)
  useEffect(() => {
    if (userId) {
      if (historyLoaded) {
        setMessages(dbHistory && dbHistory.length > 0 ? dbHistory : [WELCOME]);
        setInitialized(true);
      }
    } else {
      setMessages(loadGuestSession());
      setInitialized(true);
    }
  }, [userId, historyLoaded, dbHistory]);

  // 비회원: initialized 이후부터 messages가 바뀔 때마다 sessionStorage에 저장
  // initialized 이전에는 저장하지 않음 — 초기 [WELCOME]으로 sessionStorage를 덮어쓰는 것 방지
  useEffect(() => {
    if (!userId && initialized) {
      saveGuestSession(messages);
    }
  }, [messages, userId, initialized]);

  const { mutate: ask, isPending } = useMutation({
    mutationFn: async ({ question, intent }: { question: string; intent?: string }) => {
      const { data } = await api.post('/api/chatbot/ask', {
        question,
        user_id: userId,
        history: messages.slice(-4).map(({ role, text }) => ({ role, text })),
        ...(intent ? { intent } : {}),
      });
      return data as { answer: string; intent: string; escalated: boolean };
    },
    onSuccess: (data) => {
      setMessages((prev) => [
        ...prev,
        { id: crypto.randomUUID(), role: 'bot' as const, text: data.answer, intent: data.intent, escalated: data.escalated },
      ]);
    },
    onError: () => {
      setMessages((prev) => [
        ...prev,
        { id: crypto.randomUUID(), role: 'bot' as const, text: '죄송합니다. 잠시 후 다시 시도해 주세요.' },
      ]);
    },
  });

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages, isPending]);

  useEffect(() => {
    if (open) inputRef.current?.focus();
  }, [open]);

  const send = (question: string, intent?: string) => {
    if (!question.trim() || isPending) return;
    setMessages((prev) => [...prev, { id: crypto.randomUUID(), role: 'user' as const, text: question }]);
    setInput('');
    ask({ question, intent });
  };

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    send(input);
  };

  return (
    <>
      {open && (
        <div className="fixed bottom-24 right-6 w-[360px] max-h-[560px] bg-white rounded-2xl shadow-2xl border border-gray-200 flex flex-col z-50 overflow-hidden">
          {/* 헤더 */}
          <div className="flex items-center justify-between px-4 py-3 bg-[#03C75A] text-white shrink-0">
            <div className="flex items-center gap-2">
              <span className="text-lg">🤖</span>
              <div>
                <p className="text-sm font-semibold">FarmOS 고객지원</p>
                <p className="text-xs opacity-80">AI 챗봇</p>
              </div>
            </div>
            <button
              onClick={() => setOpen(false)}
              className="text-white/80 hover:text-white text-lg leading-none"
            >
              ✕
            </button>
          </div>

          {/* 메시지 영역 */}
          <div className="flex-1 overflow-y-auto p-4 space-y-3 min-h-0">
            {messages.map((msg) => (
              <div key={msg.id} className={`flex ${msg.role === 'user' ? 'justify-end' : 'justify-start'}`}>
                <div className={`max-w-[82%] ${msg.role === 'bot' ? 'space-y-1' : ''}`}>
                  <div
                    className={`px-3 py-2 rounded-2xl text-sm leading-relaxed whitespace-pre-wrap ${
                      msg.role === 'user'
                        ? 'bg-[#03C75A] text-white rounded-br-sm'
                        : 'bg-gray-100 text-gray-800 rounded-bl-sm'
                    }`}
                  >
                    {msg.text}
                  </div>
                  {msg.role === 'bot' && msg.intent && (
                    <div className="flex items-center gap-1.5 px-1">
                      <span className="text-xs text-gray-400">
                        [{INTENT_LABEL[msg.intent] ?? msg.intent}]
                      </span>
                      {msg.escalated && (
                        <span className="text-xs text-red-500 font-medium">상담원 연결 필요</span>
                      )}
                    </div>
                  )}
                </div>
              </div>
            ))}
            {isPending && (
              <div className="flex justify-start">
                <div className="bg-gray-100 px-4 py-2.5 rounded-2xl rounded-bl-sm">
                  <span className="flex gap-1 items-center h-4">
                    {[0, 150, 300].map((delay) => (
                      <span
                        key={delay}
                        className="w-1.5 h-1.5 bg-gray-400 rounded-full animate-bounce"
                        style={{ animationDelay: `${delay}ms` }}
                      />
                    ))}
                  </span>
                </div>
              </div>
            )}
            <div ref={bottomRef} />
          </div>

          {/* 빠른 액션 */}
          <div className="px-3 py-2 border-t border-gray-100 flex gap-1.5 overflow-x-auto shrink-0" style={{ scrollbarWidth: 'none' }}>
            {QUICK_ACTIONS.map((action) => (
              <button
                key={action.intent}
                onClick={() => send(action.text, action.intent)}
                disabled={isPending}
                className="shrink-0 text-xs px-2.5 py-1.5 rounded-full border border-gray-200 text-gray-600 hover:border-[#03C75A] hover:text-[#03C75A] transition-colors disabled:opacity-40"
              >
                {action.label}
              </button>
            ))}
          </div>

          {/* 입력 */}
          <form onSubmit={handleSubmit} className="px-3 py-3 border-t border-gray-100 flex gap-2 shrink-0">
            <input
              ref={inputRef}
              type="text"
              value={input}
              onChange={(e) => setInput(e.target.value)}
              placeholder="메시지를 입력하세요..."
              disabled={isPending}
              className="flex-1 text-sm border border-gray-200 rounded-full px-4 py-2 outline-none focus:border-[#03C75A] transition-colors disabled:opacity-50"
            />
            <button
              type="submit"
              disabled={!input.trim() || isPending}
              className="w-9 h-9 bg-[#03C75A] text-white rounded-full flex items-center justify-center shrink-0 hover:bg-[#02b050] transition-colors disabled:opacity-40 text-lg"
            >
              ↑
            </button>
          </form>
        </div>
      )}

      {/* 플로팅 버튼 */}
      <button
        onClick={() => setOpen((v) => !v)}
        className="fixed bottom-6 right-6 w-14 h-14 bg-[#03C75A] text-white rounded-full shadow-lg flex items-center justify-center text-2xl hover:bg-[#02b050] transition-all z-50 hover:scale-105"
        aria-label="고객지원 챗봇"
      >
        {open ? '✕' : '💬'}
      </button>
    </>
  );
}
