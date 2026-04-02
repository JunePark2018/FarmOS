import { useQuery } from '@tanstack/react-query';
import api from '@/lib/api';
import type { DashboardData } from '@/types/dashboard';
import type { ChatLog } from '@/types/chatlog';

export function useDashboard() {
  return useQuery<DashboardData>({
    queryKey: ['dashboard'],
    queryFn: async () => {
      const { data } = await api.get('/api/analytics/dashboard');
      return data;
    },
  });
}

export function useEscalatedLogs() {
  return useQuery<ChatLog[]>({
    queryKey: ['escalated-logs'],
    queryFn: async () => {
      const { data } = await api.get('/api/chatbot/logs/escalated');
      return data;
    },
  });
}
