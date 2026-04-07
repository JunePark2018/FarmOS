import { useState, useEffect, useCallback } from 'react';
import type { SensorReading, IrrigationEvent, SensorAlert } from '@/types';

const API_BASE = 'http://iot.lilpa.moe/api/v1';
const POLL_INTERVAL = 3000; // 3초 간격 폴링

interface SensorData {
  latest: SensorReading | null;
  history: SensorReading[];
  alerts: SensorAlert[];
  irrigations: IrrigationEvent[];
  connected: boolean;
}

export function useSensorData() {
  const [data, setData] = useState<SensorData>({
    latest: null,
    history: [],
    alerts: [],
    irrigations: [],
    connected: false,
  });

  const fetchAll = useCallback(async () => {
    try {
      const [latestRes, historyRes, alertsRes, irrigationsRes] = await Promise.all([
        fetch(`${API_BASE}/sensors/latest`),
        fetch(`${API_BASE}/sensors/history?limit=100`),
        fetch(`${API_BASE}/sensors/alerts`),
        fetch(`${API_BASE}/irrigation/events`),
      ]);

      const latest = await latestRes.json();
      const history = await historyRes.json();
      const alerts = await alertsRes.json();
      const irrigations = await irrigationsRes.json();

      setData({
        latest: latest.timestamp ? latest : null,
        history,
        alerts,
        irrigations,
        connected: true,
      });
    } catch {
      setData(prev => ({ ...prev, connected: false }));
    }
  }, []);

  useEffect(() => {
    fetchAll();
    const timer = setInterval(fetchAll, POLL_INTERVAL);
    return () => clearInterval(timer);
  }, [fetchAll]);

  return data;
}
