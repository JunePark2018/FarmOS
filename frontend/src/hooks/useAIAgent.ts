import { useState, useEffect, useCallback } from 'react';
import type { AIAgentStatus, CropProfile } from '@/types';

const API_BASE = 'http://iot.lilpa.moe/api/v1';
const POLL_INTERVAL = 30000;

export function useAIAgent() {
  const [status, setStatus] = useState<AIAgentStatus | null>(null);
  const [loading, setLoading] = useState(true);

  const fetchStatus = useCallback(async () => {
    try {
      const res = await fetch(`${API_BASE}/ai-agent/status`, { credentials: 'omit' });
      if (res.ok) {
        const data = await res.json();
        setStatus(data);
      }
    } catch {
      // 무시
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchStatus();
    const timer = setInterval(fetchStatus, POLL_INTERVAL);
    return () => clearInterval(timer);
  }, [fetchStatus]);

  const toggle = useCallback(async () => {
    try {
      const res = await fetch(`${API_BASE}/ai-agent/toggle`, {
        method: 'POST',
        credentials: 'omit',
      });
      if (res.ok) {
        await fetchStatus();
      }
    } catch {
      // 무시
    }
  }, [fetchStatus]);

  const updateCropProfile = useCallback(async (profile: CropProfile) => {
    try {
      const res = await fetch(`${API_BASE}/ai-agent/crop-profile`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'omit',
        body: JSON.stringify(profile),
      });
      if (res.ok) {
        await fetchStatus();
      }
    } catch {
      // 무시
    }
  }, [fetchStatus]);

  const override = useCallback(async (controlType: string, values: Record<string, unknown>, reason: string) => {
    try {
      await fetch(`${API_BASE}/ai-agent/override`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'omit',
        body: JSON.stringify({ control_type: controlType, values, reason }),
      });
      await fetchStatus();
    } catch {
      // 무시
    }
  }, [fetchStatus]);

  return { status, loading, toggle, updateCropProfile, override, refetch: fetchStatus };
}
